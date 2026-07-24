from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from db_fetch import create_exam, delete_exam, fetch_all_exams, update_exam

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Run project: d:\AI_CR\env\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8001

VERIFY_TOKEN = "exam_bot_verify_2026"

@app.get("/webhook")
async def verify(
    hub_mode: str ,
    hub_verify_token: str ,
    hub_challenge: str
):
    if hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Verification failed", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print(data)
    return {"status": "ok"}


@app.get("/exams")
async def get_exams():
    try:
        return {"records": fetch_all_exams()}
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post('/exams')
async def add_exam(request: Request):
    payload = await request.json()
    try:
        return create_exam(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.patch('/exams/{exam_id}')
async def edit_exam(exam_id: int, request: Request):
    payload = await request.json()
    try:
        return update_exam(exam_id, payload)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.delete('/exams/{exam_id}')
async def remove_exam(exam_id: int):
    try:
        return delete_exam(exam_id)
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error