"""Editable roadmap tasks through owner-scoped HTTP APIs, using synthetic plans."""
import copy
from uuid import uuid4

from planner_fixtures import assignment, draft
from test_planner_flow import H, Scripted, Sources, accepted, client_for, generate, read

PREFIX = '/api/v1/roadmaps/planner'


def request(client, endpoint, state, **data):
    return client.post(PREFIX + '/tasks/' + endpoint, headers=H,
                       json={'expected_version': state['version'], 'mutation_id': str(uuid4()), **data})


def save(client, endpoint, state, **data):
    response = request(client, endpoint, state, **data)
    assert response.status_code == 200, response.text
    return response.json()


def definition(**changes):
    return {'title': 'Practise explaining a project', 'instructions': 'Record a short explanation.',
            'completion_outcome': 'A recording exists.', 'estimated_minutes': 45,
            'requirement_refs': [], 'prerequisites': [], 'milestone_key': None, 'schedule': [], **changes}


def tasks(client, **params):
    response = client.get(PREFIX + '/tasks', headers=H, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def by_title(state, title):
    return next(t for t in state['planner']['active']['editable_tasks'] if t['title'] == title)

def test_add_unscheduled_personal_task_restore_and_owner_isolation():
    sources = Sources()
    with client_for(Scripted([draft()]), sources) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition())
        added = by_title(state, 'Practise explaining a project')
        assert added['requirement_refs'] == [] and added['milestone_key'] is None and added['schedule'] == []
        listing = tasks(client, start_date='2030-01-09', end_date='2030-01-09')
        visible = next(t for t in listing['tasks'] if t['id'] == added['id'])
        assert visible['unscheduled_minutes'] == 45
        assert visible['readiness']['actionable'] is True
        restored = read(client)
        assert by_title(restored, added['title'])['id'] == added['id']
        sources.owner = '22222222-2222-4222-8222-222222222222'
        assert read(client)['planner']['active'] is None
        response = request(client, 'edit', read(client), task_id=added['id'], changes={'title': 'Other account'})
        assert response.status_code in (404, 409)
        sources.owner = '11111111-1111-4111-8111-111111111111'
        assert by_title(read(client), added['title'])['id'] == added['id']

def test_validation_rejects_invalid_definitions_and_stale_or_reused_keys():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        for bad in (definition(title='  '), definition(instructions=' '), definition(completion_outcome=''),
                    definition(estimated_minutes=0), definition(estimated_minutes=-1)):
            assert request(client, 'add', state, task=bad).status_code == 422
        body = {'expected_version': state['version'], 'mutation_id': str(uuid4()), 'task': definition()}
        first = client.post(PREFIX + '/tasks/add', headers=H, json=body)
        assert first.status_code == 200, first.text
        saved = first.json()
        replay = client.post(PREFIX + '/tasks/add', headers=H, json=body)
        assert replay.status_code == 200, replay.text
        assert replay.json()['version'] == saved['version']
        assert len([t for t in replay.json()['planner']['active']['editable_tasks'] if t['title'] == body['task']['title']]) == 1
        changed = copy.deepcopy(body); changed['task']['title'] = 'Different change'
        assert client.post(PREFIX + '/tasks/add', headers=H, json=changed).status_code == 409
        assert request(client, 'add', state, task=definition(title='Stale save')).status_code == 409

def test_edits_removals_and_prerequisites_preserve_dependents_and_history():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='First task'))
        prerequisite = by_title(state, 'First task')['id']
        state = save(client, 'add', state, task=definition(title='Dependent task', prerequisites=[prerequisite]))
        dependent = by_title(state, 'Dependent task')['id']
        view = next(t for t in tasks(client)['tasks'] if t['id'] == dependent)
        assert not view['readiness']['actionable'] and view['readiness']['reasons']
        state = save(client, 'edit', state, task_id=prerequisite, changes={'instructions': 'Practise the explanation twice.'})
        assert by_title(state, 'First task')['instructions'] == 'Practise the explanation twice.'
        state = save(client, 'remove', state, task_id=prerequisite, reason='No longer useful')
        removed = by_title(state, 'First task')
        assert removed['removed'] and removed['removal']['reason'] == 'No longer useful'
        assert by_title(state, 'Dependent task')['prerequisites'] == [prerequisite]
        visible = tasks(client)['tasks']
        assert all(t['id'] != prerequisite for t in visible)
        blocked = next(t for t in visible if t['id'] == dependent)
        assert not blocked['readiness']['actionable'] and blocked['readiness']['reasons']

def test_manual_overlapping_slots_are_saved_with_warnings_not_silent_rescheduling():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        schedule = [{'date': '2030-01-09', 'start_time': '19:00', 'duration_minutes': 45}]
        state = save(client, 'add', state, task=definition(schedule=schedule))
        added = by_title(state, 'Practise explaining a project')
        assert added['schedule'] == schedule
        listing = tasks(client, start_date='2030-01-09', end_date='2030-01-09')
        assert any(added['id'] in warning['task_ids'] for warning in listing['warnings'])
        assert by_title(read(client), added['title'])['schedule'] == schedule

