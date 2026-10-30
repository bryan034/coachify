import copy
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore,Problem,begin
from app.main import create_app
from app.schemas import AdviserReply,Preferences,Message
from app.scheduler import schedule,review_saved
from app.adviser import propose

OWNER='11111111-1111-4111-8111-111111111111';H={'Authorization':'Bearer synthetic'}
def task(key='task1',minutes=180,prerequisites=None):
    return {'id':key,'title':'Explain your project','instructions':'Explain your synthetic project decisions.','completion_outcome':'Write two trade-offs.',
        'estimated_minutes':minutes,'rationale':'Practise communicating your experience.','requirement_refs':['job:python'],
        'prerequisites':prerequisites or [],'milestone':'Explain your work','splittable':True,'status':'not_started'}
def prefs():return Preferences(start_date='2030-01-07',target_date='2030-01-21',weekly_minutes=180,days=[{'day':0,'minutes':60},{'day':5,'minutes':120}],max_session_minutes=60).model_dump(mode='json')
def assessment():
    return {'id':'assessment1','input_hash':'hash1','role':'Developer','target_type':'specific_job','research_coverage':'no_findings',
        'job_skill_gaps':[{'ref':'job:python','name':'Python','match_status':'uncertain','components':[{'dimension':'independence','status':'uncertain','explanation':'Independence unknown.','evidence_refs':['cv:a']}]}],
        'interview_prep_gaps':[],'constraints':[],'groups':[],'priorities':[],'evidence':{'cv:a':{'text':'Declared project use.'}}}
class Sources:
    def __init__(self):self.owner=OWNER;self.hash='hash1'
    async def account(self,token):return {'id':self.owner,'token':token,'profile':{'version':1,'weekly_hours':3,'availability_periods':[]}}
    async def read(self,service,path,token,params=None):
        if path.endswith('/context'):return {'ready':True,'issues':[],'input_hash':self.hash,'research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job','job_dates':[]},'cv':{'id':'cv1','name':'synthetic.docx'}}
        return {'version':0,'ready':True,'result':assessment(),'stale':False,'operation':None}
class Adviser:
    configured=True
    def __init__(self):self.calls=0;self.fail=False
    async def generate(self,schema,instructions,context):
        self.calls+=1
        if self.fail:raise Problem('Try again.',503,'model_provider')
        definition=task();definition.pop('status')
        if context.get('current_plan') and context['current_plan']['tasks']:definition['id']=context['current_plan']['tasks'][0]['id']
        return AdviserReply(reply='We could practise explaining your project on your chosen days. You can change this proposal.',
            preferences={'start_date':'2030-01-07','target_date':'2030-01-21','weekly_minutes':180,'days':[{'day':0,'minutes':60},{'day':5,'minutes':120}]},task_changes=[definition])
def finish(client):
    for _ in range(100):
        response=client.get('/api/v1/roadmaps/workspace',headers=H);assert response.status_code==200,response.text
        state=response.json()
        if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
        time.sleep(.01)
    raise AssertionError('operation did not finish')
def send(client,version=0):
    body={'expected_version':version,'mutation_id':str(uuid4()),'message':'I can do three hours on Mondays and Saturdays. Propose activities.','allow_partial_assessment':False}
    assert client.post('/api/v1/roadmaps/messages',json=body,headers=H).status_code==202
    return body,finish(client)
def change(client,path,state,**body):
    payload={'expected_version':state['version'],'mutation_id':str(uuid4()),**body}
    response=client.post('/api/v1/roadmaps'+path,json=payload,headers=H)
    assert response.status_code==200,response.text
    return payload,response.json()

def test_selected_days_effort_conservation_and_prerequisite_order():
    result=schedule([task('a',150),task('b',60,['a'])],prefs())
    assert result['status']=='feasible'
    assert sum(a['minutes'] for a in result['allocations'] if a['task_id']=='a')==150
    from datetime import date
    assert all(date.fromisoformat(a['date']).weekday() in (0,5) for a in result['allocations'])
    positions={key:[i for i,a in enumerate(result['allocations']) if a['task_id']==key] for key in ('a','b')}
    assert max(positions['a'])<min(positions['b'])
    for day,cap in result['daily_capacity'].items():assert sum(a['minutes'] for a in result['allocations'] if a['date']==day)<=cap

def test_missing_preferences_zero_capacity_cycles_and_independent_work():
    assert schedule([task()],Preferences().model_dump(mode='json'))['status']=='needs_preferences'
    result=schedule([task()],{**prefs(),'weekly_minutes':0,'days':[{'day':0,'minutes':0}]})
    assert result['status']=='partial' and result['remainders']['task1']==180
    result=schedule([task('a',30,['b']),task('b',30,['a']),task('c',30)],prefs())
    assert result['remainders']['a']==30 and result['remainders']['b']==30
    assert any(a['task_id']=='c' for a in result['allocations'])

