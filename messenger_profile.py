"""Messenger Page profile: the ready-made questions ("ice breakers") students see
when they open a chat with the Page for the first time.

Tapping one sends a postback to /webhook with its payload; main.py turns the
payload into the matching question and answers it like a typed message.
Apply changes to Facebook with:  python scripts/setup_messenger.py
"""
from __future__ import annotations

# (button text shown to students, postback payload, question the bot answers)
ICE_BREAKERS: tuple[tuple[str, str, str], ...] = (
    ('Next exam date', 'NEXT_EXAM_DATE', 'When is the next exam?'),
    ('Next exam syllabus', 'NEXT_EXAM_SYLLABUS', 'What is the syllabus of the next exam?'),
    ('Next exam notes', 'NEXT_EXAM_NOTES', 'Notes of the next exam'),
    ("Next week's update", 'NEXT_WEEK_UPDATE', 'What exams are scheduled next week?'),
)

_QUESTION_FOR_PAYLOAD = {payload: question for _, payload, question in ICE_BREAKERS}


def question_for_postback(postback: dict) -> str | None:
    """Known payload -> its fixed question; otherwise the button title (e.g. an older button)."""
    payload = str(postback.get('payload') or '')
    if payload in _QUESTION_FOR_PAYLOAD:
        return _QUESTION_FOR_PAYLOAD[payload]
    title = str(postback.get('title') or '').strip()
    return title or None


def profile_payload() -> dict:
    return {
        'ice_breakers': [{
            'locale': 'default',
            'call_to_actions': [{'question': text, 'payload': payload} for text, payload, _ in ICE_BREAKERS],
        }],
    }
