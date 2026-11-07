"""A legacy session exposes only an unambiguous current task-to-gap link."""
import copy

from app.planning.tasks import ensure_tasks, project_assignments
from planner_fixtures import gap
from test_planner_flow import learning_plan


def plan_and_task():
    plan=learning_plan()
    plan.update(assessment_id='assessment-1',assessment_hash='hash-1')
    plan['gaps']=[gap(),gap('sql',name='SQL',priority=2,requirement_ref='job:sql')]
    plan['milestones'][0]['gap_ids']=['python']
    plan['assignments']=plan['assignments'][:1]
    plan['assignments'][0]['gap_id']='python'
    task=ensure_tasks(plan)[0]
    task['schedule'].append({'date':'2030-01-15','start_time':'18:00','duration_minutes':30})
    return plan,task


def assert_projection(plan,task,gap_id,skill_gap_ids):
    before=copy.deepcopy(task)
    sessions=project_assignments(plan)
    assert len(sessions)==2
    assert all((s['gap_id'],s['skill_gap_ids'])==(gap_id,skill_gap_ids) for s in sessions)
    assert task==before


def test_relink_unlink_and_multiple_links_never_reuse_original_skill():
    plan,task=plan_and_task()
    assert_projection(plan,task,'python',['python'])
    task.update(requirement_refs=['job:sql'],overrides=['requirement_refs'])
    assert_projection(plan,task,'sql',['sql'])
    task['requirement_refs']=[]
    assert_projection(plan,task,None,[])
    task['requirement_refs']=['job:python','job:sql']
    assert_projection(plan,task,None,[])


def test_new_task_explicit_links_are_respected_before_any_edit():
    plan,task=plan_and_task()
    task.update(origin='user',source_assignment=None,overrides=[],requirement_refs=['job:sql'])
    assert_projection(plan,task,'sql',['sql'])
    task['requirement_refs']=[]
    assert_projection(plan,task,None,[])


def test_legacy_inferred_gap_and_single_milestone_fallback_remain_available():
    plan,task=plan_and_task()
    plan['gaps'][0].update(requirement_ref=None,source='inferred')
    task['requirement_refs']=[]
    assert_projection(plan,task,'python',['python'])
    task['source_assignment']['gap_id']=None
    assert_projection(plan,task,None,['python'])
    plan['milestones'][0]['gap_ids']=['python','sql']
    assert_projection(plan,task,None,[])


def test_unknown_ambiguous_or_stale_requirement_cannot_claim_a_skill():
    plan,task=plan_and_task()
    task.update(origin='user',source_assignment=None,requirement_refs=['missing'])
    assert_projection(plan,task,None,[])
    task['requirement_refs']=['job:python']
    plan['gaps'][1]['requirement_ref']='job:python'
    assert_projection(plan,task,None,[])
    plan['gaps'][1]['requirement_ref']='job:sql'
    plan['assessment_hash']='new-hash'
    task['requirement_source_hash']='old-hash'
    assert_projection(plan,task,None,[])


def test_missing_or_changed_provenance_cannot_reassign_or_claim_a_skill():
    initial,task=plan_and_task()
    for missing in ('requirement_source_hash','requirement_source_id'):
        plan=copy.deepcopy(initial)
        plan['editable_tasks'][0][missing]=None
        assert_projection(plan,plan['editable_tasks'][0],None,[])
    for key in ('assessment_hash','assessment_id'):
        plan=copy.deepcopy(initial)
        plan[key]='changed'
        assert_projection(plan,plan['editable_tasks'][0],None,[])
    # An inherited inferred source gap is not diagnostic evidence after a
    # known provenance change, even though the old source is retained.
    plan=copy.deepcopy(initial)
    task=plan['editable_tasks'][0]
    task['requirement_refs']=[]
    task['requirement_source_hash']='old-hash'
    task['source_assignment']['kind']='diagnostic'
    assert task['source_assignment']['gap_id']=='python'
    assert_projection(plan,task,None,[])


def test_provenance_free_unlinked_legacy_inference_is_preserved():
    plan,task=plan_and_task()
    task['requirement_refs']=[]
    task['requirement_source_hash']=None
    task['requirement_source_id']=None
    assert_projection(plan,task,'python',['python'])