def test_revision_retains_edits_personal_tasks_and_removal_intent():
    revised = draft(assignments=[assignment('a1')])
    with client_for(Scripted([draft(), revised])) as client:
        state = accepted(client)
        generated = next(t for t in state['planner']['active']['editable_tasks'] if t['schedule'])
        state = save(client, 'edit', state, task_id=generated['id'], changes={'instructions': 'My own instructions.'})
        state = save(client, 'add', state, task=definition(title='My own task'))
        state = save(client, 'remove', state, task_id=generated['id'], reason='Not needed')
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        removed = next(t for t in candidate['editable_tasks'] if t['id'] == generated['id'])
        assert removed['removed'] and removed['removal']['reason'] == 'Not needed'
        assert removed['instructions'] == 'My own instructions.'
        assert any(t['title'] == 'My own task' and not t['removed'] for t in candidate['editable_tasks'])
        assert not any(t['id'] != generated['id'] and t.get('generated_key') == 'a1' and not t['removed'] for t in candidate['editable_tasks'])

def test_edit_invalidates_preexisting_revision_preview():
    with client_for(Scripted([draft(), draft()])) as client:
        state = accepted(client)
        state = generate(client, state)
        assert state['planner']['candidate']
        generated = state['planner']['active']['editable_tasks'][0]
        state = save(client, 'edit', state, task_id=generated['id'], changes={'title': 'Changed after preview'})
        assert 'active_changed' in {item['code'] for item in state['planner']['candidate_blockers']}
        response = client.post(PREFIX + '/accept', headers=H,
                               json={'expected_version': state['version'], 'mutation_id': str(uuid4())})
        assert response.status_code == 409

def test_revision_requires_explicit_review_of_unmatched_work_after_removal():
    with client_for(Scripted([draft(), draft(assignments=[assignment('new-key')])])) as client:
        state = accepted(client)
        old = state['planner']['active']['editable_tasks'][0]
        state = save(client, 'remove', state, task_id=old['id'], reason='Do not restore this')
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        assert candidate['revision_review']
        review = candidate['revision_review'][0]
        assert old['id'] in review['removed_task_ids']
        assert 'revision_review_required' in {item['code'] for item in state['planner']['candidate_blockers']}
        blocked = client.post(PREFIX + '/accept', headers=H,
                              json={'expected_version': state['version'], 'mutation_id': str(uuid4())})
        assert blocked.status_code == 409
        state = save(client, 'reconcile', state, candidate_id=candidate['id'],
                     decisions=[{'task_id': review['task_id'], 'decision': 'discard'}])
        response = client.post(PREFIX + '/accept', headers=H,
                               json={'expected_version': state['version'], 'mutation_id': str(uuid4())})
        assert response.status_code == 200, response.text
        active = response.json()['planner']['active']['editable_tasks']
        assert any(t['id'] == old['id'] and t['removed'] for t in active)
        assert not any(t['id'] == review['task_id'] and not t['removed'] for t in active)

def test_requirement_links_are_validated_and_edited_without_inventing_a_link():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        assert request(client, 'add', state, task=definition(requirement_refs=['job:invented'])).status_code == 422
        state = save(client, 'add', state, task=definition(requirement_refs=['job:python', 'job:sql']))
        task = by_title(state, 'Practise explaining a project')
        assert task['requirement_refs'] == ['job:python', 'job:sql']
        state = save(client, 'edit', state, task_id=task['id'], changes={'requirement_refs': []})
        assert by_title(state, task['title'])['requirement_refs'] == []

def test_period_views_include_unscheduled_remainder_and_filter_fully_scheduled_work():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        slot = {'date': '2030-01-10', 'start_time': '13:00', 'duration_minutes': 20}
        state = save(client, 'add', state, task=definition(title='Partly scheduled', estimated_minutes=45, schedule=[slot]))
        partial = by_title(state, 'Partly scheduled')['id']
        state = save(client, 'add', state, task=definition(title='Fully scheduled', estimated_minutes=20, schedule=[slot]))
        full = by_title(state, 'Fully scheduled')['id']
        outside = tasks(client, start_date='2030-01-11', end_date='2030-01-11')['tasks']
        assert next(t for t in outside if t['id'] == partial)['unscheduled_minutes'] == 25
        assert all(t['id'] != full for t in outside)
        inside = tasks(client, start_date='2030-01-10', end_date='2030-01-10')['tasks']
        assert {partial, full}.issubset({t['id'] for t in inside})
        assert client.get(PREFIX + '/tasks', headers=H, params={'start_date': '2030-01-10'}).status_code == 422
        assert client.get(PREFIX + '/tasks', headers=H, params={'start_date': '2030-01-11', 'end_date': '2030-01-10'}).status_code == 422

