"""The roadmap's real model client, through the OpenAI SDK, with only the network replaced."""
import json
import time
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Model
from planner_fixtures import NOW, assessment, draft, outline_rows, settings
from app.main import create_app
from app.schemas import ChatTurn, PlanOutline, WindowDetail

H={'Authorization':'Bearer synthetic'}
class Sources:
    async def account(self,token):return {'id':'owner','token':token,'profile':{'version':1,'weekly_hours':5,'availability_periods':[]}}
    async def read(self,service,path,token,params=None):
        if path.endswith('/context'):return {'ready':True,'issues':[],'input_hash':'hash1','research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job'},'cv':{'id':'cv1','name':'synthetic.docx'},'evidence':assessment()['evidence']}
        return {'version':0,'ready':True,'result':assessment(),'stale':False,'operation':None}
def references(value):
    if isinstance(value,dict):return any(k in ('$ref','$defs') or references(v) for k,v in value.items())
    return isinstance(value,list) and any(references(v) for v in value)
def run_flow(monkeypatch,base,*,parameter=None):
    monkeypatch.setenv('ROADMAP_LLM_API_KEY','synthetic-key');monkeypatch.setenv('ROADMAP_LLM_BASE_URL',base);monkeypatch.setenv('ROADMAP_LLM_MODEL','synthetic-model')
    if parameter:monkeypatch.setenv('ROADMAP_LLM_TOKEN_PARAMETER',parameter)
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append((request,body))
        sent=json.loads(body['messages'][1]['content']);fields=draft();tasks=fields.pop('assignments')
        content={'outline':{**fields,'outline':outline_rows(sent.get('planned_capacity',[]))},'detail':{'assignments':tasks}}.get(sent.get('stage'),{'reply':'Saved.','settings':{'weekly_minutes':300},'revision_instruction':None})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
    with TestClient(create_app(MemoryStore(),Sources(),None,clock=lambda:NOW)) as client:
        client.app.state.model=Model(httpx.AsyncClient(transport=httpx.MockTransport(handler)),'ROADMAP')
        def finish():
            for _ in range(300):
                state=client.get('/api/v1/roadmaps/workspace',headers=H).json()
                if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
                time.sleep(.01)
            raise AssertionError('operation did not finish')
        state=client.post('/api/v1/roadmaps/planner/config',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'config':settings()}).json()
        assert client.post('/api/v1/roadmaps/messages',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Five hours a week.','allow_partial_assessment':False}).status_code==202
        state=finish();assert state['operation']['status']=='succeeded',state['operation']
        assert client.post('/api/v1/roadmaps/planner/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())}).status_code==202
        time.sleep(.01);state=finish();assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['candidate']['summary']=='Build Python depth first.'
    return requests

def test_gemini_requests_use_the_openai_sdk_and_a_provider_ready_schema(monkeypatch):
    requests=run_flow(monkeypatch,'https://generativelanguage.googleapis.com/v1beta/openai')
    assert len(requests)==3
    for request,body in requests:
        assert str(request.url)=='https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
        assert request.headers['authorization']=='Bearer synthetic-key'
        assert request.headers['user-agent'].startswith('AsyncOpenAI/Python') and request.headers['x-stainless-lang']=='python'
        assert body['model']=='synthetic-model' and body['response_format']['type']=='json_schema' and body['response_format']['json_schema']['strict'] is True
        assert not references(body['response_format']['json_schema']['schema'])
    assert [body['response_format']['json_schema']['name'] for _,body in requests]==[ChatTurn.__name__,PlanOutline.__name__,WindowDetail.__name__]
    assert requests[0][1]['max_tokens']==8192 and requests[1][1]['max_tokens']==24000 and requests[2][1]['max_tokens']==12000

def test_openai_requests_use_the_selected_token_parameter_and_json_output(monkeypatch):
    requests=run_flow(monkeypatch,'https://api.openai.com/v1',parameter='max_completion_tokens')
    for request,body in requests:
        assert str(request.url)=='https://api.openai.com/v1/chat/completions' and request.headers['user-agent'].startswith('AsyncOpenAI/Python')
        assert body['response_format']=={'type':'json_object'} and 'max_tokens' not in body and 'JSON schema' in body['messages'][0]['content']
    assert requests[1][1]['max_completion_tokens']==24000
