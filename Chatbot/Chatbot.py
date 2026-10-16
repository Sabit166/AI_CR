"""Student-facing exam assistant.

Flow per message (no AI service; normally 1-2 database calls):
  1. Load the course catalog (cached; see catalog.py).
  2. Parse the question with rules (intent.py).
  3. Resolve course/teacher mentions deterministically against the catalog.
  4. Compute the date range in Asia/Dhaka and run ONE filtered exam_details query.
  5. Format the rows deterministically (no generated facts).

Everything is scoped to one class (a Discord channel): its catalog and its exams.

Run from the repo root:  python -m Chatbot.Chatbot --class-id 1 "what exams do we have next week?"
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass

import date_ranges as dr
import db_fetch

from . import formatter
from .catalog import CatalogCache, catalog_cache as default_catalog_cache
from .intent import heuristic_parse
from .resolver import scan_message_for_courses
from .retrieval import ExamRepository, execute, plan_query

logger = logging.getLogger('aicr.chat')

MAX_INPUT_CHARS = 1000


@dataclass
class BotReply:
    messages: list[str]
    outcome: str
    intent_source: str | None
    metrics: db_fetch.CallMetrics

    @property
    def text(self) -> str:
        return '\n\n'.join(self.messages)


LIST_TIME_KINDS = {'this_week', 'next_week', 'weekday_range', 'date_range', 'upcoming'}


def _parse(message: str, exam_type_names: list[str], catalog):
    intent = heuristic_parse(message, exam_type_names)
    intent.course_mentions = scan_message_for_courses(message, catalog)
    return _normalize_fields(intent)


def _normalize_fields(intent):
    # "What exams are scheduled next week?" is a request for the schedule, not just dates:
    # list-style answers show full details unless something more specific was asked.
    if intent.time.kind in LIST_TIME_KINDS and set(intent.fields) <= {'date', 'time'}:
        intent.fields = []
    return intent


def answer(
    message: str,
    *,
    class_id: int,
    clock: dr.Clock | None = None,
    repo: ExamRepository = db_fetch,
    cache: CatalogCache = default_catalog_cache,
) -> BotReply:
    metrics = db_fetch.start_metrics()
    started = time.perf_counter()
    outcome, source = 'error', None
    message = (message or '').strip()[:MAX_INPUT_CHARS]

    try:
        if not message:
            outcome = 'greeting'
            return BotReply([formatter.HELP_TEXT], outcome, source, metrics)

        now = dr.now_local(clock)
        catalog = cache.get(class_id)
        intent = _parse(message, catalog.exam_type_names(), catalog)
        source = intent.source

        if intent.category == 'greeting':
            outcome = 'greeting'
            return BotReply([formatter.HELP_TEXT], outcome, source, metrics)
        if intent.category == 'off_topic':
            outcome = 'off_topic'
            return BotReply([formatter.OFF_TOPIC_TEXT], outcome, source, metrics)

        plan = plan_query(intent, message, catalog, now, class_id)
        if plan.status in ('clarify_course', 'clarify_faculty'):
            outcome = 'clarify'
            return BotReply([formatter.format_clarification(plan)], outcome, source, metrics)
        if plan.status in ('unknown_course', 'unknown_faculty'):
            outcome = 'unknown'
            return BotReply(formatter.split_message(formatter.format_unknown(plan, catalog)), outcome, source, metrics)

        result = execute(plan, repo, now)
        outcome = 'answered' if result.rows else 'empty'
        return BotReply(formatter.format_result(result, catalog, now.date()), outcome, source, metrics)

    except db_fetch.DatabaseError as error:
        # A failed lookup is never reported as "no exams".
        outcome = 'db_error'
        logger.error('database error while answering: code=%s status=%s', error.code, error.status)
        return BotReply([formatter.DB_ERROR_TEXT], outcome, source, metrics)
    except Exception:
        outcome = 'error'
        logger.exception('unexpected error while answering')
        return BotReply([formatter.GENERIC_ERROR_TEXT], outcome, source, metrics)
    finally:
        logger.info(
            'chat outcome=%s db_calls=%d db_ms=%.0f total_ms=%.0f',
            outcome, metrics.db_calls, metrics.db_ms,
            (time.perf_counter() - started) * 1000,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description='Chat with the exam bot.')
    parser.add_argument('message', help='User message to evaluate')
    parser.add_argument('--class-id', type=int, required=True, help='Class (public.classes.id) to answer for')
    args = parser.parse_args()

    reply = answer(args.message, class_id=args.class_id)
    for part in reply.messages:
        print(part)
        print('-' * 40)


if __name__ == '__main__':
    main()
