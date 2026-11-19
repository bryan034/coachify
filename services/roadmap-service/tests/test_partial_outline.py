"""Two model attempts, then backend recovery of invalid requirement-reference rows."""
from planner_fixtures import draft, gap, milestone
from test_planner_flow import Scripted, client_for, configure, generate, accept_outline, read
from app.planning.partial_outline import recover_outline
from app.schemas.outlines import OutlineDraft


def mixed_outline():
    return draft(gaps=[gap(),gap('invalid',name='Preferred infrastructure',requirement_ref='job:unknown')],
        milestones=[milestone(),milestone('bad',title='Unsupported infrastructure',gap_ids=['invalid'],estimated_minutes=60,projected_start='2030-01-21',projected_end='2030-01-27')])


def test_two_attempts_then_partial_preview_without_a_third_outline_model_call():
    bad=mixed_outline();model=Scripted([bad,bad])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        outline=state['planner']['outline_candidate']
        assert len(model.sent('OutlineDraft'))==2 and outline['generation']['attempts']==2
        assert model.sent('OutlineDraft')[1]['validation_errors'][0]['code']=='unknown_requirement'
        assert [g['id'] for g in outline['gaps']]==['python']
        assert [m['key'] for m in outline['milestones']]==['m1']
        assert [w['week_start'] for w in outline['weeks']]==['2030-01-07','2030-01-14']
        assert {item['kind'] for item in outline['partial_review']['omitted_items']}=={'gap','milestone','week'}
        assert state['planner']['active'] is None
        state=accept_outline(client,state)
        assert state['planner']['active'] is not None
        assert state['planner']['outline_active']['partial_review']==outline['partial_review']
        assert state['planner']['week_candidate'] is None
        assert read(client)['planner']['outline_active']['partial_review'] is not None


def test_a_successful_second_attempt_needs_no_partial_recovery():
    model=Scripted([mixed_outline(),draft()])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded'
        assert state['planner']['outline_candidate']['partial_review'] is None
        assert len(model.sent('OutlineDraft'))==2


def test_other_validation_errors_remain_blocking_after_invalid_rows_are_removed():
    bad=mixed_outline();bad['milestones'][0]['estimated_minutes']=60000
    model=Scripted([bad,bad])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='failed' and state['operation']['error']['code']=='outline_validation'
        assert len(model.sent('OutlineDraft'))==2
        assert state['planner']['outline_candidate'] is None and state['planner']['active'] is None


def test_no_invalid_reference_rows_means_no_partial_validation_bypass():
    bad=draft(milestones=[milestone(estimated_minutes=60000)])
    model=Scripted([bad,bad])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='failed' and len(model.sent('OutlineDraft'))==2
        assert state['planner']['outline_candidate'] is None


def test_recovery_cleans_shared_gap_links_and_dependent_rows_without_mutating_input():
    from planner_fixtures import assessment
    value=mixed_outline();value.pop('assignments')
    value['milestones'][0]['gap_ids']=['python','invalid']
    value['milestones'].append(milestone('dependent',gap_ids=['python'],prerequisite_keys=['bad']))
    value['weeks']=[{'week_start':'2030-01-07','objective':'Build endpoints','expected_outcome':'Test passes','estimated_minutes':60,'milestone_key':'m1','gap_ids':['python','invalid']}]
    value['routine_rules']=[{'id':'r1','milestone_key':'bad','activity':'Build infrastructure','weekdays':[0],'duration_minutes':30,'start_date':'2030-01-21','end_date':'2030-01-21'}]
    original=OutlineDraft.model_validate(value);before=original.model_dump()
    recovered,review=recover_outline(original,assessment())
    assert original.model_dump()==before
    assert [m.key for m in recovered.milestones]==['m1'] and recovered.milestones[0].gap_ids==['python']
    assert recovered.weeks[0].gap_ids==['python'] and recovered.routine_rules==[]
    assert {'bad','dependent'}<={item['id'] for item in review['omitted_items']}


def test_fallback_refuses_an_empty_plan_or_removal_of_saved_work():
    from planner_fixtures import assessment
    value=mixed_outline();value.pop('assignments')
    value['weeks']=[{'week_start':'2030-01-07','objective':'Build endpoints','expected_outcome':'Test passes','estimated_minutes':60,'milestone_key':'m1','gap_ids':['python']}]
    original=OutlineDraft.model_validate(value)
    assert recover_outline(original,assessment(),{'editable_tasks':[{'milestone_key':'bad'}]})==(None,None)
    value['gaps']=[value['gaps'][1]];value['milestones']=[value['milestones'][1]];value['weeks'][0]['milestone_key']='bad'
    assert recover_outline(OutlineDraft.model_validate(value),assessment())==(None,None)


def test_uncovered_priorities_are_reported_instead_of_silently_claiming_full_coverage():
    from planner_fixtures import assessment
    value=mixed_outline();value.pop('assignments')
    value['milestones'][0]['prerequisite_keys']=['bad']
    value['milestones'].append(milestone('retained',gap_ids=[],prerequisite_keys=[]))
    value['weeks']=[{'week_start':'2030-01-07','objective':'Retained work','expected_outcome':'A review','estimated_minutes':60,'milestone_key':'retained','gap_ids':[]}]
    recovered,review=recover_outline(OutlineDraft.model_validate(value),assessment())
    assert review['uncovered_requirements']==['job:python']
    assert 'complete coverage' in recovered.deadline_outcome.summary


def test_partially_recovered_coverage_still_passes_full_validation():
    from planner_fixtures import assessment, settings, NOW
    from app.planning.capacity import Capacity
    from app.planning.outlines import validate_outline
    from app.schemas.roadmap import PlannerConfig
    value=mixed_outline();value.pop('assignments')
    value['milestones'][0]['prerequisite_keys']=['bad']
    value['milestones'].append(milestone('retained',gap_ids=[],prerequisite_keys=[],estimated_minutes=60))
    value['weeks']=[{'week_start':s,'objective':'Retained practice','expected_outcome':'Working example','estimated_minutes':m,'milestone_key':'retained','gap_ids':[]} for s,m in [('2030-01-07',60),('2030-01-14',0),('2030-01-21',0)]]
    recovered,review=recover_outline(OutlineDraft.model_validate(value),assessment())
    assert review['uncovered_requirements']==['job:python']
    assert recovered.gaps==[]
    errors=validate_outline(recovered,Capacity(PlannerConfig.model_validate(settings()),NOW),assessment(),{},require_weeks=True,partial_review=review)
    assert errors==[]


def test_recovery_does_not_waive_unrelated_deadline_validation():
    bad=mixed_outline();bad['deadline_outcome']['fits_in_runway']=False
    model=Scripted([bad,bad])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='failed'
        assert 'fits_in_runway' in state['operation']['error']['detail']
        assert state['planner']['outline_candidate'] is None
