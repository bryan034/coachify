"""To-do sessions: generated names, skills and checkpoints, then the user's own edits, moves and skips."""
from datetime import timedelta
from uuid import uuid4

import pytest

from planner_fixtures import NOW, assignment, draft, gap, milestone
from app.schemas.roadmap import PlanDraft
from test_planner_flow import H, Scripted, accepted, client_for, generate, read

PREFIX = '/api/v1/roadmaps/planner'


class Clock:
    def __init__(self): self.now = NOW
    def __call__(self): return self.now


def call(client, path, state, **data):
    return client.post(PREFIX + path, headers=H, json={'expected_version': state['version'], 'mutation_id': str(uuid4()), **data})


def save(client, path, state, **data):
    response = call(client, path, state, **data)
    assert response.status_code == 200, response.text
    return response.json()


def sessions(state): return state['planner']['active_sessions']
def only(state): return sessions(state)[0]


def rich_draft():
    """What the model is asked for: a short name, the skills practised and dated checkpoints."""
    return draft(
        milestones=[milestone(checkpoints=[{'key': 'late', 'title': 'The API answers one request', 'date': '2030-01-20'},
                                           {'key': 'early', 'title': 'The skeleton runs locally', 'date': '2030-01-13'}])],
        assignments=[assignment(title='Write one tested endpoint', gap_ids=['python'])])


def test_generation_fills_the_to_do_name_skills_and_checkpoints():
    model = Scripted([rich_draft()])
    with client_for(model) as client:
        state = accepted(client)
        row = only(state)
        assert row['title'] == 'Write one tested endpoint' and row['instructions'] == 'Write one tested Python endpoint.'
        assert row['completion_criterion'] == 'The endpoint test passes.'
        assert row['skills'] == [{'name': 'Python', 'canonical_skill_id': row['skills'][0]['canonical_skill_id'], 'gap_id': 'python'}]
        assert (row['date'], row['start_time'], row['duration_minutes'], row['status'], row['missed']) == ('2030-01-09', '19:00', 60, 'scheduled', False)
        assert row['origin'] == 'generated' and row['edited'] is False and row['original'] is None
        assert state['planner']['active']['assignments'][0]['title'] == 'Write one tested endpoint'
        marks = state['planner']['active']['milestones'][0]['checkpoints']
        assert [(c['key'], c['reached_at']) for c in marks] == [('early', None), ('late', None)]
    prompt = model.contexts and __import__('app.planning.generator', fromlist=['x']).PLAN_INSTRUCTIONS
    assert all(word in prompt for word in ('title', 'gap_ids', 'checkpoints', 'Done when'))


def test_a_milestone_without_checkpoints_gets_its_completing_one_and_legacy_sessions_fall_back():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        assert state['planner']['active']['milestones'][0]['checkpoints'] == [
            {'key': 'complete', 'title': 'A small API running locally that you can walk through.', 'date': '2030-01-20', 'reached_at': None}]
        # No gap_ids from the model: the single milestone gap is still shown as the skill.
        assert [skill['gap_id'] for skill in only(state)['skills']] == ['python']


def test_the_validator_rejects_long_names_unknown_skill_gaps_and_misplaced_checkpoints():
    from planner_fixtures import assessment, settings
    from app.planning.capacity import Capacity
    from app.planning.validator import validate_plan
    from app.schemas.roadmap import PlannerConfig
    from datetime import date
    bad = PlanDraft.model_validate(draft(
        milestones=[milestone(checkpoints=[{'key': 'c', 'title': 'One', 'date': '2030-01-25'}, {'key': 'c', 'title': 'Two', 'date': '2030-01-10'}])],
        assignments=[assignment(title='x' * 81, gap_ids=['nowhere'])]))
    capacity = Capacity(PlannerConfig.model_validate(settings()), NOW)
    codes = {e['code'] for e in validate_plan(bad, capacity, assessment(), date(2030, 1, 7))}
    assert {'assignment_title_too_long', 'unknown_gap', 'duplicate_checkpoint', 'checkpoint_outside_milestone'} <= codes
    with pytest.raises(ValueError): PlanDraft.model_validate(draft(assignments=[{k: v for k, v in assignment().items() if k != 'title'}]))


