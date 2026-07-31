import os
import json
from datetime import date, timedelta
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL")


def _require_model() -> str:
    if not MODEL:
        raise RuntimeError("MODEL must be set")
    return MODEL


def _build_date_context() -> dict:
    today    = date.today()
    day_name = today.strftime("%A")
    tomorrow = today + timedelta(days=1)

    days_to_thursday = (3 - today.weekday()) % 7
    this_thursday    = today + timedelta(days=days_to_thursday)

    days_to_sunday = (6 - today.weekday()) % 7 + 1
    next_sunday    = today + timedelta(days=days_to_sunday)
    next_thursday  = next_sunday + timedelta(days=4)

    if day_name in ["Friday", "Saturday"]:
        week_from = next_sunday
        week_to   = next_thursday
    else:
        week_from = today
        week_to   = this_thursday

    return {
        "today"        : today.isoformat(),
        "day_name"     : day_name,
        "tomorrow"     : tomorrow.isoformat(),
        "three_days"   : (today + timedelta(days=3)).isoformat(),
        "week_from"    : week_from.isoformat(),
        "week_to"      : week_to.isoformat(),
        "next_sunday"  : next_sunday.isoformat(),
        "next_thursday": next_thursday.isoformat(),
    }


async def match_to_db_value(
    user_message: str,
    filter_columns: list[str],
    column_values: dict[str, list[str]],
) -> dict:
    """
    Single LLM call that, given a (possibly multi-column) query:
      1. Matches the query text to the correct DB value(s) for EACH non-date filter column.
      2. Resolves any date term into a structured date filter (mode + target/range) —
         using ONLY the Python-computed date table below, never matching literal DB timestamps.
      3. Identifies which columns the student wants returned.

    Returns:
        {
          "column_matches": {"<column>": ["<value>", ...], ...},
          "date_filter": {"mode": "exact"|"nearest"|"range"|None, "target": str|None, "range": {...}|None},
          "return_columns": ["<column>", ...]
        }
    """

    d = _build_date_context()
    has_date_column = "Exam Date" in filter_columns

    columns_block_parts = []
    for column, values in column_values.items():
        values_list = "\n".join(f"    - {v}" for v in values)
        columns_block_parts.append(f"  {column}:\n{values_list}")
    columns_block = "\n\n".join(columns_block_parts) if columns_block_parts else "  (none — this query has no non-date filter columns)"

    system_prompt = f"""You are a query planner for a university exam chatbot.
A query can reference MULTIPLE filter columns at once (e.g. course + exam type + date).
Resolve EVERY filter column into a precise, structured filter.

━━━ DATE CONTEXT (use ONLY if Exam Date is a filter column) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Today            : {d['today']} ({d['day_name']})
Tomorrow         : {d['tomorrow']}
3 days later     : {d['three_days']}
This week        : {d['week_from']} → {d['week_to']}
Next week        : {d['next_sunday']} → {d['next_thursday']}
Exam Date is a filter for this query: {"YES" if has_date_column else "NO"}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ NON-DATE FILTER COLUMNS AND THEIR DB VALUES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{columns_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ OUTPUT FORMAT — return ONLY this JSON, nothing else ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "column_matches": {{
    "<column name>": ["<exact value(s) from that column's DB list above>"]
  }},
  "date_filter": {{
    "mode": "exact" | "nearest" | "range" | null,
    "target": "YYYY-MM-DD" or null,
    "range": {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}} or null
  }},
  "return_columns": ["<column>", ...]
}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ RULE A — non-date columns (Course Code, Course Title, Course Teacher, Course Section, Exam Type, Exam Day) ━━━
  - For EVERY such column shown above, pick the exact DB value(s) that match the query.
  - Match abbreviations, short forms, nicknames, honorifics, and typos to the full DB value.
  - A column can match MORE THAN ONE value if the query implies it (e.g. "CT-1 and CT-2").
  - If a listed column has no match in the query, still include it with an empty list — do not omit it.
  - NEVER invent a value that isn't in the DB list shown above.

  Examples:
    "CI exam"              + Course Title[Computer Interfacing, Human Computer Interface]        → ["Computer Interfacing"]
    "HCI and CI exam"      + Course Title[Computer Interfacing, Human Computer Interface]        → ["Computer Interfacing", "Human Computer Interface"]
    "Shahriar sir"         + Course Teacher[Shahriar Sajjad, Fairooz Tasnia]                     → ["Shahriar Sajjad"]
    "Mid exam of cse 415"  + Course Code[CSE-401, CSE-415] + Exam Type[Mid, Final, CT-1]         → Course Code: ["CSE-415"], Exam Type: ["Mid"]
    "Class Test 2 of HCI"  + Course Title[...] + Exam Type[CT-1, CT-2, Final]                    → Course Title: ["Human Computer Interface"], Exam Type: ["CT-2"]

━━━ RULE B — "Exam Date" column (date_filter) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Only fill this in if Exam Date is a filter for this query (see YES/NO flag above).
  Otherwise leave "date_filter": {{"mode": null, "target": null, "range": null}}.

  mode "exact"   → a single specific day. Use for: "today", "tomorrow", "next day", "three days later", "on 27 July"
                   target = the resolved YYYY-MM-DD from the date context above
  mode "nearest" → the closest upcoming exam. Use for: "next exam", "upcoming exam", "next <course/type> exam"
                   target = {d['today']}
  mode "range"   → a span of days. Use for: "this week", "next week", "weekly update"
                   range.from / range.to = the resolved dates from the date context above

━━━ RETURN COLUMNS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Available: "Course Code", "Course Title", "Course Teacher", "Course Section",
           "Exam Type", "Exam Day", "Exam Date", "Syllabus", "Exam Notes Drive Link"
Use ["*"] for general/info queries.

Examples:
  "next exam info"               → ["*"]
  "next week updates"            → ["*"]
  "syllabus for tomorrow"        → ["Syllabus"]
  "when is next exam"            → ["Exam Date"]
  "next CSE-401 exam"            → ["*"]
  "class test 2 of HCI syllabus" → ["Syllabus"]
  "notes for next exam"          → ["Exam Notes Drive Link"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=400,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message}
        ]
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("OpenAI returned an empty response")

    return json.loads(content.strip())


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Match a multi-column query to DB values.")
    parser.add_argument("message", help="User message to analyze")
    parser.add_argument("filter_columns", help="JSON array of filter columns")
    parser.add_argument("column_values", help="JSON object mapping column -> list of DB values")
    args = parser.parse_args()

    print(asyncio.run(match_to_db_value(
        args.message,
        json.loads(args.filter_columns),
        json.loads(args.column_values),
    )))