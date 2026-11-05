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


def test_counts_milestones_requirements_and_split_are_distinct():
    with client() as c:
        data=c.get('/api/v1/dashboard?period=weekly&focus_date=2030-01-10',headers=H).json()
        assert data['period']['start_date']=='2030-01-07' and data['period']['end_date']=='2030-01-13'
        progress=data['progress']
        assert progress['overall']['total']==2 and progress['overall']['completed']==1
        assert progress['overall']['in_progress']==1 and progress['overall']['remaining_estimated_minutes']==60
        assert progress['overall']['completion_ratio']==0.5 and progress['removed_task_ids']==['c']
        assert progress['selected_task_ids']==['a'] and progress['planned_minutes']==60
        assert progress['unscheduled_task_ids']==['b'] and progress['unscheduled_minutes']==60
        assert data['milestones'][0]['progress']['review_needed'] and data['milestones'][0]['blocked_task_ids']==['b']
        assert data['requirements']['items'][0]['match_status']=='uncertain'
        assert data['requirements']['items'][0]['linked_task_ids']==['a']
        assert data['requirements']['groups'][0]['operator']=='any'
        assert data['pace']['items'][0]['classification']=='completed_early'


def test_empty_plan_ratio_is_unknown_and_removed_last_task_never_completes_milestone():
    fake=Fake();fake.roadmap['active']['editable_tasks']=[task('removed',removed=True)]
    fake.roadmap['active_review']['milestones']['m1']={'tasks_total':0,'tasks_completed':0,'review_needed':True}
    with client(fake) as c:
        data=c.get('/api/v1/dashboard',headers=H).json()
        assert data['state']=='empty' and data['progress']['overall']['completion_ratio'] is None
        assert data['milestones'][0]['progress']['review_needed'] is True
        assert {'no_active_tasks','removed_work'} <= {r['code'] for r in data['milestones'][0]['review_reasons']}


def test_period_boundaries_follow_plan_zone_and_do_not_duplicate_split_task():
    with client() as c:
        # 02:00 UTC is already January 10 in Singapore.
        daily=c.get('/api/v1/dashboard?period=daily',headers=H).json()
        assert daily['period']['focus_date']=='2030-01-10' and daily['progress']['planned_minutes']==30
        monthly=c.get('/api/v1/dashboard?period=monthly&focus_date=2030-02-16',headers=H).json()
        assert monthly['period']['start_date']=='2030-02-01' and monthly['period']['end_date']=='2030-02-28'
        assert monthly['progress']['selected']['total']==0 and monthly['progress']['unscheduled_task_ids']==['b']
        whole=c.get('/api/v1/dashboard',headers=H).json()
        assert whole['progress']['selected']['total']==2 and whole['progress']['planned_minutes']==60


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


def test_pace_requires_identified_baseline_and_estimate_snapshot():
    fake=Fake();fake.roadmap['active']['pace_baseline_id']=None
    with client(fake) as c:assert c.get('/api/v1/dashboard',headers=H).json()['pace']['state']=='unavailable'
    fake=Fake();fake.roadmap['active']['editable_tasks'][0]['history'][0].pop('estimated_minutes_at_completion')
    with client(fake) as c:assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='non_comparable'


def test_reopen_and_scope_changes_are_not_credited_as_completed_pace():
    fake=Fake();fake.roadmap['active']['editable_tasks'][0]['status']='in_progress'
    fake.roadmap['active']['editable_tasks'][0]['history'].append({'at':'2030-01-09T11:00:00+00:00','from':'completed','to':'in_progress'})
    with client(fake) as c:assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='upcoming'
    fake.roadmap['active']['editable_tasks'][0]['completion_outcome']='Changed'
    with client(fake) as c:assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='changed'


def test_invalid_period_rejected_and_no_cache():
    with client() as c:
        assert c.get('/api/v1/dashboard?period=yearly',headers=H).status_code==422
        assert c.get('/api/v1/dashboard',headers=H).headers['cache-control']=='no-store'


