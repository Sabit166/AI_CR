import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Chatbot.Classify_Query import classify_query
from Chatbot.Fetch_Column_Values import fetch_column_values
from Chatbot.Identify_Filter_Column import identify_filter_column
from Chatbot.Is_relevant import is_relevant
from Chatbot.Match_to_DB_Value import match_to_db_value
from Chatbot.Execute_Exact_Query import execute_exact_query
from Chatbot.Generate_Answer import generate_answer


async def chat(req) -> dict:
    
    # Step 1: Classify user query → relevant or not + filter column
    result = await classify_query(req)
    # → {"relevant": True, "filter_columns": ["Course Code"]}

    if not result["relevant"]:
        return {"reply": "I can only answer questions about your exam topics."}
    
    # Step 2: Fetch all distinct values of that column
    filter_column = result["filter_columns"][0]
    db_values = await fetch_column_values(filter_column)  # no LLM, pure Supabase
    
    if not db_values:
        return {"reply": "The database seems empty right now."}
    
    # Step 3: Match user input → exact DB value + return columns
    match = await match_to_db_value(req.message, filter_column, db_values)
    
    if not match["matched_value"]:
        return {"reply": "I couldn't find a match. Could you be more specific?"}
    
    # Step 4: Exact Supabase query (no LLM)
    rows = await execute_exact_query(
        filter_column,
        match["matched_value"],
        match["return_columns"]
    )
    
    if not rows:
        return {"reply": "No exam records found for that."}
    
    # Step 5: Natural language answer
    #answer = await generate_answer(req.message, rows)
    return {"reply": rows}