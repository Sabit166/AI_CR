# Fifth step of Pipeline

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_fetch import fetch_exam_rows
from db_fetch import fetch_exam_rows_by_range

async def execute_exact_query(
    filter_column: str,
    matched_value: str,
    return_columns: list[str]
) -> list:

    return fetch_exam_rows(filter_column, matched_value, return_columns)


async def execute_range_query(
    filter_column: str,
    matched_range: dict[str, str],
    return_columns: list[str]
) -> list:

    return fetch_exam_rows_by_range(filter_column, matched_range, return_columns)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch exact Exams rows for a filter value.")
    parser.add_argument("filter_column", help="Column to filter on")
    parser.add_argument("matched_value", help="Exact value to match")
    parser.add_argument("return_columns", help="JSON array of columns to return")
    args = parser.parse_args()

    print(fetch_exam_rows(args.filter_column, args.matched_value, args.return_columns))