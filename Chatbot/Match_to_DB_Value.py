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
    today      = date.today()
    day_name   = today.strftime("%A")
    tomorrow   = today + timedelta(days=1)

    # "This week" → today to this Thursday
    days_to_thursday = (3 - today.weekday()) % 7
    this_thursday    = today + timedelta(days=days_to_thursday)

    # "Next week" → next Sunday to next Thursday
    days_to_sunday = (6 - today.weekday()) % 7 + 1
    next_sunday    = today + timedelta(days=days_to_sunday)
    next_thursday  = next_sunday + timedelta(days=4)

    # Point 1: if today is Friday or Saturday, "this week" = next Sunday to next Thursday
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
        "week_from"    : week_from.isoformat(),
        "week_to"      : week_to.isoformat(),
        "next_sunday"  : next_sunday.isoformat(),
        "next_thursday": next_thursday.isoformat(),
    }


# Fourth step of Pipeline
async def match_to_db_value(
    user_message: str,
    filter_column: str,
    db_values: list[str]
) -> dict:

    values_list = "\n".join(f"- {v}" for v in db_values)
    d = _build_date_context()

    system_prompt = f"""You are a query planner for a university exam chatbot.

━━━ DATE CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Today         : {d['today']} ({d['day_name']})
Tomorrow      : {d['tomorrow']}
This week     : {d['week_from']} → {d['week_to']} (Sunday–Thursday)
Next week     : {d['next_sunday']} → {d['next_thursday']} (Sunday–Thursday)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Filter column : {filter_column}
DB values     :
{values_list}

Match the student query to DB values and identify what columns to return.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY this JSON, nothing else:
{{
  "matched_values" : ["<exact value from DB list>", ...],
  "matched_range"  : {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}} or null,
  "return_columns" : ["<col>", ...]
}}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ MATCHING RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[Non-date filters] → use "matched_values", set "matched_range" to null
  - Match ALL DB values that fit (can be more than one)
  - Match abbreviations, short forms, nicknames, and typos to full DB names
  - Examples:
      "CI exam"         + [Computer Interfacing, Human Computer Interface] → ["Computer Interfacing"]
      "HCI and CI exam" + [Computer Interfacing, Human Computer Interface] → ["Computer Interfacing", "Human Computer Interface"]
      "Shahriar sir"    + [Shahriar Sajjad, Fairooz Tasnia]               → ["Shahriar Sajjad"]
      "Fairuz miss"     + [Shahriar Sajjad, Fairooz Tasnia]               → ["Fairooz Tasnia"]
      "CT exams"        + [CT-1, CT-2, Midterm]                           → ["CT-1", "CT-2"]

[Date filters] → use "matched_range", set "matched_values" to []
  Resolve these terms using the date context above:

  Term                          → Range
  ─────────────────────────────────────────────────
  "today"                       → {d['today']} to {d['today']}
  "tomorrow" / "next day"       → {d['tomorrow']} to {d['tomorrow']}
  "next exam" / "upcoming exam" → {d['today']} to {d['today']} + 7 days (find nearest)
  "X days later" / "in X days"  → today + X days (single date)
  "three days later"            → {(date.fromisoformat(d['today']) + timedelta(days=3)).isoformat()} (single date)
  "this week" / "weekly update" → {d['week_from']} to {d['week_to']}
  "next week"                   → {d['next_sunday']} to {d['next_thursday']}
  ─────────────────────────────────────────────────
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ RETURN COLUMNS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Available: "Course Code", "Course Title", "Course Teacher",
           "Course Section", "Exam Type", "Exam Day", "Exam Date",
           "Syllabus", "Exam Notes Drive Link"

Use ["*"] for general/info queries.

Examples:
  "next exam info"                              → ["*"]
  "next week updates"                           → ["*"]
  "syllabus for Fairooz miss's mid"             → ["Syllabus", "Exam Date"]
  "topic for next exam"                         → ["Syllabus"]
  "day and date of CSE-415 CT-1"                → ["Exam Day", "Exam Date"]
  "syllabus of CSE-415 mid, which section?"     → ["Course Section"]
  "next exam date and syllabus"                 → ["Exam Date", "Syllabus"]
  "notes for next exam"                         → ["Exam Notes Drive Link"]
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

    return json.loads(content.strip())


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