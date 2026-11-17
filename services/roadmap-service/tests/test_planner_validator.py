"""Outline checks: milestones, gaps and weekly objectives. Tasks are checked when a week is planned."""
from datetime import date
from planner_fixtures import NOW, assessment, draft, gap, milestone, settings
from app.planning.capacity import Capacity
from app.planning.outlines import validate_outline
from app.schemas.roadmap import OutlineDraft, PlannerConfig

def outline(**changes):
    value=draft(**changes);value.pop('assignments')
    return value
def codes(output,*,config=None,completed=(),confirmations=None,instruction=None,source=None,require_weeks=False):
    capacity=Capacity(PlannerConfig.model_validate(config or settings()),NOW,completed)
    errors=validate_outline(OutlineDraft.model_validate(output),capacity,source or assessment(),confirmations or {},completed,instruction,require_weeks=require_weeks)
    return {e['code'] for e in errors}
def objective(week='2030-01-07',**changes):
    return {'week_start':week,'objective':'Write and test one endpoint.','expected_outcome':'A passing endpoint test.','estimated_minutes':60,'milestone_key':'m1','gap_ids':['python'],**changes}

def test_a_fitting_outline_passes():
    assert codes(outline())==set()
    assert codes(outline(weeks=[objective(),objective('2030-01-14',estimated_minutes=180),objective('2030-01-21',estimated_minutes=0)]),require_weeks=True)==set()

def test_every_week_through_the_deadline_needs_an_objective_even_after_scope_ends():
    assert codes(outline(),require_weeks=True)=={'week_missing'}
    assert codes(outline(weeks=[objective()]),require_weeks=True)=={'week_missing'}
    both=[objective(),objective('2030-01-14')]
    # The full journey includes a zero-effort contingency week after the milestone.
    assert codes(outline(weeks=both),require_weeks=True)=={'week_missing'}
    assert codes(outline(weeks=[*both,objective('2030-01-21',estimated_minutes=0)]),require_weeks=True)==set()
    assert 'week_repeated' in codes(outline(weeks=[*both,objective()]))
    assert 'week_unknown' in codes(outline(weeks=[*both,objective('2030-01-08')]))
    assert 'week_unknown' in codes(outline(weeks=[*both,objective('2030-02-04')]))
    assert 'week_outside_milestone' in codes(outline(weeks=[*both,objective('2030-01-21')]))
    assert 'unknown_milestone' in codes(outline(weeks=[objective(milestone_key='nope'),both[1]]))
    assert 'unknown_gap' in codes(outline(weeks=[objective(gap_ids=['nope']),both[1]]))
    assert 'week_effort_exceeds_hours' in codes(outline(weeks=[objective(estimated_minutes=301),both[1]],milestones=[milestone(estimated_minutes=600,projected_end='2030-01-27')]))
    assert 'week_effort_exceeds_milestone' in codes(outline(weeks=[objective(),objective('2030-01-14',estimated_minutes=200)]))

def test_milestone_structure_errors():
    assert 'milestone_after_target' in codes(outline(milestones=[milestone(projected_end='2030-02-01')]))
    assert 'milestone_window_invalid' in codes(outline(milestones=[milestone(projected_start='2030-01-15',projected_end='2030-01-14')]))
    assert 'milestone_before_start' in codes(outline(milestones=[milestone(projected_start='2030-01-02')]))
    assert 'duplicate_milestone' in codes(outline(milestones=[milestone(),milestone()]))
    assert 'unknown_prerequisite' in codes(outline(milestones=[milestone(prerequisite_keys=['nope'])]))
    cycle=[milestone('m1',prerequisite_keys=['m2']),milestone('m2',prerequisite_keys=['m1'])]
    assert 'prerequisite_cycle' in codes(outline(milestones=cycle))
    order=[milestone('m1',projected_end='2030-01-27'),milestone('m2',prerequisite_keys=['m1'],projected_end='2030-01-20')]
    assert 'prerequisite_order' in codes(outline(milestones=order))

