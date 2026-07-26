import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Chatbot.Fetch_Column_Values import fetch_column_values
from Chatbot.Identify_Filter_Column import identify_filter_column
from Chatbot.Is_relevant import is_relevant
from Chatbot.Match_to_DB_Value import match_to_db_value
from Chatbot.Execute_Exact_Query import execute_exact_query
from Chatbot.Generate_Answer import generate_answer


async def chat(req) -> dict:
    
    # Step 1: Guard
    if not await is_relevant(req.message):
        return {"reply": "I can only answer questions about your exam schedule, syllabus, and related topics."}
    
    # Step 2: Identify filter column
    filter_column = await identify_filter_column(req.message)
    
    # Step 3: Fetch all distinct values of that column
    db_values = await fetch_column_values(filter_column)  # no LLM, pure Supabase
    
    if not db_values:
        return {"reply": "The database seems empty right now."}
    
    # Step 4: Match user input → exact DB value + return columns
    match = await match_to_db_value(req.message, filter_column, db_values)
    
    if not match["matched_value"]:
        return {"reply": "I couldn't find a match. Could you be more specific?"}
    
    # Step 5: Exact Supabase query (no LLM)
    rows = await execute_exact_query(
        filter_column,
        match["matched_value"],
        match["return_columns"]
    )
    
    if not rows:
        return {"reply": "No exam records found for that."}
    
    # Step 6: Natural language answer
    answer = await generate_answer(req.message, rows)
    return {"reply": answer}