def test_checkpoints_are_ticked_by_the_user_and_survive_a_revision():
    with client_for(Scripted([rich_draft(), rich_draft()])) as client:
        state = accepted(client)
        state = save(client, '/milestones/checkpoint', state, milestone_id='m1', checkpoint_key='early', reached=True)
        marks = {c['key']: c['reached_at'] for c in state['planner']['active']['milestones'][0]['checkpoints']}
        assert marks['early'] and marks['late'] is None
        assert call(client, '/milestones/checkpoint', state, milestone_id='m1', checkpoint_key='missing', reached=True).status_code == 404
        state = generate(client, state)
        kept = {c['key']: c['reached_at'] for c in state['planner']['candidate']['milestones'][0]['checkpoints']}
        assert kept['early'] == marks['early']
        state = save(client, '/milestones/checkpoint', state, milestone_id='m1', checkpoint_key='early', reached=False)
        assert state['planner']['active']['milestones'][0]['checkpoints'][0]['reached_at'] is None


def test_saving_details_renames_keeps_the_original_and_restores_it():
    with client_for(Scripted([rich_draft()])) as client:
        state = accepted(client); row = only(state)
        state = save(client, '/sessions/save', state, session_id=row['id'],
                     changes={'title': 'Ship the endpoint', 'completion_criterion': 'Two tests pass.', 'confidence': 7, 'difficulty': 4,
                              'notes': {'blocks': [{'type': 'paragraph', 'runs': [{'text': 'Used a dataclass.'}]}]}})
        row = only(state)
        assert (row['title'], row['completion_criterion'], row['edited']) == ('Ship the endpoint', 'Two tests pass.', True)
        assert row['original'] == {'title': 'Write one tested endpoint', 'completion_criterion': 'The endpoint test passes.'}
        assert (row['confidence'], row['difficulty']) == (7, 4) and row['rated_at'] and row['notes']['blocks'][0]['runs'][0]['text'] == 'Used a dataclass.'
        task = state['planner']['active']['editable_tasks'][0]
        assert {'title', 'completion_outcome'} <= set(task['overrides']) and task['status'] == 'not_started'
        assert state['planner']['active']['assignments'][0]['title'] == 'Ship the endpoint'
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'restore_original': True, 'confidence': None, 'difficulty': None})
        row = only(state); task = state['planner']['active']['editable_tasks'][0]
        assert (row['title'], row['edited'], row['original'], row['confidence']) == ('Write one tested endpoint', False, None, None)
        assert not {'title', 'completion_outcome'} & set(task['overrides']) and task['original'] is None
        assert call(client, '/sessions/save', state, session_id=row['id'], changes={'title': None}).status_code == 422
        assert call(client, '/sessions/save', state, session_id=row['id'], changes={'confidence': 11}).status_code == 422


def test_a_renamed_task_is_kept_through_a_revision():
    with client_for(Scripted([rich_draft(), draft(assignments=[assignment('other', start_time='20:00', duration_minutes=30)])])) as client:
        state = accepted(client); row = only(state)
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'title': 'Ship the endpoint'})
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        assert 'Ship the endpoint' in [r['title'] for r in state['planner']['candidate_sessions']]


def test_skills_come_from_the_plan_or_the_skills_profile_only():
    with client_for(Scripted([rich_draft()])) as client:
        state = accepted(client); row = only(state)
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'skills': ['git', 'Python']})
        assert [(s['name'], s['gap_id']) for s in only(state)['skills']] == [('Git', None), ('Python', 'python')]
        assert 'skills' in state['planner']['active']['editable_tasks'][0]['overrides']
        refused = call(client, '/sessions/save', state, session_id=row['id'], changes={'skills': ['Juggling']})
        assert refused.status_code == 422 and 'Skills Profile' in refused.json()['detail']
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'skills': []})
        assert only(state)['skills'] == []


