"""Saved unfinished sessions reduce the model's budget for their scheduled week."""
from datetime import timedelta

from planner_fixtures import NOW, assignment
from test_editable_tasks import by_title, definition, save
from test_planner_flow import Clock, Scripted, accept_week, accepted, client_for, long_draft, plan_week, read, task, week_draft


def test_missed_sessions_reduce_the_model_budget_for_the_current_week():
    clock = Clock()

    def proposal(minutes):
        return lambda context: week_draft(
            [task('b1', 'Add a second endpoint', 80), task('b2', 'Validate request bodies', minutes)],
            carryover=[{'task_id': item['task_id'], 'action': 'defer', 'reason': 'Review later.'}
                       for item in context['progress']['unfinished']],
        )

    model = Scripted([long_draft()], weeks=[week_draft([assignment()]), proposal(160), proposal(100)])
    with client_for(model, clock=clock) as client:
        state = accepted(client)
        state = save(client, 'add', state, task=definition(title='Missed practice', estimated_minutes=120,
            schedule=[{'date': day, 'start_time': '19:00', 'duration_minutes': 60}
                      for day in ('2030-01-14', '2030-01-15')]))
        clock.now = NOW + timedelta(days=7)
        state = plan_week(client, read(client), '2030-01-14')
        assert state['operation']['status'] == 'succeeded', state['operation']
        first, retry = model.sent('WeekDraft')[-2:]
        assert first['target_minutes'] == first['new_task_minutes'] == 180
        assert by_title(state, 'Missed practice')['id'] in {item['task_id'] for item in first['progress']['unfinished']}
        assert any('room for 180' in error for error in retry['validation_errors'])
        state = accept_week(client, state)
        assert by_title(state, 'Missed practice')['deferred_week'] == '2030-01-14'
