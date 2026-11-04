import pytest
from datetime import date
from planner_fixtures import NOW, assessment, assignment, draft, gap, milestone, settings
from app.planning.capacity import Capacity
from app.planning.validator import validate_plan
from app.schemas.roadmap import PlanDraft, PlannerConfig

WEEK=date(2030,1,7)
def codes(output,*,config=None,completed=(),retained=(),confirmations=None,instruction=None,source=None,week=WEEK):
    capacity=Capacity(PlannerConfig.model_validate(config or settings()),NOW,completed)
    errors=validate_plan(PlanDraft.model_validate(output),capacity,source or assessment(),week,completed=completed,retained_milestones=retained,confirmations=confirmations,instruction=instruction)
    return {e['code'] for e in errors}

def test_a_fitting_plan_passes():
    assert codes(draft())==set()

@pytest.mark.parametrize('change,code',[
    ({'date':'2030-01-12','start_time':'10:00'},'assignment_on_blackout'),
    ({'date':'2030-01-14'},'assignment_outside_first_week'),
    ({'start_time':'18:00'},'assignment_outside_block'),
    ({'duration_minutes':120},'assignment_outside_block'),
    ({'date':'2030-01-13','start_time':'09:00'},'backup_not_enabled'),
    ({'milestone_key':'missing'},'unknown_milestone'),
])
def test_assignment_placement_errors(change,code):
    assert code in codes(draft(assignments=[assignment(**change)]))

@pytest.mark.parametrize('rule,code',[
    ({'frequency':'weekly','start_date':'2030-01-07','weekdays':[2]},'assignment_on_blackout'),
    ({'frequency':'once','start_date':'2030-01-09','start_time':'19:30','end_time':'20:00'},'assignment_on_blackout'),
    ({'frequency':'once','start_date':'2030-01-09','start_time':'20:00','end_time':'20:30'},None),
    ({'frequency':'weekly','start_date':'2030-01-07','weekdays':[3]},None),
])
def test_assignments_cannot_overlap_a_recurring_or_timed_blackout(rule,code):
    found=codes(draft(),config=settings(blackouts=[rule]))
    assert (code in found) if code else 'assignment_on_blackout' not in found

def test_assignment_already_passed_is_rejected():
    config=settings(start_date='2030-01-09',target_date='2030-01-27')
    capacity_now=NOW.replace(hour=12)  # 20:00 Wednesday in Singapore.
    capacity=Capacity(PlannerConfig.model_validate(config),capacity_now)
    errors=validate_plan(PlanDraft.model_validate(draft()),capacity,assessment(),WEEK)
    assert 'assignment_in_past' in {e['code'] for e in errors}

def test_assignment_after_target_is_rejected():
    config=settings(target_date='2030-01-10')
    output=draft(assignments=[assignment(date='2030-01-11')],milestones=[milestone(projected_end='2030-01-10',estimated_minutes=60)])
    assert 'assignment_after_target' in codes(output,config=config)

def test_overlap_and_weekly_budget():
    config=settings(blocks=[{'day':2,'start_time':'18:00','duration_minutes':180,'kind':'preferred'}],weekly_minutes=100)
    output=draft(assignments=[assignment('a1',start_time='18:00'),assignment('a2',start_time='18:30')])
    found=codes(output,config=config)
    assert {'assignment_overlap','weekly_budget_exceeded'}<=found

def test_backup_needs_exhausted_preferred_time():
    config=settings(use_backup=True)
    assert 'backup_before_preferred' in codes(draft(assignments=[assignment(date='2030-01-13',start_time='09:00')]),config=config)
    filled=[assignment('a1',duration_minutes=90),assignment('a2',date='2030-01-13',start_time='09:00')]
    assert codes(draft(assignments=filled),config=config)==set()

def test_milestone_structure_errors():
    assert 'milestone_after_target' in codes(draft(milestones=[milestone(projected_end='2030-02-01')]))
    assert 'milestone_window_invalid' in codes(draft(milestones=[milestone(projected_start='2030-01-15',projected_end='2030-01-14')]))
    assert 'milestone_before_start' in codes(draft(milestones=[milestone(projected_start='2030-01-02')]))
    assert 'duplicate_milestone' in codes(draft(milestones=[milestone(),milestone()]))
    assert 'unknown_prerequisite' in codes(draft(milestones=[milestone(prerequisite_keys=['nope'])]))
    cycle=[milestone('m1',prerequisite_keys=['m2']),milestone('m2',prerequisite_keys=['m1'])]
    assert 'prerequisite_cycle' in codes(draft(milestones=cycle))
    order=[milestone('m1',projected_end='2030-01-27'),milestone('m2',prerequisite_keys=['m1'],projected_end='2030-01-20')]
    assert 'prerequisite_order' in codes(draft(milestones=order))
    assert 'assignment_effort_exceeds_milestone' in codes(draft(milestones=[milestone(estimated_minutes=30)]))

def test_milestone_effort_must_fit_capacity_through_its_window_alone_and_together():
    # Wednesday's 90 preferred minutes are all that exist before Monday the 14th.
    assert 'milestone_capacity_exceeded' in codes(draft(milestones=[milestone(projected_end='2030-01-13',estimated_minutes=91)]))
    assert 'milestone_capacity_exceeded' not in codes(draft(milestones=[milestone(projected_end='2030-01-13',estimated_minutes=90)]))
    # Each fits its own window, but both share the same 690 minutes.
    shared=[milestone('m1',estimated_minutes=400,projected_end='2030-01-27'),milestone('m2',estimated_minutes=400,projected_start='2030-01-09',projected_end='2030-01-27')]
    assert 'milestone_capacity_exceeded' in codes(draft(milestones=shared))

