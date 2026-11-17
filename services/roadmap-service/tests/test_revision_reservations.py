"""Saved student schedules reserve time during synthetic plan revisions."""
import pytest
from planner_fixtures import assignment, draft
from test_planner_flow import Scripted, accepted, client_for, generate
from test_editable_tasks import definition, save, by_title


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
