"""Machinery for exporting query results as JSON to Cloud storage."""

from google.cloud import bigquery
import smart_open

import os
import sys
import re

# sys.path needs to be modified to enable package imports from parent
# and sibling directories. Also see:
# https://stackoverflow.com/questions/6323860/sibling-package-imports/23542795#23542795
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bigquery_etl.parse_metadata import Metadata  # noqa E402


METADATA_FILE = "metadata.yaml"
SUBMISSION_DATE_RE = re.compile(r"^submission_date:DATE:(\d\d\d\d-\d\d-\d\d)$")
QUERY_FILE_RE = re.compile(r"^.*/([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)_(v[0-9]+)/query\.sql$")


class JsonPublisher:
    """Publishes query results as JSON."""

    def __init__(
        self,
        client,
        storage_client,
        project_id,
        query_file,
        api_version,
        target_bucket,
        parameter=None,
    ):
        """Init JsonPublisher."""
        self.project_id = project_id
        self.query_file = query_file
        self.api_version = api_version
        self.target_bucket = target_bucket
        self.parameter = parameter
        self.client = client
        self.storage_client = storage_client
        self.temp_table = None
        self.date = None

        self.metadata = Metadata.of_sql_file(self.query_file)

        if self.parameter:
            date_search = re.search(SUBMISSION_DATE_RE, self.parameter)

            if date_search:
                self.date = date_search.group(1)

        query_file_re = re.search(QUERY_FILE_RE, self.query_file)
        if query_file_re:
            self.dataset = query_file_re.group(1)
            self.table = query_file_re.group(2)
            self.version = query_file_re.group(3)
        else:
            print("Invalid file naming format: {}", self.query_file)
            sys.exit(1)

    def __exit__(self):
        """Delete temporary tables."""
        if self.temp_table:
            self.client.delete_table(self.temp_table)

    def publish_json(self):
        """Publish query results as JSON to GCP Storage bucket."""
        if self.metadata.is_incremental():
            if self.date is None:
                print("Cannot publish JSON. submission_date missing in parameter.")
                sys.exit(1)

            # if it is an incremental query, then the query result needs to be
            # written to a temporary table to get exported as JSON
            self._write_results_to_temp_table()
            self._publish_table_as_json(self.temp_table)
        else:
            # for non-incremental queries, the entire destination table is exported
            result_table = f"{self.dataset}.{self.table}_{self.version}"
            self._publish_table_as_json(result_table)

    def _publish_table_as_json(self, result_table):
        """Export the `result_table` data as JSON to Cloud Storage."""
        prefix = (
            f"api/{self.api_version}/tables/{self.dataset}/"
            f"{self.table}/{self.version}/files/"
        )

        if self.date is not None:
            # if date exists, then query is incremental and newest results are exported
            prefix += f"{self.date}/"

        table_ref = self.client.get_table(result_table)

        job_config = bigquery.ExtractJobConfig()
        job_config.destination_format = "NEWLINE_DELIMITED_JSON"

        # "*" makes sure that files larger than 1GB get split up into JSON files
        destination_uri = f"gs://{self.target_bucket}/" + prefix + "*.json"
        extract_job = self.client.extract_table(
            table_ref, destination_uri, location="US", job_config=job_config
        )
        extract_job.result()

        self._gcp_convert_ndjson_to_json(prefix)

    def _gcp_convert_ndjson_to_json(self, gcp_path):
        """Convert ndjson files on GCP to json files."""
        blobs = self.storage_client.list_blobs(self.target_bucket, prefix=gcp_path)
        bucket = self.storage_client.bucket(self.target_bucket)

        for blob in blobs:
            blob_path = f"gs://{self.target_bucket}/{blob.name}"
            tmp_blob = bucket.blob(blob.name + ".tmp")
            tmp_blob_name = blob_path + ".tmp"

            # stream from GCS
            with smart_open.open(blob_path) as fin:
                with smart_open.open(tmp_blob_name, "w") as fout:
                    fout.write("[\n")

                    first_line = True

                    for line in fin:
                        if not first_line:
                            fout.write(",\n")

                        first_line = False
                        fout.write(line.replace("\n", ""))

                    fout.write("]")

            bucket.rename_blob(tmp_blob, blob.name)

    def _write_results_to_temp_table(self):
        """Write the query results to a temporary table and return the table name."""
        table_date = self.date.replace("-", "")
        self.temp_table = (
            f"{self.project_id}.tmp.{self.table}_{self.version}_{table_date}_temp"
        )

        with open(self.query_file) as query_stream:
            sql = query_stream.read()
            job_config = bigquery.QueryJobConfig(destination=self.temp_table)
            query_job = self.client.query(sql, job_config=job_config)
            query_job.result()