def test_gap_labels_follow_the_assessment():
    assert 'unknown_labelled_confirmed' in codes(draft(gaps=[gap(),gap('sql',name='SQL',requirement_ref='job:sql',status='confirmed_gap',plan_impact='minor')]))
    assert 'shortfall_labelled_unknown' in codes(draft(gaps=[gap(status='unknown',plan_impact='minor')]))
    assert 'supported_as_gap' in codes(draft(gaps=[gap(),gap('git',name='Git',requirement_ref='job:git',status='unknown',plan_impact='minor')]))
    assert 'constraint_as_gap' in codes(draft(gaps=[gap(),gap('visa',name='Visa',requirement_ref='condition:visa',status='unknown',plan_impact='minor')]))
    assert 'unknown_requirement' in codes(draft(gaps=[gap(),gap('x',requirement_ref='job:missing',status='unknown',plan_impact='minor')]))

def test_inferred_requirements_are_labelled_and_stay_unknown():
    inferred=dict(name='Docker',requirement_ref=None,source='inferred',status='unknown',plan_impact='minor',inference_reason='Common for this role.')
    assert codes(draft(gaps=[gap(),gap('docker',**inferred)]))==set()
    assert 'inference_unexplained' in codes(draft(gaps=[gap(),gap('docker',**{**inferred,'inference_reason':None})]))
    assert 'unknown_labelled_confirmed' in codes(draft(gaps=[gap(),gap('docker',**{**inferred,'status':'confirmed_gap'})]))
    assert 'requirement_label_mismatch' in codes(draft(gaps=[gap(),gap('docker',**{**inferred,'requirement_ref':'job:python'})]))

def test_material_unknown_needs_a_diagnostic_or_a_confirmation_question():
    unknown=dict(name='SQL',requirement_ref='job:sql',status='unknown',plan_impact='material')
    assert 'unresolved_material_unknown' in codes(draft(gaps=[gap(),gap('sql',**unknown)]))
    assert 'unresolved_material_unknown' in codes(draft(gaps=[gap(),gap('sql',**unknown,resolution='diagnostic')]))
    assert 'unresolved_material_unknown' in codes(draft(gaps=[gap(),gap('sql',**unknown,resolution='confirm_experience')]))
    asked=gap('sql',**unknown,resolution='confirm_experience',confirmation_question='Have you written SQL joins for a project?')
    assert codes(draft(gaps=[gap(),asked]))==set()
    test=assignment('d1',kind='diagnostic',gap_id='sql',duration_minutes=30,task='Write three SQL joins.',completion_criterion='The joins return the expected rows.')
    assert codes(draft(gaps=[gap(),gap('sql',**unknown,resolution='diagnostic')],assignments=[test]))==set()
    assert 'diagnostic_too_long' in codes(draft(gaps=[gap(),gap('sql',**unknown,resolution='diagnostic')],assignments=[{**test,'duration_minutes':45}]))
    assert codes(draft(gaps=[gap(),gap('sql',**unknown)]),confirmations={'sql':{'answer':'not_sure'}})==set()

def test_priorities_must_be_placed_or_explicitly_excluded():
    assert 'priority_not_covered' in codes(draft(milestones=[milestone(gap_ids=[])]))
    assert 'priority_not_covered' in codes(draft(gaps=[]))
    excluded=draft(gaps=[],milestones=[milestone(gap_ids=[])],exclusions=[{'requirement_ref':'job:python','reason':'User choice.','quote':'Skip Python for now.'}])
    assert 'exclusion_without_quote' in codes(excluded)
    assert codes(excluded,instruction='Please skip it. Skip Python for now.')==set()

def test_deadline_outcome_must_match_work_beyond_the_deadline():
    later={'title':'Advanced Python','gap_ids':['python'],'reason':'Exceeds the runway.','estimated_minutes':600}
    assert 'deadline_outcome_inconsistent' in codes(draft(beyond_deadline=[later]))
    assert 'deadline_outcome_inconsistent' in codes(draft(deadline_outcome={'summary':'Not everything fits.','achievable_by_target':[],'fits_in_runway':False}))

def test_completed_sessions_cannot_be_rewritten_dropped_or_overlapped():
    session={**assignment('done'),'status':'completed'}
    # The completed hour is no longer an eligible window, so a new session cannot use it.
    assert 'assignment_outside_block' in codes(draft(),completed=[session],retained=['m1'])
    assert 'completed_assignment_rewritten' in codes(draft(assignments=[assignment('done',start_time='20:00',duration_minutes=30)]),completed=[session],retained=['m1'])
    assert 'completed_milestone_dropped' in codes(draft(),completed=[session],retained=['earlier'])
    moved=draft(assignments=[assignment('next',start_time='20:00',duration_minutes=30)])
    assert codes(moved,completed=[session],retained=['m1'])==set()
    tight=settings(weekly_minutes=70)
    assert 'weekly_budget_exceeded' in codes(moved,config=tight,completed=[session],retained=['m1'])
