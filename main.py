from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

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