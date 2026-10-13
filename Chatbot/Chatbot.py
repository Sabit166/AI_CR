"""Student-facing exam assistant.

Flow per message (at most 1 LLM call, normally 1-2 database calls):
  1. Load the course catalog (cached; see catalog.py).
  2. Parse intent with one structured-output LLM call (rule-based fallback if unavailable).
  3. Resolve course/teacher mentions deterministically against the catalog.
  4. Compute the date range in Asia/Dhaka and run ONE filtered exam_details query.
  5. Format the rows deterministically (no generated facts).

Run from the repo root:  python -m Chatbot.Chatbot "what exams do we have next week?"
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass

import date_ranges as dr
import db_fetch

from . import formatter
from .catalog import CatalogCache, catalog_cache as default_catalog_cache
from .intent import IntentUnavailable, _heuristic_time, heuristic_parse, llm_parse
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


# Time expressions the rule parser recognises unambiguously. When one is present it
# overrides the LLM's choice: small models sometimes read "exams next week" as
# "the next exam", and the weekly answer must never depend on that guess.
DETERMINISTIC_TIME_KINDS = {
    'next_week', 'this_week', 'today', 'tomorrow', 'day_after_tomorrow', 'in_days',
    'weekday_range', 'date',
}
LIST_TIME_KINDS = {'this_week', 'next_week', 'weekday_range', 'date_range', 'upcoming'}


def _parse(message: str, exam_type_names: list[str], catalog, use_llm: bool):
    if use_llm:
        try:
            intent = llm_parse(message, exam_type_names)
        except IntentUnavailable as error:
            logger.warning('intent LLM unavailable, using rule-based parser: %s', error)
        else:
            rule_time = _heuristic_time(message.lower())
            if rule_time.kind in DETERMINISTIC_TIME_KINDS and rule_time != intent.time:
                intent.time = rule_time
            if intent.category == 'off_topic' and rule_time.kind in DETERMINISTIC_TIME_KINDS:
                intent.category = 'exam_query'
            if not intent.exam_types:
                # Explicit keywords ("CT 2", "lab test") are matched deterministically too.
                intent.exam_types = heuristic_parse(message, exam_type_names).exam_types
            return _normalize_fields(intent)
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
    clock: dr.Clock | None = None,
    repo: ExamRepository = db_fetch,
    cache: CatalogCache = default_catalog_cache,
    use_llm: bool = True,
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
        catalog = cache.get()
        intent = _parse(message, catalog.exam_type_names(), catalog, use_llm)
        source = intent.source

        if intent.category == 'greeting':
            outcome = 'greeting'
            return BotReply([formatter.HELP_TEXT], outcome, source, metrics)
        if intent.category == 'off_topic':
            outcome = 'off_topic'
            return BotReply([formatter.OFF_TOPIC_TEXT], outcome, source, metrics)

        plan = plan_query(intent, message, catalog, now)
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
            'chat outcome=%s intent=%s llm_calls=%d llm_ms=%.0f db_calls=%d db_ms=%.0f total_ms=%.0f',
            outcome, source, metrics.llm_calls, metrics.llm_ms, metrics.db_calls, metrics.db_ms,
            (time.perf_counter() - started) * 1000,
        )


async def chat(req: str) -> str:
    """Backwards-compatible entry point: the full reply as one string."""
    reply = await asyncio.to_thread(answer, req)
    return reply.text


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description='Chat with the exam bot.')
    parser.add_argument('message', help='User message to evaluate')
    parser.add_argument('--no-llm', action='store_true', help='Use the rule-based parser only')
    args = parser.parse_args()

    reply = answer(args.message, use_llm=not args.no_llm)
    for part in reply.messages:
        print(part)
        print('-' * 40)


if __name__ == '__main__':
    main()
