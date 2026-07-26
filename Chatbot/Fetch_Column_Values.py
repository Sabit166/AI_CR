# Third step of Pipeline

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_fetch import fetch_exam_column_values

async def fetch_column_values(column: str) -> list[str]:

    return fetch_exam_column_values(column)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch unique values for an Exams column.")
    parser.add_argument("column", help="Column name to fetch distinct values from")
    args = parser.parse_args()

    print(fetch_exam_column_values(args.column))