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
    """
    Single LLM call that:
      1. Checks whether the message is relevant to the exam chatbot.
      2. If relevant, identifies the single database column the user is filtering by.

    Returns:
        {
            "relevant": bool,
            "filter_column": str    # empty string if not relevant
        }
    """
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=60,
        messages=[
            {
                "role": "system",
                "content": """You are an intelligent guard and query classifier for a university exam information chatbot.

## Your Two Jobs (done in one step)

### Job 1 — Relevance Check
Decide if the student's message is relevant to the chatbot's scope:
RELEVANT topics:
  - Upcoming exam schedules, dates, times, and days
  - Exam types: Class Test (CT-1/2/3), Mid, Final, Quiz, Assignment, Project Update, Project Presentation
  - Exam syllabus and topics
  - Course teachers, course codes (e.g. CSE-415), and course titles
  - Course sections
  - Exam notes

NOT RELEVANT: anything outside the above (greetings, general questions, unrelated topics).

### Job 2 — Filter Column Identification (only if relevant)
If relevant, identify the single best database column the user is filtering by.

Available columns:
  "Course Code"     — e.g. CSE-415, CSE-429
  "Course Title"    — e.g. HCI, SDP, CI
  "Course Teacher"  — e.g. Shahriar sir, Mahbub sir
  "Course Section"  — e.g. section A, B
  "Exam Type"       — CT-1/2/3, Mid, Final, Quiz, Assignment, Project Update, Project Presentation
  "Exam Day"        — e.g. Monday, Sunday
  "Exam Date"       — e.g. 27 July, tomorrow, next week

Priority rules when multiple columns are implied — pick only ONE:
  - Course Code   beats  Course Title  beats  Exam Type
  - Course Teacher beats  Exam Type
  - Explicit date/day references → Exam Date / Exam Day
  - Schedule with no specific course → Exam Date

Examples:
  "When is CSE-429 Class Test 2"         → "Course Code"
  "Syllabus of next CT-3 of Mahbub sir"  → "Course Teacher"
  "Class Test-3 exam date of HCI"        → "Course Title"
  "Which section is the next exam in"    → "Course Section"
  "When is the next CI Project Update"   → "Course Title"
  "Next week schedule"                   → "Exam Date"
  "Exam on 27 July"                      → "Exam Date"
  "Give me next exam info"               → "Exam Date"
  "Hello, how are you"                   → not relevant

## Output Format
Respond ONLY with a valid JSON object — no explanation, no markdown:
{
  "relevant": true | false,
  "filter_column": "Column Name" | ""
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
    filter_column = result.get("filter_column", "") if relevant else ""

    return {
        "relevant": relevant,
        "filter_column": filter_column,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Classify a student query — relevance check + filter column identification."
    )
    parser.add_argument("message", help="User message to classify")
    args = parser.parse_args()

    output = asyncio.run(classify_query(args.message))
    print(json.dumps(output, indent=2))