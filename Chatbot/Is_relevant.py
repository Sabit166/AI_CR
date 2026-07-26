import os
from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL")

# First step of Pipeline


def _require_model() -> str:
    if not MODEL:
        raise RuntimeError("MODEL must be set")
    return MODEL


async def is_relevant(user_message: str) -> bool:
    
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=10,
        messages=[
            {
                "role": "system",
                "content": """You are a guard for an exam information chatbot.
The chatbot ONLY answers questions about:
- Exams on next daysor weeks
- Exam schedule, dates, times
- Exams, exam syllabus and topics
- Course teachers
- Course codes and titles (CSE-415, CSE-429, etc.)
- Exam types (midterm, final, CT, Mid, Presentation, Assignment, Quiz)
- Exam notes

Reply ONLY with "YES" if the question is relevant, "NO" if not."""
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

    return content.strip().upper() == "YES"


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Check whether a message is relevant to the exam chatbot.")
    parser.add_argument("message", help="User message to evaluate")
    args = parser.parse_args()

    print(asyncio.run(is_relevant(args.message)))