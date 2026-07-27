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
Exam Types: "Class Test (one, two, three)", "Mid", "Final", "Project Update", "Project Presentation",  "Quiz", "Assignment"

Return ONLY the column name, nothing else. If multiple columns, choose only one from the columns.

Examples:
"Next exam of *name* sir/miss/madam"   → Course Teacher 
"Next CI exam of Shahriar sir"         → Course Teacher
"Class Test-3 exam date of HCI"                → Course Title, Exam Type → Course Title
"Syllabus of next CT-3 of Mahbub sir" → Course Teacher, Exam Type → Exam  Type
"Which day is SDP Project Update"      → Course Title, Exam Type → Course Title
"Syllabus of CI mid exam"              → Course Title, Exam Type  → Course Title
"When is CSE-429 Class Test 2"                 → Course Code, Exam Type → Course Code
"When is the CSE-305 mid exam"         → Course Code, Exam Type → Course Code
"CSE 464 Project Update topics"        → Course Code, Exam Type → Course Code
"Which section will the next exam be held in" → Course Section
"When is the next mid of Shahriar sir" → Course Teacher, Exam Type → Course Teacher
"When is the next CI Project Update"   → Exam Type
"Syllabus of tomorrow's HCI exam"      → Course Title, Exam Date → Course Title
"Next week Schedule"                   → Exam Date
"Exam on 27 July"                      → Exam Date
"Give me next exam info"               → Exam Date

If the user message does not match any of the columns, return "Unknown".

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

    return content.strip()

if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Identify the filter column from a user message.")
    parser.add_argument("message", help="User message to analyze")
    args = parser.parse_args()

    print(asyncio.run(identify_filter_column(args.message)))