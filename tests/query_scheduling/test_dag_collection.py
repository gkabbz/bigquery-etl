from pathlib import Path
import pytest

from bigquery_etl.query_scheduling.dag_collection import DagCollection
from bigquery_etl.query_scheduling.dag import InvalidDag, DagParseException
from bigquery_etl.query_scheduling.task import Task
from bigquery_etl.metadata.parse_metadata import Metadata

TEST_DIR = Path(__file__).parent.parent


class TestDagCollection:
    def test_dags_from_file(self):
        dags_file = TEST_DIR / "data" / "dags.yaml"
        dags = DagCollection.from_file(dags_file)

        assert len(dags.dags) == 2
        assert dags.dag_by_name("not existing") is None
        assert dags.dag_by_name("bqetl_events") is not None
        assert dags.dag_by_name("bqetl_core") is not None

        events_dag = dags.dag_by_name("bqetl_events")
        assert len(events_dag.tasks) == 0

        core_dag = dags.dag_by_name("bqetl_core")
        assert len(core_dag.tasks) == 0

    def test_dags_from_dict(self):
        dags = DagCollection.from_dict(
            {
                "test_dag1": {
                    "schedule_interval": "daily",
                    "default_args": {"owner": "test@example.org"},
                },
                "test_dag2": {"schedule_interval": "daily", "default_args": {}},
            }
        )

        assert len(dags.dags) == 2
        assert dags.dag_by_name("test_dag1") is not None
        assert dags.dag_by_name("test_dag2") is not None

        dag1 = dags.dag_by_name("test_dag1")
        assert len(dag1.tasks) == 0
        assert dag1.schedule_interval == "daily"
        assert dag1.default_args == {"owner": "test@example.org"}

        dag2 = dags.dag_by_name("test_dag2")
        assert len(dag2.tasks) == 0
        assert dag2.schedule_interval == "daily"
        assert dag2.default_args == {}

    def test_dags_from_empty_dict(self):
        dags = DagCollection.from_dict({})
        assert len(dags.dags) == 0

    def test_dags_from_invalid_dict(self):
        with pytest.raises(DagParseException):
            DagCollection.from_dict({"foo": "bar"})

    def test_dag_by_name(self):
        dags = DagCollection.from_dict(
            {"test_dag1": {"schedule_interval": "daily", "default_args": {}}}
        )

        assert dags.dag_by_name("test_dag1") is not None
        assert dags.dag_by_name("test_dag1").name == "test_dag1"
        assert dags.dag_by_name("non_existing") is None

    def test_dags_with_tasks(self):
        query_file = (
            TEST_DIR
            / "data"
            / "test_sql"
            / "test"
            / "incremental_query_v1"
            / "query.sql"
        )

        metadata = Metadata(
            "test",
            "test",
            {},
            {"dag_name": "test_dag", "depends_on_past": True, "param": "test_param"},
        )

        tasks = [Task(query_file, metadata)]

        dags = DagCollection.from_dict(
            {"test_dag": {"schedule_interval": "daily", "default_args": {}}}
        ).with_tasks(tasks)

        assert len(dags.dags) == 1

        dag = dags.dag_by_name("test_dag")
        assert len(dag.tasks) == 1
        assert dag.tasks[0].dag_name == "test_dag"

    def test_dags_with_invalid_tasks(self):
        with pytest.raises(InvalidDag):
            query_file = (
                TEST_DIR
                / "data"
                / "test_sql"
                / "test"
                / "incremental_query_v1"
                / "query.sql"
            )

            metadata = Metadata(
                "test",
                "test",
                {},
                {
                    "dag_name": "non_exisiting_dag",
                    "depends_on_past": True,
                    "param": "test_param",
                },
            )

            tasks = [Task(query_file, metadata)]

            DagCollection.from_dict(
                {"test_dag": {"schedule_interval": "daily", "default_args": {}}}
            ).with_tasks(tasks)
