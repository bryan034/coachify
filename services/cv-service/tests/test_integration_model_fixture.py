"""The integration provider accepts only explicitly labelled synthetic cases."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('cv_model_fixture',
    Path(__file__).resolve().parents[3] / 'infrastructure/testing/cv-model.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def test_semantic_fixture_checks_claim_and_cited_source_together():
    text = "I wrote the Python loader for six months with my tutor's help."
    statement = "For the user's Python work, assistance is supervised."
    request = {'source_blocks': [{'id': 'a', 'text': text}, {'id': 'b', 'text': 'Unrelated synthetic source.'}],
        'summaries': [{'index': 0, 'block_id': 'a', 'excerpt': statement},
                      {'index': 1, 'block_id': 'a', 'excerpt': statement.replace('supervised', 'independent')},
                      {'index': 2, 'block_id': 'b', 'excerpt': statement},
                      {'index': 3, 'block_id': 'missing', 'excerpt': statement}]}
    assert fixture.semantic_fixture(request) == {'supported': [0]}


def test_manual_fixture_cites_only_the_current_message():
    text = 'I use Figma to make posters for my student society.'
    value = fixture.intake_fixture({'message': text, 'message_id': 'synthetic-turn'})
    skill = value['entries'][0]['skills'][0]
    assert skill['evidence'] == [{'message_id': 'synthetic-turn', 'quote': text}]
    assert 'dimensions' not in skill
    with pytest.raises(ValueError):
        fixture.intake_fixture({'message': 'Invent unlabelled skills.', 'message_id': 'other'})
    with pytest.raises(RuntimeError):
        fixture.intake_fixture({'message': 'SYNTHETIC_CHAT_PROVIDER_FAILURE'})


def test_guided_review_fixture_refuses_unknown_sources():
    with pytest.raises(ValueError):
        fixture.review_question_fixture({'target': {'source_title': 'Personal CV', 'field': 'complexity'}})


def test_interview_fixture_is_finite_and_keeps_side_questions_read_only():
    source = {'id': 'synthetic-project', 'title': 'Team dashboard', 'kind': 'project', 'skill_ids': ['skill:python'], 'skill_names': ['Python']}
    value = {'task': 'cv_interview_interpret', 'focused_source': source, 'sources': [source],
             'active_question': {'id': 'question', 'item_id': source['id'], 'question': 'What was your personal contribution?'},
             'source_answers': [], 'message': 'Why are you asking?'}
    result = fixture.interview_fixture(value)
    assert result['intent'] == 'side_question' and not result['interpretations']
    with pytest.raises(ValueError): fixture.interview_fixture({**value, 'message': 'Invent an unlabelled contribution.'})
    with pytest.raises(ValueError): fixture.interview_fixture({**value, 'focused_source': {**source, 'title': 'Private CV'}})
