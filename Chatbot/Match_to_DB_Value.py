import os
from datetime import date, timedelta
from dotenv import load_dotenv
from openai import OpenAI
import json

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


def _parse_db_values(db_values: list[str] | str) -> list[str]:
    if isinstance(db_values, list):
        return db_values
    try:
        return json.loads(db_values)
    except json.JSONDecodeError:
        return json.loads(db_values.replace("'", '"'))


# Python matches DB values by date prefix — no LLM involved
def _match_dates_from_db(target_date: str, db_values: list[str]) -> list[str]:
    return [v for v in db_values if v.startswith(target_date)]


def _find_nearest_date(db_values: list[str], from_date: str) -> list[str]:
    future = sorted([v for v in db_values if v[:10] >= from_date])
    if not future:
        return []
    nearest_date = future[0][:10]
    return [v for v in future if v.startswith(nearest_date)]


async def match_to_db_value(
    user_message: str,
    filter_column: str,
    db_values: list[str] | str
) -> dict:

    parsed_values = _parse_db_values(db_values)
    values_list   = "\n".join(f"- {v}" for v in parsed_values)
    d             = _build_date_context()

    system_prompt = f"""You are a query planner for a university exam chatbot.

━━━ DATE CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Today         : {d['today']} ({d['day_name']})
Tomorrow      : {d['tomorrow']}
3 days later  : {d['three_days']}
This week     : {d['week_from']} → {d['week_to']}
Next week     : {d['next_sunday']} → {d['next_thursday']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Filter column : {filter_column}
DB values     :
{values_list}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY this JSON, nothing else:
{{
  "date_target"    : "<YYYY-MM-DD if query is date-based, else null>",
  "date_mode"      : "<'exact' | 'nearest' | 'range' | null>",
  "range"          : {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}} or null,
  "matched_values" : ["<exact value from DB list>"],
  "return_columns" : ["<col>", ...]
}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ DATE MODE RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use date_mode "exact" + date_target for:
  "today"              → date_target: {d['today']}
  "tomorrow"/"next day"→ date_target: {d['tomorrow']}
  "three days later"   → date_target: {d['three_days']}
  Leave matched_values as [] — Python will fill it.

Use date_mode "nearest" for:
  "next exam" / "upcoming exam" / "which exam is next"
  → date_target: {d['today']}
  Leave matched_values as [] — Python will fill it.

Use date_mode "range" + range for:
  "this week"  → range: {d['week_from']} to {d['week_to']}
  "next week"  → range: {d['next_sunday']} to {d['next_thursday']}
  "in X days"  → range: today+X to today+X
  Leave matched_values as [] — Python will fill it.

━━━ NON-DATE RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For Course Title, Course Teacher, Exam Type etc:
  → date_target: null, date_mode: null, range: null
  → Pick ALL matching DB values into matched_values
  → Match abbreviations, nicknames, typos to full names

  Examples:
  "CI exam"      + [Computer Interfacing, Human Computer Interface] → ["Computer Interfacing"]
  "HCI and CI"   + [Computer Interfacing, Human Computer Interface] → ["Computer Interfacing", "Human Computer Interface"]
  "Shahriar sir" + [Shahriar Sajjad, Fairooz Tasnia]               → ["Shahriar Sajjad"]
  "Fairuz miss"  + [Shahriar Sajjad, Fairooz Tasnia]               → ["Fairooz Tasnia"]
  "CT exams"     + [CT-1, CT-2, Midterm]                           → ["CT-1", "CT-2"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ RETURN COLUMNS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Available: "Course Code", "Course Title", "Course Teacher",
           "Course Section", "Exam Type", "Exam Day", "Exam Date",
           "Syllabus", "Exam Notes Drive Link"

Use ["*"] for general/info queries.

Examples:
  "next exam info"              → ["*"]
  "next week updates"           → ["*"]
  "what exam is tomorrow"       → ["Course Title", "Course Code"]
  "which course exam tomorrow"  → ["Course Code", "Course Title"]
  "syllabus for tomorrow"       → ["Syllabus"]
  "when is next exam"           → ["Exam Date"]
  "day and date of CSE-415 CT"  → ["Exam Day", "Exam Date"]
  "notes for next exam"         → ["Exam Notes Drive Link"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=150,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message}
        ]
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("OpenAI returned an empty response")

    result = json.loads(content.strip())

    # Python fills matched_values based on date_mode — LLM never does this
    if result.get("date_mode") == "exact" and result.get("date_target"):
        result["matched_values"] = _match_dates_from_db(result["date_target"], parsed_values)

    elif result.get("date_mode") == "nearest" and result.get("date_target"):
        result["matched_values"] = _find_nearest_date(parsed_values, result["date_target"])

    elif result.get("date_mode") == "range" and result.get("range"):
        from_date = result["range"]["from"]
        to_date   = result["range"]["to"]
        result["matched_values"] = [
            v for v in parsed_values
            if from_date <= v[:10] <= to_date
        ]

    return result


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Match a message to DB values and return columns.")
    parser.add_argument("message",       help="User message to analyze")
    parser.add_argument("filter_column", help="Column used to filter the database")
    parser.add_argument("db_values",     help="JSON array of available database values")
    args = parser.parse_args()

    print(asyncio.run(match_to_db_value(
        args.message,
        args.filter_column,
        args.db_values
    )))