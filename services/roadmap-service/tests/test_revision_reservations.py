"""Saved student schedules reserve time during synthetic plan revisions."""
import pytest
from planner_fixtures import assignment, draft
from test_planner_flow import Scripted, accepted, client_for, generate
from test_editable_tasks import definition, save, by_title


@pytest.mark.parametrize('status', ['not_started', 'in_progress', 'completed'])
def test_personal_task_reserves_its_time_without_inventing_a_milestone(status):
    overlap = draft(assignments=[assignment('replacement', duration_minutes=30)])
    available = draft(assignments=[assignment('replacement', start_time='19:30', duration_minutes=60)])
    model = Scripted([draft(), overlap, available])
    with client_for(model) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='Personal work', estimated_minutes=30,
            schedule=[{'date':'2030-01-09','start_time':'19:00','duration_minutes':30}]))
        task = by_title(state, 'Personal work')
        if status != 'not_started':
            state = save(client, 'status', state, task_id=task['id'], status=status)
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        assert model.contexts[1]['reserved_work'][0]['id'] == task['id']
        assert model.contexts[1]['reserved_work'][0]['start_time'] == '19:00'
        assert model.contexts[1]['completed_work'] == []
        assert any(e['code'] == 'assignment_outside_block' for e in model.contexts[2]['validation_errors'])
        candidate = state['planner']['candidate']
        assert next(t for t in candidate['editable_tasks'] if t['id'] == task['id'])['milestone_key'] is None
        assert candidate['assignments'][0]['start_time'] == '19:30'


def test_completed_multi_segment_task_is_preserved_once_in_revision():
    revised = draft(assignments=[assignment('replacement', start_time='19:30', duration_minutes=60)])
    model = Scripted([draft(), revised])
    with client_for(model) as client:
        state = accepted(client)
        slots = [{'date':'2030-01-09','start_time':'19:00','duration_minutes':15},
                 {'date':'2030-01-09','start_time':'19:15','duration_minutes':15}]
        state = save(client, 'add', state, task=definition(title='Two part task', estimated_minutes=30,
            milestone_key='m1', schedule=slots))
        task = by_title(state, 'Two part task')
        state = save(client, 'status', state, task_id=task['id'], status='completed')
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        candidate = state['planner']['candidate']
        completed = [t for t in candidate['editable_tasks'] if t['status'] == 'completed' and not t['removed']]
        assert [t['id'] for t in completed] == [task['id']]
        assert completed[0]['schedule'] == slots
        assert len([a for a in candidate['assignments'] if a['status'] == 'completed']) == 2
        assert sum(s['duration_minutes'] for s in model.contexts[1]['reserved_work']) == 30


def test_edited_generated_task_reserves_time_and_is_retained():
    overlap = draft(assignments=[assignment('replacement')])
    available = draft(assignments=[assignment('replacement', start_time='20:00', duration_minutes=30)])
    model = Scripted([draft(), overlap, available])
    with client_for(model) as client:
        state = accepted(client)
        original = state['planner']['active']['editable_tasks'][0]
        state = save(client, 'edit', state, task_id=original['id'], changes={'instructions':'My saved instructions.'})
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        assert any(e['code'] == 'assignment_outside_block' for e in model.contexts[2]['validation_errors'])
        candidate = state['planner']['candidate']
        retained = next(t for t in candidate['editable_tasks'] if t['id'] == original['id'])
        assert retained['instructions'] == 'My saved instructions.'
        assert len([a for a in candidate['assignments'] if a['start_time'] == '19:00']) == 1
        assert any(a['start_time'] == '20:00' for a in candidate['assignments'])


def test_missed_unfinished_slot_does_not_consume_weekly_capacity():
    from app.planning.generator import reserved_sessions
    from planner_fixtures import NOW
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='Missed',
            schedule=[{'date':'2030-01-08','start_time':'19:00','duration_minutes':45}]))
        plan = state['planner']['active']
        assert not any(s['id'] == by_title(state, 'Missed')['id'] for s in reserved_sessions(plan, NOW))
        state = save(client, 'status', state, task_id=by_title(state, 'Missed')['id'], status='completed')
        assert any(s['id'] == by_title(state, 'Missed')['id'] for s in reserved_sessions(state['planner']['active'], NOW))


def test_changed_milestone_definition_requires_new_outcome_confirmation():
    from uuid import uuid4
    from planner_fixtures import milestone
    from test_planner_flow import H
    revised = draft(milestones=[milestone(demonstrable_outcome='A different outcome.')])
    with client_for(Scripted([draft(), revised])) as client:
        state = accepted(client)
        response = client.post('/api/v1/roadmaps/planner/milestones/outcome', headers=H, json={
            'expected_version': state['version'], 'mutation_id': str(uuid4()),
            'milestone_id': 'm1', 'demonstrated': True, 'note': 'I demonstrated the original outcome.'})
        assert response.status_code == 200, response.text
        state = generate(client, response.json())
        assert state['operation']['status'] == 'succeeded', state['operation']
        outcome = state['planner']['candidate']['milestones'][0]['outcome']
        assert outcome['demonstrated'] and outcome['definition_review_required']
        assert outcome['previous_definition'] != 'A different outcome.'
        assert state['planner']['candidate_review']['milestones']['m1']['review_needed']


def test_running_slot_reserves_only_the_remaining_time():
    from app.planning.generator import reserved_sessions
    from planner_fixtures import NOW
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='Partly elapsed',
            schedule=[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}]))
        slots = reserved_sessions(state['planner']['active'], NOW.replace(hour=11, minute=30))
        slot = next(s for s in slots if s['id'] == by_title(state, 'Partly elapsed')['id'])
        assert slot['start_time'] == '19:30' and slot['duration_minutes'] == 30


def test_legacy_completed_task_retains_original_assessment_on_revision():
    from app.planning.generator import protected_tasks
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        plan = state['planner']['active']
        plan.pop('editable_tasks')
        plan['assignments'][0]['status'] = 'completed'
        plan['assignments'][0]['gap_id'] = plan['gaps'][0]['id']
        preserved = protected_tasks(plan)
        assert preserved[0]['requirement_refs'] == [plan['gaps'][0]['requirement_ref']]
        assert preserved[0]['requirement_source_id'] == plan['assessment_id']
        assert 'editable_tasks' not in plan
