"""Calculate percentiles for scalars."""
from argparse import ArgumentParser
from itertools import combinations
from typing import List

from jinja2 import Environment, PackageLoader

from bigquery_etl.format_sql.formatter import reformat


def render_query(attributes: List[str], **kwargs) -> str:
    """Render the main query."""
    env = Environment(loader=PackageLoader("bigquery_etl", "glam/templates"))
    sql = env.get_template("scalar_percentiles_v1.sql")

    max_combinations = len(attributes) + 1
    attribute_combinations = []
    for subset_size in reversed(range(max_combinations)):
        for grouping in combinations(attributes, subset_size):
            select_expr = []
            for attribute in attributes:
                select_expr.append((attribute, attribute in grouping))
            attribute_combinations.append(select_expr)

    return reformat(sql.render(attribute_combinations=attribute_combinations, **kwargs))


def glean_variables():
    """Variables for bucket_counts."""
    return dict(
        attributes=["ping_type", "os", "app_version", "app_build_id", "channel"],
        aggregate_attributes="""
            metric,
            metric_type,
            key
        """,
    )


def main():
    """Generate query."""
    parser = ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--source-table", default="glam_etl.fenix_clients_scalar_aggregates_v1"
    )
    args = parser.parse_args()
    module_name = "bigquery_etl.glam.scalar_percentiles"
    header = f"-- generated by: python3 -m {module_name}"
    header += " " + " ".join(
        [f"--{k} {v}" for k, v in vars(args).items() if k != "init"]
    )
    print(
        render_query(header=header, source_table=args.source_table, **glean_variables())
    )


if __name__ == "__main__":
    main()