def test_times_are_checked_and_a_task_can_be_anytime():
    with client_for(Scripted([rich_draft()])) as client:
        state = accepted(client); row = only(state)
        state = save(client, '/sessions/add', state, session={'title': 'Read the docs', 'date': '2030-01-09', 'start_time': '20:00', 'duration_minutes': 30})
        own = next(r for r in sessions(state) if r['origin'] == 'user')
        assert own['completion_criterion'] == 'You finished “Read the docs”.' and own['milestone_key'] is None and own['skills'] == []
        overlap = call(client, '/sessions/save', state, session_id=row['id'], changes={'duration_minutes': 90})
        assert overlap.status_code == 409 and overlap.json()['code'] == 'overlap' and 'Read the docs' in overlap.json()['detail']
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'duration_minutes': 90}, allow_overlap=True)
        assert next(r for r in sessions(state) if r['id'] == row['id'])['duration_minutes'] == 90
        assert call(client, '/sessions/save', state, session_id=row['id'], changes={'start_time': '23:30'}).status_code == 422
        blocked = call(client, '/sessions/save', state, session_id=row['id'], changes={'date': '2030-01-12', 'start_time': '10:00', 'duration_minutes': 30})
        assert blocked.status_code == 409 and blocked.json()['code'] == 'blackout'
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'start_time': None, 'duration_minutes': 45})
        anytime = next(r for r in sessions(state) if r['id'] == row['id'])
        assert (anytime['start_time'], anytime['duration_minutes'], anytime['date']) == (None, 45, '2030-01-09')
        assert not [a for a in state['planner']['active']['assignments'] if a['id'] == row['id']]
        assert 'unscheduled_remainder' not in {w['code'] for w in state['planner']['task_warnings'] if row['id'] in w['task_ids']}
        state = save(client, '/tasks/status', state, task_id=row['task_id'], status='completed')
        assert next(r for r in sessions(state) if r['id'] == row['id'])['status'] == 'completed'
        state = save(client, '/sessions/save', state, session_id=row['id'], changes={'start_time': '19:00'})
        assert next(r for r in sessions(state) if r['id'] == row['id'])['start_time'] == '19:00'


def test_an_own_task_takes_done_when_skills_and_its_plan_milestone():
    with client_for(Scripted([rich_draft()])) as client:
        state = accepted(client)
        state = save(client, '/sessions/add', state, session={'title': 'Skim the framework docs', 'completion_criterion': 'Three notes written.',
                     'skills': ['Python', 'Git'], 'date': '2030-01-10', 'start_time': None, 'duration_minutes': 20})
        own = next(r for r in sessions(state) if r['origin'] == 'user')
        assert (own['completion_criterion'], own['start_time'], own['milestone_key'], own['date']) == ('Three notes written.', None, 'm1', '2030-01-10')
        task = next(t for t in state['planner']['active']['editable_tasks'] if t['origin'] == 'user')
        assert task['requirement_refs'] == ['job:python'] and task['anytime_date'] == '2030-01-10'
        assert call(client, '/sessions/add', state, session={'title': 'Too late', 'date': '2030-01-08', 'duration_minutes': 30}).status_code == 422
        assert call(client, '/sessions/add', state, session={'title': ' ', 'date': '2030-01-10', 'duration_minutes': 30}).status_code == 422


def missed_plan(client, clock):
    state = accepted(client)
    clock.now = NOW + timedelta(days=1)
    return read(client)


def test_a_missed_session_waits_in_the_backlog_and_elo_proposes_a_free_study_time():
    clock = Clock()
    with client_for(Scripted([rich_draft()]), clock=clock) as client:
        state = missed_plan(client, clock); row = only(state)
        assert row['missed'] is True
        plan = client.post(PREFIX + '/sessions/backlog-plan', headers=H, json={})
        assert plan.status_code == 200, plan.text
        assert plan.json()['moves'] == [{'session_id': row['id'], 'title': 'Write one tested endpoint', 'duration_minutes': 60, 'date': '2030-01-14', 'start_time': '19:00'}]
        free = client.post(PREFIX + '/sessions/free-times', headers=H, json={'duration_minutes': 60, 'session_id': row['id']}).json()
        days = {d['date']: d for d in free['days']}
        assert free['today'] == '2030-01-10' and list(days)[0] == '2030-01-10' and list(days)[-1] == '2030-01-20'
        assert days['2030-01-10']['rest_day'] and days['2030-01-10']['kind'] == 'rest_day' and days['2030-01-10']['starts'][0] == '08:00'
        assert days['2030-01-12']['kind'] == 'none' and days['2030-01-12']['starts'] == []  # a whole-day blackout
        assert days['2030-01-14']['starts'] == ['19:00', '19:15', '19:30', '19:45', '20:00'] and days['2030-01-14']['kind'] == 'study'
        state = save(client, '/sessions/move', state, moves=[{'session_id': row['id'], 'date': '2030-01-14', 'start_time': '19:00'}])
        moved = only(state)
        assert (moved['date'], moved['start_time'], moved['missed'], moved['moved_from_backlog']) == ('2030-01-14', '19:00', False, True)
        assert client.post(PREFIX + '/sessions/backlog-plan', headers=H, json={}).json()['moves'] == []


