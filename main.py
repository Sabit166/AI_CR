import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

import scheduler  # noqa: E402  (needs env loaded first)
from cr_api import router as cr_router  # noqa: E402
from discord_bot.events import router as discord_events_router  # noqa: E402
from discord_bot.interactions import router as discord_router  # noqa: E402
from public_api import router as public_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('aicr.main')


async def _scheduler_loop() -> None:
    logger.info('scheduler started (weekly %s Fri, reminders %s)', scheduler.weekly_time(), scheduler.reminder_time())
    while True:
        try:
            summary = await asyncio.to_thread(scheduler.run_tick)
            if any(k in summary for k in ('sent', 'failed', 'retry', 'db_error')):
                logger.info('scheduler tick: %s', summary)
        except Exception:
            logger.exception('scheduler tick failed')
        await asyncio.sleep(scheduler.TICK_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_scheduler_loop()) if scheduler.enabled() else None
    if task is None:
        logger.info('scheduler disabled (SCHEDULER_ENABLED=0 or no DISCORD_BOT_TOKEN)')
    yield
    if task:
        task.cancel()


app = FastAPI(title='AI CR', lifespan=lifespan)

# Comma-separated list of web app origins, e.g. https://ai-cr.vercel.app,http://localhost:5173
_origins = [o.strip() for o in os.getenv('CORS_ALLOW_ORIGINS', '').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ['*'],
    allow_origin_regex=os.getenv('CORS_ALLOW_ORIGIN_REGEX') or None,
    allow_credentials=False,  # editor links use a bearer token, never cookies
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
)
app.include_router(cr_router)
app.include_router(public_router)
app.include_router(discord_router)
app.include_router(discord_events_router)

# Run project: d:\AI_CR\env\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8001


@app.get("/")
@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.post('/cron/tick')
async def cron_tick(x_cron_secret: str | None = Header(default=None)) -> dict:
    """Run the automatic posts now. For an external cron; the in-process loop does the same."""
    secret = os.getenv('CRON_SECRET', '')
    if not secret:
        raise HTTPException(status_code=404)
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret, secret):
        raise HTTPException(status_code=403, detail='invalid cron secret')
    return {'result': await asyncio.to_thread(scheduler.run_tick)}