def test_cyclic_and_unknown_prerequisites_are_rejected_without_changing_saved_tasks():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        assert request(client, 'add', state, task=definition(prerequisites=['missing'])).status_code == 422
        state = save(client, 'add', state, task=definition(title='First'))
        first = by_title(state, 'First')['id']
        state = save(client, 'add', state, task=definition(title='Second', prerequisites=[first]))
        second = by_title(state, 'Second')['id']
        assert request(client, 'edit', state, task_id=first, changes={'prerequisites': [second]}).status_code == 422
        restored = read(client)
        assert by_title(restored, 'First')['prerequisites'] == []
        assert by_title(restored, 'Second')['prerequisites'] == [first]

def test_reused_generated_key_with_changed_content_requires_reconciliation():
    changed = draft(assignments=[assignment('a1', task='A different generated exercise.', start_time='20:00', duration_minutes=30)])
    with client_for(Scripted([draft(), changed])) as client:
        state = accepted(client)
        original = state['planner']['active']['editable_tasks'][0]
        state = save(client, 'edit', state, task_id=original['id'], changes={'instructions': 'My saved exercise.'})
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        assert next(t for t in candidate['editable_tasks'] if t['id'] == original['id'])['instructions'] == 'My saved exercise.'
        review = candidate['revision_review'][0]
        assert original['id'] in review['related_task_ids']
        assert 'revision_review_required' in {item['code'] for item in state['planner']['candidate_blockers']}
        state = save(client, 'reconcile', state, candidate_id=candidate['id'],
                     decisions=[{'task_id': review['task_id'], 'decision': 'keep'}])
        response = client.post(PREFIX + '/accept', headers=H,
                               json={'expected_version': state['version'], 'mutation_id': str(uuid4())})
        assert response.status_code == 200, response.text
        tasks_after = response.json()['planner']['active']['editable_tasks']
        assert next(t for t in tasks_after if t['id'] == original['id'])['instructions'] == 'My saved exercise.'
        assert any(t['id'] == review['task_id'] and not t['removed'] for t in tasks_after)

def test_revision_preserves_prerequisite_of_personal_task():
    initial = draft(assignments=[assignment('a1'), assignment('a2', start_time='20:00', duration_minutes=30)])
    revised = draft(assignments=[assignment('a1')])
    with client_for(Scripted([initial, revised])) as client:
        state = accepted(client)
        prerequisite = next(t for t in state['planner']['active']['editable_tasks'] if t['generated_key'] == 'a2')
        state = save(client, 'add', state, task=definition(title='My dependent', prerequisites=[prerequisite['id']]))
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']['editable_tasks']
        assert any(t['id'] == prerequisite['id'] and not t['removed'] for t in candidate)
        dependent = next(t for t in candidate if t['title'] == 'My dependent')
        assert dependent['prerequisites'] == [prerequisite['id']]

def test_old_requirement_link_survives_an_unrelated_edit_and_is_flagged():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(requirement_refs=['job:python']))
        ident = by_title(state, 'Practise explaining a project')['id']
        owner = '11111111-1111-4111-8111-111111111111'
        # A revised assessment no longer contains the old reference.
        plan = client.app.state.store.data[owner]['planner']['active']
        plan['assessment']['job_skill_gaps'] = []
        state = read(client)
        state = save(client, 'edit', state, task_id=ident, changes={'instructions': 'Revise the recording.'})
        view = next(t for t in tasks(client)['tasks'] if t['id'] == ident)
        assert view['requirement_refs'] == ['job:python']
        assert view['stale_requirement_refs'] == ['job:python']
        assert request(client, 'edit', state, task_id=ident, changes={'requirement_refs': ['job:unknown']}).status_code == 422

def test_same_requirement_id_from_new_assessment_is_flagged_until_reselected():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(requirement_refs=['job:python']))
        ident = by_title(state, 'Practise explaining a project')['id']
        owner = '11111111-1111-4111-8111-111111111111'
        plan = client.app.state.store.data[owner]['planner']['active']
        plan['assessment_hash'] = 'new-assessment-with-same-ids'
        state = read(client)
        view = next(t for t in tasks(client)['tasks'] if t['id'] == ident)
        assert view['stale_requirement_refs'] == ['job:python']
        state = save(client, 'edit', state, task_id=ident, changes={'requirement_refs': ['job:python']})
        view = next(t for t in tasks(client)['tasks'] if t['id'] == ident)
        assert view['stale_requirement_refs'] == []

def test_requirement_source_uses_result_id_even_when_input_hash_is_unchanged():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(requirement_refs=['job:python']))
        ident = by_title(state, 'Practise explaining a project')['id']
        owner = '11111111-1111-4111-8111-111111111111'
        client.app.state.store.data[owner]['planner']['active']['assessment_id'] = 'new-result-same-input'
        state = read(client)
        assert next(t for t in tasks(client)['tasks'] if t['id'] == ident)['stale_requirement_refs'] == ['job:python']
        state = save(client, 'edit', state, task_id=ident, changes={'requirement_refs': ['job:python']})
        assert next(t for t in tasks(client)['tasks'] if t['id'] == ident)['stale_requirement_refs'] == []
