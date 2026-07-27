import os
from datetime import date
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

# Fourth step of Pipeline

async def match_to_db_value(
    user_message: str,
    filter_column: str,
    db_values: list[str]
) -> dict:
    
    values_list = "\n".join(f"- {v}" for v in db_values)
    today_date = date.today().strftime("%Y-%m-%d") # Date
    today_day = date.today().strftime("%A") # Day of the week
    
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=100,
        messages=[
            {
                "role": "system",
                "content": f"""You match a student's query to exact database values and identify what they want returned.

Today's date: {today_date}
Today's day: {today_day}
Filter column: {filter_column}
Available values in DB:
{values_list}

Return ONLY a JSON object:
{{
  "matched_value": "<exact value from the list above, or null if no match>",
  "return_columns": ["<col1>", "<col2>", "..."],
}}

Available return columns: "Course Code", "Course Title", "Course Teacher", 
"Course Section", "Exam Type", "Exam Day", "Exam Date", "Syllabus", 
"Exam Notes Drive Link"

You are provided with today's date and day, if student query is related to day and dates, you can return the following values if they exist in the database:
tomorrow: Return date column value for tomorrow's date (if exists in DB)
next week: Return date column value from next Sunday to next Thursday inclusive (if exists in DB)

Use ["*"] if student wants general info.

Examples of Return Columns:
"Tell me information about next exam" ->  ["*"]
"Give me next week updates about exams" -> ["*"]
"What is the date and syllabus for Fairooz miss's mid exam" -> ["Syllabus", "Exam Date"]
"What is the topic for the next exam" -> ["Syllabus"]
"Day and date of the CSE-415 Class Test one" -> ["Exam Day", "Exam Date"]
"The syllabus of CSE-415 mid is from which section?" -> ["Course Section"]
"Which section which course will the next exam be held in" -> ["Course Section", "Course Title"]
"When will be the next exam and what is the syllabus?" -> ["Exam Date", "Syllabus"]
"Give me notes for the next exam" -> ["Exam Notes Drive Link"]

Examples of Matched Values:
"Syllabus of CI mid exam"  "[Software Development Project, Computer Interfacing, Human Computer Interface, Computer Security]"  ->  "Computer Interfacing" (Short form "CI" is matched to full course name)
"CT-3 exam date of HCI"     "[Software Development Project, Computer Interfacing, Human Computer Interface, Computer Security]"  ->  "Computer Interfacing" (Short form "CI" is matched to full course name)
"Shahriar sir's CT-2 date"  "[Shahriar Sajjad, Fairooz Tasnia, Mahbubur Rahman]"  ->  "Shahriar Sajjad" (Short form "Shahriar sir" is matched to full name)
"Fairuz miss's CT-2 date"  "[Shahriar Sajjad, Fairooz Tasnia, Mahbubur Rahman]"  ->  "Fairooz Tasnia" (Short form "Fairuz miss" is matched to full name)
"Next week update"         "[Number of date records]"  ->  "All exams from next Sunday to next Thursday" (Next week is matched to the date range)

"""
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )
    
    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("OpenAI returned an empty response")

    return json.loads(content.strip())

"""
possible_queries = [
    "tell me information about next exam",
    "what is the syllabus for the next exam",
    "Tell me information about exams in upcoming week",
    "What will come in exam for the next CI exam",
    "Which is the next exam of Shahriar Sajjad sir",
    "When is the next exam",
    
]
"""


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Match a message to an Exams value and return columns.")
    parser.add_argument("message", help="User message to analyze")
    parser.add_argument("filter_column", help="Column used to filter the database")
    parser.add_argument("db_values", help="JSON array of available database values")
    args = parser.parse_args()

    print(asyncio.run(match_to_db_value(args.message, args.filter_column, args.db_values)))