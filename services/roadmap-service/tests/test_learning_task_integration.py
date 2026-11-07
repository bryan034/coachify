"""Learning progress reflects saved editable tasks without mutating the plan."""
import copy

from app.planning.state import learning_view
from app.planning.tasks import change_status, ensure_tasks, project_assignments
from planner_fixtures import NOW, draft
from test_editable_tasks import definition, save
from test_planner_flow import H, Scripted, accepted, client_for, learning_plan, post


def test_learning_does_not_finish_while_linked_unscheduled_work_remains():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        session=state['planner']['active']['assignments'][0]
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        milestone=state['planner']['active']['milestones'][0]['key']
        state=save(client,'add',state,task=definition(title='Additional work',milestone_key=milestone))
        task=next(t for t in state['planner']['active']['editable_tasks'] if t['title']=='Additional work')
        result=client.get('/api/v1/roadmaps/learning',headers=H)
        assert result.status_code==200
        assert result.json()['skills_done']==0
        assert result.json()['steps'][0]['state']=='in_progress'
        state=save(client,'status',state,task_id=task['id'],status='completed')
        assert client.get('/api/v1/roadmaps/learning',headers=H).json()['steps'][0]['state']=='done'
        state=save(client,'remove',state,task_id=task['id'],reason='No longer needed')
        assert client.get('/api/v1/roadmaps/learning',headers=H).json()['steps'][0]['state']=='in_progress'


def test_removed_last_task_and_definition_review_do_not_count_as_done():
    plan=learning_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    tasks=ensure_tasks(plan)
    tasks[0]['definition_review_required']=True
    assert learning_view(plan,NOW)['steps'][0]['state']=='in_progress'
    tasks[0]['removed']=True
    assert learning_view(plan,NOW)['steps'][0]['state']=='not_scheduled'


def test_split_task_is_counted_once_for_completion_and_sessions_still_count_separately():
    plan=learning_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    task=ensure_tasks(plan)[0]
    task['schedule'].append({'date':'2030-01-15','start_time':'18:00','duration_minutes':30})
    original=copy.deepcopy(plan)
    result=learning_view(plan,NOW)
    assert result['steps'][0]['state']=='done'
    assert result['steps'][0]['sessions_total']==2
    assert result['steps'][0]['sessions_completed']==2
    assert plan==original  # The read does not rewrite the saved projection.
    task['status']='in_progress'
    result=learning_view(plan,NOW)
    assert result['steps'][0]['state']=='in_progress'
    assert result['steps'][0]['sessions_completed']==0


def test_legacy_session_only_plan_preserves_its_previous_progress():
    plan=learning_plan()
    original=copy.deepcopy(plan)
    result=learning_view(plan,NOW)
    assert [step['state'] for step in result['steps']]==['in_progress','in_progress','not_scheduled']
    assert plan==original


def test_legacy_session_projection_translates_status_history_without_changing_tasks():
    plan=learning_plan()
    task=ensure_tasks(plan)[1]
    change_status(task,'in_progress')
    change_status(task,'completed','Synthetic evidence')
    change_status(task,'not_started')
    before=copy.deepcopy(task['history'])
    session=next(item for item in project_assignments(plan) if item['id']==task['id'])
    assert [(e['from'],e['to']) for e in session['history']]==[
        ('scheduled','scheduled'),('scheduled','completed'),('completed','scheduled')]
    assert task['history']==before
    assert [(e['from'],e['to']) for e in task['history']]==[
        ('not_started','in_progress'),('in_progress','completed'),('completed','not_started')]


def test_unscheduled_requirement_link_blocks_done_without_a_milestone():
    plan=learning_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    tasks=ensure_tasks(plan)
    personal=copy.deepcopy(tasks[0])
    personal.update(id='personal-task',source_assignment=None,milestone_key=None,
                    requirement_refs=['job:python'],schedule=[],status='not_started')
    tasks.append(personal)
    assert learning_view(plan,NOW)['steps'][0]['state']=='in_progress'
    personal['status']='in_progress'
    assert learning_view(plan,NOW)['steps'][0]['state']=='in_progress'
    personal['status']='completed'
    assert learning_view(plan,NOW)['steps'][0]['state']=='done'
