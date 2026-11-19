"""Configure, generate, review and plan week by week through the HTTP API, with scripted model output."""
import copy
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from planner_fixtures import NOW, OWNER, CleanableStore, assessment, assignment, draft, gap, milestone, settings
from app.main import create_app
from app.planning.state import learning_view
from app.schemas.roadmap import ChatTurn, LearningPlan, OutlineDraft, PlannedRoadmap
from app.schemas.weeks import WeekDraft

H={'Authorization':'Bearer synthetic'}
PREFIX='/api/v1/roadmaps/planner'
class Sources:
    def __init__(self):self.owner=OWNER;self.hash='hash1';self.ready=True;self.result=assessment();self.writes=[];self.reads=[];self.periods=[]
    async def account(self,token):return {'id':self.owner,'token':token,'profile':{'version':1,'weekly_hours':6,'application_date':None,'availability_periods':self.periods}}
    async def read(self,service,path,token,params=None):
        self.reads.append(path)
        if path.endswith('/context'):
            return {'ready':self.ready,'issues':[] if self.ready else [{'source':'cv','message':'Select a CV.','href':'/cv'}],'input_hash':self.hash,'research_coverage':'no_findings','goal':{'role':'Developer','target_type':'specific_job','job_dates':[]},'cv':{'id':'cv1','name':'synthetic.docx'},'evidence':assessment()['evidence'],'evaluation':{'freshness':'current'}}
        if path.endswith('/operation'):return {'operation':{'status':'succeeded'},'result':self.result,'retry_request':None}
        return {'version':0,'ready':self.ready,'result':self.result,'stale':False,'evaluation':{'freshness':'current'},'operation':None}
    async def write(self,service,path,token,body):
        self.writes.append(path);self.result=assessment(self.hash);return {'version':1}
def objectives(item,context):
    """A weekly objective for each week a milestone covers, sharing out its estimate."""
    left={m['key']:m['estimated_minutes'] for m in item['milestones']};weeks=[]
    for row in context['weekly_capacity']:
        first=row['week_start'];last=(datetime.fromisoformat(first)+timedelta(days=6)).date().isoformat()
        found=next((m for m in item['milestones'] if m['projected_start']<=last and m['projected_end']>=first),None)
        if not found:found=item['milestones'][-1] if item['milestones'] else None
        if not found:continue
        covered=found['projected_start']<=last and found['projected_end']>=first
        minutes=min(row['usable_minutes'],left[found['key']]) if covered else 0;left[found['key']]-=minutes
        weeks.append({'week_start':first,'objective':'Advance '+found['title'],'expected_outcome':found['demonstrable_outcome'][:400],
            'estimated_minutes':minutes,'milestone_key':found['key'],'gap_ids':found['gap_ids'][:8]})
    return weeks
def week_draft(tasks=(),**changes):
    """A week written by the model: tasks without times. Fixture assignments are accepted and their dates ignored."""
    return {'summary':'This week builds on what you finished.','tasks':[{'key':t['key'],'milestone_key':t['milestone_key'],'title':t['title'],
        'description':t.get('description') or '1. Implement the endpoint using the project conventions.\n2. Run its tests and fix failures.\n3. Save the passing result.',
        'instructions':t.get('task') or t['instructions'],'completion_outcome':t.get('completion_criterion') or t['completion_outcome'],
        'duration_minutes':t['duration_minutes'],'kind':t.get('kind','study'),'gap_id':t.get('gap_id')} for t in tasks],'carryover':[],'objective_changes':[],**changes}
class Scripted:
    """Returns each supplied outline once. A fixture draft's assignments become the tasks of its first week unless `weeks` scripts them."""
    configured=True
    def __init__(self,plans=(),chats=(),weeks=()):
        self.plans=list(plans);self.chats=list(chats);self.weeks=list(weeks);self.contexts=[];self.tokens=[];self.schemas=[];self.first_week=[]
    async def generate(self,schema,instructions,context,max_tokens=8192):
        self.contexts.append(copy.deepcopy(context));self.tokens.append(max_tokens);self.schemas.append(schema.__name__)
        if schema is ChatTurn:return ChatTurn.model_validate(self.chats.pop(0))
        if schema is OutlineDraft:
            item=self.plans.pop(0)
            if isinstance(item,Exception):raise item
            item=copy.deepcopy(item);self.first_week=item.pop('assignments',[])
            item.setdefault('weeks',objectives(item,context))
            return OutlineDraft.model_validate(item)
        assert schema is WeekDraft
        item=self.weeks.pop(0) if self.weeks else week_draft(self.first_week)
        if isinstance(item,Exception):raise item
        return WeekDraft.model_validate(item(context) if callable(item) else item)
    def sent(self,schema):
        return [context for name,context in zip(self.schemas,self.contexts) if name==schema]
class Clock:
    def __init__(self,now=NOW):self.now=now
    def __call__(self):return self.now
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
def request(client,path,state,**body):
    return client.post(PREFIX+path,headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),**body})
def post(client,path,state,**body):
    response=request(client,path,state,**body)
    assert response.status_code==200,response.text
    return response.json()
def configure(client,state=None,**changes):
    # Ten-minute breaks, as a new account has.
    return post(client,'/config',state or read(client),config=settings(**{'break_minutes_per_hour':10,**changes}))
