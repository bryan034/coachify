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
