import os
from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL")



def _require_model() -> str:
    if not MODEL:
        raise RuntimeError("MODEL must be set")
    return MODEL

# Second step of Pipeline


async def identify_filter_column(user_message: str) -> str:
    
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=20,
        messages=[
            {
                "role": "system",
                "content": """You identify which database column a student is filtering by.

Columns: "Course Code", "Course Title", "Course Teacher", 
         "Course Section", "Exam Type", "Exam Day", "Exam Date"

Return ONLY the column name, nothing else.

Examples:
"Next exam of *name* sir/miss/madam"   → Course Teacher
"Next CI exam of Shahriar sir"         → Course Teacher
"When is the CSE-301 exam"             → Course Code
"Exam on Monday"                       → Exam Day
"What is in the midterm"               → Exam Type
"What exam tomorrow"                   → Exam Date
"Next week Schedule"                   → Exam Date
"Exam on 27 July"                      → Exam Date
"Give me next exam info"               → Exam Date"""
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

    return content.strip()


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Identify the filter column from a user message.")
    parser.add_argument("message", help="User message to analyze")
    args = parser.parse_args()

    print(asyncio.run(identify_filter_column(args.message)))