def generate(client,state,allow_partial=False):
    """Outline and first week in one operation."""
    response=request(client,'/outlines/generate',state,allow_partial_assessment=allow_partial)
    assert response.status_code==202,response.text
    time.sleep(.01)
    return finish(client)
def plan_week(client,state,week_start,**body):
    response=request(client,'/weeks/generate',state,week_start=week_start,**body)
    assert response.status_code==202,response.text
    time.sleep(.01)
    return finish(client)
def accept_outline(client,state):
    return post(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/accept',state)
def accept_week(client,state):
    return post(client,'/weeks/'+state['planner']['week_candidate']['id']+'/accept',state)
def chat(client,state,message):
    body={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':message,'allow_partial_assessment':False}
    response=client.post('/api/v1/roadmaps/messages',headers=H,json=body);assert response.status_code==202,response.text
    return finish(client)
def accepted(client,**changes):
    state=generate(client,configure(client,**changes));assert state['operation']['status']=='succeeded',state['operation']
    return accept_outline(client,state)

SUNDAY=NOW+timedelta(days=4)  # 2030-01-13 08:00 in Singapore: the last day of the first week.
def task(key,title,minutes=60,**changes):
    return assignment(key,title=title,task=title+'.',duration_minutes=minutes,**changes)
def long_draft(**changes):
    """A milestone that runs to the target date, so all three weeks have an objective."""
    return draft(milestones=[milestone(estimated_minutes=600,projected_end='2030-01-27')],**changes)
def schedule_of(state,key):
    found=next(t for t in state['planner']['active']['editable_tasks'] if t.get('generated_key')==key)
    return [(s['date'],s['start_time'],s['duration_minutes']) for s in found['schedule']]
def carry_all(action='carry',**extra):
    return lambda context:[{'task_id':t['task_id'],'action':action,'reason':'Still the next step.',**extra} for t in context['progress']['unfinished']]

# One generation, one acceptance

def test_one_generation_previews_the_whole_outline_and_the_first_week_and_one_acceptance_publishes_both():
    model=Scripted([long_draft()])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        planner=state['planner']
        assert model.schemas==['OutlineDraft','WeekDraft'] and planner['active'] is None and 'candidate' not in planner
        assert [(w['week_start'],w['status'],w['tasks_total']) for w in planner['weeks']]==[('2030-01-07','open',0),('2030-01-14','projected',0),('2030-01-21','projected',0)]
        assert all(w['objective'] and w['expected_outcome'] and w['milestone_key']=='m1' for w in planner['weeks'])
        preview=planner['week_candidate']
        assert preview['outline_id']==planner['outline_candidate']['id'] and preview['week_start']=='2030-01-07'
        assert [(t['title'],t['schedule']) for t in preview['tasks']]==[('Write one tested endpoint',[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}])]
        assert (preview['target']['weekly_minutes'],preview['target']['target_minutes'])==(300,80)
        assert [r['code'] for r in preview['target']['reasons']]==['partial_week','remaining_scope']
        row=planner['preview_sessions'][0]
        assert (row['title'],row['date'],row['start_time'],row['duration_minutes'])==('Write one tested endpoint','2030-01-09','19:00',60)
        body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        path=PREFIX+'/outlines/'+planner['outline_candidate']['id']+'/accept'
        response=client.post(path,headers=H,json=body);assert response.status_code==200,response.text
        state=response.json();planner=state['planner'];active=planner['active']
        assert planner['outline_candidate'] is None and planner['week_candidate'] is None and planner['outline_active']['status']=='accepted'
        assert [a['title'] for a in active['assignments']]==['Write one tested endpoint'] and active['pace_baseline_id']==active['id']
        assert active.keys()<={field.alias or name for name,field in PlannedRoadmap.model_fields.items()}|{'editable_tasks'}
        assert [b['week_start'] for b in planner['week_blocks']]==['2030-01-07']
        assert [(w['status'],w['tasks_total'],w['planned_minutes']) for w in planner['weeks']]==[('planned',1,60),('projected',0,0),('projected',0,0)]
        assert (planner['week_planning']['action'],planner['week_planning']['available'],planner['week_planning']['reason'])==('plan_next',False,'waiting')
        retry=client.post(path,headers=H,json=body)
        assert retry.status_code==200 and retry.json()['planner']['active']['id']==active['id'] and len(model.contexts)==2

def test_an_outline_is_still_reviewable_when_its_first_week_cannot_be_prepared():
    model=Scripted([long_draft()],weeks=[Problem('Provider unavailable.',503,'model_provider'),week_draft([assignment()])])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded' and state['planner']['week_candidate'] is None
        assert state['planner']['outline_candidate']['first_week_error']=='Provider unavailable.'
        state=accept_outline(client,state);planner=state['planner']
        assert planner['active']['editable_tasks']==[] and planner['outline_active']['first_week_error'] is None
        assert (planner['week_planning']['action'],planner['week_planning']['week_start'],planner['week_planning']['available'])==('plan_this','2030-01-07',True)
        state=accept_week(client,plan_week(client,state,'2030-01-07'))
        assert schedule_of(state,'a1')==[('2030-01-09','19:00',60)]

def test_a_discarded_outline_preview_takes_its_first_week_with_it():
    with client_for(Scripted([draft()])) as client:
        state=generate(client,configure(client))
        state=post(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/discard',state)
        assert state['planner']['outline_candidate'] is None and state['planner']['week_candidate'] is None and state['planner']['active'] is None

def test_a_week_under_or_over_the_agreed_hours_is_sent_back_with_the_reason():
    light=week_draft([task('a1','Read one page',30)]);heavy=week_draft([task('a1','Write endpoints',90)])
    model=Scripted([draft()],weeks=[light,heavy,week_draft([assignment()])])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        first,second,third=model.sent('WeekDraft')
        assert (first['target_minutes'],first['new_task_minutes'],first['session_minutes'])==(80,80,60) and first['validation_errors']==[]
        assert 'under the agreed hours' in second['validation_errors'][0]
        assert 'New tasks total 90 minutes but this week has room for 80' in third['validation_errors'][0]
        assert state['planner']['week_candidate']['generation']['attempts']==3

def test_three_rejected_weeks_fail_without_touching_saved_work():
    bad=week_draft([task('a1','Write far too much',200)])
    with client_for(Scripted([draft()],weeks=[bad,bad,bad,bad,bad,bad])) as client:
        state=accept_outline(client,generate(client,configure(client)))
        assert state['planner']['active']['editable_tasks']==[]
        active=state['planner']['active']
        state=plan_week(client,state,'2030-01-07')
        assert state['operation']['error']['code']=='week_validation' and 'room for 80' in state['operation']['error']['detail']
        assert state['planner']['active']==active and state['planner']['week_candidate'] is None
        assert state['planner']['retry_week']['week_start']=='2030-01-07'

# Planning the next week

def test_next_week_opens_on_the_planning_day_or_once_every_task_is_done():
    clock=Clock()
    with client_for(Scripted([long_draft()]),clock=clock) as client:
        state=accepted(client)
        early=request(client,'/weeks/generate',state,week_start='2030-01-14')
        assert early.status_code==409 and early.json()['code']=='week_not_open' and '2030-01-13' in early.json()['detail']
        assert request(client,'/weeks/generate',state,week_start='2030-01-21').status_code==409
        assert request(client,'/weeks/generate',state,week_start='2030-01-15').status_code==422
        clock.now=SUNDAY
        planning=read(client)['planner']['week_planning']
        assert (planning['action'],planning['week_start'],planning['available'],planning['reason'],planning['unfinished_count'])==('plan_next','2030-01-14',True,'plan_day',1)
    with client_for(Scripted([long_draft()])) as client:
        state=accepted(client)
        state=post(client,'/tasks/status',state,task_id=state['planner']['active']['editable_tasks'][0]['id'],status='completed')
        planning=state['planner']['week_planning']
        assert (planning['available'],planning['reason'],planning['week_done'])==(True,'week_done',True)
    with client_for(Scripted([long_draft()]),clock=clock) as client:
        clock.now=NOW
        state=accepted(client,plan_day=4)  # Friday
        assert state['planner']['week_planning']['plan_day']=='2030-01-11' and not state['planner']['week_planning']['available']
        clock.now=NOW+timedelta(days=2)
        assert read(client)['planner']['week_planning']['available']

def test_next_week_carries_unfinished_work_once_and_proposes_later_changes_for_review():
    clock=Clock()
    change={'week_start':'2030-01-21','objective':'Catch up on endpoint tests.','expected_outcome':'Every endpoint has a passing test.','estimated_minutes':220,
        'milestone_key':'m1','gap_ids':['python'],'reason':'The first week slipped, so testing moves here.'}
    next_week=lambda context:week_draft([task('b1','Add a second endpoint'),task('b2','Validate request bodies'),task('b3','Return clear errors'),task('b4','Tidy the README',30)],
        carryover=carry_all()(context),objective_changes=[change])
    model=Scripted([long_draft()],weeks=[week_draft([assignment()]),next_week])
    with client_for(model,clock=clock) as client:
        state=accepted(client);first=state['planner']['active']['editable_tasks'][0]
        clock.now=SUNDAY
        state=plan_week(client,read(client),'2030-01-14',feedback={'workload':'too_light','note':'I could do more.'})
        assert state['operation']['status']=='succeeded',state['operation']
        sent=model.sent('WeekDraft')[-1]
        assert [t['task_id'] for t in sent['progress']['unfinished']]==[first['id']] and sent['feedback']['workload']=='too_light'
        assert sent['last_week']=={'tasks_planned':1,'tasks_completed':0,'minutes_planned':60,'minutes_completed':0,'average_difficulty':None,'average_confidence':None}
        assert sent['objective']['week_start']=='2030-01-14' and 'date' not in str(sent['progress'])
        planner=state['planner'];preview=planner['week_candidate']
        assert planner['active']['editable_tasks']==[first] or planner['active']['editable_tasks'][0]['schedule']==first['schedule']
        entry=preview['carryover'][0]
        assert (entry['task_id'],entry['action'],entry['proposed_action'],entry['adjusted'])==(first['id'],'carry','carry',False)
        assert entry['schedule']==[{'date':'2030-01-14','start_time':'19:00','duration_minutes':60}] and entry['previous_schedule']==first['schedule']
        placed={t['generated_key']:[(s['date'],s['start_time'],s['duration_minutes']) for s in t['schedule']] for t in preview['tasks']}
        assert placed=={'b1':[('2030-01-16','19:00',60)],'b2':[('2030-01-19','10:00',60)],'b3':[('2030-01-19','11:10',60)],'b4':[('2030-01-14','20:10',30)]}
        assert preview['objective_changes'][0]['previous']['objective']=='Advance Build a Python API' and preview['objective_changes'][0]['reason']==change['reason']
        assert sorted(row['title'] for row in planner['preview_sessions'])==sorted(['Write one tested endpoint','Add a second endpoint','Validate request bodies','Return clear errors','Tidy the README'])
        again=request(client,'/weeks/generate',state,week_start='2030-01-14',feedback={'workload':'too_light','note':'I could do more.'})
        assert again.status_code==409 and again.json()['code']=='week_preview_exists'
        state=accept_week(client,state);planner=state['planner'];tasks=planner['active']['editable_tasks']
        assert len(tasks)==5 and [t['id'] for t in tasks].count(first['id'])==1
        moved=next(t for t in tasks if t['id']==first['id'])
        assert moved['schedule']==entry['schedule'] and moved['status']=='not_started'
        assert (moved['history'][-1]['event'],moved['history'][-1]['reason'])==('carried','Still the next step.')
        assert planner['outline_active']['revision']==2 and planner['outline_active']['weeks'][2]['objective']=='Catch up on endpoint tests.'
        assert planner['outline_active']['weeks'][2]['revised_reason']==change['reason']
        assert [(b['week_start'],b['feedback'] and b['feedback']['workload']) for b in planner['week_blocks']]==[('2030-01-07',None),('2030-01-14','too_light')]
        assert request(client,'/weeks/generate',state,week_start='2030-01-14').json()['code']=='week_already_accepted'
        assert len(model.sent('WeekDraft'))==2

def test_each_unfinished_task_gets_a_reviewed_decision_that_the_user_can_change():
    clock=Clock()
    two=draft(assignments=[task('a1','First',45),task('a2','Second',45)])
    drop_first=lambda context:week_draft([task('b1','Add a second endpoint'),task('b2','Validate request bodies')],
        carryover=[{'task_id':context['progress']['unfinished'][0]['task_id'],'action':'drop','reason':'Superseded by this week.'}])
    model=Scripted([two],weeks=[week_draft(two['assignments']),drop_first,week_draft()])
    with client_for(model,clock=clock) as client:
        state=accepted(client,break_minutes_per_hour=0)
        first,second=state['planner']['active']['editable_tasks']
        clock.now=SUNDAY
        state=plan_week(client,read(client),'2030-01-14')
        assert state['operation']['status']=='succeeded',state['operation']
        preview=state['planner']['week_candidate']
        assert [(c['title'],c['action']) for c in preview['carryover']]==[('First','drop'),('Second','carry')]
        assert 'your setting for unfinished work' in preview['carryover'][1]['reason']
        state=post(client,'/weeks/'+preview['id']+'/carryover',state,decisions=[{'task_id':first['id'],'action':'defer'}])
        entry=state['planner']['week_candidate']['carryover'][0]
        assert (entry['action'],entry['proposed_action'],entry['reason'])==('defer','drop','Your choice.')
        assert len(model.sent('WeekDraft'))==2
        state=accept_week(client,state);tasks={t['title']:t for t in state['planner']['active']['editable_tasks']}
        assert (tasks['First']['schedule'],tasks['First']['removed'],tasks['First']['deferred_week'])==([],False,'2030-01-14')
        assert tasks['First']['history'][-1]['event']=='deferred' and tasks['Second']['schedule'][0]['date']=='2030-01-14'
        clock.now=SUNDAY+timedelta(days=7)
        state=read(client);assert state['planner']['week_planning']['unfinished_count']==4
        state=plan_week(client,state,'2030-01-21')
        assert state['operation']['status']=='succeeded',state['operation']
        assert first['id'] in [t['task_id'] for t in model.sent('WeekDraft')[-1]['progress']['unfinished']]
        entries=state['planner']['week_candidate']['carryover']
        assert sum(c['estimated_minutes'] for c in entries if c['action']=='carry')==150
        held=[c for c in entries if c['adjusted']]
        assert len(held)==1 and held[0]['action']=='defer' and 'more than 150 minutes' in held[0]['reason']

def test_splitting_and_dropping_unfinished_work_keep_their_history():
    clock=Clock()
    two=draft(assignments=[task('a1','First',45),task('a2','Second',45)])
    decide=lambda context:week_draft([task('b1','Add a second endpoint'),task('b2','Validate request bodies')],carryover=[
        {'task_id':context['progress']['unfinished'][0]['task_id'],'action':'split','minutes':25,'reason':'Finish the first half.'},
        {'task_id':context['progress']['unfinished'][1]['task_id'],'action':'drop','reason':'No longer needed.'}])
    with client_for(Scripted([two],weeks=[week_draft(two['assignments']),decide]),clock=clock) as client:
        state=accepted(client,break_minutes_per_hour=0)
        clock.now=SUNDAY
        state=accept_week(client,plan_week(client,read(client),'2030-01-14'))
        tasks={t['title']:t for t in state['planner']['active']['editable_tasks'] if t.get('schedule') or t.get('removed')}
        remainder=next(t for t in state['planner']['active']['editable_tasks'] if t['history'] and t['history'][0].get('event')=='split_remainder')
        assert remainder['estimated_minutes']==20 and remainder['deferred_week']=='2030-01-14'
        assert remainder['id']!=tasks['First']['id']
        assert [(s['date'],s['duration_minutes']) for s in tasks['First']['schedule']]==[('2030-01-14',25)] and tasks['First']['estimated_minutes']==25
        assert tasks['First']['history'][-1]['event']=='split'
        state=post(client,'/tasks/status',state,task_id=tasks['First']['id'],status='completed')
        saved={t['id']:t for t in state['planner']['active']['editable_tasks']}
        assert saved[tasks['First']['id']]['status']=='completed'
        assert saved[remainder['id']]['status']=='not_started' and saved[remainder['id']]['estimated_minutes']==20
        assert saved[remainder['id']]['history'][0]['source_task_id']==tasks['First']['id']
        assert tasks['Second']['removed'] and tasks['Second']['removal']['reason']=='No longer needed.' and tasks['Second']['history'][-1]['event']=='removed'
        assert [row['title'] for row in state['planner']['active_sessions'] if row['title']=='Second']==[]

SPREAD=[{'day':2,'start_time':'19:00','duration_minutes':70},{'day':6,'start_time':'19:00','duration_minutes':70}]
def sunday_preview(client,clock,model):
    """Wednesday's task was missed and Sunday evening's is still ahead when next week is previewed on Sunday morning."""
    state=accepted(client,blocks=SPREAD,blackouts=[])
    clock.now=SUNDAY
    state=plan_week(client,read(client),'2030-01-14')
    assert state['operation']['status']=='succeeded',state['operation']
    return state
def spread_model():
    week_one=week_draft([task('a1','First'),task('a2','Second')])
    return Scripted([draft()],weeks=[week_one,lambda context:week_draft([task('b1','Add a second endpoint')],carryover=carry_all()(context))])

def test_progress_elsewhere_keeps_a_preview_valid_but_progress_on_carried_work_does_not():
    clock=Clock()
    with client_for(spread_model(),clock=clock) as client:
        state=sunday_preview(client,clock,None);tasks={t['title']:t for t in state['planner']['active']['editable_tasks']}
        assert [c['title'] for c in state['planner']['week_candidate']['carryover']]==['First']
        state=post(client,'/tasks/status',state,task_id=tasks['Second']['id'],status='completed')
        state=accept_week(client,state)
        done=next(t for t in state['planner']['active']['editable_tasks'] if t['title']=='Second')
        assert done['status']=='completed' and done['schedule']==tasks['Second']['schedule']
    clock=Clock()
    with client_for(spread_model(),clock=clock) as client:
        state=sunday_preview(client,clock,None);carried=state['planner']['week_candidate']['carryover'][0]['task_id']
        state=post(client,'/tasks/status',state,task_id=carried,status='completed')
        response=request(client,'/weeks/'+state['planner']['week_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='week_stale'
        after=read(client)
        assert next(t for t in after['planner']['active']['editable_tasks'] if t['id']==carried)['status']=='completed'

def test_schedule_settings_apply_from_the_next_week_and_shape_settings_need_the_outline_reviewed():
    clock=Clock()
    with client_for(spread_model(),clock=clock) as client:
        state=sunday_preview(client,clock,None)
        state=configure(client,state,blocks=[*SPREAD,{'day':1,'start_time':'07:00','duration_minutes':60}],blackouts=[])
        assert 'settings' not in {s['kind'] for s in state['planner']['signals']}
        response=request(client,'/weeks/'+state['planner']['week_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='week_stale'
        state=post(client,'/weeks/'+state['planner']['week_candidate']['id']+'/discard',state)
        state=configure(client,state,blocks=SPREAD,blackouts=[],weekly_minutes=240)
        assert 'settings' in {s['kind'] for s in state['planner']['signals']}
        response=request(client,'/weeks/generate',state,week_start='2030-01-14')
        assert response.status_code==409 and response.json()['code']=='settings_changed'

def test_revising_an_accepted_week_replaces_only_untouched_future_tasks():
    clock=Clock()
    first=lambda context:week_draft([task('b1','Add a second endpoint'),task('b2','Validate request bodies'),task('b3','Return clear errors'),task('b4','Tidy the README',30)],carryover=carry_all()(context))
    second=week_draft([task('r1','Write a health check'),task('r2','Add request logging'),task('r3','Document the endpoints',60)])
    model=Scripted([long_draft()],weeks=[week_draft([assignment()]),first,second])
    with client_for(model,clock=clock) as client:
        state=accepted(client);clock.now=SUNDAY
        state=accept_week(client,plan_week(client,read(client),'2030-01-14'))
        rows={row['title']:row for row in state['planner']['active_sessions']}
        state=post(client,'/sessions/save',state,session_id=rows['Add a second endpoint']['id'],changes={'title':'Add the orders endpoint'})
        before={t['generated_key']:t for t in state['planner']['active']['editable_tasks']}
        state=plan_week(client,state,'2030-01-14',revision=True)
        assert state['operation']['status']=='succeeded',state['operation']
        preview=state['planner']['week_candidate']
        assert sorted(preview['replaced_task_ids'])==sorted(before[key]['id'] for key in ('b2','b3','b4')) and preview['revision']==2
        state=accept_week(client,state);after={t['generated_key']:t for t in state['planner']['active']['editable_tasks']}
        assert set(after)=={'a1','b1','r1','r2','r3'} and after['b1']['title']=='Add the orders endpoint' and after['a1']==before['a1']
        slots=sorted((s['date'],s['start_time']) for t in after.values() for s in t['schedule'])
        assert len(slots)==len(set(slots))==6
        assert all(s['duration_minutes']<=60 for t in after.values() for s in t['schedule'])
        assert sum(s['duration_minutes'] for key in ('r1','r2','r3') for s in after[key]['schedule'])==180
        assert [b.get('revision',1) for b in state['planner']['week_blocks']]==[1,2]

def test_a_missed_planning_window_plans_the_current_week_from_today():
    clock=Clock()
    late=lambda context:week_draft([task('b1','Add a second endpoint',80),task('b2','Validate request bodies',160)],carryover=carry_all('defer')(context))
    with client_for(Scripted([long_draft()],weeks=[week_draft([assignment()]),late]),clock=clock) as client:
        state=accepted(client)
        clock.now=NOW+timedelta(days=7)  # Wednesday of the next week; nobody planned it on Sunday.
        state=read(client);planning=state['planner']['week_planning']
        assert (planning['action'],planning['week_start'],planning['available'],planning['reason'])==('plan_this','2030-01-14',True,'week_unplanned')
        state=plan_week(client,state,'2030-01-14')
        assert state['operation']['status']=='succeeded',state['operation']
        preview=state['planner']['week_candidate']
        assert preview['start_date']=='2030-01-16' and all(s['date']>='2030-01-16' for t in preview['tasks'] for s in t['schedule'])
        assert 'saved_work' not in [r['code'] for r in preview['target']['reasons']] and preview['target']['target_minutes']<300

# Compatibility with saved work

def test_saved_backup_blocks_months_and_legacy_previews_stay_readable():
    store=CleanableStore()
    with TestClient(create_app(store,Sources(),Scripted([long_draft()]),clock=lambda:NOW)) as client:
        state=accepted(client)
        row=store.data[OWNER];planner=row['planner']
        # As saved before weekly planning: a month block, a month preview, a legacy preview and backup settings.
        planner['week_blocks']=[]
        planner['month_blocks']=[{'id':'m-1','month':'2030-01','status':'accepted','start_date':'2030-01-09','end_exclusive':'2030-01-28','task_ids':[t['id'] for t in planner['active']['editable_tasks']],'outline_id':'x','config_hash':'h'}]
        planner['month_candidate']={'id':'m-2','month':'2030-02'};planner['candidate']={'id':'legacy'}
        planner['config'].update(use_backup=False);planner['config']['blocks'].append({'day':6,'start_time':'09:00','duration_minutes':120,'kind':'backup'})
        state=read(client);view=state['planner']
        assert len(view['config']['blocks'])==4 and 'use_backup' not in view['config'] and 'candidate' not in view
        assert view['month_blocks'][0]['month']=='2030-01'
        assert view['week_planning']['action'] is None
        assert [w['status'] for w in view['weeks']]==['planned','planned','planned']

def test_a_roadmap_from_before_weekly_planning_keeps_its_progress_and_is_invited_to_update():
    store=CleanableStore()
    with TestClient(create_app(store,Sources(),Scripted([long_draft(),long_draft()]),clock=lambda:NOW)) as client:
        state=accepted(client)
        state=post(client,'/tasks/status',state,task_id=state['planner']['active']['editable_tasks'][0]['id'],status='completed')
        planner=store.data[OWNER]['planner'];planner['outline_active']=None;planner['week_blocks']=[]
        state=read(client)
        assert state['planner']['week_planning'] is None and [s['kind'] for s in state['planner']['signals']]==['progress']
        assert state['planner']['active']['assignments'][0]['status']=='completed'
        state=accept_outline(client,generate(client,state))
        done=state['planner']['active']['editable_tasks'][0]
        assert done['status']=='completed' and done['schedule']==[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}]

def test_reduced_periods_come_from_profile_and_lower_that_weeks_target():
    sources=Sources();sources.periods=[{'id':'p1','start_date':'2030-01-14','end_date':'2030-01-18','weekly_hours':2}]
    with client_for(Scripted([long_draft()]),sources) as client:
        state=configure(client,reduced_periods=[{'start_date':'2030-01-21','end_date':'2030-01-22','weekly_minutes':0}])
        assert state['planner']['config']['reduced_periods']==[{'start_date':'2030-01-14','end_date':'2030-01-18','weekly_minutes':120}]
        weeks=state['planner']['runway']['weeks']
        assert [(w['weekly_cap'],w['reduced']) for w in weeks]==[(300,False),(120,True),(300,False)]
        assert 'reduced_periods' in [n['code'] for n in state['planner']['runway']['notices']]
        state=configure(client,state,apply_reduced_periods=False)
        assert [w['weekly_cap'] for w in state['planner']['runway']['weeks']]==[300,300,300]

def test_a_saved_plan_or_settings_holding_old_fields_is_rejected_on_read():
    from pydantic import ValidationError
    with client_for(Scripted([draft()])) as client:
        plan=accepted(client)['planner']['active']
    for field,value in {'buffer_percent':20,'checkin_day':4,'checkin_time':'18:00','blackout_dates':['2030-02-01']}.items():
        with pytest.raises(ValidationError):PlannedRoadmap.model_validate({**plan,'config':{**plan['config'],field:value}})

# Settings, chat, sources and saved evaluation

def restarted(store,model=None,sources=None):
    return TestClient(create_app(store,sources or Sources(),model or Scripted(),clock=lambda:NOW))

def test_runway_is_shown_before_any_model_call_and_generation_is_gated():
    model=Scripted()
    with client_for(model) as client:
        state=read(client)
        assert state['planner']['config']['allow_overflow'] is True
        assert state['planner']['config_saved'] is False and not state['planner']['runway']['can_generate']
        assert {i['code'] for i in state['planner']['runway']['issues']}>={'missing_target','no_budget'}
        response=client.post('/api/v1/roadmaps/planner/runway',headers=H,json={'config':settings()})
        assert response.status_code==200 and response.json()['study']=={'preferred_minutes':690,'overflow_minutes':0,'usable_minutes':690}
        response=client.post('/api/v1/roadmaps/planner/outlines/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
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
        response=client.post('/api/v1/roadmaps/planner/outlines/generate',headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4())})
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

def test_missing_assessment_requires_explicit_evaluation_before_planning():
    sources=Sources();sources.result=None;model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
        assert sources.writes==[] and state['planner']['outline_candidate'] is None
        assert state['operation']['error']['code']=='assessment_required'
        assert model.contexts==[]

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
        assert model.sent('OutlineDraft')[-1]['confirmations']['sql']['answer']=='some_experience'
        assert state['operation']['status']=='succeeded',state['operation']
        assert not state['planner']['signals']

def test_changed_evidence_prompts_a_revision():
    sources=Sources();model=Scripted([draft()])
    with client_for(model,sources) as client:
        accepted(client);sources.hash='hash2'
        assert 'evidence' in {s['kind'] for s in read(client)['planner']['signals']}

def test_chat_collects_settings_without_generating_a_plan():
    patch={'target_date':'2030-01-27','weekly_minutes':300,'blocks':settings()['blocks'],'blackouts':[{'frequency':'once','start_date':'2030-01-12'}]}
    model=Scripted(chats=[{'reply':'Saved those. Please review the panel.','settings':patch}])
    with client_for(model) as client:
        state=chat(client,read(client),'Study until 27 Jan, five hours a week.')
        assert state['operation']['status']=='succeeded',state['operation']
        planner=state['planner']
        assert planner['config']['weekly_minutes']==300 and planner['config']['start_date']=='2030-01-09'
        assert planner['runway']['can_generate'] and planner['outline_candidate'] is None
        assert state['messages'][-1]['content']=='Saved those. Please review the panel.'
        assert len(model.contexts)==1 and model.contexts[0]['settings']['weekly_minutes'] is None

def test_invalid_chat_settings_change_nothing_and_are_explained():
    model=Scripted(chats=[{'reply':'Added your late block.','settings':{'blocks':[{'day':0,'start_time':'23:30','duration_minutes':60}]}}])
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

@pytest.mark.parametrize('extra',[{'buffer_percent':20},{'checkin_day':4},{'checkin_time':'18:00'},{'blackout_dates':['2030-02-01']},{'unknown_setting':True}])
def test_new_settings_requests_reject_retired_or_unknown_fields(extra):
    with client_for(Scripted()) as client:
        before=read(client)
        response=client.post('/api/v1/roadmaps/planner/config',headers=H,json={
            'expected_version':before['version'],'mutation_id':str(uuid4()),'config':settings(**extra)})
        assert response.status_code==422
        assert client.post('/api/v1/roadmaps/planner/runway',headers=H,json={'config':settings(**extra)}).status_code==422
        assert read(client)==before

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

def test_learning_steps_need_an_active_roadmap_and_make_no_upstream_or_model_calls():
    sources=Sources();model=Scripted([])
    with client_for(model,sources) as client:
        assert client.get('/api/v1/roadmaps/learning').status_code==401
        response=client.get('/api/v1/roadmaps/learning',headers=H);assert response.status_code==200,response.text
        assert response.json()=={'has_roadmap':False,'roadmap_id':None,'skills_total':0,'skills_started':0,'skills_done':0,'steps':[]}
    assert sources.reads==[] and sources.writes==[] and model.contexts==[]

def test_learning_steps_follow_the_active_roadmap_through_the_api():
    with client_for(Scripted([draft()])) as client:
        state=accepted(client);plan=state['planner']['active'];session=plan['assignments'][0]
        body=client.get('/api/v1/roadmaps/learning',headers=H).json()
        assert (body['has_roadmap'],body['roadmap_id'],body['skills_total'],body['skills_started'])==(True,plan['id'],1,0)
        assert body['steps'][0]['next_session']['id']==session['id'] and body['steps'][0]['state']=='not_started'
        post(client,'/assignments/status',state,assignment_id=session['id'],status='completed')
        body=client.get('/api/v1/roadmaps/learning',headers=H).json()
    step=body['steps'][0]
    assert (body['skills_started'],body['skills_done'],step['state'],step['sessions_completed'],step['next_session'])==(1,1,'done',1,None)

def test_learning_steps_report_each_skills_progress_in_priority_order():
    body=learning_view(learning_plan(),NOW)
    python,sql,rust=body['steps']
    assert [python['name'],sql['name'],rust['name']]==['Python','SQL','Rust']
    assert (body['skills_total'],body['skills_started'],body['skills_done'])==(3,2,0)
    assert (python['state'],python['sessions_total'],python['sessions_completed'],python['completed_minutes'],python['remaining_minutes'])==('in_progress',2,1,60,60)
    assert python['next_session']['task']=='Add a route.' and sql['next_session']['task']=='Write a join.'
    assert python['milestones']==['Build a Python API'] and rust['milestones']==[]
    assert (rust['state'],rust['sessions_total'],rust['next_session'])==('not_scheduled',0,None)
    LearningPlan.model_validate(body)

def test_a_passed_session_is_missed_rather_than_next():
    step=learning_view(learning_plan(),NOW+timedelta(days=30))['steps'][1]
    assert (step['name'],step['sessions_missed'],step['next_session'],step['state'])==('SQL',1,None,'in_progress')

@pytest.mark.parametrize('complete_after', [3, None])
def test_assessment_polling_uses_two_second_intervals_and_stops_at_sixty(monkeypatch, complete_after):
    import asyncio
    sleeps=[]
    original_sleep=asyncio.sleep
    async def sleep(seconds):
        sleeps.append(seconds)
        await original_sleep(0)
    monkeypatch.setattr('app.main.asyncio.sleep',sleep)
    class Processing(Sources):
        polls=0
        async def read(self,service,path,token,params=None):
            if path.endswith('/current') and not (complete_after and self.polls>=complete_after):
                return {'version':0,'ready':True,'result':None,'operation':{'status':'running'}}
            if path.endswith('/operation'):
                self.polls+=1
                if not (complete_after and self.polls>=complete_after):
                    return {'operation':{'status':'running'},'result':None}
            return await super().read(service,path,token,params)
    sources=Processing();model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
    assert sources.polls==(complete_after or 60)
    assert sleeps==[2]*(complete_after or 60)
    assert sources.writes==[]
    if complete_after:
        assert state['operation']['status']=='succeeded'
    else:
        assert state['operation']['error']['code']=='assessment_processing'
        assert model.contexts==[]

def test_current_evaluation_is_reused_with_skill_judgements_and_reference_metadata_only():
    sources=Sources();sources.result['skill_profile']['skills']=[{'name':'Python','competence_score':3,'required_score':5}]
    model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded'
    assert sources.writes==[] and not any(path.endswith('/operation') for path in sources.reads)
    sent=model.contexts[0]['assessment']
    assert sent['skill_profile']==sources.result['skill_profile']
    assert set(sent['evidence'])==set(sources.result['evidence'])
    assert all('text' not in record for record in sent['evidence'].values())

@pytest.mark.parametrize('kind',['outdated','legacy','unavailable'])
def test_unusable_saved_evaluation_never_starts_assessment_or_plan_model(kind):
    class NotCurrent(Sources):
        async def read(self,service,path,token,params=None):
            value=await super().read(service,path,token,params)
            if path.endswith('/current'):
                if kind=='legacy':value['result'].pop('skill_profile')
                else:value.update(stale=True,evaluation={'freshness':kind})
            return value
    sources=NotCurrent();model=Scripted([draft()])
    with client_for(model,sources) as client:
        state=generate(client,configure(client))
    assert state['operation']['error']['code']=='assessment_required'
    assert sources.writes==[] and model.contexts==[]

def test_preview_cannot_be_accepted_when_saved_evaluation_needs_an_update():
    class EvaluationSource(Sources):
        freshness='current'
        async def read(self,service,path,token,params=None):
            value=await super().read(service,path,token,params)
            if path.endswith('/context'):value['evaluation']={'freshness':self.freshness}
            return value
    sources=EvaluationSource()
    with client_for(Scripted([draft()]),sources) as client:
        state=generate(client,configure(client))
        assert state['planner']['outline_candidate']
        sources.freshness='outdated'
        response=request(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='assessment_required'
        state=read(client)
        assert state['planner']['outline_candidate'] and state['planner']['week_candidate'] and state['planner']['active'] is None

def test_a_restart_turns_old_blackout_dates_into_rules_without_a_settings_change():
    store=CleanableStore();model=Scripted([draft()])
    with restarted(store,model) as client:
        accepted(client)
    row=store.data[OWNER]
    for section in (row['planner'],row['planner']['active'],row['planner']['outline_active']):
        config=section['config']
        config['blackout_dates']=[rule['start_date'] for rule in config.pop('blackouts')]
    with restarted(store,model) as client:
        assert 'blackout_dates' not in store.data[OWNER]['planner']['config']
        state=read(client)
        assert state['planner']['config']['blackouts'][0]['start_date']=='2030-01-12'
        assert 'settings' not in {s['kind'] for s in state['planner']['signals']}

def learning_plan():
    def session(key,**changes):return {**assignment(key,**changes),'id':key,'status':changes.get('status','scheduled')}
    return {'id':'plan1','config':settings(),'gaps':[gap('sql',name='SQL',priority=2),gap('python'),gap('rust',name='Rust',status='unknown',priority=3)],
        'milestones':[{**milestone(gap_ids=['python','sql']),'id':'m1'}],
        'assignments':[session('a1',status='completed'),session('a2',gap_id='sql',date='2030-01-14',task='Write a join.'),session('a3',gap_id='python',date='2030-01-15',task='Add a route.')]}
