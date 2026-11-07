"""Learning progress reflects saved editable tasks without mutating the plan."""
import copy

from app.planning.state import learning_view
from app.planning.tasks import change_status, ensure_tasks, project_assignments
from planner_fixtures import NOW, assignment, draft, gap
from test_editable_tasks import definition, save
from test_planner_flow import H, Scripted, accepted, client_for, learning_plan, post


def current_plan():
    plan=learning_plan()
    plan.update(assessment_id='assessment-1',assessment_hash='hash-1')
    return plan


def test_learning_does_not_finish_while_linked_unscheduled_work_remains():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        session=state['planner']['active']['assignments'][0]
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        milestone=state['planner']['active']['milestones'][0]['key']
        state=save(client,'add',state,task=definition(title='Additional work',milestone_key=milestone,requirement_refs=['job:python']))
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
    plan=current_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    tasks=ensure_tasks(plan)
    tasks[0]['definition_review_required']=True
    assert learning_view(plan,NOW)['steps'][0]['state']=='in_progress'
    tasks[0]['removed']=True
    assert learning_view(plan,NOW)['steps'][0]['state']=='not_scheduled'


def test_split_task_is_counted_once_for_completion_and_sessions_still_count_separately():
    plan=current_plan()
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
    plan=current_plan()
    original=copy.deepcopy(plan)
    result=learning_view(plan,NOW)
    assert [step['state'] for step in result['steps']]==['in_progress','in_progress','not_scheduled']
    assert plan==original


def test_legacy_session_projection_translates_status_history_without_changing_tasks():
    plan=current_plan()
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
    plan=current_plan()
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


def test_relink_and_unlink_move_completed_split_sessions_to_the_current_requirement():
    plan=current_plan()
    plan['gaps']=[gap(),gap('sql',name='SQL',priority=2,requirement_ref='job:sql')]
    plan['milestones'][0]['gap_ids']=['python','sql']
    plan['assignments']=plan['assignments'][:1]
    plan['assignments'][0]['gap_id']='python'
    task=ensure_tasks(plan)[0]
    task['schedule'].append({'date':'2030-01-15','start_time':'18:00','duration_minutes':30})

    def by_gap():
        return {step['gap_id']:step for step in learning_view(plan,NOW)['steps']}

    initial=by_gap()
    assert (initial['python']['state'],initial['python']['sessions_completed'])==('done',2)
    assert (initial['sql']['state'],initial['sql']['sessions_total'])==('not_scheduled',0)

    # The immutable source assignment still points at Python; the user's edit
    # is authoritative for both task state and session-based progress.
    task['requirement_refs']=['job:sql']
    task['overrides']=['requirement_refs']
    before=copy.deepcopy(plan)
    relinked=by_gap()
    assert (relinked['python']['state'],relinked['python']['sessions_completed'],
            relinked['python']['completed_minutes'])==('not_scheduled',0,0)
    assert (relinked['sql']['state'],relinked['sql']['sessions_completed'],
            relinked['sql']['completed_minutes'])==('done',2,90)
    assert plan==before

    task['requirement_refs']=[]
    unlinked=by_gap()
    assert all((step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)
               for step in unlinked.values())


def test_inferred_gap_without_requirement_retains_legacy_link_until_explicit_unlink():
    plan=current_plan()
    plan['gaps']=[gap('inferred',name='Inferred',requirement_ref=None,source='inferred',inference_reason='Synthetic')]
    plan['milestones'][0]['gap_ids']=['inferred']
    plan['assignments']=plan['assignments'][:1]
    plan['assignments'][0]['gap_id']='inferred'
    # A legacy saved plan has no canonical tasks and must retain its progress.
    assert learning_view(plan,NOW)['steps'][0]['state']=='done'
    task=ensure_tasks(plan)[0]
    assert learning_view(plan,NOW)['steps'][0]['state']=='done'
    task['overrides']=['requirement_refs']
    task['requirement_refs']=[]
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)


def test_saved_unlink_updates_learning_status_and_session_counts_through_api():
    model=Scripted([draft(assignments=[assignment('a1',gap_id='python')])])
    with client_for(model) as client:
        state=accepted(client)
        task=state['planner']['active']['editable_tasks'][0]
        assert task['source_assignment']['gap_id']=='python'
        state=save(client,'status',state,task_id=task['id'],status='completed')
        assert client.get('/api/v1/roadmaps/learning',headers=H).json()['steps'][0]['state']=='done'
        state=save(client,'edit',state,task_id=task['id'],changes={'requirement_refs':[]})
        assert 'requirement_refs' in state['planner']['active']['editable_tasks'][0]['overrides']
        result=client.get('/api/v1/roadmaps/learning',headers=H)
        assert result.status_code==200
        step=result.json()['steps'][0]
        assert (step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)


