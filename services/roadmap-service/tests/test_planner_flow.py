"""Configure, generate, review and revise through the HTTP API, with scripted model output."""
import copy
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from planner_fixtures import NOW, OWNER, Staged, assessment, assignment, draft, gap, milestone, second_week, settings
from app.main import create_app

H={'Authorization':'Bearer synthetic'}
class Sources:
    def __init__(self):self.owner=OWNER;self.hash='hash1';self.ready=True;self.result=assessment();self.writes=[];self.reads=[]
    async def account(self,token):return {'id':self.owner,'token':token,'profile':{'version':1,'weekly_hours':6,'application_date':None,'availability_periods':[]}}
    async def read(self,service,path,token,params=None):
        self.reads.append(path)
        if path.endswith('/context'):
            return {'ready':self.ready,'issues':[] if self.ready else [{'source':'cv','message':'Select a CV.','href':'/cv'}],'input_hash':self.hash,'research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job','job_dates':[]},'cv':{'id':'cv1','name':'synthetic.docx'},'evidence':assessment()['evidence']}
        if path.endswith('/operation'):return {'operation':{'status':'succeeded'},'result':self.result,'retry_request':None}
        return {'version':0,'ready':self.ready,'result':self.result,'stale':False,'operation':None}
    async def write(self,service,path,token,body):
        self.writes.append(path);self.result=assessment(self.hash);return {'version':1}
Scripted=Staged
def client_for(model,sources=None,clock=None):
    return TestClient(create_app(MemoryStore(),sources or Sources(),model,clock=clock or (lambda:NOW)))
def read(client):
    response=client.get('/api/v1/roadmaps/workspace',headers=H);assert response.status_code==200,response.text
    return response.json()
def finish(client):
    for _ in range(300):
        state=read(client)
        if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
        time.sleep(.01)
    raise AssertionError('operation did not finish')
def post(client,path,state,**body):
    response=client.post('/api/v1/roadmaps/planner'+path,headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),**body})
    assert response.status_code==200,response.text
    return response.json()
def configure(client,state=None,**changes):
    return post(client,'/config',state or read(client),config=settings(**changes))
