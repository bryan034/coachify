"""Task actions, custom tasks, deterministic rescheduling, Undo and repeated access, through the API."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore
from planner_fixtures import NOW, OWNER, Staged, assignment, draft, milestone, second_week, settings
from test_planner_flow import H, Sources, accepted, generate, post, read
from app.main import create_app

class Clock:
    def __init__(self,moment=NOW):self.moment=moment
    def __call__(self):return self.moment
    def set(self,day,hour=0,month=1):self.moment=NOW.replace(day=day,hour=hour,month=month)
def client(model=None,clock=None,sources=None):
    return TestClient(create_app(MemoryStore(),sources or Sources(),model or Staged([draft()]),clock=clock or Clock()))
def task(state,key):
    return next(a for a in state['planner']['active']['assignments'] if a['key']==key)
def rejected(c,path,state,**body):
    response=c.post('/api/v1/roadmaps/planner'+path,headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),**body})
    assert response.status_code>=400,response.text
    return response.status_code,response.json()['code']
def custom(c,state,**changes):
    return post(c,'/tasks/custom',state,**{'title':'Mock interview','duration_minutes':60,'week_start':'2030-01-14',**changes})
def added(state,title='Mock interview'):
    return next(a for a in state['planner']['active']['assignments'] if a['task']==title)

def test_completion_is_one_click_and_feedback_is_optional():
    with client() as c:
        state=accepted(c);one=task(state,'a1')
        state=post(c,'/assignments/status',state,assignment_id=one['id'],status='completed')
        done=task(state,'a1')
        assert done['status']=='completed' and done['evidence_note'] is None and done['completed_at'] and done['feedback'] is None
        state=post(c,'/tasks/update',state,task_id=one['id'],feedback='too_hard')
        assert task(state,'a1')['feedback']=='too_hard'
        assert 'too hard' in ' '.join(state['planner']['active_view']['coach']['messages'])

def test_skipped_tasks_leave_the_schedule_stay_in_history_and_can_return_to_backlog():
    with client() as c:
        state=accepted(c);one=task(state,'a1')
        before=state['planner']['active_view']['progress']['generated_tasks']
        state=post(c,'/tasks/skip',state,task_id=one['id'])
        view=state['planner']['active_view']
        assert task(state,'a1')['status']=='skipped' and view['skipped_task_ids']==[one['id']]
        assert view['next_task_id']!=one['id'] and view['progress']['generated_tasks']==before
        state=post(c,'/tasks/restore',state,task_id=one['id'])
        assert task(state,'a1')['status']=='backlog' and task(state,'a1')['date'] is None
        row=state['planner']['active_view']['backlog'][0]
        assert row['task_id']==one['id'] and row['suggested_slot']

def test_manual_moves_are_validated_and_explained():
    with client() as c:
        state=accepted(c);one=task(state,'a1')
        move=lambda **body:rejected(c,'/tasks/move',state,task_id=one['id'],**body)
        assert move(date='2030-01-09',start_time='07:00')==(409,'slot_in_past')
        assert move(date='2030-01-28',start_time='19:00')==(409,'after_target')
        assert move(date='2030-01-12',start_time='10:00')==(409,'slot_blackout')
        assert move(date='2030-01-14',start_time='19:30')==(409,'slot_occupied')
        assert move(date='2030-01-10',start_time='23:30')==(409,'slot_invalid')
        assert move(date='2030-01-10',start_time='12:00')==(409,'outside_study_blocks')
        state=post(c,'/tasks/move',state,task_id=one['id'],date='2030-01-10',start_time='12:00',confirm_outside_blocks=True)
        moved=task(state,'a1')
        assert (moved['date'],moved['start_time'],moved['manual_moves'],moved['auto_moves'])==('2030-01-10','12:00',1,0)

def test_weekly_maximum_applies_to_included_hours_and_excluded_tasks_still_occupy_time():
    with client() as c:
        state=accepted(c)
        state=custom(c,state,title='Long block',duration_minutes=240,date='2030-01-16',start_time='09:00',confirm_outside_blocks=True)
        # a2 is 60 minutes, so the week holds 300 of 300 included minutes.
        code=rejected(c,'/tasks/custom',state,title='One more',duration_minutes=30,week_start='2030-01-14',date='2030-01-17',start_time='09:00',confirm_outside_blocks=True)
        assert code==(409,'weekly_maximum')
        state=custom(c,state,title='Dentist',duration_minutes=30,date='2030-01-17',start_time='09:00',confirm_outside_blocks=True,count_hours=False)
        assert added(state,'Dentist')['status']=='scheduled'
        assert state['planner']['active_view']['progress']['custom_excluded_minutes']==30
        one=task(state,'a1')
        assert rejected(c,'/tasks/move',state,task_id=one['id'],date='2030-01-17',start_time='09:15',confirm_outside_blocks=True)==(409,'slot_occupied')
        dentist=added(state,'Dentist')
        assert rejected(c,'/tasks/update',state,task_id=dentist['id'],count_hours=True)==(409,'weekly_maximum')

def test_a_custom_task_with_no_placement_waits_in_backlog_with_its_week_preference():
    with client() as c:
        state=custom(c,accepted(c),note='Ask a mentor.')
        item=added(state)
        assert item['status']=='backlog' and item['week_start']=='2030-01-14' and item['note']=='Ask a mentor.' and item['count_hours']
        assert state['planner']['active_view']['backlog'][0]['reason']=='No time chosen yet.'
        assert rejected(c,'/tasks/custom',state,title='Half placed',duration_minutes=30,week_start='2030-01-14',date='2030-01-15')[0]==422

def test_only_custom_tasks_can_be_excluded_from_hours():
    with client() as c:
        state=accepted(c)
        assert rejected(c,'/tasks/update',state,task_id=task(state,'a1')['id'],count_hours=False)==(409,'task_generated')

def test_a_missed_task_moves_once_with_a_message_and_stable_counts():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        clock.set(9,hour=14)  # 22:00 Wednesday: the task's day hasn't ended, so it isn't missed yet.
        assert task(read(c),'a1')['date']=='2030-01-09'
        clock.set(10)  # 08:00 Thursday in Singapore.
        state=read(c);moved=task(state,'a1')
        # Saturday is a blackout, and Monday 19:00 is taken by a2, so Monday 20:00 is the earliest fit.
        assert (moved['date'],moved['start_time'],moved['auto_moves'],moved['manual_moves'],moved['duration_minutes'])==('2030-01-14','20:00',1,0,60)
        events=state['planner']['active_view']['coach']['recent_moves']
        assert [e['message'] for e in events]==['Moved to Monday 20:00']

def test_repeated_and_concurrent_access_produce_one_result():
    clock=Clock()
    with client(clock=clock) as c:
        accepted(c);clock.set(10)
        first=read(c);second=read(c)
        assert first['version']==second['version'] and first['planner']['active']==second['planner']['active']
        assert len([e for e in second['planner']['active']['events'] if e['type']=='auto_move'])==1
    clock=Clock()
    with client(clock=clock) as c:
        accepted(c);clock.set(10)
        with ThreadPoolExecutor(8) as pool:states=list(pool.map(lambda _:read(c),range(8)))
        latest=read(c)
        moved=[e for e in latest['planner']['active']['events'] if e['type']=='auto_move']
        assert len(moved)==1 and task(latest,'a1')['auto_moves']==1
        assert len([h for h in task(latest,'a1')['history'] if h['action']=='auto_move'])==1
        assert all(task(s,'a1')['date']=='2030-01-14' for s in states)

def test_dependencies_move_first_and_a_prerequisite_stays_before_its_dependent():
    plan=draft(assignments=[assignment('a1',duration_minutes=40),assignment('a3',start_time='19:40',duration_minutes=30,depends_on=['a1']),second_week('a4',start_time='20:00')])
    clock=Clock()
    with client(Staged([plan]),clock=clock) as c:
        state=accepted(c);clock.set(10);state=read(c)
        one,three=task(state,'a1'),task(state,'a3')
        assert (one['date'],one['start_time'])==('2030-01-14','19:00')
        # 19:40 on Monday would run into a4 at 20:00, so the dependent waits for Wednesday's block.
        assert (three['date'],three['start_time'])==('2030-01-16','19:00')

def test_a_prerequisite_with_no_slot_before_its_dependent_goes_to_backlog_with_the_reason():
    plan=draft(assignments=[assignment('a1'),second_week('a2',depends_on=['a1'],start_time='19:00')])
    clock=Clock()
    with client(Staged([plan]),clock=clock) as c:
        accepted(c);clock.set(10);state=read(c)
        one=task(state,'a1')
        assert one['status']=='backlog' and 'before the task that depends on it' in one['backlog_reason']

def test_a_dependent_waits_while_its_prerequisite_is_not_scheduled():
    plan=draft(assignments=[assignment('a1',duration_minutes=40),assignment('a3',start_time='20:00',duration_minutes=30,depends_on=['a1']),second_week()])
    clock=Clock()
    with client(Staged([plan]),clock=clock) as c:
        state=accepted(c)
        state=post(c,'/tasks/update',state,task_id=task(state,'a1')['id'],pinned=True)
        clock.set(10);state=read(c)
        assert task(state,'a1')['action_needed']['reason']=='missed_pinned'
        three=task(state,'a3')
        assert three['status']=='backlog' and 'depends on' in three['backlog_reason']

def test_a_long_task_with_no_contiguous_room_goes_to_backlog_and_never_splits():
    blocks=[{'day':2,'start_time':'19:00','duration_minutes':90,'kind':'preferred'},{'day':0,'start_time':'19:00','duration_minutes':45,'kind':'preferred'},{'day':4,'start_time':'19:00','duration_minutes':45,'kind':'preferred'}]
    for target,expected in (('2030-01-16','2030-01-16'),('2030-01-15',None)):
        plan=draft(assignments=[assignment('a1',duration_minutes=70),assignment('a2',date='2030-01-14',start_time='19:00',duration_minutes=30)],milestones=[milestone(estimated_minutes=100,projected_end=target)])
        clock=Clock()
        with client(Staged([plan]),clock=clock) as c:
            state=c.post('/api/v1/roadmaps/planner/config',headers=H,json={'expected_version':read(c)['version'],'mutation_id':str(uuid4()),'config':settings(blocks=blocks,blackouts=[],target_date=target)}).json()
            state=generate(c,state);assert state['operation']['status']=='succeeded',state['operation']
            state=post(c,'/accept',state)
            clock.set(10);state=read(c);one=task(state,'a1')
            # Friday has 45 minutes and Monday 15 are free. Only Wednesday the 16th holds 70 together.
            assert one['duration_minutes']==70
            if expected:assert one['date']==expected
            else:assert one['status']=='backlog' and 'fits before your target date' in one['backlog_reason']

def test_a_full_week_is_passed_over_for_the_next_one():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        state=custom(c,state,title='Fill week two',duration_minutes=240,date='2030-01-15',start_time='09:00',confirm_outside_blocks=True)
        clock.set(10);state=read(c)
        # Week two holds 300 of 300 included minutes, so the task goes to week three's first block.
        assert task(state,'a1')['date']=='2030-01-21'

def test_automatic_moves_stop_after_two_and_ask_the_user():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        clock.set(10);state=read(c);assert task(state,'a1')['date']=='2030-01-14'
        clock.set(15);state=read(c)
        assert task(state,'a1')['auto_moves']==2 and task(state,'a1')['date']>'2030-01-15'
        day=int(task(state,'a1')['date'][-2:])
        clock.set(day+1);state=read(c)
        one=task(state,'a1')
        assert one['auto_moves']==2 and one['action_needed']['reason']=='auto_move_limit' and one['id'] in state['planner']['active_view']['coach']['action_needed_task_ids']
        before=state['version']
        assert read(c)['version']==before

def test_completed_pinned_and_custom_tasks_never_move_and_show_action_needed():
    clock=Clock()
    plan=draft(assignments=[assignment('a1',duration_minutes=30),assignment('a3',start_time='19:30',duration_minutes=30),second_week()])
    with client(Staged([plan]),clock=clock) as c:
        state=accepted(c)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        state=post(c,'/tasks/update',state,task_id=task(state,'a3')['id'],pinned=True)
        state=custom(c,state,week_start='2030-01-07',date='2030-01-09',start_time='20:00',duration_minutes=30)
        clock.set(10);state=read(c)
        assert task(state,'a1')['date']=='2030-01-09' and task(state,'a1')['status']=='completed'
        assert task(state,'a3')['date']=='2030-01-09' and task(state,'a3')['action_needed']['reason']=='missed_pinned'
        mock=added(state)
        assert mock['date']=='2030-01-09' and mock['action_needed']['reason']=='missed_custom'
        assert not [e for e in state['planner']['active']['events'] if e['type']=='auto_move']
        assert set(state['planner']['active_view']['coach']['action_needed_task_ids'])=={task(state,'a3')['id'],mock['id']}
        state=post(c,'/tasks/move',state,task_id=mock['id'],date='2030-01-16',start_time='19:00')
        assert added(state)['action_needed'] is None

def test_undo_restores_the_placement_and_reconciliation_leaves_it_for_the_user():
    clock=Clock()
    with client(clock=clock) as c:
        accepted(c);clock.set(10);state=read(c)
        event=state['planner']['active_view']['coach']['recent_moves'][0]
        state=post(c,'/events/undo',state,event_id=event['id'])
        one=task(state,'a1')
        assert (one['date'],one['start_time'],one['auto_moves'])==('2030-01-09','19:00',0) and one['action_needed']['reason']=='undone'
        assert state['planner']['active_view']['coach']['recent_moves']==[]
        again=read(c)
        assert task(again,'a1')['date']=='2030-01-09' and again['version']==state['version']

def test_undo_explains_a_conflict_after_a_later_change_and_manual_placement_still_works():
    clock=Clock()
    with client(clock=clock) as c:
        accepted(c);clock.set(10);state=read(c)
        event=state['planner']['active_view']['coach']['recent_moves'][0];one=task(state,'a1')
        state=post(c,'/tasks/move',state,task_id=one['id'],date='2030-01-16',start_time='19:00')
        assert rejected(c,'/events/undo',state,event_id=event['id'])==(409,'undo_conflict')
        assert task(state,'a1')['date']=='2030-01-16'

def test_undo_of_a_move_to_backlog_also_restores_it():
    plan=draft(assignments=[assignment('a1'),second_week('a2',depends_on=['a1'])])
    clock=Clock()
    with client(Staged([plan]),clock=clock) as c:
        accepted(c);clock.set(10);state=read(c)
        event=state['planner']['active_view']['coach']['recent_moves'][0]
        assert event['type']=='auto_backlog'
        state=post(c,'/events/undo',state,event_id=event['id'])
        assert task(state,'a1')['status']=='scheduled' and task(state,'a1')['action_needed']['reason']=='undone'

def test_a_replayed_task_action_applies_once():
    with client() as c:
        state=accepted(c);one=task(state,'a1')
        body={'expected_version':state['version'],'mutation_id':str(uuid4()),'task_id':one['id']}
        first=c.post('/api/v1/roadmaps/planner/tasks/skip',headers=H,json=body).json()
        second=c.post('/api/v1/roadmaps/planner/tasks/skip',headers=H,json=body).json()
        assert first['version']==second['version'] and len([e for e in second['planner']['active']['events'] if e['type']=='skip'])==1

def test_stale_versions_and_other_owners_cannot_change_tasks():
    sources=Sources()
    with client(sources=sources) as c:
        state=accepted(c);one=task(state,'a1')
        fresh=post(c,'/tasks/update',state,task_id=one['id'],pinned=True)
        assert rejected(c,'/tasks/skip',state,task_id=one['id'])[0]==409
        sources.owner='22222222-2222-4222-8222-222222222222'
        assert rejected(c,'/tasks/skip',{'version':0},task_id=one['id'])[0]==409
        sources.owner=OWNER
        assert task(read(c),'a1')['status']=='scheduled' and fresh['version']==read(c)['version']