def test_milestone_effort_must_fit_capacity_through_its_window_alone_and_together():
    # Wednesday's 90 minutes are all that exist before Monday the 14th.
    assert 'milestone_capacity_exceeded' in codes(outline(milestones=[milestone(projected_end='2030-01-13',estimated_minutes=91)]))
    assert 'milestone_capacity_exceeded' not in codes(outline(milestones=[milestone(projected_end='2030-01-13',estimated_minutes=90)]))
    # Each fits its own window, but both share the same 690 minutes.
    shared=[milestone('m1',estimated_minutes=400,projected_end='2030-01-27'),milestone('m2',estimated_minutes=400,projected_start='2030-01-09',projected_end='2030-01-27')]
    assert 'milestone_capacity_exceeded' in codes(outline(milestones=shared))
    # Breaks are part of capacity: 60 + 10 break leaves 20 minutes, too short for a session.
    assert 'milestone_capacity_exceeded' in codes(outline(milestones=[milestone(projected_end='2030-01-13',estimated_minutes=90)]),config=settings(break_minutes_per_hour=10))

def test_gap_labels_follow_the_assessment():
    assert 'unknown_labelled_confirmed' in codes(outline(gaps=[gap(),gap('sql',name='SQL',requirement_ref='job:sql',status='confirmed_gap',plan_impact='minor')]))
    assert 'shortfall_labelled_unknown' in codes(outline(gaps=[gap(status='unknown',plan_impact='minor')]))
    assert 'supported_as_gap' in codes(outline(gaps=[gap(),gap('git',name='Git',requirement_ref='job:git',status='unknown',plan_impact='minor')]))
    assert 'constraint_as_gap' in codes(outline(gaps=[gap(),gap('visa',name='Visa',requirement_ref='condition:visa',status='unknown',plan_impact='minor')]))
    assert 'unknown_requirement' in codes(outline(gaps=[gap(),gap('x',requirement_ref='job:missing',status='unknown',plan_impact='minor')]))

def test_inferred_requirements_are_labelled_and_stay_unknown():
    inferred=dict(name='Docker',requirement_ref=None,source='inferred',status='unknown',plan_impact='minor',inference_reason='Common for this role.')
    assert codes(outline(gaps=[gap(),gap('docker',**inferred)]))==set()
    assert 'inference_unexplained' in codes(outline(gaps=[gap(),gap('docker',**{**inferred,'inference_reason':None})]))
    assert 'unknown_labelled_confirmed' in codes(outline(gaps=[gap(),gap('docker',**{**inferred,'status':'confirmed_gap'})]))
    assert 'requirement_label_mismatch' in codes(outline(gaps=[gap(),gap('docker',**{**inferred,'requirement_ref':'job:python'})]))

def test_material_unknown_needs_a_diagnostic_intent_or_a_confirmation_question():
    unknown=dict(name='SQL',requirement_ref='job:sql',status='unknown',plan_impact='material')
    assert 'unresolved_material_unknown' in codes(outline(gaps=[gap(),gap('sql',**unknown)]))
    assert 'unresolved_material_unknown' in codes(outline(gaps=[gap(),gap('sql',**unknown,resolution='confirm_experience')]))
    asked=gap('sql',**unknown,resolution='confirm_experience',confirmation_question='Have you written SQL joins for a project?')
    assert codes(outline(gaps=[gap(),asked]))==set()
    # The diagnostic task itself is required when the first week is planned.
    assert codes(outline(gaps=[gap(),gap('sql',**unknown,resolution='diagnostic')]))==set()
    assert codes(outline(gaps=[gap(),gap('sql',**unknown)]),confirmations={'sql':{'answer':'not_sure'}})==set()

def test_priorities_must_be_placed_or_explicitly_excluded():
    assert 'priority_not_covered' in codes(outline(milestones=[milestone(gap_ids=[])]))
    assert 'priority_not_covered' in codes(outline(gaps=[]))
    excluded=outline(gaps=[],milestones=[milestone(gap_ids=[])],exclusions=[{'requirement_ref':'job:python','reason':'User choice.','quote':'Skip Python for now.'}])
    assert 'exclusion_without_quote' in codes(excluded)
    assert codes(excluded,instruction='Please skip it. Skip Python for now.')==set()

def test_deadline_outcome_must_match_work_beyond_the_deadline():
    later={'title':'Advanced Python','gap_ids':['python'],'reason':'Exceeds the runway.','estimated_minutes':600}
    assert 'deadline_outcome_inconsistent' in codes(outline(beyond_deadline=[later]))
    assert 'deadline_outcome_inconsistent' in codes(outline(deadline_outcome={'summary':'Not everything fits.','achievable_by_target':[],'fits_in_runway':False}))

def test_a_milestone_with_completed_sessions_must_stay():
    session={'id':'done','milestone_key':'earlier','date':'2030-01-09','start_time':'19:00','duration_minutes':60,'status':'completed'}
    assert 'completed_milestone_dropped' in codes(outline(),completed=[session])
    assert date(2030,1,9)
