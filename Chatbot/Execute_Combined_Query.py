import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_fetch import fetch_exams


def _day_bounds(day_str: str) -> tuple[str, str]:
    return f"{day_str}T00:00:00", f"{day_str}T23:59:59"


async def execute_combined_query(
    column_matches: dict[str, list[str]],
    date_filter: dict,
    return_columns: list[str],
) -> list[dict]:
    """
    Builds and runs ONE combined Supabase query:
      - AND across different columns (Course Code AND Exam Type, etc.)
      - OR within a single column's multiple matched values
      - special two-step handling for "nearest exam" so ties on the same
        date are all returned, not just one row
    """

    # Non-date filters first — AND across columns, OR (in.) within one column
    filters: dict[str, dict] = {}
    for column, values in column_matches.items():
        if not values:
            continue
        if len(values) == 1:
            filters[column] = {"op": "eq", "value": values[0]}
        else:
            filters[column] = {"op": "in", "values": values}

    if return_columns == ["*"]:
        select_columns = ["*"]
    else:
        select_columns = list(dict.fromkeys(return_columns + ["Course Title", "Course Code"]))

    mode = date_filter.get("mode")

    # Single specific day (today / tomorrow / 3 days later / explicit date)
    if mode == "exact" and date_filter.get("target"):
        start, end = _day_bounds(date_filter["target"])
        filters["Exam Date"] = {"op": "range", "from": start, "to": end}
        return fetch_exams(select_columns=select_columns, filters=filters, order="Exam Date.asc")

    # A span of days (this week / next week)
    if mode == "range" and date_filter.get("range"):
        start, _ = _day_bounds(date_filter["range"]["from"])
        _, end = _day_bounds(date_filter["range"]["to"])
        filters["Exam Date"] = {"op": "range", "from": start, "to": end}
        return fetch_exams(select_columns=select_columns, filters=filters, order="Exam Date.asc")

    # Nearest upcoming exam — two-step, so ties on the same date are all returned
    if mode == "nearest" and date_filter.get("target"):
        probe_filters = dict(filters)
        probe_filters["Exam Date"] = {"op": "gte", "value": f"{date_filter['target']}T00:00:00"}

        earliest = fetch_exams(
            select_columns=["Exam Date"],
            filters=probe_filters,
            order="Exam Date.asc",
            limit=1,
        )
        if not earliest:
            return []

        earliest_date = earliest[0]["Exam Date"][:10]
        start, end = _day_bounds(earliest_date)
        filters["Exam Date"] = {"op": "range", "from": start, "to": end}
        return fetch_exams(select_columns=select_columns, filters=filters)

    # No date filter at all — plain multi-column match
    return fetch_exams(select_columns=select_columns, filters=filters)