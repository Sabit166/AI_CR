import hashlib
import hmac
import json
import logging
import os
from collections import OrderedDict
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

load_dotenv()

from Chatbot.Chatbot import answer  # noqa: E402  (needs env loaded first)
from cr_api import router as cr_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('aicr.webhook')

app = FastAPI(title='AI CR')

# Comma-separated list of dashboard origins, e.g. https://ai-cr.vercel.app,http://localhost:5173
_origins = [o.strip() for o in os.getenv('CORS_ALLOW_ORIGINS', '').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ['*'],
    allow_origin_regex=os.getenv('CORS_ALLOW_ORIGIN_REGEX') or None,
    allow_credentials=False,  # auth uses a bearer token, never cookies
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
)
app.include_router(cr_router)

# Run project: d:\AI_CR\env\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8001

VERIFY_TOKEN = os.getenv('MESSENGER_VERIFY_TOKEN', 'exam_bot_verify_2026')
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
# Facebook App Secret. When set, webhook POSTs must carry a valid X-Hub-Signature-256.
APP_SECRET = os.getenv('MESSENGER_APP_SECRET')

_MAX_REMEMBERED_IDS = 2000
_processed_ids: OrderedDict[str, None] = OrderedDict()
_processed_lock = Lock()


def _first_time_seen(message_id: str) -> bool:
    """Messenger retries deliveries; remember recent message ids (bounded) to answer once."""
    with _processed_lock:
        if message_id in _processed_ids:
            return False
        _processed_ids[message_id] = None
        while len(_processed_ids) > _MAX_REMEMBERED_IDS:
            _processed_ids.popitem(last=False)
        return True


def _send_page_message(recipient_id: str, text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN must be set")

    url = f"https://graph.facebook.com/v23.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
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


def _reply_to(sender_id: str, user_message: str) -> None:
    """Runs after the webhook has already returned 200 to Facebook."""
    reply = answer(user_message)
    for part in reply.messages:
        try:
            _send_page_message(sender_id, part)
        except RuntimeError as error:
            logger.error('could not deliver reply part: %s', error)
            break


@app.get("/")
@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def verify(request: Request):
    # Facebook sends hub.mode / hub.verify_token / hub.challenge; the underscore
    # spelling is accepted too for compatibility with the original handler.
    params = request.query_params
    hub_verify_token = params.get('hub.verify_token') or params.get('hub_verify_token')
    hub_challenge = params.get('hub.challenge') or params.get('hub_challenge') or ''
    if hub_verify_token and hmac.compare_digest(hub_verify_token, VERIFY_TOKEN):
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    if APP_SECRET:
        signature = request.headers.get('X-Hub-Signature-256', '')
        expected = 'sha256=' + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=403, detail='Invalid signature')

    try:
        data = json.loads(body or b'{}')
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail='Invalid JSON') from error

    queued = 0
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender = event.get("sender", {})
            message = event.get("message", {})
            message_id = message.get("mid")

            if not sender.get("id") or not message or message.get("is_echo"):
                continue
            user_message = message.get("text")
            if not user_message:
                continue
            if message_id and not _first_time_seen(message_id):
                continue
            background_tasks.add_task(_reply_to, sender["id"], user_message)
            queued += 1

    logger.info('webhook received: %d message(s) queued', queued)
    return {"status": "ok"}
