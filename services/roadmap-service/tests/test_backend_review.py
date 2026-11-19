"""Regressions for defects found in a roadmap backend review.

All data and providers are synthetic.
"""
import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
import pytest
from elo_shared.runtime import Problem
from planner_fixtures import NOW, OWNER, assignment, draft, settings
from test_planner_flow import (Clock, Scripted, Sources, H, accepted, accept_week, client_for,
    configure, generate, long_draft, plan_week, post, read, request, task, week_draft, SUNDAY)
from app.planning.capacity import Capacity
from app.planning.generator import set_stage
from app.planning.outlines import validate_outline
from app.planning.capacity import Placer
from app.planning.placement import week_target
from app.planning.sessions import free_times
from app.planning.state import planning_source_changed
from app.planning.weeks import (check_week, first_open_week, remaining_scope, unfinished,
    week_basis, planning, last_week_summary)
from app.schemas.outlines import OutlineDraft
from app.schemas.roadmap import PlannerConfig
from app.schemas.weeks import WeekDraft

CONFIG=PlannerConfig.model_validate(settings(break_minutes_per_hour=10))
START,END=date(2030,1,14),date(2030,1,21)

def saved_task(id='old', **changes):
    return {'id':id,'title':'Write an endpoint','instructions':'Implement it.','completion_outcome':'Test passes.',
        'estimated_minutes':60,'milestone_key':'m1','schedule':[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}],
        'status':'not_started','removed':False,'origin':'generated','prerequisites':[],'requirement_refs':[],**changes}

def outline_data():
    value=long_draft();value.pop('assignments');value['routine_rules']=[]
    value['weeks']=[{'week_start':s,'objective':'Implement an API','expected_outcome':'A test passes','estimated_minutes':m,'milestone_key':'m1','gap_ids':['python']}
        for s,m in [('2030-01-07',60),('2030-01-14',300),('2030-01-21',240)]]
    return value

def week_errors(output, pending=(), config=CONFIG, existing=None):
    return check_week(WeekDraft.model_validate(output),outline_data(),config,existing,[],list(pending),
        {'week_start':'2030-01-14','target_minutes':300},{'m1':300})

def test_invalid_split_is_a_validation_error_not_an_exception():
    errors=week_errors(week_draft(carryover=[{'task_id':'old','action':'split','minutes':None,'reason':'Split it.'}]),[saved_task()])
    assert any('split' in e and 'minutes' in e for e in errors)

def test_omitted_carry_choices_still_count_towards_the_target():
    output=week_draft([task('new','Add validation',280)])
    errors=week_errors(output,[saved_task()])
    assert any('room for 240' in e for e in errors)

def test_excess_unfinished_work_fails_explicitly_instead_of_being_silently_omitted():
    with pytest.raises(Problem,match='no work was omitted'):
        unfinished({'editable_tasks':[saved_task(str(i)) for i in range(41)]},Capacity(CONFIG,SUNDAY))

def test_completed_work_is_subtracted_from_total_milestone_scope_and_never_repeated():
    outline=outline_data();outline['created_at']='2031-01-01T00:00:00Z'
    done=saved_task(status='completed',completed_at='2030-01-01T00:00:00Z')
    existing={'editable_tasks':[done]}
    assert remaining_scope(outline,existing,[],END)=={'m1':540}
    errors=week_errors(week_draft([task('duplicate',done['title'])]),existing=existing)
    assert any('repeats' in e for e in errors)

def test_first_week_can_be_later_than_the_next_two_weeks():
    config=CONFIG.model_copy(update={'blackouts':[], 'blocks':[], 'allow_overflow':True,
        'reduced_periods':[], 'start_date':date(2030,1,9)})
    config=PlannerConfig.model_validate({**config.model_dump(mode='json'),'blackouts':[{'frequency':'daily','start_date':'2030-01-09','end_date':'2030-01-20'}]})
    assert first_open_week({'active':None,'week_blocks':[]},outline_data(),config,NOW)==date(2030,1,21)

def test_unplanned_sunday_is_available_for_current_week_recovery():
    state={'outline_active':{'id':'outline'},'active':{'editable_tasks':[]},'week_blocks':[],'config':CONFIG.model_dump(mode='json')}
    result=planning(state,SUNDAY)
    assert result['action']=='plan_this' and result['week_start']=='2030-01-07'

