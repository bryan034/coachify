"""Staged generation, rolling detail, progress, pace, check-ins, pause, plan edits and archival, through the API."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from planner_fixtures import NOW, OWNER, Staged, assessment, assignment, draft, gap, milestone, outline_rows, second_week, settings
from test_planner_flow import H, Sources, accepted, configure, finish, generate, post, read
from test_planner_tasks import Clock, added, client, custom, rejected, task
from app.main import create_app
from app.planning.metrics import Forecast, pace, progress, projection
from app.planning.validator import validate_outline
from app.planning.capacity import Capacity
from app.schemas.roadmap import PlanOutline, PlannerConfig

LONG_TARGET='2030-03-31'
def long_plan(**changes):
    return draft(milestones=[milestone(estimated_minutes=1500,projected_end=LONG_TARGET)],**changes)
def long_setup(clock,model=None,**changes):
    """A roadmap with weeks of outline left, so that rolling detail has work to give."""
    c=client(model or Staged([long_plan()]),clock=clock);c.__enter__()
    state=configure(c,target_date=LONG_TARGET,**changes)
    state=generate(c,state);assert state['operation']['status']=='succeeded',state['operation']
    return c,post(c,'/accept',state)
def detail_for(*tasks):
    return {'assignments':list(tasks)}
def wait(c):
    return finish(c)

def test_outline_covers_every_week_and_validation_catches_missing_or_excessive_rows():
    capacity=Capacity(PlannerConfig.model_validate(settings()),NOW)
    weeks=capacity.weeks();fields={k:v for k,v in draft().items() if k!='assignments'}
    good=PlanOutline.model_validate({**fields,'outline':outline_rows(weeks)})
    assert validate_outline(good,capacity,assessment())==[]
    missing=PlanOutline.model_validate({**fields,'outline':outline_rows(weeks)[:2]})
    assert 'outline_missing_week' in {e['code'] for e in validate_outline(missing,capacity,assessment())}
    over=outline_rows(weeks);over[1]['target_minutes']=241
    assert 'outline_over_budget' in {e['code'] for e in validate_outline(PlanOutline.model_validate({**fields,'outline':over}),capacity,assessment())}
    short=outline_rows(weeks);short[1]['target_minutes']=0;short[2]['target_minutes']=0
    assert 'outline_under_scope' in {e['code'] for e in validate_outline(PlanOutline.model_validate({**fields,'outline':short}),capacity,assessment())}

def test_a_failed_detail_stage_presents_no_candidate_and_keeps_the_saved_outline_out():
    bad=draft(assignments=[assignment(date='2030-01-12',start_time='10:00'),second_week()])
    with client(Staged([bad])) as c:
        state=generate(c,configure(c))
        assert state['operation']['status']=='failed' and state['planner']['candidate'] is None and state['planner']['retry_generate']

def test_a_candidate_with_an_empty_window_week_is_not_ready():
    empty=draft(assignments=[assignment()])
    with client(Staged([empty])) as c:
        state=generate(c,configure(c))
        assert state['operation']['status']=='failed' and 'week of 2030-01-14' in state['operation']['error']['detail'] and state['planner']['candidate'] is None

def test_year_long_outline_is_compact_and_within_limits():
    start=date(2030,1,9);target=date(2031,1,5)
    capacity=Capacity(PlannerConfig.model_validate(settings(target_date=target.isoformat())),NOW)
    weeks=capacity.weeks();assert len(weeks)==52
    plan=draft(milestones=[milestone(projected_end=target.isoformat())])
    with client(Staged([plan])) as c:
        state=generate(c,configure(c,target_date=target.isoformat()))
        assert state['operation']['status']=='succeeded',state['operation']
        assert len(state['planner']['candidate']['outline'])==52
        assert state['planner']['candidate_view']['weeks'][-1]['contains_target']

def test_inferred_gaps_and_material_unknowns_reach_the_detail_stage():
    unknown=gap('sql',name='SQL',requirement_ref='job:sql',status='unknown',resolution='diagnostic')
    test=assignment('d1',kind='diagnostic',gap_id='sql',start_time='20:00',duration_minutes=10,task='Write three joins.',completion_criterion='They return rows.')
    model=Staged([draft(gaps=[gap(),unknown],assignments=[assignment(),test,second_week()])])
    with client(model) as c:
        state=generate(c,configure(c))
        assert state['operation']['status']=='succeeded',state['operation']
        assert model.contexts[1]['diagnostics_needed']==['sql'] and state['planner']['candidate']['assignments'][1]['kind']=='diagnostic'

def test_target_outcome_remaining_work_and_projected_finish_stay_distinct():
    plan=draft(milestones=[milestone(estimated_minutes=500,projected_end='2030-01-27')],
        beyond_deadline=[{'key':'adv','title':'Advanced Python','gap_ids':['python'],'reason':'Needs more time.','estimated_minutes':600,'dependencies':['m1']}],
        deadline_outcome={'summary':'A basic API by the target.','achievable_by_target':['A basic API'],'fits_in_runway':False})
    with client(Staged([plan])) as c:
        state=generate(c,configure(c));assert state['operation']['status']=='succeeded',state['operation']
        view=state['planner']['candidate_view']['projection']
        assert view['target_date']=='2030-01-27' and view['fits_target'] and view['scheduled_finish']<='2030-01-27'
        assert view['deferred_minutes']==600 and view['projected_finish']>'2030-01-27' and 'unchanged' in view['assumption']
        state=post(c,'/accept',state)
        item=state['planner']['active']['deferred_scope'][0]
        assert (item['key'],item['dependencies'],item['estimated_minutes'])==('adv',['m1'],600)
        assert str(state['planner']['active']['config']['target_date'])=='2030-01-27'
        assert not [t for t in state['planner']['active']['assignments'] if t['milestone_key']=='adv']

def test_rolling_detail_fills_the_new_week_on_access_without_changing_existing_tasks():
    clock=Clock()
    next_week=assignment('w3',date='2030-01-21',start_time='19:00',task='Add a database layer.',completion_criterion='Rows persist.')
    model=Staged([long_plan()],details=[detail_for(next_week)])
    c,state=long_setup(clock,model)
    with c:
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a2')['id'],status='completed')
        kept={t['id']:t for t in state['planner']['active']['assignments']}
        clock.set(14)  # Monday: the window is now the weeks of the 14th and the 21st.
        state=wait(c)
        assert state['operation']['status']=='succeeded',state['operation']
        assert task(state,'w3')['date']=='2030-01-21' and task(state,'w3')['baseline']=='2030-01-21 19:00'
        assert model.contexts[-1]['stage']=='rolling_detail' and model.contexts[-1]['requested_weeks']==['2030-01-21']
        assert all(task(state,t['key'])==t for t in kept.values())
        calls=len(model.contexts);read(c);read(c)
        assert len(model.contexts)==calls

def test_returning_after_weeks_away_reconciles_missed_work_before_new_detail():
    clock=Clock()
    fresh=[assignment('w6',date='2030-02-18',start_time='19:00',task='New current work.',completion_criterion='It works.')]
    model=Staged([long_plan()],details=[detail_for(*fresh)])
    c,state=long_setup(clock,model)
    with c:
        clock.set(11,month=2)  # Monday 11 February, four weeks later.
        state=wait(c)
        assert state['operation']['status']=='succeeded',state['operation']
        moved=[task(state,'a1'),task(state,'a2')]
        assert all(t['auto_moves']==1 and t['date']>='2030-02-11' for t in moved)
        # The missed tasks land in the current week, so only next week needed new detail.
        assert model.contexts[-1]['requested_weeks']==['2030-02-18']
        sent={item['key'] for item in model.contexts[-1]['fixed_items']}
        assert {'a1','a2'}<=sent
        expected=state['planner']['active_view']['pace']['expected_minutes']
        # The four elapsed outline-only weeks still count as work that was due.
        assert expected>120 and state['planner']['active_view']['pace']['status']=='behind'

def test_rolling_detail_failure_keeps_the_plan_and_offers_retry_without_repeating_on_read():
    clock=Clock()
    next_week=assignment('w3',date='2030-01-21',start_time='19:00',task='Add a database layer.',completion_criterion='Rows persist.')
    model=Staged([long_plan()],details=[Problem('Provider down.',503,'model_provider'),detail_for(next_week)])
    c,state=long_setup(clock,model)
    with c:
        clock.set(14);state=wait(c)
        assert state['operation']['status']=='failed'
        view=state['planner']['active_view']['rolling']
        assert view['status']=='failed' and view['weeks']==['2030-01-21'] and view['error']=='Provider down.'
        calls=len(model.contexts);state=read(c)
        assert len(model.contexts)==calls
        response=c.post('/api/v1/roadmaps/planner/rolling',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'weeks':[]})
        assert response.status_code==202
        import time;time.sleep(.05);state=wait(c)
        assert task(state,'w3')['status']=='scheduled'

def test_progress_separates_generated_tasks_milestones_and_custom_hours():
    with client() as c:
        state=accepted(c);view=state['planner']['active_view']['progress']
        assert view['label']=='Roadmap progress'
        assert view['roadmap_minutes']=={'completed':0,'planned':240} and view['generated_tasks']=={'completed':0,'planned':2} and view['milestones']=={'completed':0,'planned':1}
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        view=state['planner']['active_view']['progress']
        assert view['roadmap_minutes']=={'completed':60,'planned':240} and view['generated_tasks']['completed']==1

def test_unlinked_custom_tasks_do_not_inflate_progress_and_linked_ones_count_when_completed():
    with client() as c:
        state=accepted(c)
        state=custom(c,state,title='Unlinked',date='2030-01-16',start_time='19:00')
        state=custom(c,state,title='Linked',date='2030-01-14',start_time='20:00',milestone_key='m1')
        view=state['planner']['active_view']['progress']
        assert view['custom_scheduled_minutes']==120 and view['roadmap_minutes']=={'completed':0,'planned':300}
        state=post(c,'/assignments/status',state,assignment_id=added(state,'Unlinked')['id'],status='completed')
        assert state['planner']['active_view']['progress']['roadmap_minutes']=={'completed':0,'planned':300}
        state=post(c,'/assignments/status',state,assignment_id=added(state,'Linked')['id'],status='completed')
        view=state['planner']['active_view']['progress']
        assert view['roadmap_minutes']=={'completed':60,'planned':300} and view['custom_linked_completed_minutes']==60

def test_completing_a_milestone_asks_about_unfinished_tasks_and_records_the_choice():
    sources=Sources()
    with client(sources=sources) as c:
        state=accepted(c)
        assert rejected(c,'/milestones/complete',state,milestone_id='m1')==(409,'milestone_choice_required')
        state=post(c,'/milestones/complete',state,milestone_id='m1',unfinished='keep')
        assert state['planner']['active']['milestones'][0]['completion']['unfinished_choice']=='keep' and task(state,'a1')['status']=='scheduled'
        view=state['planner']['active_view']['progress']
        assert view['milestones']['completed']==1 and view['remaining_minutes']==120
        state=post(c,'/milestones/complete',state,milestone_id='m1',completed=False)
        state=post(c,'/milestones/complete',state,milestone_id='m1',unfinished='remove')
        one=task(state,'a1')
        assert one['status']=='removed' and one['removed_reason']=='milestone_completed' and one['history'][-1]['action']=='removed_from_scope'
        view=state['planner']['active_view']['progress']
        assert view['remaining_minutes']==0 and view['generated_tasks']['planned']==0
        assert sources.writes==[]  # No write goes to the Skills Profile or any other service.

def test_a_milestone_with_nothing_left_completes_without_proof():
    with client() as c:
        state=accepted(c)
        for key in ('a1','a2'):state=post(c,'/assignments/status',state,assignment_id=task(state,key)['id'],status='completed')
        state=post(c,'/milestones/complete',state,milestone_id='m1')
        assert state['planner']['active']['milestones'][0]['completion']['unfinished_choice'] is None
        assert state['planner']['active']['milestones'][0]['outcome']['demonstrated'] is False

def test_pace_needs_elapsed_work_then_compares_and_excludes_removed_work():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        pace_view=state['planner']['active_view']['pace']
        assert pace_view['status']=='insufficient_data' and pace_view['recent']['status']=='insufficient_data'
        clock.set(10);state=read(c);pace_view=state['planner']['active_view']['pace']
        assert (pace_view['status'],pace_view['expected_minutes'],pace_view['behind_minutes'])==('behind',60,60)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        pace_view=state['planner']['active_view']['pace']
        assert (pace_view['status'],pace_view['completed_minutes'],pace_view['behind_minutes'])==('on_track',60,0)

def test_recent_pace_needs_two_finished_weeks_and_reports_zero_and_lateness():
    clock=Clock()
    next_week=assignment('w3',date='2030-01-21',start_time='19:00',task='Later work.',completion_criterion='Done.')
    model=Staged([long_plan()],details=[detail_for(next_week),detail_for(assignment('w4',date='2030-01-28',start_time='19:00',task='More.',completion_criterion='Done.')),detail_for(assignment('w5',date='2030-02-04',start_time='19:00',task='Further.',completion_criterion='Done.'))])
    c,state=long_setup(clock,model)
    with c:
        recent=state['planner']['active_view']['pace']['recent']
        assert recent['status']=='insufficient_data' and recent['weeks_used']==0
        clock.set(15);state=wait(c)
        recent=state['planner']['active_view']['pace']['recent']
        assert recent['status']=='insufficient_data' and recent['weeks_used']==1
        clock.set(22);state=wait(c)
        recent=state['planner']['active_view']['pace']['recent']
        # Two finished weeks with nothing completed: no finish estimate at the current pace.
        assert recent['status']=='no_estimate' and recent['weeks_used']==2 and recent['finish_date'] is None
        state=post(c,'/assignments/status',state,assignment_id=task(state,'w3')['id'],status='completed')
        assert state['planner']['active_view']['pace']['recent']['status']=='no_estimate'  # Completed this week, not in a finished one.
        clock.set(29);state=wait(c)
        recent=state['planner']['active_view']['pace']['recent']
        assert recent['status']=='available' and recent['weekly_minutes']==20 and recent['weeks_used']==3
        assert recent['finish_date']>LONG_TARGET and recent['weeks_late']>=1
        target=date.fromisoformat(LONG_TARGET);finish=date.fromisoformat(recent['finish_date'])
        assert recent['weeks_late']==-((target-finish).days//7)

def test_pace_forecast_is_capped_by_capacity_and_accounts_for_pauses():
    clock=Clock()
    c,state=long_setup(clock)
    with c:
        plan=state['planner']['active']
        fast=Forecast(plan,clock()).finish(1000,weekly_limit=100000)
        assert fast==Forecast(plan,clock()).finish(1000,weekly_limit=300)
        plan['week_states']={'2030-01-14':{'paused':True}}
        assert Forecast(plan,clock()).finish(1000,weekly_limit=300)>fast

def open_checkin(clock,**changes):
    """Friday 18:00 in Singapore, when the default check-in opens."""
    c,state=long_setup(clock,**changes)
    clock.moment=datetime(2030,1,11,10,0,tzinfo=timezone.utc)
    return c,read(c)
def propose(c,state,week='2030-01-07',**answers):
    state=post(c,'/checkins/answer',state,week_start=week,**{'week_feel':'as_expected','next_week':'same',**answers})
    response=c.post('/api/v1/roadmaps/planner/checkins/propose',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'week_start':week})
    assert response.status_code==202,response.text
    return response.json(),state
def revision(*tasks,message='Eased next week after a busy one.'):
    return {'message':message,'assignments':list(tasks)}

def test_checkin_opens_on_the_configured_time_with_a_recap_of_the_week_so_far():
    clock=Clock()
    c,state=long_setup(clock)
    with c:
        assert state['planner']['active_view']['checkin'] is None
        clock.moment=datetime(2030,1,11,9,59,tzinfo=timezone.utc);assert read(c)['planner']['active_view']['checkin'] is None
        clock.moment=datetime(2030,1,11,10,0,tzinfo=timezone.utc);state=read(c)
        view=state['planner']['active_view']['checkin']
        assert view['status']=='open' and view['week_start']=='2030-01-07' and view['expires_at']=='2030-01-14T19:00'
        # a1 was missed on Wednesday, then moved to Monday by reconciliation, so it left this week.
        assert view['recap']['moved']==['Moved to Monday 20:00'] and view['recap']['remaining_minutes']==0

def test_checkin_expires_at_next_weeks_first_task_and_keeps_answers_and_workload():
    clock=Clock()
    model=Staged([long_plan()],details=[detail_for(assignment('w3',date='2030-01-21',start_time='19:00',task='Later.',completion_criterion='Done.'))])
    c,state=open_checkin(clock,model=model)
    with c:
        state=post(c,'/checkins/answer',state,week_start='2030-01-07',week_feel='busier',next_week='less',note='A busy week.')
        assert state['planner']['active_view']['checkin']['status']=='answered'
        clock.moment=datetime(2030,1,14,10,59,tzinfo=timezone.utc);state=read(c)  # 18:59 Monday, before the first task.
        assert state['planner']['active_view']['checkin']['week_start']=='2030-01-07'
        clock.moment=datetime(2030,1,14,11,0,tzinfo=timezone.utc)
        state=wait(c)
        record=state['planner']['active']['checkins']['2030-01-07']
        assert record['status']=='expired' and record['answers']['note']=='A busy week.'
        assert state['planner']['active_view']['checkin'] is None and state['planner']['active']['week_states']=={}
        assert 'closed before it was finished' in state['planner']['active_view']['coach']['notices'][0]
        assert task(state,'w3')['status']=='scheduled'  # Rolling detail doesn't need a completed check-in.

def test_checkin_with_no_task_next_week_expires_at_the_start_of_that_week():
    clock=Clock()
    c,state=open_checkin(clock)
    with c:
        state=post(c,'/tasks/skip',state,task_id=task(state,'a2')['id'])
        state=post(c,'/tasks/skip',state,task_id=task(state,'a1')['id'])
        assert state['planner']['active_view']['checkin']['expires_at']=='2030-01-14T00:00'
        clock.moment=datetime(2030,1,13,15,59,tzinfo=timezone.utc)
        assert read(c)['planner']['active_view']['checkin'] is not None
        clock.moment=datetime(2030,1,13,16,0,tzinfo=timezone.utc)
        state=read(c)
        assert state['planner']['active']['checkins']['2030-01-07']['status']=='expired'

def test_more_and_less_change_only_next_week_by_about_a_quarter_within_capacity():
    clock=Clock()
    keep=assignment('a2',date='2030-01-14',start_time='19:00',task='Tuned.',completion_criterion='Done.')
    model=Staged([long_plan()],revisions=[revision(keep)])
    c,state=open_checkin(clock,model=model)
    with c:
        base=state['planner']['active_view']['checkin']['next_week_target_minutes']
        assert base==240
        _,state=propose(c,state,next_week='less')
        state=wait(c);assert state['operation']['status']=='succeeded',state['operation']
        proposal=state['planner']['proposal']
        assert proposal['kind']=='checkin' and proposal['effect']['workload_before_minutes']==240 and proposal['effect']['workload_after_minutes']==180
        assert proposal['effect']['uses_buffer'] is False and proposal['effect']['finish_after']
        assert model.contexts[-1]['checkin_answers']=={'week_feel':'as_expected','next_week':'less'} and model.contexts[-1]['week_budgets']=={'2030-01-14':180}
        before=state['planner']['config']
        assert state['planner']['active']['week_states']=={}  # Not applied before acceptance.
        state=post(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])
        row=state['planner']['active']['week_states']['2030-01-14'];assert (row['workload_minutes'],row['workload_source'],row['paused'])==(180,'checkin',False)
        assert task(state,'a2')['task']=='Tuned.' and state['planner']['config']==before
        assert state['planner']['active']['checkins']['2030-01-07']['status']=='completed'
        assert state['planner']['active_view']['checkin'] is None

def test_more_uses_the_buffer_up_to_eligible_capacity_and_offers_a_block_beyond_it():
    clock=Clock()
    keep=assignment('a2',date='2030-01-14',start_time='19:00',task='Tuned.',completion_criterion='Done.')
    model=Staged([long_plan()],revisions=[revision(keep)])
    c,state=open_checkin(clock,model=model)
    with c:
        propose(c,state,next_week='more');state=wait(c)
        effect=state['planner']['proposal']['effect']
        assert (effect['workload_after_minutes'],effect['uses_buffer'],effect['add_block_suggested'])==(300,True,False)
    clock=Clock()
    # Eligible next week is capped at 250, so 20% buffer leaves 200, and 25% more would be 250 exactly: still fits.
    model=Staged([long_plan()],revisions=[revision(keep)])
    c,state=open_checkin(clock,model=model,weekly_minutes=250)
    with c:
        propose(c,state,next_week='more');state=wait(c)
        assert state['planner']['proposal']['effect']['workload_after_minutes']==250
    clock=Clock()
    # With a 40% buffer on 300 eligible minutes, more stays inside eligible. A 50% cap shows the block offer in the arithmetic below.
    from app.planning.checkin import next_week_workload
    capacity=Capacity(PlannerConfig.model_validate(settings(target_date=LONG_TARGET,buffer_percent=0,weekly_minutes=300)),clock())
    plan={'config':settings(target_date=LONG_TARGET),'outline':[],'week_states':{},'assignments':[]}
    load=next_week_workload(plan,date(2030,1,7),'more',capacity)
    assert (load['base'],load['target'],load['exceeds_capacity'])==(300,300,True)

def test_under_half_of_due_work_suggests_less():
    clock=Clock()
    plan=long_plan(assignments=[assignment('a1',duration_minutes=30,date='2030-01-09'),assignment('a3',date='2030-01-09',start_time='19:30',duration_minutes=30,task='Second.',completion_criterion='Done.'),second_week()])
    c,state=long_setup(clock,Staged([plan]))
    with c:
        state=post(c,'/tasks/update',state,task_id=task(state,'a1')['id'],pinned=True)
        state=post(c,'/tasks/update',state,task_id=task(state,'a3')['id'],pinned=True)
        clock.moment=datetime(2030,1,11,10,0,tzinfo=timezone.utc);state=read(c)
        assert state['planner']['active_view']['checkin']['recap']['suggest_less'] is True
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a3')['id'],status='completed')
        assert state['planner']['active_view']['checkin']['recap']['suggest_less'] is False

def test_checkin_failure_keeps_answers_and_schedule_and_retry_succeeds():
    clock=Clock()
    keep=assignment('a2',date='2030-01-14',start_time='19:00',task='Tuned.',completion_criterion='Done.')
    model=Staged([long_plan()],revisions=[Problem('Provider down.',503,'model_provider'),revision(keep)])
    c,state=open_checkin(clock,model=model)
    with c:
        schedule_before=[(t['id'],t['date'],t['start_time'],t['task']) for t in state['planner']['active']['assignments']]
        propose(c,state,next_week='less',note='A note to keep.');state=wait(c)
        assert state['operation']['status']=='failed' and state['planner']['proposal'] is None
        assert state['planner']['active']['checkins']['2030-01-07']['answers']['note']=='A note to keep.'
        assert [(t['id'],t['date'],t['start_time'],t['task']) for t in state['planner']['active']['assignments']]==schedule_before
        body=state['planner']['retry_checkin'];assert body
        assert c.post('/api/v1/roadmaps/planner/checkins/propose',headers=H,json=body).status_code==202
        import time;time.sleep(.05);state=wait(c)
        assert state['operation']['status']=='succeeded' and state['planner']['proposal']['kind']=='checkin'

def test_invalid_checkin_output_is_rejected_after_bounded_retries_and_nothing_applies():
    clock=Clock()
    over=assignment('a2',date='2030-01-14',start_time='19:00',duration_minutes=120,task='Too long.',completion_criterion='Done.')
    over2=assignment('a9',date='2030-01-16',start_time='19:00',duration_minutes=90,task='Too much.',completion_criterion='Done.')
    model=Staged([long_plan()],revisions=[revision(over,over2)]*3)
    c,state=open_checkin(clock,model=model)
    with c:
        propose(c,state,next_week='less');state=wait(c)
        assert state['operation']['error']['code']=='plan_validation' and state['planner']['proposal'] is None
        assert len(model.revisions)==0 and 'a9' not in {t['key'] for t in state['planner']['active']['assignments']}

def test_revisions_preserve_completed_pinned_and_custom_tasks_and_plan_around_them():
    clock=Clock()
    pinned=second_week('p1',start_time='20:00',duration_minutes=30,task='Pinned work.')
    keep=assignment('n1',date='2030-01-16',start_time='19:00',task='Replacement.',completion_criterion='Done.')
    model=Staged([long_plan(assignments=[assignment(),second_week(),pinned])],revisions=[revision(keep)])
    c,state=long_setup(clock,model)
    with c:
        state=post(c,'/tasks/update',state,task_id=task(state,'p1')['id'],pinned=True)
        state=custom(c,state,title='Custom',date='2030-01-16',start_time='20:00',duration_minutes=30)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        clock.moment=datetime(2030,1,11,10,0,tzinfo=timezone.utc);state=read(c)
        before={k:task(state,k) for k in ('a1','p1')};mock=added(state,'Custom')
        propose(c,state,next_week='same');state=wait(c);assert state['operation']['status']=='succeeded',state['operation']
        sent=model.contexts[-1];assert {'p1',mock['key'],'a1'}<={i['key'] for i in sent['fixed_items']}
        assert [t['key'] for t in sent['replaceable_tasks']]==['a2']
        assert sent['week_budgets']=={'2030-01-14':240-30-30}
        state=post(c,'/proposals/accept',state,proposal_id=state['planner']['proposal']['id'],keep_task_ids=[])
        assert task(state,'a1')==before['a1'] and task(state,'p1')==before['p1'] and added(state,'Custom')==mock
        assert task(state,'a2')['status']=='removed' and task(state,'a2')['removed_reason']=='revised' and task(state,'n1')['status']=='scheduled'

def test_stale_proposals_are_rejected_and_accepted_atomically_otherwise():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        state=post(c,'/proposals/pause',state,week_start='2030-01-14')
        proposal=state['planner']['proposal']
        state=post(c,'/tasks/update',state,task_id=task(state,'a1')['id'],pinned=True)
        assert {b['code'] for b in state['planner']['proposal_blockers']}=={'proposal_stale'}
        before=state['planner']['active']['week_states']
        assert rejected(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])==(409,'proposal_stale')
        assert read(c)['planner']['active']['week_states']==before

def test_pause_previews_moves_keeps_exceptions_and_preserves_the_target_date():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        state=custom(c,state,title='Kept',date='2030-01-16',start_time='19:00',duration_minutes=30)
        state=custom(c,state,title='Sent away',date='2030-01-16',start_time='19:30',duration_minutes=30)
        before=state['planner']['active']
        state=post(c,'/proposals/pause',state,week_start='2030-01-14')
        proposal=state['planner']['proposal'];effect=proposal['effect']
        assert state['planner']['active']==before  # Only a preview so far.
        assert effect['target_after']=='2030-01-27' and effect['tasks_moved']==[task(state,'a2')['task']]
        assert {d['title'] for d in effect['decisions']}=={'Kept','Sent away'}
        assert effect['capacity_after_minutes']<effect['capacity_before_minutes']
        kept=added(state,'Kept')['id']
        state=post(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[kept])
        row=state['planner']['active']['week_states']['2030-01-14']
        assert row['paused'] and row['exception_task_ids']==[kept]
        assert task(state,'a2')['date']>='2030-01-21' and task(state,'a2')['baseline'].startswith('2030-01-21')
        assert added(state,'Kept')['date']=='2030-01-16' and added(state,'Sent away')['status']=='backlog'
        assert str(state['planner']['active']['config']['target_date'])=='2030-01-27'
        week=next(w for w in state['planner']['active_view']['weeks'] if w['week_start']=='2030-01-14')
        assert week['paused'] and week['eligible_minutes']==0 and week['exception_task_ids']==[kept]
        # A manual move into a paused week needs confirming and becomes an exception.
        two=task(state,'a2')
        assert rejected(c,'/tasks/move',state,task_id=two['id'],date='2030-01-14',start_time='19:00')==(409,'paused_week')
        state=post(c,'/proposals/unpause',state,week_start='2030-01-14')
        proposal=state['planner']['proposal']
        assert proposal['effect']['capacity_after_minutes']>proposal['effect']['capacity_before_minutes']
        state=post(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])
        assert not state['planner']['active']['week_states']['2030-01-14']['paused']

def test_completed_work_survives_a_pause_and_past_weeks_cannot_be_paused():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        done=task(state,'a1')
        state=post(c,'/proposals/pause',state,week_start='2030-01-07')
        state=post(c,'/proposals/accept',state,proposal_id=state['planner']['proposal']['id'],keep_task_ids=[])
        assert task(state,'a1')==done
        assert rejected(c,'/proposals/pause',state,week_start='2029-12-31')==(409,'pause_invalid')

def test_edit_plan_previews_then_applies_and_preserves_progress():
    clock=Clock()
    with client(clock=clock) as c:
        state=accepted(c)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed',evidence_note='Done it.')
        done=task(state,'a1')
        blocks=[{'day':3,'start_time':'18:00','duration_minutes':120,'kind':'preferred'}]
        changed=settings(blocks=blocks,weekly_minutes=120,target_date='2030-02-03',blackouts=[])
        state=post(c,'/proposals/edit',state,config=changed)
        proposal=state['planner']['proposal'];effect=proposal['effect']
        assert state['planner']['active']['config']['weekly_minutes']==300
        assert effect['target_before']=='2030-01-27' and effect['target_after']=='2030-02-03' and effect['tasks_moved']==[task(state,'a2')['task']]
        state=post(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])
        active=state['planner']['active']
        assert active['config']['weekly_minutes']==120 and state['planner']['config']['weekly_minutes']==120
        assert task(state,'a1')==done and task(state,'a2')['date']=='2030-01-10' and active['outline'][-1]['week_start']=='2030-01-28'
        assert not [s for s in state['planner']['signals'] if s['kind']=='settings']
        assert rejected(c,'/proposals/edit',state,config=settings(target_date='2030-01-01'))==(409,'edit_invalid')

def test_pace_actions_each_prepare_a_preview():
    clock=Clock()
    two=milestone('m2',title='Add a database',prerequisite_keys=['m1'],estimated_minutes=200,projected_start='2030-01-20',projected_end='2030-01-27',gap_ids=[])
    plan=draft(milestones=[milestone(estimated_minutes=240),two])
    with client(Staged([plan]),clock=clock) as c:
        state=accepted(c);before=state['planner']['active']
        state=post(c,'/proposals/pace',state,action='add_hours',extra_minutes=60)
        effect=state['planner']['proposal']['effect']
        assert state['planner']['proposal']['kind']=='pace_add_hours' and state['planner']['active']==before
        assert state['planner']['proposal']['patch']['config']['weekly_minutes']==360
        state=post(c,'/proposals/pace',state,action='move_date',target_date='2030-02-10')
        assert state['planner']['proposal']['effect']['target_after']=='2030-02-10'
        assert rejected(c,'/proposals/pace',state,action='move_date',target_date='2030-01-20')==(409,'date_invalid')
        assert rejected(c,'/proposals/pace',state,action='cut_scope')==(409,'nothing_to_cut')  # Everything still fits.
        # Shrinking the runway makes work overflow, so cutting takes the last milestone first.
        small=settings(target_date='2030-01-27',weekly_minutes=120)
        state=post(c,'/proposals/edit',state,config=small)
        state=post(c,'/proposals/accept',state,proposal_id=state['planner']['proposal']['id'],keep_task_ids=[])
        state=post(c,'/proposals/pace',state,action='cut_scope')
        proposal=state['planner']['proposal']
        assert 'Add a database' in proposal['effect']['summary']
        state=post(c,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])
        active=state['planner']['active']
        assert [m['key'] for m in active['milestones']]==['m1'] and active['deferred_scope'][0]['key']=='m2'
        state=post(c,'/proposals/scope',state,deferred_id='deferred-m2',target_date='2030-02-24')
        proposal=state['planner']['proposal']
        assert proposal['kind']=='scope' and proposal['effect']['target_after']=='2030-02-24'
        state=post(c,'/proposals/discard',state,proposal_id=proposal['id'])
        assert state['planner']['proposal'] is None and state['planner']['active']['deferred_scope']

def test_deferred_scope_with_a_deferred_dependency_must_come_later():
    plan=draft(milestones=[milestone(estimated_minutes=240)],beyond_deadline=[{'key':'x','title':'First','gap_ids':[],'reason':'Later.','estimated_minutes':60,'dependencies':[]},{'key':'y','title':'Second','gap_ids':[],'reason':'Later.','estimated_minutes':60,'dependencies':['x']}],
        deadline_outcome={'summary':'Part of it.','achievable_by_target':[],'fits_in_runway':False})
    with client(Staged([plan])) as c:
        state=accepted(c)
        assert rejected(c,'/proposals/scope',state,deferred_id='deferred-y')==(409,'dependency_deferred')
        state=post(c,'/proposals/scope',state,deferred_id='deferred-x')
        assert state['planner']['proposal']['patch']['milestones'][-1]['key']=='x'

def test_a_new_roadmap_keeps_the_old_one_active_until_accepted_then_archives_it_read_only():
    new=draft(summary='A second roadmap.',assignments=[assignment('b1',task='New first task.',start_time='19:00'),second_week('b2',task='New second task.',start_time='20:00')])
    model=Staged([draft(),new])
    with client(model) as c:
        state=accepted(c)
        state=post(c,'/tasks/update',state,task_id=task(state,'a1')['id'],note='A private note.')
        state=custom(c,state,title='Mentor call',date='2030-01-16',start_time='19:00')
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a2')['id'],status='completed',feedback='too_easy')
        old=state['planner']['active']
        state=generate(c,state)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['active']==old and state['planner']['candidate']['summary']=='A second roadmap.'
        sent=model.contexts[-1]['prior_completed_work']
        assert sent[0]['task']==task(state,'a2')['task'] and sent[0]['feedback']=='too_easy' and sent[0]['skills']==['Python'] and sent[0]['completed_at']
        state=post(c,'/accept',state)
        active=state['planner']['active']
        assert active['summary']=='A second roadmap.' and active['id']!=old['id']
        assert 'Mentor call' in {t['task'] for t in active['assignments']}  # Custom tasks stay the user's.
        row=state['planner']['archived'][0]
        assert (row['role'],row['tasks_completed'],row['completed_minutes'])==('Developer',1,60)
        kept=c.get('/api/v1/roadmaps/history/'+row['id'],headers=H).json()
        assert kept['id']==row['id'] and kept['source_plan_id']==old['id'] and kept['events'] and any(t['note']=='A private note.' for t in kept['assignments'])
        assert state['planner']['candidate'] is None

def test_a_repeated_accept_archives_once_and_other_owners_cannot_read_archives():
    sources=Sources()
    new=draft(summary='Second.',assignments=[assignment('b1',task='New.'),second_week('b2',task='Newer.')])
    with client(Staged([draft(),new]),sources=sources) as c:
        state=generate(c,accepted(c))
        body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        first=c.post('/api/v1/roadmaps/planner/accept',headers=H,json=body).json()
        second=c.post('/api/v1/roadmaps/planner/accept',headers=H,json=body).json()
        assert len(first['planner']['archived'])==len(second['planner']['archived'])==1
        identifier=first['planner']['archived'][0]['id']
        sources.owner='22222222-2222-4222-8222-222222222222'
        assert c.get('/api/v1/roadmaps/history/'+identifier,headers=H).status_code==404
        assert c.get('/api/v1/roadmaps/summary',headers=H).json()=={'has_active':False,'schema_version':None,'role':None,'target_date':None,'current_week':None,'next_task':None,'progress':None,'pace':None,'projection':None}

def legacy_row():
    plan=draft();tasks=plan.pop('assignments');beyond=plan.pop('beyond_deadline')
    return {**plan,'schema_version':'roadmap-v2','id':'old-plan','assessment_id':'assessment1','assessment_hash':'hash1','assessment':assessment(),'config':settings(),'config_hash':'x','confirmations_hash':'y','base_active_id':None,'created_at':'2030-01-01T00:00:00+00:00','first_planning_week':'2030-01-07','beyond_deadline':beyond,
        'milestones':[{**milestone(),'id':'m1','outcome':{'demonstrated':False}}],'assignments':[{**{k:v for k,v in assignment().items()},'id':'a1','status':'scheduled','completed_at':None,'evidence_note':None,'history':[]}],'changes':None,'generation':{'attempts':1}}

def test_roadmap_v2_plans_stay_readable_reject_new_mutations_and_can_be_replaced():
    store=MemoryStore();row=store.load(OWNER);row['planner']={'config':settings(),'active':legacy_row(),'candidate':None,'confirmations':{}}
    store.save_result(OWNER,row['planner']['active']);store.cas(OWNER,0,row)
    clock=Clock();clock.set(20)
    model=Staged([draft(milestones=[milestone(projected_start='2030-01-20',projected_end='2030-01-27')],assignments=[assignment('n1',date='2030-01-20',start_time='09:00',task='New.'),assignment('n2',date='2030-01-21',start_time='19:00',task='Newer.')])])
    with TestClient(create_app(store,Sources(),model,clock=clock)) as c:
        state=read(c);active=state['planner']['active']
        assert active['schema_version']=='roadmap-v2' and active['assignments'][0]['date']=='2030-01-09'  # Nothing moved it.
        assert state['planner']['active_view'] is None and state['planner']['active_review']
        assert c.get('/api/v1/roadmaps/history/old-plan',headers=H).json()['schema_version']=='roadmap-v2'
        assert c.get('/api/v1/roadmaps/summary',headers=H).json()['schema_version']=='roadmap-v2'
        for path,body in (('/tasks/skip',{'task_id':'a1'}),('/assignments/status',{'assignment_id':'a1','status':'completed'}),('/proposals/pause',{'week_start':'2030-01-21'})):
            assert rejected(c,path,state,**body)==(409,'legacy_plan')
        state=read(c)
        assert state['planner']['active']==active
        state=configure(c,state,start_date='2030-01-20',use_backup=True)
        state=generate(c,state);assert state['operation']['status']=='succeeded',state['operation']
        state=post(c,'/accept',state)
        assert state['planner']['active']['schema_version']=='roadmap-v3'
        row=state['planner']['archived'][0]
        assert row['schema_version']=='roadmap-v2' and c.get('/api/v1/roadmaps/history/'+row['id'],headers=H).json()['source_plan_id']=='old-plan'

def test_a_repeated_task_needs_a_refresher_reason():
    prior=draft(assignments=[assignment('a1'),second_week()])
    repeat=draft(assignments=[assignment('b1',start_time='20:00',duration_minutes=20),second_week('b2',task='New second task.')])
    justified=draft(assignments=[assignment('b1',start_time='20:00',duration_minutes=20,refresher_reason='You marked this too hard, so it returns with more support.'),second_week('b2',task='New second task.')])
    model=Staged([prior,repeat,justified])
    with client(model) as c:
        state=accepted(c)
        state=post(c,'/assignments/status',state,assignment_id=task(state,'a1')['id'],status='completed')
        state=generate(c,state)
        assert state['operation']['error']['code']=='plan_validation' and 'repeats completed work' in state['operation']['error']['detail']
        state=generate(c,state)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['candidate']['assignments'][0]['refresher_reason']

def test_summary_exposes_reusable_progress():
    with client() as c:
        accepted(c)
        summary=c.get('/api/v1/roadmaps/summary',headers=H).json()
        assert summary['has_active'] and summary['next_task']['date']=='2030-01-09' and summary['progress']['label']=='Roadmap progress' and summary['pace']['status']=='insufficient_data' and summary['projection']['target_date']=='2030-01-27'

@pytest.mark.parametrize('zone,moment,opened',[
    ('America/New_York',datetime(2030,3,8,23,0,tzinfo=timezone.utc),True),   # Friday 18:00 EST.
    ('America/New_York',datetime(2030,3,8,22,59,tzinfo=timezone.utc),False),
])
def test_checkin_and_missed_rules_use_plan_timezone_wall_clock(zone,moment,opened):
    clock=Clock(datetime(2030,3,4,14,0,tzinfo=timezone.utc))
    blocks=[{'day':0,'start_time':'19:00','duration_minutes':120,'kind':'preferred'},{'day':5,'start_time':'10:00','duration_minutes':120,'kind':'preferred'}]
    plan=draft(milestones=[milestone(projected_start='2030-03-04',projected_end='2030-03-24')],assignments=[assignment('a1',date='2030-03-04',start_time='19:00'),assignment('a2',date='2030-03-11',start_time='19:00')])
    with client(Staged([plan]),clock=clock) as c:
        state=configure(c,time_zone=zone,start_date='2030-03-04',target_date='2030-03-24',blocks=blocks,blackouts=[])
        state=generate(c,state);assert state['operation']['status']=='succeeded',state['operation']
        post(c,'/accept',state)
        clock.moment=moment
        assert (read(c)['planner']['active_view']['checkin'] is not None)==opened

def test_a_task_on_a_daylight_saving_day_is_placed_in_real_wall_clock_time():
    # 10 March 2030: 02:00 to 03:00 doesn't exist in New York.
    clock=Clock(datetime(2030,3,4,14,0,tzinfo=timezone.utc))
    blocks=[{'day':6,'start_time':'01:00','duration_minutes':180,'kind':'preferred'},{'day':0,'start_time':'19:00','duration_minutes':120,'kind':'preferred'}]
    plan=draft(milestones=[milestone(projected_start='2030-03-04',projected_end='2030-03-24',estimated_minutes=120)],assignments=[assignment('a1',date='2030-03-04',start_time='19:00'),assignment('a2',date='2030-03-11',start_time='19:00')])
    with client(Staged([plan]),clock=clock) as c:
        state=configure(c,time_zone='America/New_York',start_date='2030-03-04',target_date='2030-03-24',blocks=blocks,blackouts=[])
        state=generate(c,state);assert state['operation']['status']=='succeeded',state['operation']
        state=post(c,'/accept',state)
        assert rejected(c,'/tasks/move',state,task_id=task(state,'a2')['id'],date='2030-03-10',start_time='02:15')==(409,'slot_invalid')
        clock.moment=datetime(2030,3,5,14,0,tzinfo=timezone.utc)  # Tuesday: a1 was missed.
        state=read(c);one=task(state,'a1')
        # Sunday's only valid minutes are 01:00-02:00 and 03:00-04:00, so 60 minutes starts at 01:00.
        assert (one['date'],one['start_time'])==('2030-03-10','01:00')
