import sys
import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .Classify_Query import classify_query
from .Fetch_Column_Values import fetch_column_values
from .Identify_Filter_Column import identify_filter_column
from .Is_relevant import is_relevant
from .Match_to_DB_Value import match_to_db_value
from .Execute_Exact_Query import execute_exact_query, execute_range_query
from .Generate_Answer import generate_answer
from .Extract_Json_Response import extract_json_response


async def chat(req) -> str:
    
    # Step 1: Classify user query → relevant or not + filter column
    result = await classify_query(req)
    # → {"relevant": True, "filter_columns": ["Course Code"]}

    if not result["relevant"]:
        return extract_json_response({"reply": "I can only answer questions about your exam topics."})
    
    # Step 2: Fetch all distinct values of that column
    filter_column = result["filter_column"]  # only one column is returned
    db_values = await fetch_column_values(filter_column)  # no LLM, pure Supabase
    
    if not db_values:
        return extract_json_response({"reply": "The database seems empty right now."})
    
    # Step 3: Match user input → exact DB value + return columns
    match = await match_to_db_value(req, filter_column, db_values)

    matched_values = match.get("matched_values") or []
    matched_range = match.get("matched_range")
    return_columns = match.get("return_columns") or ["*"]

    if not matched_values and not matched_range:
        return extract_json_response({"reply": "I couldn't find a match. Could you be more specific?"})

    # Step 4: Exact Supabase query (no LLM)
    if matched_range:
        rows = await execute_range_query(
            filter_column,
            matched_range,
            return_columns,
        )
    else:
        rows = []
        seen_rows: set[str] = set()
        for matched_value in matched_values:
            for row in await execute_exact_query(filter_column, matched_value, return_columns):
                row_key = json.dumps(row, sort_keys=True, default=str)
                if row_key not in seen_rows:
                    seen_rows.add(row_key)
                    rows.append(row)
    
    if not rows:
        return extract_json_response({"reply": "No exam records found for that."})
    
    # Step 5: Natural language answer
    #answer = await generate_answer(req.message, rows)
    return extract_json_response({"reply": rows})

def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a message is relevant to the exam chatbot.")
    parser.add_argument("message", help="User message to evaluate")
    args = parser.parse_args()
    
    print(asyncio.run(chat(args.message)))


if __name__ == "__main__":
    main()