import os
import json
import asyncio
import argparse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL")


def _require_model() -> str:
    if not MODEL:
        raise RuntimeError("MODEL env var must be set")
    return MODEL


async def classify_query(user_message: str) -> dict:
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=120,
        messages=[
            {
                "role": "system",
                "content": """You are an intelligent guard and query classifier for a university exam information chatbot.

## Job 1 — Relevance Check
Decide if the student's message is relevant to the chatbot's scope:
RELEVANT topics:
  - Upcoming exam schedules, dates, times, and days
  - Exam types: Class Test (CT-1/2/3), Mid, Final, Quiz, Assignment, Project Update, Project Presentation
  - Exam syllabus and topics
  - Course teachers, course codes (e.g. CSE-415), and course titles
  - Course sections
  - Exam notes

NOT RELEVANT: anything outside the above (greetings, general questions, unrelated topics).

## Job 2 — Filter Column Identification (only if relevant)
A query can reference MORE THAN ONE column at once — identify EVERY column the user is FILTERING BY.

Available columns:
  "Course Code"     — e.g. CSE-415, CSE-429
  "Course Title"    — e.g. HCI, SDP, CI, Human Computer Interface
  "Course Teacher"  — e.g. Shahriar sir, Mahbub sir
  "Course Section"  — e.g. section A, B
  "Exam Type"       — CT-1/2/3, Mid, Final, Quiz, Assignment, Project Update, Project Presentation
  "Exam Day"        — an EXPLICIT weekday name only, e.g. "exams on Monday"
  "Exam Date"       — ONLY when the query contains an actual date-filtering EXPRESSION

### CRITICAL DISTINCTION — filtering BY a date vs. asking FOR a date
  Do NOT add "Exam Date" just because the words "date", "exam date", "when", or "day" appear
  in the query. Those words often mean the student wants the date told to them
  (a RETURN value), not that they're filtering by a date.

  Only add "Exam Date" as a filter column if the query contains an actual date
  EXPRESSION to filter on, such as:
    - "tomorrow", "today", "next day"
    - "next" (as in "next exam", "next CT")
    - "this week", "next week"
    - "in 3 days", "three days later"
    - an explicit calendar date, e.g. "on 27 July"

  Compare:
    "Human Computer Interface Mid exam date"
      → student wants to KNOW the date, not filter by one → filter_columns: ["Course Title", "Exam Type"]
      (no date expression like "next"/"tomorrow"/explicit date present)

    "When is the next Human Computer Interface Mid exam"
      → "next" is a date expression → filter_columns: ["Course Title", "Exam Type", "Exam Date"]

    "HCI Mid exam on 27 July"
      → explicit date given → filter_columns: ["Course Title", "Exam Type", "Exam Date"]

    "What is the date of the CSE-415 Final exam"
      → asking to be TOLD the date, no filtering expression → filter_columns: ["Course Code", "Exam Type"]

### Other rules
  - Course referenced by abbreviation/short form (CI, HCI, DS) → "Course Title"
  - Course referenced by code pattern (CSE-XXX) → "Course Code"
   - Only add "Exam Type" if the query contains an EXPLICIT exam type keyword such as:
    CT, CT-1, CT-2, CT-3, Class Test, Mid, Midterm, Final, Quiz, Assignment,
    Project Update, Project Presentation
  - The word "exam" alone is NOT an exam type — do NOT add "Exam Type" just because the word "exam" appears in the query.
  - An unknown or unrecognized word (e.g. "GEEM", "MATH", "PHY") is NOT an exam type. If it looks like a department prefix or course abbreviation, treat it as "Course Title" or "Course Code", NOT "Exam Type".
  - "Exam Type" must only be added when the exam type keyword is unambiguous and explicit. When in doubt, do NOT add "Exam Type".
  Compare:
    "On which date is the next HCI exam"     → "exam" alone → do NOT add "Exam Type"
    "On which date is the next HCI Mid exam" → "Mid" is explicit → ADD "Exam Type"
    "Next CT-2 of CSE-415"                   → "CT-2" is explicit → ADD "Exam Type"
  - Any teacher name/nickname/honorific (sir/miss) → "Course Teacher"
  - An explicit weekday name with no relative-date computation implied → "Exam Day"
  - If a listed column has no filtering signal in the query, do not include it.

Examples:
  "When is CSE-429 Class Test 2"              → ["Course Code", "Exam Type"]
  "Syllabus of next CT-3 of Mahbub sir"       → ["Exam Type", "Course Teacher", "Exam Date"]
  "Class Test-3 exam date of HCI"             → ["Exam Type", "Course Title"]
  "Human Computer Interface Mid exam date"    → ["Course Title", "Exam Type"]
  "Which section is the next exam in"         → ["Exam Date"]
  "When is the next CI Project Update"        → ["Course Title", "Exam Type", "Exam Date"]
  "Next week schedule"                        → ["Exam Date"]
  "Exam on 27 July"                           → ["Exam Date"]
  "Give me next exam info"                    → ["Exam Date"]
  "Next CSE-401 exam"                         → ["Course Code", "Exam Date"]
  "Mid exam of cse 415"                       → ["Exam Type", "Course Code"]
  "Exams on Monday"                           → ["Exam Day"]
  "On which date is the next HCI exam"        → ["Course Title", "Exam Date"]
  "Next GEEM exam date"                       → ["Course Title", "Exam Date"]
  "Next GEEM-433 exam date"                   → ["Course Code", "Exam Date"]
  "Hello, how are you"                        → not relevant

## Output Format
Respond ONLY with a valid JSON object — no explanation, no markdown:
{
  "relevant": true | false,
  "filter_columns": ["Column Name", ...]
}"""
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("LLM returned an empty response")

    try:
        result = json.loads(content.strip())
    except json.JSONDecodeError:
        raise RuntimeError(f"LLM returned non-JSON output: {content!r}")

    relevant = bool(result.get("relevant", False))
    filter_columns = result.get("filter_columns", []) if relevant else []

    return {
        "relevant": relevant,
        "filter_columns": filter_columns,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Classify a student query — relevance check + ALL filter columns."
    )
    parser.add_argument("message", help="User message to classify")
    args = parser.parse_args()

    output = asyncio.run(classify_query(args.message))
    print(json.dumps(output, indent=2))