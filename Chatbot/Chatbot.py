import sys
import argparse
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .Classify_Query import classify_query
from .Fetch_Column_Values import fetch_column_values
from .Match_to_DB_Value import match_to_db_value
from .Execute_Combined_Query import execute_combined_query
from .Extract_Json_Response import extract_json_response


async def chat(req: str) -> str:

    # Step 1: Classify → relevant + ALL filter columns involved
    result = await classify_query(req)
    print(f"\n[Step 1 - Classify Query]\n{result}")

    if not result["relevant"]:
        return extract_json_response({"reply": "I can only answer questions about your exam topics."})

    filter_columns = result["filter_columns"]
    if not filter_columns:
        return extract_json_response({"reply": "Could you be more specific about your question?"})

    # Step 2: Fetch distinct DB values for every NON-DATE filter column
    column_values: dict[str, list[str]] = {}
    for column in filter_columns:
        if column == "Exam Date":
            continue
        values = await fetch_column_values(column)
        if values:
            column_values[column] = values
    print(f"\n[Step 2 - Fetch Column Values]\n{column_values}")

    # Step 3: ONE LLM call resolves every column together
    match = await match_to_db_value(req, filter_columns, column_values)
    print(f"\n[Step 3 - Match to DB Value]\n{match}")

    column_matches = match.get("column_matches") or {}
    date_filter = match.get("date_filter") or {}
    return_columns = match.get("return_columns") or ["*"]

    # Unresolved filter check
    unresolved = []
    for column in filter_columns:
        if column == "Exam Date":
            if not date_filter.get("mode"):
                unresolved.append("date")
        elif not column_matches.get(column):
            unresolved.append(column)

    if unresolved:
        return extract_json_response(
            {"reply": f"I couldn't match what you meant by {', '.join(unresolved)}. Could you double check it?"}
        )

    # Step 4: ONE combined query
    rows = await execute_combined_query(column_matches, date_filter, return_columns)
    print(f"\n[Step 4 - Execute Combined Query]\n{rows}")

    if not rows:
        return extract_json_response({"reply": "No exam records found for that."})

    # Step 5: Natural language answer
    final = extract_json_response({"reply": rows})
    print(f"\n[Step 5 - Final Answer]\n{final}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the exam bot.")
    parser.add_argument("message", help="User message to evaluate")
    args = parser.parse_args()

    print(asyncio.run(chat(args.message)))


if __name__ == "__main__":
    main()