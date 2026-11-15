"""Exercise the item-scoped review rollout with existing synthetic records."""
from copy import deepcopy

import pytest

from app.clarification import service as clarification
from app.conversation.interview_memory import reconcile_memory, topic_question_count
from app.schemas.cv import PrepareMutation
from tests.conftest import mutation, ready
from tests.test_conversation import actions, decide
from tests.test_conversation_security import PREFIX, send
from tests.test_cv_interview import opened, start_two_topics
from tests.test_review_receipt_history import accepted, question, reconciled_document


CURRENT = {'scope': 'item', 'version': 1}


@pytest.mark.parametrize('legacy_scope', ['section', 'item'])
def test_active_review_upgrades_without_reissuing_or_losing_current_question(harness, legacy_scope):
    client, app, *_ = harness
    cv, chat, _ = start_two_topics(harness, scope='item')
    active = deepcopy(chat['active_question'])
    first = active['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    service = app.state.conversations
    old = {'scope': legacy_scope, 'version': 1}

    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    replacement['review_policy_snapshot'] = old
    for q in replacement['clarifications']:
        q['_interview_policy'] = old
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def legacy_memory(conversation):
        conversation['interview_memory']['review_policy'] = old
    service.update('owner-a', chat['id'], legacy_memory)
    chat = client.get(PREFIX + '/' + chat['id']).json()

    chat = send(client, chat, 'Why are you asking?')
    after = service.cv.get('owner-a', cv['id'])
    assert after['review_policy_snapshot'] == CURRENT
    assert chat['active_question'] == active
    assert [q['id'] for q in after['clarifications']] == [active['id']]
    rebuilt = reconcile_memory(service.get('owner-a', chat['id']), after)
    assert topic_question_count(rebuilt, first) == 1
    assert topic_question_count(rebuilt, second) == 0
    expected_migrations = int(legacy_scope == 'section')
    assert len(after.get('review_policy_migrations', [])) == expected_migrations
    chat = send(client, chat, 'Why is that relevant?')
    assert chat['active_question'] == active
    assert len(service.cv.get('owner-a', cv['id']).get('review_policy_migrations', [])) == expected_migrations


def test_section_question_number_becomes_its_own_item_number_without_reissue(harness):
    client, app, *_ = harness
    cv, chat, _ = start_two_topics(harness, scope='item')
    active = deepcopy(chat['active_question'])
    other = next(t['id'] for t in chat['interview']['topics'] if t['id'] != active['item_id'])
    service = app.state.conversations
    old = {'scope': 'section', 'version': 1}
    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    existing = replacement['clarifications'][0]
    existing['_interview_policy'] = old
    previous = deepcopy(existing)
    previous.update(id='legacy-previous', item_id=other, status='skipped', answer=None,
                    uncertainty_key='legacy-previous', _interview_policy=old)
    replacement['clarifications'].insert(0, previous)
    replacement['review_policy_snapshot'] = old
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def legacy_memory(conversation):
        conversation['interview_memory']['review_policy'] = old
        conversation['active_question']['number'] = 2
    service.update('owner-a', chat['id'], legacy_memory)
    chat = client.get(PREFIX + '/' + chat['id']).json()
    assert chat['active_question']['number'] == 2
    chat = send(client, chat, 'Why are you asking?')
    assert chat['active_question']['id'] == active['id']
    assert chat['active_question']['question'] == active['question']
    assert chat['active_question']['number'] == 1
    after = service.cv.get('owner-a', cv['id'])
    assert [q['id'] for q in after['clarifications']] == ['legacy-previous', active['id']]
    rebuilt = reconcile_memory(service.get('owner-a', chat['id']), after)
    assert topic_question_count(rebuilt, active['item_id']) == 1
    assert topic_question_count(rebuilt, other) == 1


@pytest.mark.parametrize('prepare_first', [False, True])
def test_completed_section_review_reopens_unasked_project_after_reload(harness, prepare_first):
    client, app, *_ = harness
    cv, chat, _ = start_two_topics(harness, scope='item')
    first = chat['active_question']['item_id']
    other = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    service = app.state.conversations
    old = {'scope': 'section', 'version': 1}
    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    first_question = replacement['clarifications'][0]
    first_question.update(status='skipped', _interview_policy=old)
    followup = deepcopy(first_question)
    followup.update(id='legacy-followup', uncertainty_key='legacy-followup')
    replacement['clarifications'].append(followup)
    replacement['review_policy_snapshot'] = old
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def completed(conversation):
        memory = conversation['interview_memory']
        memory.update(review_policy=old, status='reviewed_with_gaps', focus_item_id=None,
                      coverage={identifier: {'item_id': identifier, 'status': 'reviewed_with_gaps',
                                             'evidence_refs': []} for identifier in (first, other)})
        conversation['active_question'] = None
    service.update('owner-a', chat['id'], completed)
    if prepare_first:
        # A target-specific request can persist the new policy before the
        # conversation is reloaded; reopening must still see the old scope.
        current = service.cv.get('owner-a', cv['id'])
        request = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target', career_target_version=1))
        clarification.prepare(service.cv, 'owner-a', cv['id'], request,
            {'id': 'target', 'version': 1, 'type': 'specific_job', 'confirmed': True,
             'skill_ids': ['skill:unrelated']}, CURRENT)
    chat = client.get(PREFIX + '/' + chat['id']).json()
    chat = send(client, chat, 'Review my CV', command='review')
    assert chat['active_question'] is not None, chat['messages'][-1]
    assert chat['active_question']['item_id'] == other
    saved = service.cv.get('owner-a', cv['id'])
    assert saved['review_policy_snapshot'] == CURRENT
    assert len([q for q in saved['clarifications'] if q['item_id'] == first]) == 2
    assert len([q for q in saved['clarifications'] if q['item_id'] == other]) == 1


def test_archived_answers_and_skips_are_counted_once_for_their_mapped_item(monkeypatch):
    document = reconciled_document()
    document['original_items'].append({'id': 'C', 'kind': 'project'})
    document['clarifications'].append(question('q3', 'C', 'unanswered'))
    document['review_policy_snapshot'] = {'scope': 'section', 'version': 1}
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    policy = clarification.review_policy(document, CURRENT)
    assert policy == CURRENT
    _, counts = clarification.group_counts(document, policy)
    assert counts == {'item:B': 2, 'item:C': 1}


def test_jobs_and_projects_have_separate_allowances_while_education_remains_section_scoped(monkeypatch):
    document = {'_id': 'cv', 'history': [], 'original_items': [
        {'id': 'P1', 'kind': 'project'}, {'id': 'P2', 'kind': 'project'},
        {'id': 'J1', 'kind': 'experience'}, {'id': 'J2', 'kind': 'experience'},
        {'id': 'E1', 'kind': 'education'}, {'id': 'E2', 'kind': 'education'}],
        'clarifications': [question('p1', 'P1', 'skipped'), question('p2', 'P1', 'answered'),
                           question('j1', 'J1', 'skipped', kind='work'),
                           question('j2', 'J1', 'answered', kind='work'),
                           question('e1', 'E1', 'skipped', kind='other', _interview_section='education'),
                           question('e2', 'E2', 'answered', kind='other', _interview_section='education')]}
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    groups, counts = clarification.group_counts(document, CURRENT)
    assert {key: groups[key] for key in ('P1', 'P2', 'J1', 'J2', 'E1', 'E2')} == {
        'P1': 'item:P1', 'P2': 'item:P2', 'J1': 'item:J1', 'J2': 'item:J2',
        'E1': 'section:education', 'E2': 'section:education'}
    assert counts == {'item:P1': 2, 'item:J1': 2, 'section:education': 2}
    assert counts.get(groups['P2'], 0) == counts.get(groups['J2'], 0) == 0


def test_legacy_per_item_count_cannot_be_reduced_by_incomplete_surviving_receipts(monkeypatch):
    from app.conversation import interview_memory as memory
    document = {'_id': 'cv', 'history': [], 'original_items': [
        {'id': 'B', 'kind': 'project', 'removed': False},
        {'id': 'C', 'kind': 'project', 'removed': False}],
        'clarifications': [question('q1', 'B', 'skipped')],
        'review_policy_snapshot': CURRENT, 'extraction_version': 1,
        'effective_version': 1, 'overlays': {}}
    monkeypatch.setattr(memory, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(memory, 'source_fingerprint', lambda item: item['id'])
    monkeypatch.setattr(memory, 'baseline_estimates', lambda _: [])
    monkeypatch.setattr(memory, 'topic_ids', lambda items: [item['id'] for item in items])
    old = {'extraction_version': 1, 'review_policy': {'scope': 'section', 'version': 1},
           'question_counts': {'B': 2}, 'sources': {}, 'input_sources': {}, 'questions': []}
    rebuilt = memory.reconcile_memory({'interview_memory': old}, document)
    assert memory.topic_question_count(rebuilt, 'B') == 2
    assert memory.topic_question_count(rebuilt, 'C') == 0


def test_legacy_counts_still_share_non_project_section_budget(monkeypatch):
    document = {'_id': 'cv', 'history': [], 'original_items': [
        {'id': 'E1', 'kind': 'education'}, {'id': 'E2', 'kind': 'education'}],
        'clarifications': [question('q1', 'E1', 'skipped', kind='other', _interview_section='education')],
        'review_legacy_counts': {'E1': 2, 'E2': 1}}
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    assert clarification.group_counts(document, CURRENT)[1] == {'section:education': 3}


@pytest.mark.parametrize('second_mapping', [False, True])
def test_legacy_count_follows_same_cv_reconciliation_for_chat_and_target_paths(monkeypatch, second_mapping):
    from app.conversation import interview_memory as memory
    from app.domain.review_policy import migrate_snapshot
    target = 'C' if second_mapping else 'B'
    history = [accepted('cv', [], 'A', 'B')]
    if second_mapping:
        history.append(accepted('cv', [], 'B', 'C'))
    document = {'_id': 'cv', 'history': history, 'original_items': [
        {'id': target, 'kind': 'project', 'removed': False},
        {'id': 'D', 'kind': 'project', 'removed': False}],
        'clarifications': [question('q1', target, 'skipped')],
        'review_policy_snapshot': {'scope': 'section', 'version': 1},
        'extraction_version': 1, 'effective_version': 1, 'overlays': {}}
    monkeypatch.setattr(memory, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(memory, 'source_fingerprint', lambda item: item['id'])
    monkeypatch.setattr(memory, 'baseline_estimates', lambda _: [])
    monkeypatch.setattr(memory, 'topic_ids', lambda items: [item['id'] for item in items])
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    old = {'extraction_version': 1, 'review_policy': {'scope': 'section', 'version': 1},
           'question_counts': {'A': 2}, 'sources': {}, 'input_sources': {}, 'questions': []}
    chat = memory.reconcile_memory({'interview_memory': old}, document)
    assert memory.topic_question_count(chat, target) == 2
    assert memory.topic_question_count(chat, 'D') == 0
    migrate_snapshot(document, {'scope': 'section', 'version': 1}, old['question_counts'])
    assert document['review_legacy_counts'] == {target: 2}
    assert clarification.group_counts(document, CURRENT)[1] == {'item:' + target: 2}


def test_legacy_count_is_not_transferred_from_a_different_cv(monkeypatch):
    from app.conversation import interview_memory as memory
    from app.domain.review_policy import migrate_snapshot
    document = {'_id': 'new-cv', 'history': [accepted('old-cv', [], 'A', 'B')],
        'original_items': [{'id': 'B', 'kind': 'project', 'removed': False}],
        'clarifications': [], 'review_policy_snapshot': {'scope': 'section', 'version': 1},
        'extraction_version': 1, 'effective_version': 1, 'overlays': {}}
    monkeypatch.setattr(memory, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(memory, 'source_fingerprint', lambda item: item['id'])
    monkeypatch.setattr(memory, 'baseline_estimates', lambda _: [])
    monkeypatch.setattr(memory, 'topic_ids', lambda items: [item['id'] for item in items])
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    old = {'extraction_version': 1, 'review_policy': {'scope': 'section', 'version': 1},
           'question_counts': {'A': 2}, 'sources': {}, 'input_sources': {}, 'questions': []}
    chat = memory.reconcile_memory({'interview_memory': old}, document)
    assert memory.topic_question_count(chat, 'B') == 0
    migrate_snapshot(document, {'scope': 'section', 'version': 1}, old['question_counts'])
    assert not document.get('review_legacy_counts')
    assert clarification.group_counts(document, CURRENT)[1] == {}


def test_merged_same_cv_sources_do_not_lose_legacy_question_counts(monkeypatch):
    from app.conversation import interview_memory as memory
    from app.domain.review_policy import migrate_snapshot
    entry = accepted('cv', [], 'A', 'C')
    entry['choices'].append({'item_id': 'B', 'target_item_id': 'C'})
    document = {'_id': 'cv', 'history': [entry], 'original_items': [
        {'id': 'C', 'kind': 'project', 'removed': False}], 'clarifications': [],
        'review_policy_snapshot': {'scope': 'section', 'version': 1},
        'extraction_version': 1, 'effective_version': 1, 'overlays': {}}
    monkeypatch.setattr(memory, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(memory, 'source_fingerprint', lambda item: item['id'])
    monkeypatch.setattr(memory, 'baseline_estimates', lambda _: [])
    monkeypatch.setattr(memory, 'topic_ids', lambda items: [item['id'] for item in items])
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    old = {'extraction_version': 1, 'review_policy': {'scope': 'section', 'version': 1},
           'question_counts': {'A': 1, 'B': 1}, 'sources': {}, 'input_sources': {}, 'questions': []}
    chat = memory.reconcile_memory({'interview_memory': old}, document)
    assert memory.topic_question_count(chat, 'C') == 2
    migrate_snapshot(document, {'scope': 'section', 'version': 1}, old['question_counts'])
    assert document['review_legacy_counts'] == {'C': 2}
    assert clarification.group_counts(document, CURRENT)[1] == {'item:C': 2}


@pytest.mark.parametrize('legacy_scope', ['section', 'item'])
def test_target_prepare_preserves_incomplete_receipt_counts_from_latest_conversation(harness, legacy_scope):
    _, app, *_ = harness
    cv, chat, _ = start_two_topics(harness, scope='item')
    first = chat['active_question']['item_id']
    other = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    service = app.state.conversations
    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    old = {'scope': legacy_scope, 'version': 1}
    replacement['review_policy_snapshot'] = old
    replacement['clarifications'][0]['_interview_policy'] = old
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def legacy_memory(conversation):
        conversation['interview_memory']['review_policy'] = old
        conversation['interview_memory']['question_counts'][first] = 2
    service.update('owner-a', chat['id'], legacy_memory)
    current = service.cv.get('owner-a', cv['id'])
    request = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target-a', career_target_version=1))
    context = {'id': 'target-a', 'version': 1, 'type': 'specific_job', 'confirmed': True,
               'skill_ids': ['skill:python', 'skill:sql']}
    clarification.prepare(service.cv, 'owner-a', cv['id'], request, context, CURRENT)
    saved = service.cv.get('owner-a', cv['id'])
    assert saved['review_policy_snapshot'] == CURRENT
    assert saved['review_legacy_counts'][first] == 2
    assert len([q for q in saved['clarifications'] if q['item_id'] == first]) == 1
    assert any(q['item_id'] == other for q in saved['clarifications'])
    _, counts = clarification.group_counts(saved, CURRENT)
    assert counts['item:' + first] == 2
    assert counts['item:' + other] <= 2


def test_retained_legacy_question_can_publish_before_policy_upgrade(harness, monkeypatch):
    from app.conversation.service import action_in
    from app.domain.errors import CvError
    client, app, *_ = harness
    cv, chat, _ = opened(harness)
    service = app.state.conversations
    original = service.cv.mutate
    fail = {'once': True}
    def interrupted(*args, **kwargs):
        if len(args) > 3 and args[3] == 'interview-question' and fail['once']:
            fail['once'] = False
            raise CvError('Synthetic lost question publication.', 503)
        return original(*args, **kwargs)
    monkeypatch.setattr(service.cv, 'mutate', interrupted)
    chat = send(client, chat, 'Review my CV', command='review')
    route = actions(chat, 'route')[-1]
    assert route['status'] == 'failed'
    saved = service.get('owner-a', chat['id'])
    assert action_in(saved, route['id']).get('_interview_plan')

    legacy = {'scope': 'section', 'version': 1}
    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    replacement['review_policy_snapshot'] = legacy
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def downgrade(conversation):
        staged = action_in(conversation, route['id'])['_interview_plan']
        staged['memory']['review_policy'] = legacy
        staged['question']['_interview_policy'] = legacy
    service.update('owner-a', chat['id'], downgrade)
    chat = client.get(PREFIX + '/' + chat['id']).json()
    chat = decide(client, chat, route, 'retry')
    assert chat['active_question'], chat['messages'][-1]
    first = deepcopy(chat['active_question'])
    after = service.cv.get('owner-a', cv['id'])
    assert [q['id'] for q in after['clarifications']] == [first['id']]
    chat = send(client, chat, 'Why are you asking?')
    assert chat['active_question'] == first
    final = service.cv.get('owner-a', cv['id'])
    assert final['review_policy_snapshot'] == CURRENT
    assert [q['id'] for q in final['clarifications']] == [first['id']]


@pytest.mark.parametrize('legacy_scope', ['section', 'item'])
@pytest.mark.parametrize('publication', ['unissued', 'unissued_changed', 'committed', 'committed_changed', 'skipped', 'answered'])
def test_retained_question_recovers_after_target_prepare_changes_policy_or_ledger(harness, monkeypatch, legacy_scope, publication):
    """The target path can win between an interview's staged write and retry."""
    from app.conversation.service import action_in
    from app.domain.errors import CvError
    client, app, *_ = harness
    cv, chat, provider = opened(harness)
    service = app.state.conversations
    original = service.cv.mutate
    fail = {'once': True}
    def interrupted(*args, **kwargs):
        if len(args) > 3 and args[3] == 'interview-question' and fail['once']:
            fail['once'] = False
            if not publication.startswith('unissued'):
                original(*args, **kwargs)  # write succeeded, reply was lost
            raise CvError('Synthetic interrupted publication.', 503)
        return original(*args, **kwargs)
    monkeypatch.setattr(service.cv, 'mutate', interrupted)
    chat = send(client, chat, 'Review my CV', command='review')
    route = actions(chat, 'route')[-1]
    assert route['status'] == 'failed'
    staged = action_in(service.get('owner-a', chat['id']), route['id'])['_interview_plan']
    planned = deepcopy(staged['question'])
    old = {'scope': legacy_scope, 'version': 1}

    document = service.cv.get('owner-a', cv['id'])
    replacement = deepcopy(document)
    replacement['review_policy_snapshot'] = old
    for q in replacement['clarifications']:
        q['_interview_policy'] = old
    replacement['revision'] += 1
    service.cv.repository.replace(document, replacement)
    def legacy_conversation(current):
        saved = action_in(current, route['id'])['_interview_plan']
        saved['memory']['review_policy'] = old
        saved['question']['_interview_policy'] = old
        if publication.startswith('unissued'):
            # An older conversation remembers two questions even though the
            # retained proposal did not reach the CV receipt ledger.
            current['interview_memory'] = deepcopy(current.get('interview_memory') or saved['memory'])
            current['interview_memory']['question_counts'] = {planned['item_id']: 2}
    service.update('owner-a', chat['id'], legacy_conversation)

    if publication in {'skipped', 'answered'}:
        latest = service.cv.get('owner-a', cv['id'])
        fields = {'action': 'skip'} if publication == 'skipped' else {
            'action': 'answer', 'answer': 'I built the Python API with guidance.'}
        response = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{planned['id']}",
                              json=mutation(latest['version'], **fields))
        assert response.status_code == 200, response.text
    current = service.cv.get('owner-a', cv['id'])
    request = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target', career_target_version=1))
    clarification.prepare(service.cv, 'owner-a', cv['id'], request,
        {'id': 'target', 'version': 1, 'type': 'specific_job', 'confirmed': True,
         'skill_ids': ['skill:unrelated']}, CURRENT)
    before_retry = service.cv.get('owner-a', cv['id'])
    assert before_retry['review_policy_snapshot'] == CURRENT
    if publication.endswith('_changed'):
        # A different source changes after the question was staged. This must
        # not make retry lose an already-issued question or loop on stale data.
        unrelated = next(item for item in before_retry['original_items'] if item['kind'] == 'skill')
        response = client.patch(f"/api/v1/cv/{cv['id']}/items/{unrelated['id']}",
                                json=mutation(before_retry['version'], action='update', title='Synthetic SQL reporting'))
        assert response.status_code == 200, response.text
        assert service.cv.get('owner-a', cv['id'])['effective_version'] != staged['memory']['evidence_version']
    provider.plans = [{'action': 'pause', 'reply': 'Pause the synthetic interview.'}]
    chat = client.get(PREFIX + '/' + chat['id']).json()
    chat = decide(client, chat, route, 'retry')
    result = actions(chat, 'route')[-1]
    assert result['status'] == 'saved', result
    after = service.cv.get('owner-a', cv['id'])
    matching = [q for q in after['clarifications'] if q['id'] == planned['id']]
    if publication.startswith('unissued'):
        assert not matching
        assert after['review_legacy_counts'][planned['item_id']] == 2
        assert chat['active_question'] is None
    elif publication.startswith('committed'):
        assert len(matching) == 1 and matching[0]['status'] == 'unanswered'
        assert chat['active_question']['id'] == planned['id']
        if publication.endswith('_changed'):
            assert 'Your saved evidence changed' in chat['messages'][-1]['text']
    else:
        assert len(matching) == 1 and matching[0]['status'] == publication
        assert chat['active_question'] is None
        assert 'already answered or skipped' in chat['messages'][-1]['text']
    assert len({q['id'] for q in after['clarifications']}) == len(after['clarifications'])
    _, counts = clarification.group_counts(after, CURRENT)
    assert counts.get('item:' + planned['item_id'], 0) <= 2


@pytest.mark.parametrize('legacy_scope', ['section', 'item'])
def test_target_prepare_upgrades_legacy_snapshot_and_replays_without_duplicate_questions(harness, legacy_scope):
    _, app, *_ = harness
    cv = ready(harness)
    service = app.state.service
    original = service.get('owner-a', cv['id'])
    data = deepcopy(original)
    project = next(item for item in data['original_items'] if item['kind'] == 'project')
    project['uncertainties'] = ['personal_contribution', 'claim']
    other = deepcopy(project)
    other['id'] += '-other'
    other['title'] = 'Another synthetic project'
    data['original_items'].append(other)
    data['revision'] += 1
    service.repository.replace(original, data)
    context = {'id': 'target-a', 'version': 1, 'type': 'specific_job', 'confirmed': True,
               'skill_ids': ['skill:python', 'skill:sql']}

    # Produce valid saved receipts, then emulate an existing v1 review where
    # only one project consumed the old shared allowance.
    for _ in range(2):
        current = service.get('owner-a', cv['id'])
        request = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target-a', career_target_version=1))
        clarification.prepare(service, 'owner-a', cv['id'], request, context, CURRENT)
    current = service.get('owner-a', cv['id'])
    legacy = deepcopy(current)
    original_questions = [q for q in legacy['clarifications'] if q['item_id'] == project['id']]
    assert len(original_questions) == 2
    for q in original_questions:
        q['_interview_policy'] = {'scope': legacy_scope, 'version': 1}
        q['status'] = 'skipped'
    legacy['clarifications'] = original_questions
    legacy['review_policy_snapshot'] = {'scope': legacy_scope, 'version': 1}
    legacy.pop('review_policy_migrations', None)
    legacy['revision'] += 1
    service.repository.replace(current, legacy)
    receipt_ids = {q['id'] for q in original_questions}

    current = service.get('owner-a', cv['id'])
    request = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target-a', career_target_version=1))
    result = clarification.prepare(service, 'owner-a', cv['id'], request, context, CURRENT)
    saved = service.get('owner-a', cv['id'])
    assert saved['review_policy_snapshot'] == CURRENT
    assert receipt_ids <= {q['id'] for q in saved['clarifications']}
    assert all(q['status'] == 'skipped' for q in saved['clarifications'] if q['id'] in receipt_ids)
    assert len([q for q in saved['clarifications'] if q['item_id'] == project['id']]) == 2
    assert any(q['item_id'] == other['id'] for q in saved['clarifications'])
    assert len(saved.get('review_policy_migrations', [])) == int(legacy_scope == 'section')
    replay = clarification.prepare(service, 'owner-a', cv['id'], request, context, CURRENT)
    assert replay['cv_version'] == result['cv_version']
    assert service.get('owner-a', cv['id'])['clarifications'] == saved['clarifications']
    from app.domain.errors import Conflict
    competing = PrepareMutation.model_validate(mutation(current['version'], career_target_id='target-a', career_target_version=1))
    with pytest.raises(Conflict):
        clarification.prepare(service, 'owner-a', cv['id'], competing, context, CURRENT)
    assert service.get('owner-a', cv['id'])['clarifications'] == saved['clarifications']