def test_a_full_study_block_offers_times_after_it_and_two_backlog_items_spread_over_days():
    clock = Clock()
    two = draft(assignments=[assignment(title='First', duration_minutes=45), assignment('a2', title='Second', start_time='19:45', duration_minutes=45)])
    with client_for(Scripted([two]), clock=clock) as client:
        state = missed_plan(client, clock)
        moves = client.post(PREFIX + '/sessions/backlog-plan', headers=H, json={}).json()['moves']
        assert [(m['title'], m['date'], m['start_time']) for m in moves] == [('First', '2030-01-14', '19:00'), ('Second', '2030-01-16', '19:00')]
        state = save(client, '/sessions/move', state, moves=[{'session_id': m['session_id'], 'date': '2030-01-16', 'start_time': t} for m, t in zip(moves, ('19:00', '19:45'))])
        free = client.post(PREFIX + '/sessions/free-times', headers=H, json={'duration_minutes': 30}).json()
        wednesday = next(d for d in free['days'] if d['date'] == '2030-01-16')
        assert wednesday['kind'] == 'after_block' and wednesday['starts'][0] == '20:30'


def test_moves_never_overlap_cross_a_blackout_or_go_into_the_past():
    clock = Clock()
    two = draft(assignments=[assignment(title='First', duration_minutes=45), assignment('a2', title='Second', start_time='19:45', duration_minutes=45)])
    with client_for(Scripted([two]), clock=clock) as client:
        state = missed_plan(client, clock); first, second = sessions(state)
        def refused(**move):
            response = call(client, '/sessions/move', state, moves=[{'session_id': first['id'], **move}])
            return response.status_code, response.json().get('code')
        assert refused(date='2030-01-12', start_time='10:00') == (409, 'blackout')
        assert refused(date='2030-01-09', start_time='21:00') == (409, 'time_passed')
        assert refused(date='2030-01-28', start_time='19:00') == (409, 'outside_plan')
        assert refused(date='2030-01-13', start_time='23:30') == (422, 'validation')
        both = call(client, '/sessions/move', state, moves=[{'session_id': first['id'], 'date': '2030-01-13', 'start_time': '19:00'},
                                                             {'session_id': second['id'], 'date': '2030-01-13', 'start_time': '19:30'}])
        assert both.status_code == 409 and both.json()['code'] == 'slot_taken'
        assert sessions(read(client)) == sessions(state)  # a refused batch moves nothing
        assert call(client, '/sessions/move', state, moves=[{'session_id': 'unknown', 'date': '2030-01-13', 'start_time': '19:00'}]).status_code == 404


def test_only_a_missed_session_can_be_skipped_and_it_leaves_the_list():
    clock = Clock()
    with client_for(Scripted([rich_draft()]), clock=clock) as client:
        state = accepted(client); row = only(state)
        early = call(client, '/sessions/skip', state, session_id=row['id'])
        assert early.status_code == 409 and early.json()['code'] == 'not_missed'
        clock.now = NOW + timedelta(days=1); state = read(client)
        state = save(client, '/sessions/skip', state, session_id=row['id'])
        assert sessions(state) == []
        task = state['planner']['active']['editable_tasks'][0]
        assert task['removed'] and task['removal']['reason'] == 'Skipped missed session.'


def test_a_moved_backlog_task_keeps_its_time_when_the_next_plan_is_prepared():
    clock = Clock()
    later = draft(milestones=[milestone(projected_start='2030-01-10')], assignments=[assignment('next', date='2030-01-14', start_time='20:00', duration_minutes=30)])
    model = Scripted([rich_draft(), later])
    with client_for(model, clock=clock) as client:
        state = missed_plan(client, clock); row = only(state)
        state = save(client, '/sessions/move', state, moves=[{'session_id': row['id'], 'date': '2030-01-14', 'start_time': '19:00'}])
        state = generate(client, state)
        assert state['operation']['status'] == 'succeeded', state['operation']
        assert {'id': row['id'], 'date': '2030-01-14', 'start_time': '19:00', 'duration_minutes': 60} in model.contexts[-1]['reserved_work']
        kept = next(r for r in state['planner']['candidate_sessions'] if r['id'] == row['id'])
        assert (kept['date'], kept['start_time']) == ('2030-01-14', '19:00')
