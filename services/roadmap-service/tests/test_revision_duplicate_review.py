"""Revisions must not silently duplicate protected work under a new model key."""
from uuid import uuid4

import pytest

from planner_fixtures import assignment, draft
from test_editable_tasks import PREFIX, definition, save
from test_planner_flow import H, Scripted, accepted, client_for, generate


@pytest.mark.parametrize('protected_by,decision', [('edit', 'discard'), ('start', 'keep'), ('complete', 'discard')])
def test_regenerated_new_key_requires_review_against_protected_work(protected_by, decision):
    revised = draft(assignments=[assignment('new-key', start_time='20:00', duration_minutes=30)])
    with client_for(Scripted([draft(), revised])) as client:
        state = accepted(client)
        original = state['planner']['active']['editable_tasks'][0]
        if protected_by == 'edit':
            state = save(client, 'edit', state, task_id=original['id'], changes={'instructions':'My edited instructions.'})
        elif protected_by == 'start':
            state = save(client, 'status', state, task_id=original['id'], status='in_progress')
        else:
            state = save(client, 'status', state, task_id=original['id'], status='completed')
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        review = next(item for item in candidate['revision_review'] if original['id'] in item['related_task_ids'])
        assert 'revision_review_required' in {b['code'] for b in state['planner']['candidate_blockers']}
        assert client.post(PREFIX + '/accept', headers=H, json={
            'expected_version':state['version'], 'mutation_id':str(uuid4())}).status_code == 409
        state = save(client, 'reconcile', state, candidate_id=candidate['id'],
                     decisions=[{'task_id':review['task_id'],'decision':decision}])
        response = client.post(PREFIX + '/accept', headers=H, json={
            'expected_version':state['version'], 'mutation_id':str(uuid4())})
        assert response.status_code == 200, response.text
        final = response.json()['planner']['active']['editable_tasks']
        assert any(t['id'] == original['id'] and not t['removed'] for t in final)
        assert next(t for t in final if t['id'] == review['task_id'])['removed'] == (decision == 'discard')


def test_reused_generated_key_with_same_text_is_not_silently_discarded():
    revised = draft(assignments=[assignment('a1', start_time='20:00', duration_minutes=30)])
    with client_for(Scripted([draft(), revised])) as client:
        state = accepted(client)
        original = state['planner']['active']['editable_tasks'][0]
        state = save(client, 'status', state, task_id=original['id'], status='in_progress')
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        review = next(item for item in candidate['revision_review'] if original['id'] in item['related_task_ids'])
        assert any(t['id'] == review['task_id'] and not t['removed'] for t in candidate['editable_tasks'])
        state = save(client, 'reconcile', state, candidate_id=candidate['id'],
                     decisions=[{'task_id':review['task_id'],'decision':'keep'}])
        response = client.post(PREFIX + '/accept', headers=H, json={
            'expected_version':state['version'], 'mutation_id':str(uuid4())})
        assert response.status_code == 200, response.text
        assert any(t['id'] == review['task_id'] and not t['removed'] for t in response.json()['planner']['active']['editable_tasks'])


def test_new_work_requires_review_against_each_unstarted_personal_task():
    revised = draft(assignments=[assignment('new-key')])
    with client_for(Scripted([draft(), revised])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='Personal one'))
        state = save(client, 'add', state, task=definition(title='Personal two'))
        personal = [t for t in state['planner']['active']['editable_tasks'] if t['origin']=='user']
        assert len(personal)==2 and all(t['status']=='not_started' and not t['overrides'] for t in personal)
        before = state['planner']['active']
        state = generate(client, state)
        assert state['operation']['status']=='succeeded', state['operation']
        assert state['planner']['active']==before
        candidate = state['planner']['candidate']
        review = candidate['revision_review'][0]
        assert {t['id'] for t in personal} <= set(review['related_task_ids'])
        assert 'revision_review_required' in {b['code'] for b in state['planner']['candidate_blockers']}
        body={'expected_version':state['version'],'mutation_id':str(uuid4()),'candidate_id':candidate['id'],
              'decisions':[{'task_id':review['task_id'],'decision':'discard'}]}
        saved=client.post(PREFIX+'/tasks/reconcile',headers=H,json=body)
        assert saved.status_code==200, saved.text
        retry=client.post(PREFIX+'/tasks/reconcile',headers=H,json=body)
        assert retry.status_code==200 and retry.json()['version']==saved.json()['version']
        accepted_response=client.post(PREFIX+'/accept',headers=H,json={
            'expected_version':saved.json()['version'],'mutation_id':str(uuid4())})
        assert accepted_response.status_code==200, accepted_response.text
        active=accepted_response.json()['planner']['active']['editable_tasks']
        assert {t['id'] for t in personal} <= {t['id'] for t in active if not t['removed']}
        assert next(t for t in active if t['id']==review['task_id'])['removed']
