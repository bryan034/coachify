"""The roadmap's real model client, through the OpenAI SDK, with only the network replaced."""
import json
import time
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Model
from planner_fixtures import NOW, assessment, assignment, draft, settings
from test_planner_flow import objectives, week_draft
from app.main import create_app

H={'Authorization':'Bearer synthetic'}
class Sources:
    async def account(self,token):return {'id':'owner','token':token,'profile':{'version':1,'weekly_hours':5,'availability_periods':[]}}
    async def read(self,service,path,token,params=None):
        if path.endswith('/context'):return {'ready':True,'issues':[],'input_hash':'hash1','research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job'},'cv':{'id':'cv1','name':'synthetic.docx'},'evidence':assessment()['evidence']}
        return {'version':0,'ready':True,'result':assessment(),'stale':False,'evaluation':{'freshness':'current'},'operation':None}
def test_openrouter_requests_use_the_openai_sdk_and_json_output(monkeypatch):
    monkeypatch.setenv('ROADMAP_LLM_API_KEY', 'synthetic-key')
    monkeypatch.setenv('ROADMAP_LLM_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('ROADMAP_LLM_MODEL', 'synthetic-model')
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append((request,body))
        sent=json.loads(body['messages'][1]['content'])
        if 'new_task_minutes' in sent:content=week_draft([assignment()])
        elif 'weekly_capacity' in sent:
            content=draft();content.pop('assignments');content['weeks']=objectives(content,sent)
        else:content={'reply':'Saved.','settings':{'weekly_minutes':300},'revision_instruction':None}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
    with TestClient(create_app(MemoryStore(),Sources(),None,clock=lambda:NOW)) as client:
        client.app.state.model=Model(httpx.AsyncClient(transport=httpx.MockTransport(handler)),'ROADMAP')
        def finish():
            for _ in range(300):
                state=client.get('/api/v1/roadmaps/workspace',headers=H).json()
                if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
                time.sleep(.01)
            raise AssertionError('operation did not finish')
        state=client.post('/api/v1/roadmaps/planner/config',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'config':settings(break_minutes_per_hour=10)}).json()
        assert client.post('/api/v1/roadmaps/messages',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Five hours a week.','allow_partial_assessment':False}).status_code==202
        state=finish();assert state['operation']['status']=='succeeded',state['operation']
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())}).status_code==202
        time.sleep(.01);state=finish();assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['outline_candidate']['summary']=='Build Python depth first.'
        assert state['planner']['week_candidate']['tasks'][0]['schedule']==[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}]

    assert len(requests)==3  # chat, then the outline and its first week
    for request,body in requests:
        assert str(request.url)=='https://openrouter.ai/api/v1/chat/completions'
        assert request.headers['authorization']=='Bearer synthetic-key'
        assert request.headers['user-agent'].startswith('AsyncOpenAI/Python') and request.headers['x-stainless-lang']=='python'
        assert body['model']=='synthetic-model' and body['response_format']=={'type':'json_object'} and 'reasoning_effort' not in body
        assert 'JSON schema' in body['messages'][0]['content']
    assert [body['max_tokens'] for _,body in requests]==[8192,24000,24000]