def test_reduced_periods_and_unsplittable_work():
    result=schedule([task(minutes=500)],{**prefs(),'reduced_periods':[{'start_date':'2030-01-07','end_date':'2030-01-13','weekly_hours':1.5}]})
    assert sum(a['minutes'] for a in result['allocations'] if a['date']<'2030-01-14')<=90
    t=task(minutes=90);t['splittable']=False
    assert schedule([t],prefs())['remainders']['task1']==90

def test_proposal_activation_resume_idempotency_and_owner_isolation():
    store=MemoryStore();source=Sources();model=Adviser()
    with TestClient(create_app(store,source,model)) as client:
        assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['active'] is None
        body,state=send(client);assert state['active'] is None and state['draft']['schedule']['status']=='feasible'
        client.post('/api/v1/roadmaps/messages',json=body,headers=H);assert model.calls==1
        activation,state=change(client,'/activate',state);identifier=state['active']['id'];assert state['draft'] is None
        assert client.post('/api/v1/roadmaps/activate',json=activation,headers=H).json()['active']['id']==identifier
        assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['messages']==state['messages']
        assert client.get('/api/v1/roadmaps/history/'+identifier,headers=H).status_code==200
        source.owner='other-owner'
        assert client.get('/api/v1/roadmaps/history/'+identifier,headers=H).status_code==404
        assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['messages']==[]

def test_completion_definition_changes_and_reopening_keep_saved_timing_and_history():
    with TestClient(create_app(MemoryStore(),Sources(),Adviser())) as client:
        _,state=send(client);_,state=change(client,'/activate',state);key=state['active']['tasks'][0]['id'];allocations=state['active']['schedule']['allocations']
        _,state=change(client,'/tasks/status',state,task_id=key,status='completed')
        completed=state['active']['tasks'][0];assert completed['completed_at'] and state['active']['schedule']['remaining_minutes']==0
        definition={k:completed[k] for k in task() if k!='status'};definition['completion_outcome']='Write three additional trade-offs.'
        _,state=change(client,'/tasks',state,task=definition)
        updated=state['active']['tasks'][0];assert updated['status']=='completed' and updated['definition_review_required']
        assert state['active']['schedule']['allocations']==allocations
        assert updated['history'][0]['definition']['completion_outcome']!='Write three additional trade-offs.'
        _,state=change(client,'/tasks/status',state,task_id=key,status='not_started')
        assert state['active']['schedule']['remaining_minutes']==180
        _,state=change(client,'/tasks/status',state,task_id=key,status='completed')
        assert not state['active']['tasks'][0]['definition_review_required']

def test_editing_effort_exposes_conflict_without_rescheduling():
    tasks=[task()];plan={'tasks':tasks,'schedule':schedule(tasks,prefs())};allocations=copy.deepcopy(plan['schedule']['allocations']);tasks[0]['estimated_minutes']=15
    reviewed=review_saved(plan)
    assert reviewed['allocations']==allocations and any('exceed' in issue for issue in reviewed['issues'])

def test_failed_message_retry_does_not_duplicate_user_entry():
    model=Adviser();model.fail=True
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        body,state=send(client);assert state['operation']['status']=='failed' and len(state['messages'])==1
        model.fail=False;client.post('/api/v1/roadmaps/messages',json=body,headers=H);state=finish(client)
        assert state['operation']['status']=='succeeded' and len(state['messages'])==2

def test_stale_proposal_cannot_overwrite_new_completion_or_changed_sources():
    source=Sources()
    with TestClient(create_app(MemoryStore(),source,Adviser())) as client:
        _,state=send(client);_,state=change(client,'/activate',state)
        _,state=send(client,state['version']);assert state['draft']
        old=state['version'];key=state['active']['tasks'][0]['id'];_,state=change(client,'/tasks/status',state,task_id=key,status='completed')
        assert client.post('/api/v1/roadmaps/activate',json={'expected_version':state['version'],'mutation_id':str(uuid4())},headers=H).status_code==409
        assert client.post('/api/v1/roadmaps/tasks/status',json={'expected_version':old,'mutation_id':str(uuid4()),'task_id':key,'status':'not_started'},headers=H).status_code==409
        source.hash='new';assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['stale']

def test_removal_needs_explicit_quote_and_restart_recovers_pending_message():
    definition={k:v for k,v in task().items() if k!='status'}
    plan=propose({'preferences':prefs()},AdviserReply(reply='Proposal.',task_changes=[definition]),assessment(),'Plan something.','op')
    output=AdviserReply(reply='Remove.',remove_tasks=[{'task_id':plan['tasks'][0]['id'],'reason':'Unwanted','quote':'Remove this task'}])
    with pytest.raises(Problem):propose({'draft':plan},output,assessment(),'Hello','op2')
    store=MemoryStore();begin(store,OWNER,Message(expected_version=0,mutation_id=uuid4(),message='Plan my week.'),'message')
    with TestClient(create_app(store,Sources(),Adviser())) as client:
        state=finish(client);assert state['operation']['status']=='succeeded' and len(state['messages'])==2