def generate(client,state,allow_partial=False):
    response=client.post('/api/v1/roadmaps/planner/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'allow_partial_assessment':allow_partial})
    assert response.status_code==202,response.text
    time.sleep(.01)
    return finish(client)
def chat(client,state,message):
    body={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':message,'allow_partial_assessment':False}
    response=client.post('/api/v1/roadmaps/messages',headers=H,json=body);assert response.status_code==202,response.text
    return finish(client)
def accepted(client):
    state=generate(client,configure(client));assert state['operation']['status']=='succeeded',state['operation']
    return post(client,'/accept',state)

def test_runway_is_shown_before_any_model_call_and_generation_is_gated():
    model=Scripted()
    with client_for(model) as client:
        state=read(client)
        assert state['planner']['config_saved'] is False and not state['planner']['runway']['can_generate']
        assert {i['code'] for i in state['planner']['runway']['issues']}>={'missing_target','no_budget','no_blocks'}
        response=client.post('/api/v1/roadmaps/planner/runway',headers=H,json={'config':settings()})
        assert response.status_code==200 and response.json()['study']=={'preferred_minutes':690,'backup_extra_minutes':120,'usable_minutes':690}
        response=client.post('/api/v1/roadmaps/planner/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
        assert response.status_code==409 and response.json()['code']=='generation_blocked'
        assert model.contexts==[]

def test_unsaved_settings_use_the_device_time_zone_until_saved():
    with client_for(Scripted()) as client:
        zone=client.get('/api/v1/roadmaps/workspace',headers=H,params={'time_zone':'Europe/London'}).json()['planner']
        assert zone['config']['time_zone']=='Europe/London' and zone['config_saved'] is False
        invalid=client.get('/api/v1/roadmaps/workspace',headers=H,params={'time_zone':'Mars/Olympus'})
        assert invalid.status_code==200 and invalid.json()['planner']['config']['time_zone']=='Asia/Singapore'
        state=configure(client,time_zone='Asia/Tokyo')
        saved=client.get('/api/v1/roadmaps/workspace',headers=H,params={'time_zone':'Europe/London'}).json()['planner']
        assert saved['config']['time_zone']=='Asia/Tokyo'

def test_missing_goal_or_cv_blocks_generation():
    sources=Sources();sources.ready=False;model=Scripted()
    with client_for(model,sources) as client:
        state=configure(client)
        response=client.post('/api/v1/roadmaps/planner/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
        assert response.status_code==409 and response.json()['code']=='inputs_missing' and model.contexts==[]

def test_the_panel_shows_the_goal_and_skills_passed_to_the_model():
    model=Scripted([draft()])
    with client_for(model) as client:
        state=read(client);inputs=state['planner']['inputs']
        assert inputs['goal']['role']=='Developer' and inputs['skills'][0]['name']=='Git' and inputs['experience'][0]['name']=='Synthetic API'
        assert inputs['skill_groups']['Git'] and 'evidence' not in state['context']
        generate(client,configure(client))
        sent=model.contexts[0]
        assert sent['goal']['role']=='Developer' and set(sent['assessment']['evidence'])=={i['ref'] for i in [*inputs['skills'],*inputs['experience']]}
        assert model.tokens[0]>8192

def test_generation_sends_settings_and_windows_for_the_partial_first_week_and_blackout():
    model=Scripted([draft()])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        sent=model.contexts[0]
        assert sent['stage']=='outline' and 'windows' not in sent
        # Monday and Tuesday have passed, Saturday is a blackout, backup is disabled and 20% is reserved.
        assert [w['planned_minutes'] for w in sent['planned_capacity']]==[72,240,240]
        detail=model.contexts[1]
        assert detail['stage']=='detail' and detail['requested_weeks']==['2030-01-07','2030-01-14'] and detail['week_budgets']=={'2030-01-07':72,'2030-01-14':240}
        assert detail['windows'][0]=={'date':'2030-01-09','start_time':'19:00','end_time':'20:30','kind':'preferred','minutes':90}
        assert state['planner']['candidate'] and not state['planner']['active']
        session=state['planner']['candidate']['assignments'][0]
        assert (session['date'],session['start_time'],session['duration_minutes'],session['milestone_key'])==('2030-01-09','19:00',60,'m1')
        review=state['planner']['candidate_review']
        assert review['next_assignment_id']==session['id'] and review['remaining']['calendar']['label']=='2 weeks, 5 days'

def test_backup_windows_are_only_offered_and_accepted_when_enabled():
    using_backup=draft(assignments=[assignment('a1',duration_minutes=90),assignment('a2',date='2030-01-13',start_time='09:00'),second_week('a3')])
    model=Scripted([using_backup])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['error']['code']=='plan_validation' and 'backup' in state['operation']['error']['detail']
    model=Scripted([using_backup])
    with client_for(model) as client:
        state=generate(client,configure(client,use_backup=True))
        assert state['operation']['status']=='succeeded',state['operation']
        assert [w['kind'] for w in model.contexts[1]['windows'] if w['date']<'2030-01-14']==['preferred','backup']
        assert [w['planned_minutes'] for w in model.contexts[0]['planned_capacity']]==[168,240,240]

def test_insufficient_runway_retries_with_errors_then_reports_what_remains():
    overcommitted=draft(milestones=[milestone(estimated_minutes=5000,projected_end='2030-01-27')])
    honest=draft(milestones=[milestone(estimated_minutes=500,projected_end='2030-01-27')],
        beyond_deadline=[{'title':'Advanced Python','gap_ids':['python'],'reason':'Needs more time than the runway allows.','estimated_minutes':4500}],
        deadline_outcome={'summary':'By the target you can show a basic API, but not advanced Python.','achievable_by_target':['A basic API'],'fits_in_runway':False})
    model=Scripted([overcommitted,honest])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        assert len(model.contexts)==3 and 'validation_errors' not in model.contexts[0]
        retry=model.contexts[1]
        assert retry['attempt']==2 and 'milestone_capacity_exceeded' in {e['code'] for e in retry['validation_errors']}
        assert any('5000 minutes' in e['message'] for e in retry['validation_errors']) and retry['previous_output']['milestones'][0]['estimated_minutes']==5000
        candidate=state['planner']['candidate']
        assert candidate['deferred_scope'][0]['title']=='Advanced Python' and candidate['deadline_outcome']['fits_in_runway'] is False
        assert candidate['generation']['attempts']==3

def test_retries_are_bounded_and_the_last_valid_plan_is_preserved():
    bad=draft(assignments=[assignment(date='2030-01-12',start_time='10:00'),second_week()])
    model=Scripted([draft(),bad])
    with client_for(model) as client:
        state=accepted(client);active=state['planner']['active']
        state=generate(client,state)
        assert len(model.contexts)==6 and state['operation']['status']=='failed' and state['operation']['error']['code']=='plan_validation'
        assert 'blackout' in state['operation']['error']['detail']
        assert state['planner']['active']==active and state['planner']['candidate'] is None
        assert state['planner']['retry_generate']['mutation_id']==state['operation']['id'] and state['retry_request'] is None

def test_provider_failure_keeps_an_earlier_preview_and_settings():
    model=Scripted([draft(),Problem('Provider unavailable.',503,'model_provider')])
    with client_for(model) as client:
        state=generate(client,configure(client));candidate=state['planner']['candidate']
        state=generate(client,state)
        assert state['operation']['error']['code']=='model_provider'
        assert state['planner']['candidate']==candidate and state['planner']['config']['weekly_minutes']==300

def test_failed_generation_retry_reuses_its_identity_and_replay_is_idempotent():
    model=Scripted([Problem('Provider unavailable.',503,'model_provider'),draft()])
    with client_for(model) as client:
        state=generate(client,configure(client))
        body=state['planner']['retry_generate']
        assert client.post('/api/v1/roadmaps/planner/generate',headers=H,json=body).status_code==202
        state=finish(client);time.sleep(.01);state=finish(client)
        assert state['operation']['status']=='succeeded' and state['planner']['candidate']
        assert client.post('/api/v1/roadmaps/planner/generate',headers=H,json=body).status_code==202
        assert model.schemas==['PlanOutline','PlanOutline','WindowDetail']

def test_assessment_runs_before_planning_when_none_is_current():
    sources=Sources();sources.result=None;model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
        assert sources.writes==['/api/v1/assessments'] and state['planner']['candidate']['assessment_id']=='assessment1'
        assert state['operation']['status']=='succeeded',state['operation']

def test_accept_requires_a_current_preview_and_snapshots_the_plan():
    sources=Sources();model=Scripted([draft(),draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
        changed=configure(client,state,weekly_minutes=240)
        response=client.post('/api/v1/roadmaps/planner/accept',headers=H,json={'expected_version':changed['version'],'mutation_id':str(uuid4())})
        assert response.status_code==409 and response.json()['code']=='settings_changed'
        assert {b['code'] for b in changed['planner']['candidate_blockers']}=={'settings_changed'}
        state=configure(client,changed)
        sources.hash='hash2'
        response=client.post('/api/v1/roadmaps/planner/accept',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
        assert response.status_code==409 and response.json()['code']=='inputs_changed'
        sources.hash='hash1'
        body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        response=client.post('/api/v1/roadmaps/planner/accept',headers=H,json=body);assert response.status_code==200,response.text
        state=response.json();plan=state['planner']['active'];assert plan and state['planner']['candidate'] is None
        assert client.post('/api/v1/roadmaps/planner/accept',headers=H,json=body).json()['planner']['active']['id']==plan['id']
        history=client.get('/api/v1/roadmaps/history/'+plan['id'],headers=H);assert history.status_code==200 and history.json()['schema_version']=='roadmap-v3'
        sources.owner='22222222-2222-4222-8222-222222222222'
        assert client.get('/api/v1/roadmaps/history/'+plan['id'],headers=H).status_code==404
        assert read(client)['planner']['active'] is None

def test_preview_expires_once_a_session_has_passed():
    moments=[NOW];model=Scripted([draft()])
    with client_for(model,clock=lambda:moments[0]) as client:
        state=generate(client,configure(client))
        moments[0]=NOW.replace(hour=12)  # 20:00 in Singapore, after the 19:00 session.
        state=read(client)
        assert 'plan_expired' in {b['code'] for b in state['planner']['candidate_blockers']}
        response=client.post('/api/v1/roadmaps/planner/accept',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
        assert response.status_code==409 and response.json()['code']=='plan_expired'

def test_new_roadmap_after_completion_stays_a_preview_and_archives_completed_work():
    sources=Sources()
    revised=draft(summary='Moved to Thursday evenings.',milestones=[milestone(estimated_minutes=120)],assignments=[assignment('a2',date='2030-01-10',start_time='18:00',duration_minutes=45,task='Write a second tested endpoint.'),second_week('a4',start_time='18:00')])
    model=Scripted([draft(assignments=[assignment('a1'),second_week('a3',task='Document the endpoint.')]),revised])
    with client_for(model,sources) as client:
        state=accepted(client);session=state['planner']['active']['assignments'][0]
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed',evidence_note='Endpoint test passed.')
        done=state['planner']['active']['assignments'][0]
        assert done['status']=='completed' and done['evidence_note']=='Endpoint test passed.'
        active_before=copy.deepcopy(state['planner']['active'])
        blocks=[{'day':3,'start_time':'18:00','duration_minutes':60,'kind':'preferred'},{'day':0,'start_time':'18:00','duration_minutes':120,'kind':'preferred'}]
        state=configure(client,state,blocks=blocks,blackouts=[])
        assert 'settings' in {s['kind'] for s in state['planner']['signals']}
        assert state['planner']['active']==active_before
        state=generate(client,state)
        assert state['operation']['status']=='succeeded',state['operation']
        sent=model.contexts[-1]
        assert sent['prior_completed_work'][0]['task']==done['task'] and sent['prior_completed_work'][0]['note']=='Endpoint test passed.' and sent['prior_completed_work'][0]['skills']==['Python']
        assert model.contexts[-2]['stage']=='outline' and sent['windows'][0]['date']=='2030-01-10'
        assert state['planner']['active']==active_before
        preview=state['planner']['candidate']
        assert [a['key'] for a in preview['assignments']]==['a2','a4']
        assert preview['changes']['assignments_removed'] and preview['changes']['assignments_added']
        state=post(client,'/accept',state)
        active=state['planner']['active']
        assert active['summary']=='Moved to Thursday evenings.' and active['accepted_at']
        archive=state['planner']['archived'][0]
        assert archive['completed_minutes']==60 and archive['tasks_completed']==1
        kept=client.get('/api/v1/roadmaps/history/'+archive['id'],headers=H).json()
        assert kept['source_plan_id']==active_before['id'] and kept['assignments'][0]==done
        assert sources.writes==[]

def test_completing_a_session_invalidates_an_older_preview():
    model=Scripted([draft(),draft(assignments=[assignment('a9',start_time='19:30'),second_week('a8')])])
    with client_for(model) as client:
        state=accepted(client);session=state['planner']['active']['assignments'][0]
        state=generate(client,state);assert state['planner']['candidate']
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        assert {b['code'] for b in state['planner']['candidate_blockers']}=={'active_changed'}

def test_session_completion_and_recorded_outcomes_stay_separate_from_proficiency():
    sources=Sources();model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=accepted(client);plan=state['planner']['active'];session=plan['assignments'][0]
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        milestone_view=state['planner']['active_review']['milestones']['m1']
        assert milestone_view['sessions_completed']==1 and state['planner']['active']['milestones'][0]['outcome']['demonstrated'] is False
        response=client.post('/api/v1/roadmaps/planner/milestones/outcome',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'milestone_id':'m1','demonstrated':True})
        assert response.status_code==422
        state=post(client,'/milestones/outcome',state,milestone_id='m1',demonstrated=True,note='Showed the API to a mentor.')
        outcome=state['planner']['active']['milestones'][0]['outcome']
        assert outcome['demonstrated'] and outcome['source']=='self_reported'
        assert state['assessment']['job_skill_gaps'][0]['match_status']=='confirmed_shortfall'
        assert sources.writes==[]
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='scheduled')
        reopened=state['planner']['active']['assignments'][0]
        assert reopened['status']=='scheduled' and reopened['completed_at'] is None and reopened['history'][0]['to']=='completed'

def test_confirmation_answers_are_self_reported_and_prompt_a_revision():
    question=gap('sql',name='SQL',requirement_ref='job:sql',status='unknown',resolution='confirm_experience',confirmation_question='Have you written SQL joins?')
    model=Scripted([draft(gaps=[gap(),question]),draft(gaps=[gap(),{**question,'plan_impact':'minor'}])])
    with client_for(model) as client:
        state=generate(client,configure(client))
        state=post(client,'/confirmations',state,gap_id='sql',answer='some_experience',note='Basic joins only.')
        assert state['planner']['confirmations']['sql']['source']=='self_reported'
        assert 'evidence' in {s['kind'] for s in state['planner']['signals']}
        state=generate(client,state)
        assert model.contexts[-1]['confirmations']['sql']['answer']=='some_experience'
        assert state['operation']['status']=='succeeded',state['operation']
        assert not state['planner']['signals']

def test_changed_evidence_prompts_a_revision():
    sources=Sources();model=Scripted([draft()])
    with client_for(model,sources) as client:
        accepted(client);sources.hash='hash2'
        assert 'evidence' in {s['kind'] for s in read(client)['planner']['signals']}

def test_a_missed_session_moves_automatically_on_the_next_access():
    moments=[NOW]
    model=Scripted([draft()])
    with client_for(model,clock=lambda:moments[0]) as client:
        state=accepted(client);session=state['planner']['active']['assignments'][0]
        moments[0]=NOW.replace(day=11)  # Friday; Wednesday's session was missed.
        state=read(client)
        moved=next(a for a in state['planner']['active']['assignments'] if a['id']==session['id'])
        assert moved['auto_moves']==1 and moved['status']=='scheduled' and moved['date']>'2030-01-11'
        assert state['planner']['active_view']['coach']['recent_moves'][0]['task_id']==session['id']

def test_chat_collects_settings_without_generating_a_plan():
    patch={'target_date':'2030-01-27','weekly_minutes':300,'blocks':settings()['blocks'],'blackouts':[{'frequency':'once','start_date':'2030-01-12'}]}
    model=Scripted(chats=[{'reply':'Saved those. Please review the panel.','settings':patch}])
    with client_for(model) as client:
        state=chat(client,read(client),'Study until 27 Jan, five hours a week.')
        assert state['operation']['status']=='succeeded',state['operation']
        planner=state['planner']
        assert planner['config']['weekly_minutes']==300 and planner['config']['start_date']=='2030-01-09'
        assert planner['runway']['can_generate'] and planner['candidate'] is None
        assert state['messages'][-1]['content']=='Saved those. Please review the panel.'
        assert len(model.contexts)==1 and model.contexts[0]['settings']['weekly_minutes'] is None

def test_invalid_chat_settings_change_nothing_and_are_explained():
    model=Scripted(chats=[{'reply':'Added your late block.','settings':{'blocks':[{'day':0,'start_time':'23:30','duration_minutes':60,'kind':'preferred'}]}}])
    with client_for(model) as client:
        state=configure(client)
        before=state['planner']['config']
        state=chat(client,state,'Add Monday at 23:30 for an hour.')
        assert state['operation']['status']=='succeeded' and state['planner']['config']==before
        assert 'unchanged' in state['messages'][-1]['content']

def test_chat_saves_a_recurring_blackout_and_the_runway_reflects_it():
    rule={'frequency':'weekly','start_date':'2030-01-09','weekdays':[2],'start_time':None,'end_time':None}
    model=Scripted(chats=[{'reply':'Wednesdays are blocked out.','settings':{'blackouts':[rule]}}])
    with client_for(model) as client:
        state=configure(client,blackouts=[])
        before=state['planner']['runway']['study']['usable_minutes']
        state=chat(client,state,'I can never study on Wednesdays.')
        assert state['operation']['status']=='succeeded',state['operation']
        saved=state['planner']['config']['blackouts']
        assert [(r['frequency'],r['weekdays'],r['interval']) for r in saved]==[('weekly',[2],1)]
        assert state['planner']['runway']['study']['usable_minutes']<before

def test_chat_blackout_that_cannot_apply_changes_nothing_and_is_explained():
    rule={'frequency':'weekly','start_date':'2030-01-09','weekdays':[]}
    model=Scripted(chats=[{'reply':'Done.','settings':{'blackouts':[rule]}}])
    with client_for(model) as client:
        state=configure(client)
        before=state['planner']['config']
        state=chat(client,state,'Block out some weeks.')
        assert state['operation']['status']=='succeeded' and state['planner']['config']==before
        assert 'unchanged' in state['messages'][-1]['content']

def test_a_plan_saved_with_blackout_dates_is_not_reported_as_changed_settings():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client)
        store=client.app.state.store;row=store.load(OWNER)
        for section in (row['planner'],row['planner']['active']):
            config=section['config']
            config['blackout_dates']=[rule['start_date'] for rule in config.pop('blackouts')]
        store.cas(OWNER,row['version'],row)
        state=read(client)
        assert state['planner']['config']['blackouts'][0]['start_date']=='2030-01-12'
        assert 'settings' not in {s['kind'] for s in state['planner']['signals']}

def test_chat_edits_prepare_a_preview_and_leave_the_active_plan_alone():
    edit={'reply':'I prepared a preview that moves the work to Thursday.','settings':{'blocks':[{'day':3,'start_time':'18:00','duration_minutes':60,'kind':'preferred'}]},'revision_instruction':'Move this week to Thursday evening.'}
    model=Scripted([draft()],[edit],revisions=[{'message':'Moved to Thursday evening.','assignments':[assignment('a2',date='2030-01-10',start_time='18:00',duration_minutes=45)]}])
    with client_for(model) as client:
        state=accepted(client);active=state['planner']['active']
        state=chat(client,state,'Can we move it to Thursday evening?')
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['active']==active and state['planner']['candidate'] is None
        proposal=state['planner']['proposal']
        assert proposal['kind']=='revision' and proposal['message']=='Moved to Thursday evening.' and proposal['patch']['config']['blocks'][0]['day']==3
        assert model.contexts[-1]['instruction']=='Move this week to Thursday evening.'
        assert state['planner']['config']['blocks'][0]['day']!=3
        assert state['messages'][-1]['role']=='assistant'
        state=post(client,'/proposals/accept',state,proposal_id=proposal['id'],keep_task_ids=[])
        assert state['planner']['config']['blocks'][0]['day']==3 and state['planner']['active']['config']['blocks'][0]['day']==3
        assert any(a['key']=='a2' and a['date']=='2030-01-10' for a in state['planner']['active']['assignments'])

def test_a_chat_edit_that_fails_validation_keeps_settings_and_preview():
    edit={'reply':'Preparing that.','settings':{'weekly_minutes':30},'revision_instruction':'Reduce the weekly budget.'}
    bad={'message':'Too much.','assignments':[assignment('a5',start_time='19:00',duration_minutes=90)]}
    model=Scripted([draft()],[edit],revisions=[bad,bad,bad])
    with client_for(model) as client:
        state=accepted(client);config=state['planner']['config'];active=state['planner']['active']
        state=chat(client,state,'Reduce to thirty minutes.')
        assert state['operation']['status']=='failed' and state['planner']['config']==config and state['planner']['proposal'] is None and state['planner']['active']==active
        assert state['retry_request'] and state['planner']['retry_generate'] is None

def test_writes_are_rejected_for_stale_versions_and_other_operations():
    with client_for(Scripted()) as client:
        state=configure(client)
        response=client.post('/api/v1/roadmaps/planner/config',headers=H,json={'expected_version':state['version']-1,'mutation_id':str(uuid4()),'config':settings()})
        assert response.status_code==409
        response=client.post('/api/v1/roadmaps/planner/config',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'config':{**settings(),'time_zone':'Mars/Olympus'}})
        assert response.status_code==422

def test_saved_roadmap_stays_readable_and_progress_records_during_a_source_outage():
    class Unavailable(Sources):
        unavailable=False
        async def read(self,service,path,token,params=None):
            if self.unavailable and path.endswith('/context'):raise Problem('Source temporarily unavailable.',503,'upstream')
            return await super().read(service,path,token,params)
    sources=Unavailable();model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=accepted(client);session=state['planner']['active']['assignments'][0]
        sources.unavailable=True
        state=read(client)
        assert state['context']['availability']=='unavailable' and state['planner']['active']
        state=post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        assert state['planner']['active']['assignments'][0]['status']=='completed'
        response=client.post('/api/v1/roadmaps/messages',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Plan more.','allow_partial_assessment':False})
        assert response.status_code==503

def test_owner_isolation_for_settings_and_plans():
    sources=Sources();model=Scripted([draft()])
    with client_for(model,sources) as client:
        accepted(client)
        sources.owner='22222222-2222-4222-8222-222222222222'
        other=read(client)
        assert other['planner']['active'] is None and other['planner']['config_saved'] is False
        assert other['version']==0
