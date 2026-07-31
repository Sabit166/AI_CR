import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from Chatbot.Chatbot import chat
from db_fetch import create_exam, delete_exam, fetch_all_exams, update_exam

load_dotenv()

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
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
PROCESSED_MESSAGE_IDS: set[str] = set()


def _send_page_message(recipient_id: str, text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN must be set")

    url = f"https://graph.facebook.com/v23.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    request = UrlRequest(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            response.read()
    except HTTPError as error:
        raise RuntimeError(f"Failed to send Messenger reply: {error.code} {error.reason}") from error
    except URLError as error:
        raise RuntimeError(f"Failed to reach Facebook Graph API: {error.reason}") from error

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

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender = event.get("sender", {})
            message = event.get("message", {})
            message_id = message.get("mid")

            if message_id and message_id in PROCESSED_MESSAGE_IDS:
                continue

            if sender.get("id") and message and not message.get("is_echo"):
                user_message = message.get("text")
                if user_message:
                    if message_id:
                        PROCESSED_MESSAGE_IDS.add(message_id)
                    reply = await chat(user_message)
                    _send_page_message(sender["id"], reply)

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