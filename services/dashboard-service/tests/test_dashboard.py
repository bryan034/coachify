"""Synthetic dashboard reads; no database, provider or private environment."""
import copy
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from elo_shared.runtime import Problem
from app.main import create_app

NOW=datetime(2030,1,10,2,tzinfo=timezone.utc)
H={'Authorization':'Bearer account-a'}


def task(id,**values):
    return {'id':id,'title':id,'status':'not_started','estimated_minutes':60,'completion_outcome':'Working outcome',
        'requirement_refs':[],'requirement_source_id':'assessment-a','requirement_source_hash':'hash-a',
        'prerequisites':[],'milestone_key':'m1','schedule':[],'history':[], 'removed':False,**values}

def slot(day,duration=30):return {'date':day,'start_time':'19:00','duration_minutes':duration}

def sources():
    items=[task('a',status='completed',completed_at='2030-01-09T10:00:00+00:00',
                history=[{'at':'2030-01-09T10:00:00+00:00','from':'not_started','to':'completed','completion_definition':'Working outcome','estimated_minutes_at_completion':60}],
                schedule=[slot('2030-01-09'),slot('2030-01-10')],requirement_refs=['job:python']),
           task('b',status='in_progress'),task('c',removed=True,removal={'at':'2030-01-08T00:00:00+00:00'})]
    plan={'id':'current-a','assessment_id':'assessment-a','assessment_hash':'hash-a','pace_baseline_id':'baseline-a',
          'config':{'time_zone':'Asia/Singapore'},'created_at':'2030-01-01T00:00:00+00:00','updated_at':'2030-01-09T10:00:00+00:00',
          'editable_tasks':items,'milestones':[{'id':'m1','key':'m1','title':'Python','outcome':{'demonstrated':False}}]}
    base=copy.deepcopy(plan);base['id']='baseline-a';base['updated_at']='2030-01-08T00:00:00+00:00';base['editable_tasks'][0]['status']='not_started';base['editable_tasks'][0]['history']=[]
    assessment={'version':2,'workspace_updated_at':'2030-01-01T00:00:00+00:00','freshness':'current','ready':True,'input_hash':'hash-a',
        'inputs':{'profile_version':1},'result':{'id':'assessment-a','input_hash':'hash-a','created_at':'2030-01-01T00:00:00+00:00',
        'job_skill_gaps':[{'ref':'job:python','name':'Python','kind':'job_skill','match_status':'uncertain','components':[{'status':'uncertain'}]}],
        'interview_prep_gaps':[],'constraints':[],'groups':[{'id':'group-1','operator':'any','requirement_refs':['job:python'],'match_status':'uncertain'}]}}
    roadmap={'version':4,'active':plan,'active_review':{'milestones':{'m1':{'tasks_total':2,'tasks_completed':1,'review_needed':True}}},
             'task_readiness':{'a':{'actionable':False,'reasons':[]},'b':{'actionable':False,'reasons':[{'code':'prerequisite_incomplete','message':'Finish earlier work.'}]}}}
    return roadmap,assessment,base

class Fake:
    def __init__(self):
        self.roadmap,self.assessment,self.baseline=sources();self.calls=[];self.race=None;self.unavailable=set()
    async def account(self,token):
        if token not in ('Bearer account-a','Bearer account-b'):raise Problem('Sign in.',401,'session')
        return {'id':token,'token':token,'profile':{'onboarding_complete':True}}
    async def read(self,service,path,token,params=None):
        self.calls.append((service,path,token))
        if service in self.unavailable:raise Problem('Unavailable',503,'upstream')
        if token=='Bearer account-b':
            if service=='roadmap':return {'version':0,'active':None,'active_review':None,'task_readiness':{}}
            return {'version':0,'freshness':'missing','result':None,'input_hash':None,'inputs':None}
        if path.endswith('dashboard-source'):
            row=copy.deepcopy(self.roadmap if service=='roadmap' else self.assessment)
            if self.race==service and sum(1 for a,b,c in self.calls if a==service and b==path)>1:row['version']+=1
            return row
        if path.endswith('/history/baseline-a'):return copy.deepcopy(self.baseline)
        raise AssertionError((service,path))


def client(fake=None):return TestClient(create_app(upstream=fake or Fake(),clock=lambda:NOW))


def test_owner_auth_no_plan_and_no_source_mutations():
    fake=Fake();before=copy.deepcopy((fake.roadmap,fake.assessment,fake.baseline))
    with client(fake) as c:
        assert c.get('/api/v1/dashboard').status_code==401
        response=c.get('/api/v1/dashboard',headers={'Authorization':'Bearer account-b'})
        assert response.status_code==200 and response.json()['state']=='no_plan'
        assert response.json()['progress'] is None
        assert c.get('/api/v1/dashboard',headers=H).json()['roadmap']['id']=='current-a'
    assert (fake.roadmap,fake.assessment,fake.baseline)==before
    assert all(p.endswith('dashboard-source') or '/history/' in p for _,p,_ in fake.calls)