def test_anytime_work_participates_in_week_completion_and_unfinished_analytics():
    item=saved_task(schedule=[],anytime_date='2030-01-09')
    plan={'editable_tasks':[item]}
    assert [t['id'] for t in unfinished(plan,Capacity(CONFIG,SUNDAY))]==['old']
    state={'outline_active':{'id':'outline'},'active':plan,'week_blocks':[{'week_start':'2030-01-07','status':'accepted'}], 'config':CONFIG.model_dump(mode='json')}
    assert not planning(state,NOW)['week_done']
    item['status']='completed'
    assert planning(state,NOW)['week_done']
    assert last_week_summary(plan,date(2030,1,14))['tasks_completed']==1

def test_fixed_day_routines_cannot_bypass_lead_time_or_date_bounds():
    config=CONFIG.model_copy(update={'allow_overflow':True,'lead_minutes':1440})
    placer=Placer(config,NOW,[],date(2030,1,9),date(2030,1,11))
    assert placer.place(30,only=date(2030,1,9)) is None
    assert placer.place(30,only=date(2030,1,12)) is None

def test_work_splits_into_shorter_windows_instead_of_failing_placement():
    config=CONFIG.model_copy(update={'blackouts':[], 'blocks':[
        type(CONFIG.blocks[0])(day=0,start_time='10:00',duration_minutes=40),
        type(CONFIG.blocks[0])(day=1,start_time='10:00',duration_minutes=40)]})
    slots=Placer(config,NOW,[],START,END).place(80)
    assert [s['duration_minutes'] for s in slots]==[40,40]

def test_runway_and_week_target_share_breaks_around_saved_commitments_and_rest_days():
    reserved=[{'date':'2030-01-14','start_time':'19:00','duration_minutes':60}]
    config=CONFIG.model_copy(update={'allow_overflow':True,'rest_days_per_week':6,'weekly_minutes':120})
    capacity=Capacity(config,NOW,reserved)
    row=next(w for w in capacity.weeks() if w['week_start']=='2030-01-14')
    target=week_target(config,NOW,reserved,START,END)
    assert row['usable_minutes']==target['target_minutes']==60
    placer=Placer(config,NOW,reserved,START,END)
    assert placer.place(60)[0]['date']=='2030-01-14'

def test_irregular_minute_targets_are_not_rounded_down_to_five_minutes():
    config=CONFIG.model_copy(update={'allow_overflow':True,'weekly_minutes':99})
    assert week_target(config,NOW,[],START,END)['target_minutes']==99

def test_outline_routines_can_split_and_combined_break_conflicts_are_rejected():
    from planner_fixtures import assessment
    value=outline_data();value['weeks']=[]
    rule={'id':'routine','milestone_key':'m1','activity':'Practise endpoints','weekdays':[0], 'duration_minutes':80,'start_date':'2030-01-14','end_date':'2030-01-14'}
    value['routine_rules']=[rule]
    config=CONFIG.model_copy(update={'blackouts':[],'blocks':[type(CONFIG.blocks[0])(day=0,start_time='10:00',duration_minutes=40),type(CONFIG.blocks[0])(day=0,start_time='11:00',duration_minutes=40)],'allow_overflow':True})
    assert 'routine_conflict' not in {e['code'] for e in validate_outline(OutlineDraft.model_validate(value),Capacity(config,NOW),assessment(),{})}
    tight=config.model_copy(update={'allow_overflow':False,'blocks':[type(CONFIG.blocks[0])(day=0,start_time='10:00',duration_minutes=60)]})
    value['routine_rules']=[{**rule,'id':str(i),'duration_minutes':30} for i in range(2)]
    assert 'routine_conflict' in {e['code'] for e in validate_outline(OutlineDraft.model_validate(value),Capacity(tight,NOW),assessment(),{})}

@pytest.mark.parametrize('field,value', [('title','Changed title'),('completion_outcome','Changed definition'),('milestone_key','m2'),('self_rating',{'difficulty':9}),('notes',{'blocks':[]})])
def test_preview_basis_detects_edits_to_carried_work(field,value):
    outline={'id':'outline','revision':1};old=saved_task();new={**old,field:value}
    assert week_basis(outline,{'editable_tasks':[old]},START,[old])!=week_basis(outline,{'editable_tasks':[new]},START,[new])

