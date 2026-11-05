"""Membership changes invalidate milestone self-reports without erasing history."""
from uuid import uuid4

from planner_fixtures import assignment, draft, milestone
from test_planner_flow import H, Scripted, accepted, client_for, generate, post
from test_editable_tasks import by_title, definition, save


def outcome(state, key='m1'):
    return next(m['outcome'] for m in state['planner']['active']['milestones'] if m['key']==key)


def test_add_and_remove_mark_outcome_for_review_and_reconfirmation_keeps_history():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='Original self-report')
        original=outcome(state)
        state=save(client,'add',state,task=definition(title='Unlinked'))
        assert outcome(state)==original
        request={'expected_version':state['version'],'mutation_id':str(uuid4()),
                 'task':definition(title='Added member',milestone_key='m1')}
        response=client.post('/api/v1/roadmaps/planner/tasks/add',headers=H,json=request)
        assert response.status_code==200, response.text
        state=response.json();marked=outcome(state)
        assert marked['demonstrated'] and marked['note']=='Original self-report'
        assert marked['definition_review_required'] and marked['membership_review_required']
        assert marked['recorded_at']==original['recorded_at']
        retry=client.post('/api/v1/roadmaps/planner/tasks/add',headers=H,json=request)
        assert retry.status_code==200 and outcome(retry.json())==marked
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='Reviewed new scope')
        confirmed=outcome(state)
        assert not confirmed.get('definition_review_required')
        assert confirmed['history'][-1]['note']=='Original self-report'
        assert confirmed['history'][-1]['membership_review_required']
        task=by_title(state,'Added member')
        state=save(client,'remove',state,task_id=task['id'])
        assert outcome(state)['membership_review_required']
        assert outcome(state)['history'][-1]['note']=='Original self-report'


def test_moving_task_marks_both_milestones_and_unchanged_membership_does_not():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        owner='11111111-1111-4111-8111-111111111111'
        plan=client.app.state.store.data[owner]['planner']['active']
        plan['milestones'].append({**milestone('m2',gap_ids=[]),'id':'m2','outcome':{'demonstrated':False}})
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='One')
        state=post(client,'/milestones/outcome',state,milestone_id='m2',demonstrated=True,note='Two')
        task=state['planner']['active']['editable_tasks'][0]
        state=save(client,'edit',state,task_id=task['id'],changes={'instructions':'New instructions'})
        assert not outcome(state,'m1').get('membership_review_required')
        assert not outcome(state,'m2').get('membership_review_required')
        state=save(client,'edit',state,task_id=task['id'],changes={'milestone_key':'m2'})
        assert outcome(state,'m1')['membership_review_required']
        assert outcome(state,'m2')['membership_review_required']


def test_revision_membership_change_invalidates_saved_outcome_and_legacy_preview_accept():
    with client_for(Scripted([draft(),draft(assignments=[assignment('a2')])])) as client:
        state=accepted(client)
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='Prior scope')
        state=generate(client,state)
        assert state['operation']['status']=='succeeded', state['operation']
        candidate=state['planner']['candidate']
        assert candidate['milestones'][0]['outcome']['membership_review_required']
        # An older preview can have been saved before membership review existed.
        owner='11111111-1111-4111-8111-111111111111'
        old_outcome=client.app.state.store.data[owner]['planner']['candidate']['milestones'][0]['outcome']
        old_outcome.pop('definition_review_required');old_outcome.pop('membership_review_required')
        response=client.post('/api/v1/roadmaps/planner/accept',headers=H,json={
            'expected_version':state['version'],'mutation_id':str(uuid4())})
        assert response.status_code==200, response.text
        assert outcome(response.json())['membership_review_required']


def test_membership_review_blocks_dependent_milestone_without_inventing_progress():
    from app.planning.milestone_membership import mark_membership_review
    from app.planning.tasks import task_readiness
    earlier={'id':'first','title':'First','milestone_key':'m1','status':'completed','removed':False,'prerequisites':[]}
    later={'id':'later','title':'Later','milestone_key':'m2','status':'not_started','removed':False,'prerequisites':[]}
    plan={'milestones':[{'key':'m1','outcome':{'demonstrated':True,'note':'Self-report'}},
                        {'key':'m2','prerequisite_keys':['m1']}]}
    assert task_readiness(later,[earlier,later],plan)['actionable']
    mark_membership_review(plan,['m1'])
    view=task_readiness(later,[earlier,later],plan)
    assert not view['actionable'] and view['reasons'][0]['code']=='milestone_prerequisite_incomplete'
    assert plan['milestones'][0]['outcome']['note']=='Self-report'


def test_discarding_new_revision_work_restores_unchanged_membership_without_false_review():
    revised=draft(assignments=[assignment('new',start_time='20:00',duration_minutes=30)])
    with client_for(Scripted([draft(),revised])) as client:
        state=accepted(client)
        task=state['planner']['active']['editable_tasks'][0]
        state=save(client,'edit',state,task_id=task['id'],changes={'instructions':'My saved work'})
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='Current scope')
        state=generate(client,state)
        candidate=state['planner']['candidate']
        assert candidate['milestones'][0]['outcome']['membership_review_required']
        review=candidate['revision_review'][0]
        state=save(client,'reconcile',state,candidate_id=candidate['id'],
                   decisions=[{'task_id':review['task_id'],'decision':'discard'}])
        restored=state['planner']['candidate']['milestones'][0]['outcome']
        assert restored['demonstrated'] and restored['note']=='Current scope'
        assert not restored.get('membership_review_required')
        assert not restored.get('definition_review_required')