def test_past_period_replays_status_without_moving_planned_cohort():
    fake=Fake();event=fake.roadmap['active']['editable_tasks'][0]['history'][0]
    fake.roadmap['active']['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    fake.baseline['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    event['at']='2030-01-10T00:00:00+00:00'  # completed on Jan 10, Singapore
    fake.roadmap['active']['editable_tasks'][0]['completed_at']=event['at']
    with client(fake) as c:
        earlier=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()
        assert earlier['pace']['as_of']=='2030-01-09T15:59:59.999999+00:00'
        assert earlier['pace']['items'][0]['classification']=='upcoming'
        later=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-10',headers=H).json()
        assert later['pace']['items']==[]
        assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='completed_late'


def test_past_reopening_is_reflected_at_period_cutoff():
    fake=Fake();fake.roadmap['active']['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    fake.baseline['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    fake.roadmap['active']['editable_tasks'][0]['history'].append(
        {'at':'2030-01-09T11:00:00+00:00','from':'completed','to':'in_progress'})
    fake.roadmap['active']['editable_tasks'][0]['history'].append(
        {'at':'2030-01-10T00:00:00+00:00','from':'in_progress','to':'completed','completion_definition':'Working outcome','estimated_minutes_at_completion':60})
    with client(fake) as c:
        earlier=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()
        assert earlier['pace']['items'][0]['classification']=='upcoming'
        later=c.get('/api/v1/dashboard',headers=H).json()
        assert later['pace']['items'][0]['classification']=='completed_late'


def test_completion_note_changes_do_not_change_completion_time():
    fake=Fake();task=fake.roadmap['active']['editable_tasks'][0]
    task['history'].append({'at':'2030-01-10T00:00:00+00:00','from':'completed','to':'completed',
        'completion_definition':'Working outcome','estimated_minutes_at_completion':60,'new_evidence_note':'A later note.'})
    task['completed_at']='2030-01-10T00:00:00+00:00'
    with client(fake) as c:
        result=c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]
        assert result['completed_at']=='2030-01-09T10:00:00+00:00'
        assert result['classification']=='completed_early'
    # A same-state edit must never supply a missing original effort snapshot.
    task['history'][0].pop('estimated_minutes_at_completion')
    with client(fake) as c:
        assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='non_comparable'


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


def test_period_includes_unscheduled_tasks_once_and_keeps_milestone_source_result():
    fake=Fake();fake.roadmap['active']['editable_tasks'][0]['estimated_minutes']=90
    fake.baseline['editable_tasks'][0]['estimated_minutes']=90
    fake.roadmap['active']['editable_tasks'][0]['history'][0]['estimated_minutes_at_completion']=90
    with client(fake) as c:
        data=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()
        ids=[t['id'] for t in data['progress']['tasks']]
        assert ids.count('a')==1 and ids.count('b')==1
        assert next(t for t in data['progress']['tasks'] if t['id']=='a')['unscheduled_minutes']==30
        assert data['milestones'][0]['progress']==fake.roadmap['active_review']['milestones']['m1']


def test_partial_split_period_does_not_claim_task_completion_for_segment():
    with client() as c:
        result=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()['pace']['items'][0]
        assert result['planned_date']=='2030-01-09' and result['planned_dates']==['2030-01-09']
        assert result['classification']=='non_comparable' and 'individual scheduled segments' in result['reason']


def test_edit_after_past_cutoff_does_not_claim_past_scope_changed():
    fake=Fake();current=fake.roadmap['active']['editable_tasks'][0]
    current['schedule']=[slot('2030-01-09',60)]
    fake.baseline['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    current['estimated_minutes']=90
    current['history'].append({'at':'2030-01-10T00:00:00+00:00','event':'edited','fields':['estimated_minutes'],'previous':{'estimated_minutes':60}})
    with client(fake) as c:
        item=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()['pace']['items'][0]
        assert item['classification']=='non_comparable' and 'cutoff' in item['reason']


def test_legacy_assignment_baseline_is_projected_in_memory():
    fake=Fake();legacy=fake.baseline;legacy['schema_version']='roadmap-v2'
    old=legacy.pop('editable_tasks')[0]
    legacy['assignments']=[{'id':'a','status':'scheduled','duration_minutes':60,'completion_criterion':'Working outcome',
        'date':'2030-01-09','start_time':'19:00','history':[]}]
    fake.roadmap['active']['editable_tasks'][0]['schedule']=[slot('2030-01-09',60)]
    before=copy.deepcopy(legacy)
    with client(fake) as c:
        result=c.get('/api/v1/dashboard',headers=H).json()['pace']
        assert result['state']=='available' and result['items'][0]['classification']=='completed_on_time'
    assert fake.baseline==before  # The snapshot remains untouched.
    fake.roadmap['active']['editable_tasks'][0]['history'][0].pop('estimated_minutes_at_completion')
    with client(fake) as c:assert c.get('/api/v1/dashboard',headers=H).json()['pace']['items'][0]['classification']=='non_comparable'


def test_current_additions_do_not_appear_as_known_historical_scope():
    fake=Fake();fake.roadmap['active']['editable_tasks'].append(task('added-later'))
    with client(fake) as c:
        historical=c.get('/api/v1/dashboard?period=daily&focus_date=2030-01-09',headers=H).json()['pace']
        assert historical['added_task_ids']==[] and historical['historical_added_scope_unknown']
        current=c.get('/api/v1/dashboard',headers=H).json()['pace']
        assert current['added_task_ids']==['added-later'] and not current['historical_added_scope_unknown']


def test_focus_date_extremes_fail_cleanly():
    with client() as c:
        for focus in ('0001-01-01','9999-12-31'):
            assert c.get('/api/v1/dashboard',params={'period':'weekly','focus_date':focus},headers=H).status_code==422


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
