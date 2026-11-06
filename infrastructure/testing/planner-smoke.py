"""Real Assessment/Roadmap HTTP + disposable MongoDB smoke, synthetic upstreams/models.

Run with the service dependencies installed and an explicit MONGODB_TEST_URI.
No environment files or application databases are read. All temporary databases
start with elo_planning_smoke_. No external provider calls are possible.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import httpx
from pymongo import MongoClient

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=r'''
from fastapi import FastAPI,Request
app=FastAPI()
OWNER='11111111-1111-4111-8111-111111111111'
@app.get('/health')
def health():return {'status':'ok'}
@app.get('/api/v1/profile/auth/session')
def account(request:Request):
    return {'id':OWNER if request.headers.get('authorization')=='Bearer synthetic-session' else '22222222-2222-4222-8222-222222222222','email_verified':True,'name':'Synthetic User','provider':'email'}
@app.get('/api/v1/profile')
def profile():return {'version':1,'onboarding_complete':True,'weekly_hours':3,'availability_periods':[],'education':None}
@app.get('/api/v1/profile/capabilities')
def declarations():return {'version':0,'declarations':[]}
@app.get('/api/v1/cv')
def listing():return {'selection':{'cv_id':'cv1','version':1},'cvs':[]}
@app.get('/api/v1/cv/cv1')
def cv():return {'id':'cv1','version':1,'status':'ready','file_name':'synthetic.docx'}
@app.get('/api/v1/cv/cv1/assessment-input')
def source():return {'cv_id':'cv1','cv_version':1,'extraction_version':1,'effective_version':1,'selection_version':1,'declarations_version':0,'skills':[],'declarations':[],
 'items':[{'id':'item1','kind':'project','title':'Synthetic project','description':'I built an API using Python.','provenance':'user_clarified','removed':False,
 'evidence':[{'id':'e1','excerpt':'I built an API using Python.','location':'answer'}],
 'skill_claims':[{'name':'Python','attribution':'personal','assistance':'independent','support_uncertain':False,'proficiency':None,'experience_months':None,'evidence_type':'user_clarified','evidence':[{'id':'e1','excerpt':'I built an API using Python.','location':'answer'}]}]}]}
@app.get('/api/v1/career/assessment-input')
def career():return {'ready':True,'selection_version':1,'research':None,'goal':{'_id':'012345678901234567890123','version':1,'role':'Developer','target_type':'specific_job','job_dates':[],
 'skills':[{'item_id':'req1','name':'Python','category':'Technical','priority':'required','origin':'employer','evidence':'Python is required.','group_operator':'all'}],'non_skill_requirements':[]}}
'''
ASSESS=r'''
from app.main import create_app
class Model:
 configured=True
 async def generate(self,schema,instructions,context):
  return schema.model_validate({'outcomes':[{'requirement_ref':r['ref'],'components':[{'dimension':'capability','status':'supported','explanation':'Declared personal API project.','evidence_refs':['cv:item1:claim:0']}],'recommendation':'Practise explaining the API decisions.','mapping_method':'canonical','mapping_reason':'Same shared Python identity.'} for r in context['requirements']]})
app=create_app(model=Model())
'''
ROADMAP=r'''
from datetime import datetime,timezone
from app.main import create_app
from app.schemas import ChatTurn
BLOCKS=[{'day':2,'start_time':'19:00','duration_minutes':90,'kind':'preferred'},{'day':5,'start_time':'10:00','duration_minutes':120,'kind':'preferred'},{'day':6,'start_time':'09:00','duration_minutes':60,'kind':'backup'}]
class Model:
 configured=True
 async def generate(self,schema,instructions,context,max_tokens=8192):
  if schema is ChatTurn:
   return schema.model_validate({'reply':'I added those to your settings. Review the panel, then press Generate.','settings':{'target_date':'2030-02-01','weekly_minutes':180,'blocks':BLOCKS,'blackouts':[{'frequency':'once','start_date':'2030-01-12'}]}})
  return schema.model_validate({'summary':'Practise explaining your existing API experience.','gaps':[],
   'milestones':[{'key':'explain','title':'Explain your API decisions','gap_ids':[],'prerequisite_keys':[],'estimated_minutes':120,'projected_start':'2030-01-09','projected_end':'2030-01-20','demonstrable_outcome':'A written explanation with two alternatives.'}],
   'assignments':[{'key':'first','milestone_key':'explain','gap_id':None,'kind':'study','date':'2030-01-09','start_time':'19:00','duration_minutes':60,'task':'Describe two trade-offs in your synthetic API project.','completion_criterion':'Write a concise explanation with two alternatives.'}],
   'deadline_outcome':{'summary':'You can explain your API decisions by the target date.','achievable_by_target':['A written explanation'],'fits_in_runway':True},'beyond_deadline':[],'exclusions':[]})
# Wednesday 2030-01-09, 08:00 in Singapore: a partial first week with one blackout.
app=create_app(model=Model(),clock=lambda:datetime(2030,1,9,0,0,tzinfo=timezone.utc))
'''
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def main():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:raise SystemExit('Set an explicit disposable MONGODB_TEST_URI.')
    client=MongoClient(uri,serverSelectionTimeoutMS=3000);client.admin.command('ping')
    prefix='elo_planning_smoke_'+uuid4().hex[:16]
    fixture_port,assess_port,roadmap_port=port(),port(),port()
    urls={'PROFILE_SERVICE_URL':f'http://127.0.0.1:{fixture_port}','CV_SERVICE_URL':f'http://127.0.0.1:{fixture_port}',
          'CAREER_SERVICE_URL':f'http://127.0.0.1:{fixture_port}','ASSESSMENT_SERVICE_URL':f'http://127.0.0.1:{assess_port}'}
    processes=[]
    def start(code,service,number):
        env={'PATH':os.environ['PATH'],'PYTHONPATH':str(ROOT/'packages/elo-shared')+os.pathsep+str(ROOT/f'services/{service}-service'),
             **urls,'MONGODB_URI':uri,'MONGODB_DATABASE':prefix+'_'+service}
        runner=code+f"\nimport uvicorn\nuvicorn.run(app,host='127.0.0.1',port={number},access_log=False,log_level='error')\n"
        process=subprocess.Popen([sys.executable,'-c',runner],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        processes.append(process)
        for _ in range(100):
            if process.poll() is not None:raise AssertionError(service+' smoke server exited')
            try:
                if httpx.get(f'http://127.0.0.1:{number}/health',trust_env=False).status_code==200:return process
            except httpx.HTTPError:pass
            time.sleep(.05)
        raise AssertionError(service+' smoke server did not start')
    try:
        start(FIXTURE,'roadmap',fixture_port);start(ASSESS,'assessment',assess_port);roadmap=start(ROADMAP,'roadmap',roadmap_port)
        with httpx.Client(base_url=f'http://127.0.0.1:{roadmap_port}',headers={'Authorization':'Bearer synthetic-session'},trust_env=False,timeout=15) as http:
            def read():
                response=http.get('/api/v1/roadmaps/workspace');assert response.status_code==200,response.text;return response.json()
            state=read();assert state['context']['ready'] and not state['active']
            def finish():
                for _ in range(100):
                    state=read()
                    if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
                    time.sleep(.1)
                raise AssertionError('operation did not finish')
            body={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Three hours a week until 1 February, not on 12 January.','allow_partial_assessment':True}
            assert http.post('/api/v1/roadmaps/messages',json=body).status_code==202
            state=finish();assert state['operation']['status']=='succeeded',state['operation']
            runway=state['planner']['runway']
            assert runway['can_generate'] and runway['weeks'][0]['partial'] and runway['weeks'][0]['usable_minutes']==90 and runway['study']['backup_extra_minutes']==60
            assert state['planner']['inputs']['experience'] and not state['planner']['candidate']
            body={'expected_version':state['version'],'mutation_id':str(uuid4()),'allow_partial_assessment':True}
            assert http.post('/api/v1/roadmaps/planner/generate',json=body).status_code==202
            state=finish();assert state['operation']['status']=='succeeded',state['operation']
            assert state['planner']['candidate']['assessment']['research_coverage']=='unavailable'
            assert state['assessment']['job_skill_gaps'][0]['match_status']=='supported'
            accept={'expected_version':state['version'],'mutation_id':str(uuid4())}
            response=http.post('/api/v1/roadmaps/planner/accept',json=accept);assert response.status_code==200,response.text;state=response.json()
            identifier=state['planner']['active']['id'];session=state['planner']['active']['assignments'][0]['id']
            assert http.post('/api/v1/roadmaps/planner/accept',json=accept).json()['planner']['active']['id']==identifier
            response=http.post('/api/v1/roadmaps/planner/assignments/status',json={'expected_version':state['version'],'mutation_id':str(uuid4()),'assignment_id':session,'status':'completed','evidence_note':'Explanation written.'})
            assert response.status_code==200,response.text
            completed=response.json()['planner']['active']
            roadmap.terminate();roadmap.wait(timeout=10);start(ROADMAP,'roadmap',roadmap_port)
            state=read();assert state['planner']['active']==completed and state['planner']['active']['assignments'][0]['evidence_note']=='Explanation written.' and len(state['messages'])==2
            assert http.get('/api/v1/roadmaps/history/'+completed['id']).json()['schema_version']=='roadmap-v2'
            assert http.get('/api/v1/roadmaps/history/'+completed['id'],headers={'Authorization':'Bearer synthetic-other'}).status_code==404
            # Old settings written by earlier versions are removed from storage on the next start.
            old={'buffer_percent':20,'checkin_day':4,'checkin_time':'18:00'}
            before=read()
            database=client[prefix+'_roadmap'];saved=database.workspaces.find_one({'planner.active.id':completed['id']})
            rules=saved['planner']['config']['blackouts']
            database.workspaces.update_one({'_id':saved['_id']},{'$set':{**{f'planner.config.{k}':v for k,v in old.items()},**{f'planner.active.config.{k}':v for k,v in old.items()},
                'planner.config.blackout_dates':[rule['start_date'] for rule in rules]},'$unset':{'planner.config.blackouts':''}})
            database.roadmaps.update_one({'_id':completed['id']},{'$set':{f'config.{k}':v for k,v in old.items()}})
            roadmap=processes[-1];roadmap.terminate();roadmap.wait(timeout=10);start(ROADMAP,'roadmap',roadmap_port)
            cleaned=database.workspaces.find_one({'_id':saved['_id']})
            removed={*old,'blackout_dates'}
            assert not removed&cleaned['planner']['config'].keys() and not removed&cleaned['planner']['active']['config'].keys()
            assert not removed&database.roadmaps.find_one({'_id':completed['id']})['config'].keys()
            assert cleaned['version']==saved['version'] and [r['start_date'] for r in cleaned['planner']['config']['blackouts']]==[r['start_date'] for r in rules]
            state=read();assert state['planner']['active']['assignments']==completed['assignments'] and state['version']==before['version']
            assert http.get('/api/v1/roadmaps/history/'+completed['id']).status_code==200
            print(json.dumps({'status':'passed','checks':['real cross-service HTTP snapshots','separate Assessment comparison','explicit partial research','chat-collected settings','calculated runway','validated timed plan','reviewed acceptance','idempotent lost-response retry','session completion and evidence','restart persistence','owner isolation','no external provider calls']}))
    finally:
        for process in processes:
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for service in ('assessment','roadmap'):client.drop_database(prefix+'_'+service)
        client.close()
if __name__=='__main__':main()