def test_future_objectives_respect_reduced_capacity_and_milestone_scope():
    output=week_draft(objective_changes=[{**outline_data()['weeks'][2],'estimated_minutes':300,'reason':'Adjust pace.'}])
    config=PlannerConfig.model_validate({**CONFIG.model_dump(mode='json'),'reduced_periods':[{'start_date':'2030-01-21','end_date':'2030-01-27','weekly_minutes':60}]})
    errors=week_errors(output,config=config)
    assert any('available study capacity' in e for e in errors)
    assert any('estimated effort' in e for e in errors)

def test_freshness_and_profile_changes_are_fenced_even_when_input_hash_is_unchanged():
    before={'ready':True,'input_hash':'same','planning_defaults':{'availability_periods':[]},'evaluation':{'freshness':'current'}}
    after={**before,'evaluation':{'freshness':'outdated'}}
    assert planning_source_changed(before,after)
    assert planning_source_changed(before,{**before,'planning_defaults':{'availability_periods':[{'weekly_hours':0}]}})

def test_acceptance_rechecks_current_profile_reduced_periods():
    clock=Clock();sources=Sources()
    with client_for(Scripted([long_draft()]),sources,clock) as client:
        state=generate(client,configure(client))
        sources.periods=[{'start_date':'2030-01-09','end_date':'2030-01-27','weekly_hours':0}]
        response=request(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/accept',state)
        assert response.status_code==409 and read(client)['planner']['active'] is None

def test_week_acceptance_rechecks_current_profile_availability():
    clock=Clock();sources=Sources()
    model=Scripted([long_draft()],weeks=[week_draft([assignment()]),lambda ctx:week_draft([task('new','Add validation',240)],carryover=[{'task_id':ctx['progress']['unfinished'][0]['task_id'],'action':'carry','reason':'Continue.'}])])
    with client_for(model,sources,clock) as client:
        state=accepted(client);clock.now=SUNDAY;state=plan_week(client,read(client),'2030-01-14')
        sources.periods=[{'start_date':'2030-01-14','end_date':'2030-01-20','weekly_hours':0}]
        response=request(client,'/weeks/'+state['planner']['week_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='week_stale'

def test_session_proposals_use_extra_time_permission_and_session_limit():
    from test_planner_flow import draft as plan_draft
    with client_for(Scripted([plan_draft()])) as client:
        state=accepted(client)
        plan=state['planner']['active']
        days=free_times(plan,NOW,60)['days']
        assert not next(d for d in days if d['date']=='2030-01-10')['starts']
        assert all(not day['starts'] for day in free_times(plan,NOW,90)['days'])

def test_strict_batch_moves_allow_a_swap_of_two_valid_slots():
    model=Scripted([draft(assignments=[task('one','First',45),task('two','Second',45)])])
    with client_for(model) as client:
        state=accepted(client,break_minutes_per_hour=0)
        rows=state['planner']['active_sessions'];first,second=rows
        response=request(client,'/sessions/move',state,moves=[{'session_id':first['id'],'date':second['date'],'start_time':second['start_time']}, {'session_id':second['id'],'date':first['date'],'start_time':first['start_time']}])
        assert response.status_code==200,response.text
        after={r['id']:r for r in response.json()['planner']['active_sessions']}
        assert after[first['id']]['start_time']==second['start_time'] and after[second['id']]['start_time']==first['start_time']

def test_outline_checkpoint_keeps_the_long_operation_lease():
    calls=[]
    class Store:
        def checkpoint(self,owner,row,seconds):calls.append(seconds)
    app=SimpleNamespace(state=SimpleNamespace(store=Store()))
    asyncio.run(set_stage(app,{'pending':{'work_seconds':420}},OWNER,'writing'))
    assert calls==[450]

def test_evidence_identity_survives_unrelated_progress_and_confirmation_retry():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        item=state['planner']['active']['editable_tasks'][0]
        state=post(client,'/tasks/status',state,task_id=item['id'],status='completed',evidence_note='Built a tested endpoint.')
        proposal=client.get('/api/v1/roadmaps/planner/evidence-proposals',headers=H).json()['items'][0]
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=False)
        again=client.get('/api/v1/roadmaps/planner/evidence-proposals',headers=H).json()['items'][0]
        assert proposal['proposal_hash']==again['proposal_hash']
        body={'expected_version':state['version'],'mutation_id':str(uuid4()),'expected_declarations_version':0,'proposal_hash':again['proposal_hash']}
        path='/api/v1/roadmaps/planner/evidence-proposals/'+again['id']+'/confirm'
        assert client.post(path,headers=H,json=body).status_code==200
        assert client.post(path,headers=H,json=body).status_code==200
        assert len(client.app.state.upstream.writes)==1
        assert client.get('/api/v1/roadmaps/planner/evidence-proposals',headers=H).json()['items']==[]

def test_splitting_preserves_notes_and_requires_the_remainder_before_dependants():
    clock=Clock()
    def next_week(ctx):
        first=next(t for t in ctx['progress']['unfinished'] if t['title']=='First')
        other=next(t for t in ctx['progress']['unfinished'] if t['title']=='Dependent')
        return week_draft([task('new','Add request validation',240)],carryover=[
            {'task_id':first['task_id'],'action':'split','minutes':30,'reason':'Divide the work.'},
            {'task_id':other['task_id'],'action':'defer','reason':'Finish the prerequisite first.'}])
    initial=draft(milestones=long_draft()['milestones'],assignments=[task('first','First',60),task('dep','Dependent',30)])
    model=Scripted([initial],weeks=[week_draft(initial['assignments']),next_week])
    with client_for(model,clock=clock) as client:
        state=accepted(client,break_minutes_per_hour=0)
        by_title={t['title']:t for t in state['planner']['active']['editable_tasks']}
        first,dependent=by_title['First'],by_title['Dependent']
        notes={'blocks':[{'type':'paragraph','runs':[{'text':'Keep this note.'}]}]}
        state=post(client,'/tasks/notes',state,task_id=first['id'],notes=notes)
        state=post(client,'/tasks/edit',state,task_id=dependent['id'],changes={'prerequisites':[first['id']]})
        clock.now=SUNDAY
        state=accept_week(client,plan_week(client,read(client),'2030-01-14'))
        tasks={t['id']:t for t in state['planner']['active']['editable_tasks']}
        remainder=next(t for t in tasks.values() if any(h.get('event')=='split_remainder' for h in t['history']))
        assert tasks[first['id']]['notes']['blocks'][0]['runs'][0]['text']=='Keep this note.'
        assert tasks[dependent['id']]['prerequisites']==[remainder['id']]
        assert remainder['prerequisites']==[first['id']]
        state=post(client,'/tasks/status',state,task_id=first['id'],status='completed')
        response=client.get('/api/v1/roadmaps/planner/tasks',headers=H).json()
        dep=next(t for t in response['tasks'] if t['id']==dependent['id'])
        assert not dep['readiness']['actionable']

def test_anytime_commitments_use_budget_without_fabricating_time_slots():
    from app.planning.placement import reservations
    config=CONFIG.model_copy(update={'allow_overflow':True,'weekly_minutes':120})
    saved={'editable_tasks':[saved_task(schedule=[],anytime_date='2030-01-14',estimated_minutes=90)]}
    target=week_target(config,NOW,reservations(saved),START,END)
    assert target['target_minutes']==30 and target['reasons'][0]['code']=='saved_work'

def test_split_sessions_obey_the_configured_minimum_as_well_as_maximum():
    config=CONFIG.model_copy(update={'preferred_session_minutes':30,'min_session_minutes':25,'allow_overflow':True})
    assert Placer(config,NOW,[],START,END).place(40) is None
    slots=Placer(config,NOW,[],START,END).place(55)
    assert sum(s['duration_minutes'] for s in slots)==55 and all(25<=s['duration_minutes']<=30 for s in slots)

def test_changed_work_rejects_carry_review_without_rearranging_stale_tasks():
    clock=Clock()
    model=Scripted([long_draft()],weeks=[week_draft([assignment()]),lambda ctx:week_draft([task('new','Add validation',240)],carryover=[{'task_id':ctx['progress']['unfinished'][0]['task_id'],'action':'carry','reason':'Continue.'}])])
    with client_for(model,clock=clock) as client:
        state=accepted(client);old=state['planner']['active']['editable_tasks'][0]
        clock.now=SUNDAY;state=plan_week(client,read(client),'2030-01-14')
        identifier=state['planner']['week_candidate']['id']
        state=post(client,'/tasks/edit',state,task_id=old['id'],changes={'completion_outcome':'A revised completion definition.'})
        before=state['planner']['week_candidate']
        response=request(client,'/weeks/'+identifier+'/carryover',state,decisions=[{'task_id':old['id'],'action':'defer'}])
        assert response.status_code==409 and response.json()['code']=='week_stale'
        assert read(client)['planner']['week_candidate']==before

def test_ready_week_revision_is_not_generated_twice():
    clock=Clock()
    initial=week_draft([assignment()])
    future=lambda ctx:week_draft([task('new','Add validation',240)],carryover=[{'task_id':ctx['progress']['unfinished'][0]['task_id'],'action':'carry','reason':'Continue.'}])
    revision=week_draft([task('revised','Write request validation',240)])
    model=Scripted([long_draft()],weeks=[initial,future,revision])
    with client_for(model,clock=clock) as client:
        state=accepted(client);clock.now=SUNDAY
        state=accept_week(client,plan_week(client,read(client),'2030-01-14'))
        state=plan_week(client,state,'2030-01-14',revision=True)
        assert state['planner']['week_candidate'] is not None,state['operation']
        count=len(model.sent('WeekDraft'))
        response=request(client,'/weeks/generate',state,week_start='2030-01-14',revision=True)
        assert response.status_code==409 and response.json()['code']=='week_preview_exists'
        assert len(model.sent('WeekDraft'))==count

def test_accepted_future_week_is_marked_for_review_when_its_objective_changes():
    import copy
    clock=Clock()
    change={'week_start':'2030-01-21','objective':'Review validation errors','expected_outcome':'Invalid inputs covered','estimated_minutes':220,'milestone_key':'m1','gap_ids':['python'],'reason':'Adapt to progress.'}
    next_week=lambda ctx:week_draft([task('new','Add validation',240)],carryover=[{'task_id':ctx['progress']['unfinished'][0]['task_id'],'action':'carry','reason':'Continue.'}],objective_changes=[change])
    model=Scripted([long_draft()],weeks=[week_draft([assignment()]),next_week])
    with client_for(model,clock=clock) as client:
        state=accepted(client)
        # A future accepted week from an earlier planning cycle; only its objective is revised.
        store=client.app.state.store
        block=copy.deepcopy(store.data[OWNER]['planner']['week_blocks'][0])
        block.update(id='future-week',week_start='2030-01-21',start_date='2030-01-21',end_exclusive='2030-01-28',task_ids=[])
        store.data[OWNER]['planner']['week_blocks'].append(block)
        clock.now=SUNDAY
        state=accept_week(client,plan_week(client,read(client),'2030-01-14'))
        future=next(b for b in state['planner']['week_blocks'] if b['id']=='future-week')
        assert future['needs_review'] is True
        assert state['planner']['outline_active']['weeks'][2]['objective']==change['objective']

def test_availability_change_during_final_acceptance_fence_prevents_publication():
    class ChangingSources(Sources):
        arm=False
        calls=0
        async def account(self,token):
            if self.arm:
                self.calls+=1
                if self.calls==2:self.periods=[{'start_date':'2030-01-09','end_date':'2030-01-27','weekly_hours':0}]
            return await super().account(token)
    sources=ChangingSources()
    with client_for(Scripted([long_draft()]),sources) as client:
        state=generate(client,configure(client))
        sources.arm=True
        response=request(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='inputs_changed'
        assert read(client)['planner']['active'] is None

def test_moving_an_anytime_task_releases_its_old_effort_reservation_once():
    model=Scripted([draft()])
    with client_for(model) as client:
        state=accepted(client)
        state=post(client,'/sessions/add',state,session={'title':'Review responses','date':'2030-01-14','duration_minutes':60,'skills':[]})
        own=next(t for t in state['planner']['active']['editable_tasks'] if t['origin']=='user')
        state=post(client,'/sessions/move',state,moves=[{'session_id':own['id'],'date':'2030-01-14','start_time':'19:00'}])
        moved=next(t for t in state['planner']['active']['editable_tasks'] if t['id']==own['id'])
        assert moved['estimated_minutes']==60 and moved['anytime_date'] is None

def test_a_changed_week_start_requires_a_matching_weekly_outline():
    with client_for(Scripted([long_draft()])) as client:
        state=accepted(client)
        config={**state['planner']['config'],'week_start_day':6}
        state=post(client,'/config',state,config=config)
        response=request(client,'/weeks/generate',state,week_start='2030-01-13')
        assert response.status_code==409 and response.json()['code']=='settings_changed'
