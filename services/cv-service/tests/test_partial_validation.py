"""A partly verified extraction is kept: verified items normally, the rest flagged as unconfirmed."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from app.conversation.interview_memory import topic_ids
from app.domain.capabilities import effective_items
from app.domain.partial_validation import ISSUE_MESSAGE, salvage
from app.domain.extraction_errors import EvidenceValidationError
from app.workflows.extraction import ExtractionHarness
from tests.conftest import ready
from tests.test_conversation_security import PREFIX, send
from tests.test_cv_interview import opened
from tests.test_extraction_harness import saver, setup_provider, read_result

BLOCKS = [{'id': 'b1', 'text': 'Example University, BSc Computing.', 'location': 'Paragraph 1'},
          {'id': 'b2', 'text': 'Project Finch: built a reporting tool in Python with a team.', 'location': 'Paragraph 2'},
          {'id': 'b3', 'text': 'Skills: Python, SQL', 'location': 'Paragraph 3'}]


def education():
    return {'kind': 'education', 'title': 'Example University', 'description': 'BSc Computing', 'explicit': True,
            'evidence': [{'block_id': 'b1', 'excerpt': BLOCKS[0]['text']}]}


def project(**changes):
    return {'kind': 'project', 'title': 'Project Finch', 'description': 'Reporting tool built with a team', 'explicit': True,
            'skill_names': ['Python'], 'evidence': [{'block_id': 'b2', 'excerpt': 'Invented text not in the CV'}], **changes}


def skill():
    return {'kind': 'skill', 'title': 'SQL', 'description': 'Listed skill', 'explicit': True, 'skill_names': ['SQL'],
            'evidence': [{'block_id': 'b3', 'excerpt': 'SQL'}]}


def kept(candidate, **options):
    return salvage(candidate, BLOCKS, 'synthetic-cv', lambda blocks, refs: frozenset(), **options)


def test_an_unverifiable_item_is_flagged_and_keeps_its_extracted_context():
    result = kept({'items': [education(), project(), skill()]})
    assert [i['kind'] for i in result.items] == ['education', 'project', 'skill']
    flagged = result.items[1]
    assert flagged['validation_issue'] == {'status': 'unverified', 'code': 'source_excerpt', 'message': ISSUE_MESSAGE}
    assert flagged['id'] in result.flagged and len(result.flagged) == 1
    # What was extracted stays visible, but nothing is claimed as verified.
    assert flagged['title'] == 'Project Finch' and flagged['description'] == 'Reporting tool built with a team'
    assert flagged['evidence'] == [{'id': 'b2', 'location': 'Paragraph 2', 'excerpt': 'Invented text not in the CV'}]
    assert flagged['skill_names'] == ['Python'] and flagged['provenance'] == 'inferred'
    assert flagged['support_uncertain'] is True and flagged['uncertainties'] == ['claim']
    assert flagged['start_date'] is None and flagged['review_evidence'] == []
    assert all('validation_issue' not in item for item in (result.items[0], result.items[2]))
    assert any('1 extracted section could not be verified' in notice for notice in result.notices)


def test_verified_items_keep_the_identity_they_would_have_had_without_flagging():
    from app.domain.capabilities import validate_extraction
    full = validate_extraction({'items': [education(), skill()]}, BLOCKS, 'synthetic-cv')
    result = kept({'items': [education(), project(), skill()]})
    assert [result.items[0]['id'], result.items[2]['id']] == [full[0]['id'], full[1]['id']]


def test_nothing_verified_still_fails_the_whole_extraction():
    assert kept({'items': [project(), project(title='Other', description='Another')]}) is None


@pytest.mark.parametrize('candidate', [
    {'items': []}, {'items': 'invalid'}, 'invalid', None,
    {'items': [education()] * 2},                      # a duplicated claim is not one item's fault
])
def test_failures_that_are_not_item_specific_stay_whole_failures(candidate):
    assert kept(candidate) is None


def test_list_size_limits_stay_whole_output_failures():
    assert kept({'items': [education()], 'other_information': [{'block_id': 'b1', 'excerpt': 'BSc'}] * 161}) is None


def test_a_circular_relationship_between_items_is_not_kept():
    first = {**education(), 'supporting_items': [1]}
    second = {**skill(), 'supporting_items': [0]}
    assert kept({'items': [first, second]}) is None


def test_unreadable_entries_are_dropped_and_counted_not_flagged():
    unreadable = [{**project(), 'kind': 'invented'}, 'text', {**project(), 'title': ''}]
    result = kept({'items': [education(), *unreadable]})
    assert [i['kind'] for i in result.items] == ['education'] and result.flagged == [] and result.dropped == 3
    assert any('3 extracted entries could not be read or verified and were left out' in n for n in result.notices)


def test_schema_invalid_item_is_flagged_with_bounded_text():
    result = kept({'items': [education(), project(description='D ' * 3000, evidence=[{'block_id': 'b2', 'excerpt': BLOCKS[1]['text']}] * 7)]})
    flagged = result.items[1]
    assert flagged['validation_issue']['code'] == 'schema_validation'
    assert len(flagged['description']) <= 4000 and flagged['title'] == 'Project Finch'


def test_evidence_citing_an_unknown_block_is_dropped_from_the_flagged_item():
    result = kept({'items': [education(), project(evidence=[{'block_id': 'zzz', 'excerpt': 'x'}, {'block_id': 'b2', 'excerpt': 'Not in CV'}])]})
    assert [e['id'] for e in result.items[1]['evidence']] == ['b2']


def test_other_information_keeps_only_what_verifies():
    result = kept({'items': [education()], 'other_information': [
        {'block_id': 'b1', 'excerpt': 'BSc Computing'}, {'block_id': 'b1', 'excerpt': 'BSc Computing'},
        {'block_id': 'b1', 'excerpt': 'Invented fact'}, {'block_id': 'zzz', 'excerpt': 'x'}]})
    assert result.other_information == [{'id': 'b1', 'location': 'Paragraph 1', 'excerpt': 'BSc Computing'}]
    assert result.other_dropped == 2


def test_relationships_to_kept_items_are_remapped_and_dropped_items_are_ignored():
    derived = {**skill(), 'supporting_items': [1, 3, 99, 0, 'x', 2]}
    result = kept({'items': [education(), project(), derived, {**project(), 'kind': 'invented'}]})
    by_kind = {i['kind']: i for i in result.items}
    # Unknown, dropped, self and non-integer references vanish; real ones point at the final item IDs.
    assert by_kind['skill']['supporting_item_ids'] == [by_kind['project']['id'], by_kind['education']['id']]
    assert by_kind['project']['supporting_item_ids'] == []


def test_semantic_support_is_reused_not_requested_again():
    calls = []
    paraphrase = {**education(), 'evidence': [{'block_id': 'b1', 'excerpt': 'Studied computing at Example University.'}]}
    def verify(blocks, refs):
        calls.append(refs)
        return frozenset((ref['block_id'], ref['excerpt']) for ref in refs if ref['block_id'] == 'b1')
    result = salvage({'items': [paraphrase, project()]}, BLOCKS, 'synthetic-cv', verify)
    assert len(calls) == 1 and [r['block_id'] for r in calls[0]] == ['b1', 'b2']
    assert 'validation_issue' not in result.items[0] and 'validation_issue' in result.items[1]
    reused = salvage({'items': [paraphrase, project()]}, BLOCKS, 'synthetic-cv', verify, frozenset({('b1', 'Studied computing at Example University.')}))
    assert len(calls) == 1 and reused.items[0]['evidence'][0]['excerpt'] == 'Studied computing at Example University.'


def test_a_user_explanation_resolves_the_flag_and_flagged_skills_stay_uncertain():
    result = kept({'items': [education(), project()]})
    document = {'original_items': deepcopy(result.items), 'overlays': {}, 'clarifications': [], 'history': [], 'version': 1}
    flagged = next(i for i in effective_items(document) if i['kind'] == 'project')
    assert flagged['validation_issue'] and flagged['support_uncertain']
    assert all(c['support_uncertain'] for c in flagged['skill_claims'])
    document['overlays'] = {flagged['id']: {'description': 'I built the reporting tool.', '_field_sequences': {'description': 1}}}
    resolved = next(i for i in effective_items(document) if i['kind'] == 'project')
    assert 'validation_issue' not in resolved


def test_flagged_sections_of_any_kind_become_review_topics_with_a_warning():
    result = kept({'items': [{**education(), 'evidence': [{'block_id': 'b1', 'excerpt': 'Made up'}]}, skill(), project()]})
    items = effective_items({'original_items': deepcopy(result.items), 'overlays': {}, 'clarifications': [], 'history': [], 'version': 1})
    flagged_ids = {i['id'] for i in items if i.get('validation_issue')}
    assert {i['kind'] for i in items if i['id'] in flagged_ids} == {'education', 'project'}
    assert set(topic_ids(items)) == flagged_ids


def test_the_harness_keeps_a_partial_extraction_only_when_allowed():
    def build(allow):
        calls = []
        def model(blocks, candidate, feedback):
            calls.append(feedback)
            return {'items': [education(), project(), skill()]}, {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}
        harness = ExtractionHarness('synthetic-cv', lambda _: {'blocks': BLOCKS}, model, lambda _: None, checkpointer=saver(),
                                    thread_id='operation:1', verify_evidence=lambda _, refs: frozenset(), allow_partial=allow)
        return harness, calls
    strict, calls = build(False)
    with pytest.raises(EvidenceValidationError):
        strict.run(b'synthetic')
    assert len(calls) == 2                                   # extraction and its single repair
    lenient, calls = build(True)
    result = lenient.run(b'synthetic')
    assert len(calls) == 2 and len(result['items']) == 3
    assert [i['kind'] for i in result['items'] if i.get('validation_issue')] == ['project']
    assert result['partial_notices']


def worker_candidate(harness):
    """The default synthetic CV with its project citing text the CV does not contain."""
    items = harness[2].extract([{'id': 'b1', 'text': 'Education: Example University, Computing'},
                                {'id': 'b2', 'text': 'Project A: Team built a Python and SQL application.'},
                                {'id': 'b3', 'text': 'Independent SQL queries for a personal dataset.'}])[0]
    items['items'][1]['evidence'][0]['excerpt'] = 'Invented quotation'
    return items


def test_the_last_attempt_publishes_verified_items_and_flags_the_rest(harness):
    client, app, extractor, *_ = harness
    extractor.payload = worker_candidate(harness)
    cv = ready(harness)
    assert cv['error'] is None and cv['status'] == 'ready'
    flagged = [i for i in cv['items'] if i.get('validation_issue')]
    assert [i['title'] for i in flagged] == ['Project A'] and flagged[0]['validation_issue']['status'] == 'unverified'
    assert [i['title'] for i in cv['items'] if not i.get('validation_issue')] == ['Example University', 'SQL']
    assert any('could not be verified' in notice for notice in cv['notices'])
    project_skills = [s for s in cv['skills'] if s['name'] == 'Python']
    assert project_skills and project_skills[0]['sources'][0]['support_uncertain'] is True


def test_earlier_attempts_retry_instead_of_keeping_a_partial_extraction(harness, monkeypatch):
    client, app, queued, calls = setup_provider(harness, monkeypatch,
        [{'items': [education(), project()]}, {'supported': []}] * 2)
    app.state.worker.settings = replace(app.state.worker.settings, extraction_auto_retries=2)
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'queued' and result['items'] == [] and result['extraction_version'] == 0
    assert result['error'] is None


def test_the_chat_and_topic_list_flag_the_section_and_say_it_again_in_the_first_question(harness):
    client, app, extractor, *_ = harness
    extractor.payload = worker_candidate(harness)
    cv, chat, provider = opened(harness)
    chat = send(client, chat, 'Review my CV', command='review')
    topics = chat['interview']['topics']
    assert [(t['title'], t['validation']) for t in topics] == [('Project A', 'unverified')]
    question = chat['active_question']['question']
    first = next(m['text'] for m in chat['messages'] if m['role'] == 'assistant' and question in m['text'])
    assert first.startswith('Heads up: I couldn’t automatically verify “Project A” against your CV')
    assert 'explain this section to me here in the chat' in first
    focused = next(c for c in provider.calls if c.get('task') == 'cv_interview_plan')['focused_source']
    assert focused['validation_issue']['status'] == 'unverified'
    # Said once, before the first question about that section only.
    chat = send(client, chat, 'Skip', command='skip')
    texts = [m['text'] for m in chat['messages'] if m['role'] == 'assistant']
    assert texts[-1] == 'What was the scope of your task?' and sum('Heads up' in text for text in texts) == 1
