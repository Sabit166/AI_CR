import json
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


# Sixth step of Pipeline

async def generate_answer(user_message: str, rows: list) -> str:
    
    context = json.dumps(rows, indent=2, default=str)
    
    response = client.chat.completions.create(
        model=_require_model(),
        max_tokens=400,
        messages=[
            {
                "role": "system",
                "content": f"""You are a friendly class representative assistant.
Answer the student's question using ONLY the data below.

Rules:
- Talk naturally, like a CR texting a classmate
- Never say "based on the data" or "according to the database"
- Format dates nicely (e.g. "27th July, Monday")
- If syllabus is long, break it into a clean list
- End with something helpful like "Good luck! 🍀" when relevant
- If data is missing, say so honestly

Data:
{context}"""
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

    return content


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Generate a natural-language answer from Exams rows.")
    parser.add_argument("message", help="User message to answer")
    parser.add_argument("rows", help="JSON array of row objects")
    args = parser.parse_args()

    print(asyncio.run(generate_answer(args.message, json.loads(args.rows))))