import os
import sys
from pathlib import Path
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
    
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=100,
        messages=[
            {
                "role": "system",
                "content": f"""You match a student's query to exact database values and identify what they want returned.

Filter column: {filter_column}
Available values in DB:
{values_list}

Return ONLY a JSON object:
{{
  "matched_value": "<exact value from the list above, or null if no match>",
  "return_columns": ["<col1>", "<col2>"]
}}

Available return columns: "Course Code", "Course Title", "Course Teacher", 
"Course Section", "Exam Type", "Exam Day", "Exam Date", "Syllabus", 
"Exam Notes Drive Link"

Use ["*"] if student wants general info."""
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


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Match a message to an Exams value and return columns.")
    parser.add_argument("message", help="User message to analyze")
    parser.add_argument("filter_column", help="Column used to filter the database")
    parser.add_argument("db_values", help="JSON array of available database values")
    args = parser.parse_args()

    print(asyncio.run(match_to_db_value(args.message, args.filter_column, json.loads(args.db_values))))