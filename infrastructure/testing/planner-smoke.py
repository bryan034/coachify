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
from app.main import create_app
class Model:
 configured=True
 async def generate(self,schema,instructions,context):
  return schema.model_validate({'reply':'Let us use your chosen days to practise explaining your existing API experience. This is a proposal you can edit.',
   'preferences':{'start_date':'2030-01-07','target_date':'2030-02-01','weekly_minutes':180,'days':[{'day':0,'minutes':60},{'day':5,'minutes':120}]},
   'task_changes':[{'id':'explain','title':'Explain API decisions','instructions':'Describe two trade-offs in your synthetic API project.','completion_outcome':'Write a concise explanation with two alternatives.','estimated_minutes':120,'rationale':'Build on declared Python experience.','requirement_refs':['job:req1'],'prerequisites':[],'milestone':'Explain your project','splittable':True}]})
app=create_app(model=Model())
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
            body={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'I can do three hours on Mondays and Saturdays. Please propose a project explanation activity.','allow_partial_assessment':True}
            assert http.post('/api/v1/roadmaps/messages',json=body).status_code==202
            for _ in range(100):
                state=read()
                if (state['operation'] or {}).get('status') in ('succeeded','failed'):break
                time.sleep(.1)
            assert state['operation']['status']=='succeeded',state['operation']
            assert state['draft']['schedule']['status']=='feasible' and state['assessment']['research_coverage']=='unavailable'
            assert state['assessment']['job_skill_gaps'][0]['match_status']=='supported'
            activate={'expected_version':state['version'],'mutation_id':str(uuid4())}
            response=http.post('/api/v1/roadmaps/activate',json=activate);assert response.status_code==200,response.text;state=response.json()
            identifier=state['active']['id'];task_id=state['active']['tasks'][0]['id']
            assert http.post('/api/v1/roadmaps/activate',json=activate).json()['active']['id']==identifier
            response=http.post('/api/v1/roadmaps/tasks/status',json={'expected_version':state['version'],'mutation_id':str(uuid4()),'task_id':task_id,'status':'completed'})
            assert response.status_code==200,response.text
            roadmap.terminate();roadmap.wait(timeout=10);start(ROADMAP,'roadmap',roadmap_port)
            state=read();assert state['active']['tasks'][0]['status']=='completed' and len(state['messages'])==3
            assert http.get('/api/v1/roadmaps/history/'+identifier,headers={'Authorization':'Bearer synthetic-other'}).status_code==404
            print(json.dumps({'status':'passed','checks':['real cross-service HTTP snapshots','separate Assessment comparison','explicit partial research','daily allocation','reviewed activation','idempotent lost-response retry','task completion','MongoDB restart persistence','cross-owner history rejection']}))
    finally:
        for process in processes:
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for service in ('assessment','roadmap'):client.drop_database(prefix+'_'+service)
        client.close()
if __name__=='__main__':main()
