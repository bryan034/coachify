"""Calendar extremes cannot make a saved roadmap unreadable."""
import copy
from uuid import uuid4

import pytest

from planner_fixtures import OWNER, draft
from test_editable_tasks import by_title, definition, request
from test_planner_flow import H, Scripted, accepted, client_for


@pytest.mark.parametrize('day', ['0001-01-01', '9999-12-31'])
def test_extreme_calendar_dates_save_and_remain_readable(day):
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        response = request(client, 'add', state, task=definition(title='Calendar boundary',
            schedule=[{'date':day, 'start_time':'12:00', 'duration_minutes':30}]))
        assert response.status_code == 200, response.text
        after = response.json()
        task = by_title(after, 'Calendar boundary')
        assert task['schedule'][0]['date'] == day
        assert any(w['code'] == 'outside_plan' and task['id'] in w['task_ids']
                   for w in after['planner']['task_warnings'])
        if day == '9999-12-31':
            assert any(w['code'] == 'calendar_unavailable' and task['id'] in w['task_ids']
                       for w in after['planner']['task_warnings'])
            assert not any(w['code'] == 'outside_study_time' and task['id'] in w['task_ids']
                           for w in after['planner']['task_warnings'])
        restored = client.get('/api/v1/roadmaps/workspace', headers=H)
        assert restored.status_code == 200
        listing = client.get('/api/v1/roadmaps/planner/tasks', headers=H)
        assert listing.status_code == 200
        assert next(t for t in listing.json()['tasks'] if t['id'] == task['id'])['schedule'][0]['date'] == day


def test_existing_extreme_date_can_be_read_and_corrected():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        row = client.app.state.store.data[OWNER]
        task = row['planner']['active']['editable_tasks'][0]
        task['schedule'] = [{'date':'9999-12-31', 'start_time':'12:00', 'duration_minutes':30}]
        saved = copy.deepcopy(row)
        response = client.get('/api/v1/roadmaps/workspace', headers=H)
        assert response.status_code == 200
        assert client.app.state.store.data[OWNER] == saved
        body = {'expected_version':state['version'], 'mutation_id':str(uuid4()),
                'task_id':task['id'], 'changes':{'schedule':[]}}
        corrected = client.post('/api/v1/roadmaps/planner/tasks/edit', headers=H, json=body)
        assert corrected.status_code == 200, corrected.text
        assert next(t for t in corrected.json()['planner']['active']['editable_tasks'] if t['id'] == task['id'])['schedule'] == []


def test_extreme_dates_return_bounded_warnings_for_every_affected_task():
    from app.planning.tasks import schedule_warnings
    from planner_fixtures import NOW, settings
    slot={'date':'9999-12-31','start_time':'12:00','duration_minutes':30}
    tasks=[{'id':name,'schedule':[slot],'estimated_minutes':30,'status':'not_started',
            'removed':False,'prerequisites':[]} for name in ('first','second')]
    warnings=schedule_warnings({'config':settings(),'milestones':[],'editable_tasks':tasks},NOW)
    unknown=[w for w in warnings if w['code']=='calendar_unavailable']
    assert len(unknown)==1 and set(unknown[0]['task_ids'])=={'first','second'}
    assert set(next(w for w in warnings if w['code']=='overlap')['task_ids'])=={'first','second'}
