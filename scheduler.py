"""Automatic posts in each class channel (Asia/Dhaka time):

* Friday at WEEKLY_UPDATE_TIME (default 18:00): next week's exams. If the server
  was down then, it is sent as soon as it is back, until Saturday night.
* At EXAM_REMINDER_TIME (default 20:00) the day before an exam day: every exam
  on that day, with times. Sent until midnight if the server was down at 20:00;
  an exam added later that evening still gets its reminder.

`run_tick()` is called every minute by a background loop in the web process
(main.py) and can also be triggered externally (POST /cron/tick). Each post is
claimed in public.class_notifications before sending, so it goes out once per
class even with restarts, several instances or both triggers at the same time.

Every RECONCILE_SECONDS the tick also checks which servers the bot is still in
(Discord sends HTTP-only bots no event when they are removed) and deactivates
the classes of servers it has left; a post that fails because the channel was
deleted deactivates that class too. Deactivated classes keep their data and
come back with /setup in the same channel.
"""
from __future__ import annotations

import logging
import os
import time as clock
from datetime import datetime, time, timedelta

import date_ranges as dr
import db_fetch
import updates
from discord_bot import client

logger = logging.getLogger('aicr.scheduler')

FRIDAY, SATURDAY = 4, 5
TICK_SECONDS = 60
RECONCILE_SECONDS = 300
_last_reconcile = float('-inf')

_finished: set[tuple[int, str]] = set()  # claims this process already saw; skips repeat queries


def _env_time(name: str, default: str) -> time:
    raw = os.getenv(name, default)
    try:
        return datetime.strptime(raw.strip(), '%H:%M').time()
    except ValueError:
        logger.warning('%s=%r is not HH:MM; using %s', name, raw, default)
        return datetime.strptime(default, '%H:%M').time()


def weekly_time() -> time:
    return _env_time('WEEKLY_UPDATE_TIME', '18:00')


def reminder_time() -> time:
    return _env_time('EXAM_REMINDER_TIME', '20:00')


def enabled() -> bool:
    return os.getenv('SCHEDULER_ENABLED', '1') not in ('0', 'false', 'no') and bool(os.getenv('DISCORD_BOT_TOKEN'))


def due_posts(cls: dict, now: datetime) -> list[tuple[str, callable]]:
    """(claim key, message builder) for every post this class is due right now."""
    today = now.date()
    due = []
    weekly_due = (today.weekday() == FRIDAY and now.time() >= weekly_time()) or today.weekday() == SATURDAY
    if weekly_due:
        week = dr.next_week(today)
        due.append((f'weekly:{week.start.isoformat()}', lambda: updates.week_update(cls['id'], 'next', now)))
    if now.time() >= reminder_time():
        tomorrow = today + timedelta(days=1)
        due.append((f'eve:{tomorrow.isoformat()}', lambda: updates.reminder_update(cls['id'], tomorrow)))
    return due


def _send(cls: dict, key: str, build) -> str:
    """Reminders are built before claiming: an empty one is not claimed, so an exam added
    later that evening still gets its reminder. Weekly updates are always posted."""
    if (cls['id'], key) in _finished:
        return 'already'
    update = build()
    if not update.messages:
        return 'nothing'
    if not db_fetch.claim_notification(cls['id'], key):
        _remember(cls['id'], key)
        return 'already'
    try:
        client.post_messages(cls['discord_channel_id'], update.messages)
    except client.DiscordError as error:
        if error.code == client.UNKNOWN_CHANNEL:
            db_fetch.release_notification(cls['id'], key)
            db_fetch.deactivate_class(cls['id'])
            logger.warning('class %s: channel %s no longer exists; class deactivated', cls['id'], cls['discord_channel_id'])
            return 'deactivated'
        if error.permanent:
            db_fetch.finish_notification(cls['id'], key, 'failed', str(error))
            _remember(cls['id'], key)
            logger.error('class %s: %s not posted (%s)', cls['id'], key, error)
            return 'failed'
        db_fetch.release_notification(cls['id'], key)  # temporary: retry next tick
        logger.warning('class %s: %s will be retried (%s)', cls['id'], key, error)
        return 'retry'
    db_fetch.finish_notification(cls['id'], key, 'sent', f'{update.exam_count} exam(s)')
    _remember(cls['id'], key)
    logger.info('class %s: posted %s (%d exam(s))', cls['id'], key, update.exam_count)
    return 'sent'


def _remember(class_id: int, key: str) -> None:
    if len(_finished) > 5000:
        _finished.clear()
    _finished.add((class_id, key))


def deactivate_removed_servers() -> int:
    """Deactivate every class whose server the bot is no longer in. Returns how many."""
    try:
        present = client.bot_guild_ids()
    except client.DiscordError as error:
        # Never guess from a failed request: that would deactivate every class.
        logger.warning("could not list the bot's servers: %s", error)
        return 0
    removed = 0
    for cls in db_fetch.fetch_discord_classes():
        if cls['discord_guild_id'] not in present and db_fetch.deactivate_class(cls['id']):
            removed += 1
            logger.info('class %s (%s): bot is no longer in server %s; class deactivated',
                        cls['id'], cls['name'], cls['discord_guild_id'])
    return removed


def run_tick(now: datetime | None = None) -> dict[str, int]:
    global _last_reconcile
    now = now or dr.now_local()
    summary: dict[str, int] = {}
    if clock.monotonic() - _last_reconcile >= RECONCILE_SECONDS:
        _last_reconcile = clock.monotonic()
        try:
            removed = deactivate_removed_servers()
        except db_fetch.DatabaseError as error:
            logger.error('server check skipped, database error %s', error.code)
            removed = 0
        if removed:
            summary['deactivated'] = removed
    try:
        classes = db_fetch.fetch_scheduled_classes()
    except db_fetch.DatabaseError as error:
        logger.error('scheduler could not load classes: %s', error.code)
        return {'db_error': 1}
    for cls in classes:
        for key, build in due_posts(cls, now):
            try:
                result = _send(cls, key, build)
            except db_fetch.DatabaseError as error:
                logger.error('class %s: %s skipped, database error %s', cls['id'], key, error.code)
                result = 'db_error'
            summary[result] = summary.get(result, 0) + 1
    return summary
