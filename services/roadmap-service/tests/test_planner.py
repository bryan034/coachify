"""Chat recovery, plus read-only access to plans saved before timed roadmaps."""
import time
from uuid import uuid4
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore,Problem,begin
from app.main import create_app
from app.schemas import ChatTurn,Message

OWNER='11111111-1111-4111-8111-111111111111';H={'Authorization':'Bearer synthetic'}
def earlier_plan():
    task={'id':'task1','title':'Explain your project','instructions':'Explain your synthetic project decisions.','completion_outcome':'Write two trade-offs.','estimated_minutes':180,
        'rationale':'Practise communicating your experience.','requirement_refs':['job:python'],'prerequisites':[],'milestone':'Explain your work','splittable':True,'status':'not_started'}
    return {'id':'earlier','assessment_id':'assessment1','assessment_hash':'hash1','assessment':{'id':'assessment1','job_skill_gaps':[],'interview_prep_gaps':[],'constraints':[]},'tasks':[task],
        'preferences':{'start_date':'2030-01-07','target_date':'2030-01-21','weekly_minutes':180,'days':[{'day':0,'minutes':180}]},'exclusions':[],
        'schedule':{'status':'feasible','issues':[],'allocations':[{'task_id':'task1','date':'2030-01-07','minutes':180,'order':0}],'remainders':{},'milestones':[]}}
class Sources:
    def __init__(self):self.owner=OWNER;self.hash='hash1'
    async def account(self,token):return {'id':self.owner,'token':token,'profile':{'version':1,'weekly_hours':3,'availability_periods':[]}}
    async def read(self,service,path,token,params=None):
        return {'ready':True,'issues':[],'input_hash':self.hash,'research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job','job_dates':[]},'cv':{'id':'cv1','name':'synthetic.docx'}}
class Adviser:
    configured=True
    def __init__(self):self.calls=0;self.fail=False
    async def generate(self,schema,instructions,context):
        self.calls+=1
        if self.fail:raise Problem('Try again.',503,'model_provider')
        assert schema is ChatTurn
        return ChatTurn(reply='Which days suit you?')
def finish(client):
    for _ in range(100):
        response=client.get('/api/v1/roadmaps/workspace',headers=H);assert response.status_code==200,response.text
        state=response.json()
        if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
        time.sleep(.01)
    raise AssertionError('operation did not finish')
def send(client,version=0):
    body={'expected_version':version,'mutation_id':str(uuid4()),'message':'I can do three hours on Mondays and Saturdays.','allow_partial_assessment':False}
    assert client.post('/api/v1/roadmaps/messages',json=body,headers=H).status_code==202
    return body,finish(client)
def seed_earlier(store):
    row=store.load(OWNER);row['active']=earlier_plan();store.save_result(OWNER,row['active']);store.cas(OWNER,row['version'],row)

def test_replayed_message_makes_one_model_call_and_adds_one_turn():
    model=Adviser()
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        body,state=send(client);assert model.calls==1 and len(state['messages'])==2
        assert client.post('/api/v1/roadmaps/messages',json=body,headers=H).status_code==202
        assert model.calls==1 and len(finish(client)['messages'])==2

def test_failed_message_retry_does_not_duplicate_user_entry():
    model=Adviser();model.fail=True
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        body,state=send(client);assert state['operation']['status']=='failed' and len(state['messages'])==1 and state['retry_request']
        model.fail=False;client.post('/api/v1/roadmaps/messages',json=body,headers=H);state=finish(client)
        assert state['operation']['status']=='succeeded' and len(state['messages'])==2

def test_restart_recovers_a_pending_message():
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

def test_earlier_untimed_plans_stay_readable_and_owner_scoped():
    store=MemoryStore();seed_earlier(store);sources=Sources()
    with TestClient(create_app(store,sources,Adviser())) as client:
        state=client.get('/api/v1/roadmaps/workspace',headers=H).json()
        assert state['active']['tasks'][0]['title']=='Explain your project' and state['planner']['active'] is None
        assert client.get('/api/v1/roadmaps/history/earlier',headers=H).json()['tasks'][0]['id']=='task1'
        sources.hash='changed';assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['stale']
        sources.owner='22222222-2222-4222-8222-222222222222'
        assert client.get('/api/v1/roadmaps/history/earlier',headers=H).status_code==404
        assert client.get('/api/v1/roadmaps/workspace',headers=H).json()['active'] is None

def test_endpoints_for_untimed_plans_are_gone():
    with TestClient(create_app(MemoryStore(),Sources(),Adviser())) as client:
        for path in ('activate','draft/discard','preferences','tasks','tasks/remove','tasks/status'):
            assert client.post('/api/v1/roadmaps/'+path,json={},headers=H).status_code in (404,405),path