def test_empty_plan_ratio_is_unknown_and_removed_last_task_never_completes_milestone():
    fake=Fake();fake.roadmap['active']['editable_tasks']=[task('removed',removed=True)]
    fake.roadmap['active_review']['milestones']['m1']={'tasks_total':0,'tasks_completed':0,'review_needed':True}
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['state']=='empty' and data['progress']['overall']['completion_ratio'] is None
        assert data['milestones'][0]['progress']['review_needed'] is True
        assert {'no_active_tasks','removed_work'} <= {r['code'] for r in data['milestones'][0]['review_reasons']}

def test_stale_and_mismatched_assessment_never_establishes_capability():
    fake=Fake();fake.assessment['freshness']='stale';fake.assessment['result']['id']='assessment-new'
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['assessment']['state']=='stale' and data['assessment']['roadmap_match']=='different'
        assert data['requirements']['state']=='stale' and data['requirements']['stale_link_task_ids']==['a']
        assert data['requirements']['items'][0]['linked_task_ids']==[]
        assert data['requirements']['items'][0]['match_status']=='uncertain'

def test_unavailable_and_changed_sources_are_never_zero():
    fake=Fake();fake.unavailable.add('assessment')
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['state']=='available' and data['assessment']['state']=='unavailable'
        assert data['requirements']['items']==[] and data['requirements']['state']=='unavailable'
    for service in ('roadmap','assessment'):
        fake=Fake();fake.race=service
        with client(fake) as c:
            data=c.get('/api/v1/dashboard',headers=H).json()
            assert data['state']=='conflict' and data['progress'] is None
    fake=Fake();fake.unavailable.add('roadmap')
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['state']=='unavailable' and data['progress'] is None

def test_source_transport_forwards_only_bearer_and_bounds_response():
    import asyncio
    import httpx
    from app.main import DashboardUpstream
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path.endswith('/large'):return httpx.Response(200,content=b' '*(5*1024*1024+1))
        if request.url.path.endswith('/changed'):return httpx.Response(409,json={'detail':'private'})
        if request.url.path.endswith('/denied'):return httpx.Response(401)
        if request.url.path.endswith('/redirect'):return httpx.Response(302,headers={'Location':'http://other.invalid/'})
        return httpx.Response(200,json={'version':4})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False) as http:
            adapter=DashboardUpstream(http)
            assert await adapter.read('roadmap','/ok','Bearer synthetic')=={'version':4}
            for path,status,code in [('/large',503,'source_capacity'),('/changed',409,'source_changed'),('/denied',401,'session'),('/redirect',503,'upstream')]:
                try:await adapter.read('roadmap',path,'Bearer synthetic')
                except Problem as error:assert (error.status,error.code)==(status,code)
                else:assert False, path
    asyncio.run(run())
    assert all(request.headers['Authorization']=='Bearer synthetic' for request in seen)
    assert len(seen)==5  # A redirect was not followed.

def test_completed_unscheduled_work_is_distinct_from_remaining_unscheduled_estimate():
    fake=Fake()
    fake.roadmap['active']['editable_tasks'].append(task('personal-done',status='completed',milestone_key=None))
    with client(fake) as c:
        progress=c.get('/api/v1/dashboard',headers=H).json()['progress']
        assert progress['unscheduled_minutes']==120
        assert progress['remaining_unscheduled_minutes']==60
        assert 'personal-done' in progress['unscheduled_task_ids']

def test_milestone_effort_is_labeled_and_unconfirmed_outcome_is_explained():
    fake=Fake();fake.roadmap['active_review']['milestones']['m1']['completed_minutes']=30
    with client(fake) as c:
        milestone=c.get('/api/v1/dashboard',headers=H).json()['milestones'][0]
        assert milestone['progress']['completed_scheduled_minutes_estimate']==30
        assert 'completed_minutes' not in milestone['progress']
        assert 'outcome_unconfirmed' in {reason['code'] for reason in milestone['review_reasons']}

def test_missing_roadmap_update_time_is_not_replaced_by_creation_time():
    fake=Fake();fake.roadmap['active'].pop('updated_at')
    with client(fake) as c:
        source=c.get('/api/v1/dashboard',headers=H).json()['roadmap']
        assert source['updated_at'] is None and source['created_at']=='2030-01-01T00:00:00+00:00'

def test_current_partial_assessment_reports_coverage_limit():
    fake=Fake();fake.assessment['result'].update(analysis_status='partial',research_coverage='unavailable')
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['assessment']['state']=='current'
        assert data['assessment']['analysis_status']=='partial'
        assert data['assessment']['research_coverage']=='unavailable'
        assert any('partial' in message for message in data['warnings'])

def test_failed_assessment_refresh_is_visible_without_exposing_error_details():
    fake=Fake();fake.assessment['operation']={'id':'operation-1','status':'failed','stage':'failed','error':{'detail':'private provider error'}}
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['assessment']['operation']=={'id':'operation-1','status':'failed','stage':'failed'}
        assert any('operation failed' in message for message in data['warnings'])
        assert 'private provider error' not in str(data)

def test_milestone_membership_changes_are_explained():
    fake=Fake();fake.roadmap['active']['milestones'][0]['outcome']={
        'demonstrated':True,'definition_review_required':True,'membership_review_required':True}
    with client(fake) as c:
        milestone=c.get('/api/v1/dashboard',headers=H).json()['milestones'][0]
        assert 'membership_changed' in {item['code'] for item in milestone['review_reasons']}
        assert 'outcome_definition_changed' not in {item['code'] for item in milestone['review_reasons']}
