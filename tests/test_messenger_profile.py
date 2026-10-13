"""Ice breakers: Facebook's format and the questions the bot actually understands."""
import pytest

from Chatbot.intent import heuristic_parse
from conftest import EXAM_TYPES
from messenger_profile import ICE_BREAKERS, profile_payload, question_for_postback

TYPES = [t['name'] for t in EXAM_TYPES]


def test_profile_payload_shape():
    breakers = profile_payload()['ice_breakers']
    assert len(breakers) == 1 and breakers[0]['locale'] == 'default'
    actions = breakers[0]['call_to_actions']
    assert [a['question'] for a in actions] == ['Next exam date', 'Next exam syllabus', 'Next exam notes', "Next week's update"]
    assert len(actions) <= 4  # Facebook's limit
    assert all(len(a['question']) <= 80 and a['payload'] for a in actions)


@pytest.mark.parametrize('payload,kind,field', [
    ('NEXT_EXAM_DATE', 'next', 'date'),
    ('NEXT_EXAM_SYLLABUS', 'next', 'syllabus'),
    ('NEXT_EXAM_NOTES', 'next', 'notes_link'),
    ('NEXT_WEEK_UPDATE', 'next_week', None),
])
def test_questions_parse_as_intended_without_llm(payload, kind, field):
    question = question_for_postback({'payload': payload})
    parsed = heuristic_parse(question, TYPES)
    assert parsed.category == 'exam_query'
    assert parsed.time.kind == kind
    assert parsed.course_mentions == [] and parsed.exam_types == []
    if field:
        assert field in parsed.fields


def test_unknown_postback():
    assert question_for_postback({'payload': 'X', 'title': ' Hi '}) == 'Hi'
    assert question_for_postback({}) is None
    assert {p for _, p, _ in ICE_BREAKERS} == {'NEXT_EXAM_DATE', 'NEXT_EXAM_SYLLABUS', 'NEXT_EXAM_NOTES', 'NEXT_WEEK_UPDATE'}