def test_new_user_task_explicit_requirement_takes_precedence_over_milestone():
    plan=current_plan()
    plan['gaps']=[gap(),gap('sql',name='SQL',priority=2,requirement_ref='job:sql')]
    plan['milestones'][0]['gap_ids']=['python']
    plan['assignments']=plan['assignments'][:1]
    task=ensure_tasks(plan)[0]
    task.update(origin='user',source_assignment=None,requirement_refs=['job:sql'],overrides=[])
    task['schedule'].append({'date':'2030-01-15','start_time':'18:00','duration_minutes':30})
    before=copy.deepcopy(plan)
    result={step['gap_id']:step for step in learning_view(plan,NOW)['steps']}
    assert (result['python']['state'],result['python']['sessions_total'],
            result['python']['completed_minutes'])==('not_scheduled',0,0)
    assert (result['sql']['state'],result['sql']['sessions_completed'],
            result['sql']['completed_minutes'])==('done',2,90)
    assert plan==before


def test_user_task_without_requirement_does_not_claim_an_inferred_milestone():
    plan=current_plan()
    plan['gaps']=[gap('inferred',name='Inferred',requirement_ref=None,source='inferred',inference_reason='Synthetic')]
    plan['milestones'][0]['gap_ids']=['inferred']
    plan['assignments']=plan['assignments'][:1]
    task=ensure_tasks(plan)[0]
    task.update(origin='user',source_assignment=None,requirement_refs=[],overrides=[])
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_completed'],step['completed_minutes'])==('not_scheduled',0,0)


def test_legacy_generated_task_without_requirement_keeps_single_inferred_milestone():
    plan=learning_plan()
    plan['gaps']=[gap('inferred',name='Inferred',requirement_ref=None,source='inferred',inference_reason='Synthetic')]
    plan['milestones'][0]['gap_ids']=['inferred']
    plan['assignments']=plan['assignments'][:1]
    task=ensure_tasks(plan)[0]
    assert task['origin']=='generated' and task['requirement_refs']==[] and task['overrides']==[]
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_completed'],step['completed_minutes'])==('done',1,60)


def test_missing_or_stale_requirement_provenance_is_not_current_learning():
    plan=current_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    plan['assignments'][0]['gap_id']='python'
    task=ensure_tasks(plan)[0]
    assert learning_view(plan,NOW)['steps'][0]['state']=='done'
    for field in ('requirement_source_hash','requirement_source_id'):
        changed=copy.deepcopy(plan)
        changed['editable_tasks'][0][field]=None
        step=learning_view(changed,NOW)['steps'][0]
        assert (step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)
    for field in ('assessment_id','assessment_hash'):
        changed=copy.deepcopy(plan)
        changed[field]='different'
        step=learning_view(changed,NOW)['steps'][0]
        assert (step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)
    # A stale inferred source gap is not fallback evidence either.
    task['requirement_refs']=[]
    task['requirement_source_hash']='stale'
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_total'])==('not_scheduled',0)


def test_removed_requirement_only_task_does_not_block_remaining_or_finish_last_task():
    plan=current_plan()
    plan['gaps']=plan['gaps'][1:2]
    plan['assignments']=plan['assignments'][:1]
    task=ensure_tasks(plan)[0]
    removed=copy.deepcopy(task)
    removed.update(id='removed-personal',origin='user',source_assignment=None,
                   milestone_key=None,requirement_refs=['job:python'],removed=True,
                   removal={'at':'2030-01-10T00:00:00Z','reason':'Not needed'})
    plan['editable_tasks'].append(removed)
    original=copy.deepcopy(plan)
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_completed'])==('done',1)
    assert plan==original
    task['removed']=True
    step=learning_view(plan,NOW)['steps'][0]
    assert (step['state'],step['sessions_total'],step['completed_minutes'])==('not_scheduled',0,0)


def test_ambiguous_milestone_only_legacy_task_has_no_inferred_skill():
    plan=current_plan()
    plan['gaps']=[gap(),gap('sql',name='SQL',priority=2,requirement_ref='job:sql')]
    plan['milestones'][0]['gap_ids']=['python','sql']
    plan['assignments']=plan['assignments'][:1]
    assert plan['assignments'][0]['gap_id'] is None
    # A historical session-only snapshot keeps the original read behavior.
    legacy=learning_view(plan,NOW)
    assert [(step['state'],step['sessions_completed']) for step in legacy['steps']]==[('done',1),('done',1)]
    task=ensure_tasks(plan)[0]
    assert task['origin']=='generated' and not task['requirement_refs'] and not task['overrides']
    assert (task['source_assignment'] or {}).get('gap_id') is None
    before=copy.deepcopy(plan)
    projected=project_assignments(copy.deepcopy(plan))
    assert (projected[0]['gap_id'],projected[0]['skill_gap_ids'])==(None,[])
    current=learning_view(plan,NOW)
    assert [(step['state'],step['sessions_total'],step['completed_minutes']) for step in current['steps']]==[
        ('not_scheduled',0,0),('not_scheduled',0,0)]
    assert plan==before
