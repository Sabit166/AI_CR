"""Automatic posts: when they are due, sent once, retried only when it can help."""
import pytest

import db_fetch
import scheduler
from conftest import CLASS_ID, FakeRepo, clock_at, exam_row
from discord_bot import client as discord

CLASS = {'id': CLASS_ID, 'name': 'CSE 22', 'discord_channel_id': '900000000000000002', 'auto_updates': True}


@pytest.fixture
def env(monkeypatch):
    scheduler._finished.clear()
    claims: dict[tuple, str] = {}
    posted = []
    rows = [exam_row(1, 1, 'CT 2', '2026-10-18', exam_time='10:00:00'),   # Sunday
            exam_row(2, 3, 'Lab Test', '2026-10-20')]                      # Tuesday
    monkeypatch.setattr(db_fetch, 'query_exams', FakeRepo(rows).query_exams)
    monkeypatch.setattr(db_fetch, 'fetch_scheduled_classes', lambda: [CLASS])

    def claim(class_id, key):
        if (class_id, key) in claims:
            return False
        claims[(class_id, key)] = 'sending'
        return True
    monkeypatch.setattr(db_fetch, 'claim_notification', claim)
    monkeypatch.setattr(db_fetch, 'finish_notification', lambda cid, key, status, detail=None: claims.__setitem__((cid, key), status))
    monkeypatch.setattr(db_fetch, 'release_notification', lambda cid, key: claims.pop((cid, key)))
    monkeypatch.setattr(discord, 'post_messages', lambda channel, messages: posted.append((channel, messages)))
    return {'claims': claims, 'posted': posted}


def tick(at):
    return scheduler.run_tick(clock_at(at)())


def test_friday_evening_posts_next_week_once(env):
    assert tick('2026-10-16T17:59') == {}
    assert tick('2026-10-16T18:00') == {'sent': 1}
    assert tick('2026-10-16T18:01') == {'already': 1}
    channel, messages = env['posted'][0]
    assert channel == CLASS['discord_channel_id'] and "Next week's exams" in messages[0]
    assert 'Sunday, 18 October 2026' in messages[0]
    assert env['claims'] == {(CLASS_ID, 'weekly:2026-10-18'): 'sent'}


def test_missed_friday_is_caught_up_on_saturday(env):
    assert tick('2026-10-17T09:00')['sent'] == 1
    assert 'weekly:2026-10-18' in {k for _, k in env['claims']}


def test_day_before_reminder(env):
    summary = tick('2026-10-17T20:00')    # Saturday 20:00: weekly (catch-up) + Sunday's reminder
    assert summary == {'sent': 2}
    reminder = env['posted'][1][1][0]
    assert 'Reminder: 1 exam tomorrow' in reminder and 'CSE-415' in reminder and '10:00 AM' in reminder
    assert tick('2026-10-17T21:00') == {'already': 2}


def test_no_reminder_without_exams_tomorrow(env):
    assert tick('2026-10-18T20:00') == {'nothing': 1}   # Monday has no exam
    assert env['posted'] == [] and env['claims'] == {}


def test_reminder_waits_for_its_time(env):
    assert tick('2026-10-19T19:59') == {}
    assert tick('2026-10-19T20:00') == {'sent': 1}       # Tuesday's Lab Test


def test_temporary_discord_failure_is_retried(env, monkeypatch):
    def down(channel, messages):
        raise discord.DiscordError('503', status=503)
    monkeypatch.setattr(discord, 'post_messages', down)
    assert tick('2026-10-16T18:00') == {'retry': 1}
    assert env['claims'] == {}
    monkeypatch.setattr(discord, 'post_messages', lambda channel, messages: env['posted'].append(channel))
    assert tick('2026-10-16T18:01') == {'sent': 1}


def test_missing_channel_access_is_not_retried_forever(env, monkeypatch):
    def denied(channel, messages):
        raise discord.DiscordError('403', status=403, code=discord.MISSING_ACCESS)
    monkeypatch.setattr(discord, 'post_messages', denied)
    assert tick('2026-10-16T18:00') == {'failed': 1}
    assert tick('2026-10-16T18:01') == {'already': 1}
    assert env['claims'][(CLASS_ID, 'weekly:2026-10-18')] == 'failed'


def test_claimed_elsewhere_is_not_sent_again(env):
    env['claims'][(CLASS_ID, 'weekly:2026-10-18')] = 'sent'   # another instance got there first
    assert tick('2026-10-16T18:00') == {'already': 1} and env['posted'] == []


def test_database_outage_skips_the_tick(env, monkeypatch):
    def down():
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'fetch_scheduled_classes', down)
    assert tick('2026-10-16T18:00') == {'db_error': 1}


def test_times_are_configurable(env, monkeypatch):
    monkeypatch.setenv('WEEKLY_UPDATE_TIME', '17:30')
    monkeypatch.setenv('EXAM_REMINDER_TIME', 'nonsense')
    assert tick('2026-10-16T17:30') == {'sent': 1}
    assert scheduler.reminder_time().strftime('%H:%M') == '20:00'
