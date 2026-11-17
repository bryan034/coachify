"""Stable, collision-safe compatibility keys for multi-session tasks."""
import copy
from uuid import NAMESPACE_URL, uuid5

from app.planning.state import completed_sessions
from app.planning.tasks import project_assignments
from planner_fixtures import OWNER, assignment, draft
from test_editable_tasks import save
from test_planner_flow import Scripted, accepted, client_for, generate


def task(ident, key, slots, *, status='not_started'):
    return {'id':ident,'generated_key':key,'milestone_key':'m1','schedule':slots,
            'instructions':'Complete synthetic work.','completion_outcome':'Synthetic work is complete.',
            'status':status,'removed':False,'history':[]}


def slot(start):
    return {'date':'2030-01-09','start_time':start,'duration_minutes':15}


def test_split_keys_do_not_collide_with_existing_keys_or_change_session_ids():
    task_id='task-a'
    generated_split='slot-'+str(uuid5(NAMESPACE_URL,f'roadmap:split:{task_id}:1:0'))
    plan={'milestones':[{'key':'m1'}], 'editable_tasks':[
        task(task_id,'a',[slot('19:00'),slot('19:15')]),
        task('task-b','a-1',[slot('19:30')]),
        task('task-c',generated_split,[slot('19:45')]),
    ]}
    projected=project_assignments(plan)
    assert len({a['key'] for a in projected})==4
    assert [a['key'] for a in projected[::2]]==['a','a-1']
    assert projected[3]['key']==generated_split
    assert projected[1]['key'] not in {'a','a-1',generated_split}
    assert projected[0]['id']==task_id
    assert projected[1]['id']==str(uuid5(NAMESPACE_URL,task_id+':slot:1'))
    assert project_assignments(plan)==projected
    reordered=copy.deepcopy(plan);reordered['editable_tasks'].reverse()
    assert {a['id']:a['key'] for a in project_assignments(reordered)}=={a['id']:a['key'] for a in projected}


def test_duplicate_primary_keys_are_resolved_deterministically():
    plan={'milestones':[{'key':'m1'}], 'editable_tasks':[
        task('task-b','same',[slot('19:30')]),task('task-a','same',[slot('19:00')]) ]}
    result=project_assignments(plan)
    assert len({a['key'] for a in result})==2
    assert next(a for a in result if a['id']=='task-a')['key']=='same'
    plan['editable_tasks'].reverse()
    assert {a['id']:a['key'] for a in project_assignments(plan)}=={a['id']:a['key'] for a in result}


def test_completed_projection_repairs_saved_collisions_in_memory_only():
    plan={'milestones':[{'key':'m1'}], 'editable_tasks':[
        task('task-a','a',[slot('19:00'),slot('19:15')],status='completed'),
        task('task-b','a-1',[slot('19:30')],status='completed')],
        'assignments':[{'id':'task-a','key':'a','status':'completed'},
                       {'id':'old-split','key':'a-1','status':'completed'},
                       {'id':'task-b','key':'a-1','status':'completed'}]}
    before=copy.deepcopy(plan)
    completed=completed_sessions(plan)
    assert len(completed)==3 and len({a['key'] for a in completed})==3
    assert plan==before
    legacy={'assignments':[{'id':'old','key':'old-key','status':'completed'}]}
    assert completed_sessions(legacy)==legacy['assignments']