def test_provider_retry_delay_is_persisted_and_new_messages_cannot_bypass_it():
    class Quota(Adviser):
        async def generate(self,*args):
            self.calls+=1
            raise Problem('Provider capacity.',429,'model_quota',30)
    model=Quota()
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        _,state=send(client)
        assert 0<state['operation']['retry_after']<=30
        response=client.post('/api/v1/roadmaps/messages',json={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Another request.','allow_partial_assessment':False},headers=H)
        assert response.status_code==429 and model.calls==1


def test_reviewed_chat_and_availability_revisions_apply_without_losing_completed_work():
    with TestClient(create_app(MemoryStore(),Sources(),Adviser())) as client:
        _,state=send(client);_,state=change(client,'/activate',state)
        key=state['active']['tasks'][0]['id']
        _,state=change(client,'/tasks/status',state,task_id=key,status='completed')
        _,state=send(client,state['version'])
        assert state['draft']['base_active_id']==state['active']['id']
        _,state=change(client,'/activate',state)
        assert len(state['active']['tasks'])==1 and state['active']['tasks'][0]['status']=='completed'
        preferences={**state['active']['preferences'],'weekly_minutes':240}
        _,state=change(client,'/preferences',state,preferences=preferences)
        assert state['draft']['base_active_id']==state['active']['id']
        _,state=change(client,'/activate',state)
        assert state['active']['preferences']['weekly_minutes']==240
        assert state['active']['tasks'][0]['status']=='completed'


def test_reconciled_editor_preserves_concurrent_changes_to_unedited_fields():
    with TestClient(create_app(MemoryStore(),Sources(),Adviser())) as client:
        _,state=send(client);_,state=change(client,'/activate',state)
        original={k:state['active']['tasks'][0][k] for k in task() if k!='status'}
        _,state=change(client,'/tasks',state,task={**original,'estimated_minutes':240})
        _,state=change(client,'/tasks',state,task={**original,'instructions':'Explain one decision in depth.'},base_definition=original)
        assert state['active']['tasks'][0]['estimated_minutes']==240
        assert state['active']['tasks'][0]['instructions']=='Explain one decision in depth.'
        response=client.post('/api/v1/roadmaps/tasks',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),
            'task':{**original,'instructions':'A conflicting change.'},'base_definition':original})
        assert response.status_code==409


def test_malformed_or_overlapping_reduced_periods_are_rejected_at_input_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Preferences.model_validate({**prefs(),'reduced_periods':[{}]})
    with pytest.raises(ValidationError):Preferences.model_validate({**prefs(),'reduced_periods':[
        {'start_date':'2030-01-07','end_date':'2030-01-13','weekly_hours':1},
        {'start_date':'2030-01-13','end_date':'2030-01-14','weekly_hours':0}]})


def test_user_can_reconsider_a_previous_scope_exclusion_without_losing_other_choices():
    row={'preferences':prefs(),'draft':{'tasks':[],'preferences':prefs(),'exclusions':[{'requirement_ref':'job:python','reason':'Later','quote':'Skip Python for now.'}]}}
    reply=AdviserReply(reply='We can reconsider that activity.',scope_inclusions=[{'requirement_ref':'job:python','reason':'User wants to revisit it.','quote':'Include Python again.'}])
    result=propose(row,reply,assessment(),'Include Python again.','reconsider')
    assert result['exclusions']==[]


def test_saved_plan_remains_readable_and_progress_can_be_recorded_during_source_outage():
    class Unavailable(Sources):
        unavailable=False
        async def read(self,service,path,token,params=None):
            if self.unavailable and path.endswith('/context'):raise Problem('Source temporarily unavailable.',503,'upstream')
            return await super().read(service,path,token,params)
    source=Unavailable()
    with TestClient(create_app(MemoryStore(),source,Adviser())) as client:
        _,state=send(client);_,state=change(client,'/activate',state);key=state['active']['tasks'][0]['id']
        source.unavailable=True
        response=client.get('/api/v1/roadmaps/workspace',headers=H)
        assert response.status_code==200
        state=response.json();assert state['context']['availability']=='unavailable' and state['active']
        _,state=change(client,'/tasks/status',state,task_id=key,status='completed')
        assert state['active']['tasks'][0]['status']=='completed'
        response=client.post('/api/v1/roadmaps/messages',json={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Plan more.','allow_partial_assessment':False},headers=H)
        assert response.status_code==503
