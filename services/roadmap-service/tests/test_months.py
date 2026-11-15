from datetime import date, datetime, timezone
import copy
import pytest
from elo_shared.runtime import Problem, digest
from app.planning.months import month_interval, routine_occurrences, check_tasks, accept_month
from app.planning.state import config_digest
from app.schemas.months import MonthDraft
from app.schemas.roadmap import PlannerConfig

NOW=datetime(2028,2,15,0,0,tzinfo=timezone.utc)
def config(**updates):
    return PlannerConfig.model_validate({'start_date':'2028-02-15','target_date':'2028-03-20',
        'weekly_minutes':420,'time_zone':'Asia/Singapore','blocks':[
            {'day':d,'start_time':'19:00','duration_minutes':60,'kind':'preferred'} for d in range(7)],**updates})
def outline(**updates):
    cfg=config()
    return {'id':'outline-1','revision':1,'status':'accepted','config':cfg.model_dump(mode='json'),
        'config_hash':config_digest(cfg),'assessment_id':'assessment','assessment_hash':'source',
        'assessment':{},'confirmations_hash':digest({}),'first_planning_week':'2028-02-14',
        'summary':'Plan','gaps':[],'milestones':[{'id':'m','key':'m','title':'Build',
        'estimated_minutes':3000,'projected_start':'2028-02-15','projected_end':'2028-03-20',
        'gap_ids':[],'prerequisite_keys':[],'demonstrable_outcome':'Show work','outcome':{'demonstrated':False}}],
        'deadline_outcome':{'summary':'Build','fits_in_runway':True,'achievable_by_target':[]},
        'beyond_deadline':[],'exclusions':[],'routine_rules':[],'generation':{},**updates}
def rule(**updates):
    return {'id':'practice','revision':1,'milestone_key':'m','activity':'Solve one problem',
        'weekdays':list(range(7)),'duration_minutes':30,'topic_progression':['arrays','graphs'],
        'difficulty':'medium','start_date':'2028-02-15','end_date':'2028-03-20','user_wording':'Choose and solve a problem.',**updates}

def test_month_windows_include_leap_day_and_trim_first_and_final_month():
    assert month_interval('2028-02',config(),NOW)==(date(2028,2,15),date(2028,3,1))
    assert month_interval('2028-03',config(),NOW)==(date(2028,3,1),date(2028,3,21))
    with pytest.raises(Problem):month_interval('2028-01',config(),NOW)

def test_routine_occurrences_are_stable_and_removed_dates_do_not_reappear():
    o=outline(routine_rules=[rule()]);first=routine_occurrences(o,date(2028,2,28),date(2028,3,1),NOW,None)
    assert [t['schedule'][0]['date'] for t in first]==['2028-02-28','2028-02-29']
    first[0]['removed']=True
    again=routine_occurrences(o,date(2028,2,28),date(2028,3,1),NOW,{'editable_tasks':first})
    assert again==[]
    assert routine_occurrences(o,date(2028,2,28),date(2028,3,1),NOW,None)[0]['id']==first[0]['id']


def test_month_revision_preserves_notes_and_self_ratings_from_session_editor():
    from app.planning.months import revision_basis
    o=outline(routine_rules=[rule(start_date='2028-02-15',end_date='2028-02-17')])
    tasks=routine_occurrences(o,date(2028,2,15),date(2028,2,18),NOW,None)
    tasks[0]['notes']={'blocks':[{'type':'paragraph','text':'Keep these notes'}]}
    tasks[1]['self_rating']={'confidence':7,'difficulty':4,'recorded_at':'2028-02-15T00:00:00Z'}
    block={'task_ids':[t['id'] for t in tasks]}
    basis,replaced=revision_basis({'editable_tasks':tasks,'milestones':o['milestones']},block,NOW,config())
    assert replaced==[tasks[2]['id']]
    assert [t['id'] for t in basis['editable_tasks']]==[tasks[0]['id'],tasks[1]['id']]


def test_empty_or_duplicate_month_does_not_silently_hide_unfinished_work():
    o=outline();start=date(2028,2,15);end=date(2028,3,1)
    empty=MonthDraft.model_validate({'tasks':[]})
    assert any('no planned work' in e for e in check_tasks(empty,o,start,end,NOW,None,[]))
    task={'key':'x','milestone_key':'m','title':'Practise arrays','instructions':'Practise.',
          'completion_outcome':'Save notes.','date':'2028-02-15','start_time':'19:00','duration_minutes':30}
    deleted={'id':'old','title':'Practise arrays','milestone_key':'m','estimated_minutes':30,
             'removed':True,'status':'not_started','schedule':[{'date':'2028-02-15','start_time':'19:00','duration_minutes':30}]}
    errors=check_tasks(MonthDraft.model_validate({'tasks':[task]}),o,start,end,NOW,{'editable_tasks':[deleted]},[])
    assert any('duplicates saved' in e for e in errors)
    later={**task,'date':'2028-02-16'}
    errors=check_tasks(MonthDraft.model_validate({'tasks':[later]}),o,start,end,NOW,{'editable_tasks':[deleted]},[])
    assert any('duplicates removed or overdue' in e for e in errors)
    overdue={**deleted,'removed':False,'schedule':[{'date':'2028-02-14','start_time':'19:00','duration_minutes':30}]}
    errors=check_tasks(MonthDraft.model_validate({'tasks':[later]}),o,start,end,NOW,{'editable_tasks':[overdue]},[])
    assert any('duplicates removed or overdue' in e for e in errors)

def test_blackout_and_weekly_cap_produce_explicit_routine_conflict():
    cfg=config(weekly_minutes=30)
    o=outline(config=cfg.model_dump(mode='json'),routine_rules=[rule()])
    with pytest.raises(Problem) as e:routine_occurrences(o,date(2028,2,28),date(2028,3,2),NOW,None)
    assert e.value.code=='routine_conflict'
    cfg=config(blackouts=[{'frequency':'once','start_date':'2028-02-28'}])
    o=outline(config=cfg.model_dump(mode='json'),routine_rules=[rule()])
    with pytest.raises(Problem) as e:routine_occurrences(o,date(2028,2,28),date(2028,3,1),NOW,None)
    assert e.value.code=='routine_conflict'

def test_cross_month_weekly_capacity_includes_saved_adjacent_block():
    cfg=config(weekly_minutes=60);o=outline(config=cfg.model_dump(mode='json'))
    existing={'editable_tasks':[{'id':'old','removed':False,'estimated_minutes':60,'milestone_key':'m',
        'schedule':[{'date':'2028-02-29','start_time':'19:00','duration_minutes':60}]}]}
    draft=MonthDraft.model_validate({'tasks':[{'key':'next','milestone_key':'m','title':'Build a prototype',
        'instructions':'Build the prototype.','completion_outcome':'Save a working prototype.',
        'date':'2028-03-01','start_time':'19:00','duration_minutes':30}]})
    assert any('weekly budget' in error for error in check_tasks(draft,o,date(2028,3,1),date(2028,4,1),NOW,existing,[]))

def test_accept_preserves_old_work_and_rejects_stale_or_duplicate_month():
    o=outline();existing={'editable_tasks':[{'id':'old','title':'Old','instructions':'Old','completion_outcome':'Done',
        'estimated_minutes':30,'requirement_refs':[],'prerequisites':[],'milestone_key':'m',
        'schedule':[{'date':'2028-02-16','start_time':'19:00','duration_minutes':30}],'status':'completed',
        'origin':'user','removed':False,'evidence_note':'Keep this note','history':[]}],
        'milestones':copy.deepcopy(o['milestones']),'assignments':[]}
    proposed=routine_occurrences(outline(routine_rules=[rule(weekdays=[4])]),date(2028,2,18),date(2028,2,19),NOW,existing)
    candidate={'id':'preview','month':'2028-02','status':'preview','outline_id':'outline-1','outline_revision':1,
        'basis':digest(existing),'tasks':proposed}
    state={'active':existing,'outline_active':o,'config':o['config'],'month_candidate':candidate}
    accept_month(state,{'ready':True,'input_hash':'source'},'preview',NOW)
    assert state['active']['editable_tasks'][0]['evidence_note']=='Keep this note'
    assert state['month_blocks'][0]['task_ids']==[proposed[0]['id']]
    state['month_candidate']={**candidate,'basis':digest(state['active'])}
    with pytest.raises(Problem) as e:accept_month(state,{'ready':True,'input_hash':'source'},'preview',NOW)
    assert e.value.code=='month_already_accepted'

def test_explicit_month_preview_and_acceptance_keep_existing_api_views():
    import time
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from app.schemas.outlines import OutlineDraft
    from test_outline import outline as draft_outline
    from test_planner_flow import H, Sources, configure, finish, read
    from planner_fixtures import NOW as FLOW_NOW
    class Model:
        configured=True
        def __init__(self):self.calls=0
        async def generate(self,schema,instructions,context,max_tokens=8192):
            self.calls+=1
            if schema is OutlineDraft:
                return draft_outline(routine_rules=[{'id':'r','milestone_key':'m1','activity':'Practise arrays',
                    'weekdays':[2],'duration_minutes':30,'start_date':'2030-01-09','end_date':'2030-01-09'}])
            assert schema is MonthDraft
            if self.calls>2:return MonthDraft.model_validate({'tasks':[]})
            return MonthDraft.model_validate({'tasks':[{'key':'first','milestone_key':'m1',
                'title':'Write an API endpoint','instructions':'Write and test a Python endpoint.',
                'completion_outcome':'Save a passing test.','date':'2030-01-09',
                'start_time':'19:30','duration_minutes':60}]})
    model=Model()
    with TestClient(create_app(MemoryStore(),Sources(),model,clock=lambda:FLOW_NOW)) as client:
        state=configure(client)
        body=lambda state,**values:{'expected_version':state['version'],'mutation_id':str(uuid4()),**values}
        response=client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H)
        assert response.status_code==409 and response.json()['code']=='outline_required'
        response=client.post('/api/v1/roadmaps/planner/outlines/generate',json=body(state),headers=H)
        assert response.status_code==202,response.text
        state=finish(client);outline_id=state['planner']['outline_candidate']['id']
        response=client.post('/api/v1/roadmaps/planner/outlines/'+outline_id+'/accept',json=body(state),headers=H)
        assert response.status_code==200,response.text
        state=response.json()
        response=client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H)
        assert response.status_code==202,response.text
        time.sleep(.01)
        state=finish(client);assert state['operation']['status']=='succeeded',state['operation']
        candidate=state['planner']['month_candidate']
        assert state['planner']['active'] is None and len(candidate['tasks'])==2
        response=client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H)
        assert response.status_code==409 and response.json()['code']=='month_preview_exists'
        path='/api/v1/roadmaps/planner/months/'+candidate['id']+'/accept';request=body(state)
        response=client.post(path,json=request,headers=H);assert response.status_code==200,response.text
        state=response.json();assert len(state['planner']['active']['editable_tasks'])==2
        assert len(state['planner']['active']['assignments'])==2
        assert state['planner']['active']['editable_tasks'][0]['routine_rule_id']=='r'
        assert state['planner']['active']['assignments'][1]['task']=='Write an API endpoint'
        assert read(client)['planner']['active']['editable_tasks'][0]['routine_rule_id']=='r'
        assert client.post(path,json=request,headers=H).status_code==200
        response=client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H)
        assert response.status_code==409 and response.json()['code']=='month_already_accepted'
        task=state['planner']['active']['editable_tasks'][1]
        response=client.post('/api/v1/roadmaps/planner/tasks/status',json=body(state,task_id=task['id'],status='completed',evidence_note='Saved note'),headers=H)
        assert response.status_code==200,response.text
        state=response.json()
        response=client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01',revision=True),headers=H)
        assert response.status_code==202,response.text
        time.sleep(.01);state=finish(client)
        assert state['operation']['status']=='succeeded',state['operation']
        revision=state['planner']['month_candidate']
        assert revision['revision']==2 and len(revision['replaced_task_ids'])==1
        response=client.post('/api/v1/roadmaps/planner/months/'+revision['id']+'/accept',json=body(state),headers=H)
        assert response.status_code==200,response.text
        state=response.json()
        assert len(state['planner']['month_blocks'])==1 and state['planner']['month_blocks'][0]['revision']==2
        saved=next(t for t in state['planner']['active']['editable_tasks'] if t['id']==task['id'])
        assert saved['status']=='completed' and saved['evidence_note']=='Saved note'
        assert model.calls==3

def test_month_validation_rejects_unrelated_gap_and_missing_diagnostic():
    o=outline(gaps=[{'id':'unknown','status':'unknown','plan_impact':'material','resolution':'diagnostic'}])
    task={'key':'x','milestone_key':'m','title':'Check foundations','instructions':'Try the exercise.',
        'completion_outcome':'Save notes.','date':'2028-02-15','start_time':'19:00',
        'duration_minutes':30,'kind':'diagnostic','gap_id':'unknown'}
    draft=MonthDraft.model_validate({'tasks':[task]})
    errors=check_tasks(draft,o,date(2028,2,15),date(2028,3,1),NOW,None,[],diagnostic_week=date(2028,2,14))
    assert any('gap outside its milestone' in e for e in errors)
    o['milestones'][0]['gap_ids']=['unknown']
    assert not check_tasks(draft,o,date(2028,2,15),date(2028,3,1),NOW,None,[],diagnostic_week=date(2028,2,14))
    draft=MonthDraft.model_validate({'tasks':[]})
    assert any('needs a diagnostic' in e for e in check_tasks(draft,o,date(2028,2,15),date(2028,3,1),NOW,None,[],diagnostic_week=date(2028,2,14)))

def test_month_preview_size_limit_is_explicit():
    from app.planning.months import bounded_size
    with pytest.raises(Problem) as e:bounded_size({'text':'x'*200},100,'Reduce this month.')
    assert e.value.code=='month_capacity'

def test_new_month_reopens_demonstrated_milestone_after_membership_changes():
    o=outline();old=copy.deepcopy(o['milestones'][0]);old['outcome']={'demonstrated':True,'note':'Old outcome','recorded_at':'2028-02-14T00:00:00Z'}
    old['demonstrable_outcome']='Previous definition'
    existing={'editable_tasks':[],'milestones':[old],'assignments':[]}
    new=routine_occurrences(outline(routine_rules=[rule(weekdays=[1])]),date(2028,2,15),date(2028,2,16),NOW,existing)
    candidate={'id':'preview','month':'2028-02','status':'preview','outline_id':'outline-1','outline_revision':1,
        'basis':digest(existing),'tasks':new}
    state={'active':existing,'outline_active':o,'config':o['config'],'month_candidate':candidate}
    accept_month(state,{'ready':True,'input_hash':'source'},'preview',NOW)
    outcome=state['active']['milestones'][0]['outcome']
    assert outcome['definition_review_required'] and outcome['previous_definition']=='Previous definition'
    assert outcome['membership_review_required']

def test_expired_preview_can_be_discarded_and_regenerated():
    import time
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from app.schemas.outlines import OutlineDraft
    from test_outline import outline as draft_outline
    from test_planner_flow import H, Sources, configure, finish
    from planner_fixtures import NOW as FLOW_NOW
    clock=[FLOW_NOW]
    class Model:
        configured=True
        async def generate(self,schema,instructions,context,max_tokens=8192):
            if schema is OutlineDraft:return draft_outline()
            window=context['windows'][0]
            return MonthDraft.model_validate({'tasks':[{'key':'first','milestone_key':'m1',
                'title':'Write an API endpoint','instructions':'Write and test a Python endpoint.',
                'completion_outcome':'Save a passing test.','date':window['date'],
                'start_time':window['start_time'],'duration_minutes':60}]})
    with TestClient(create_app(MemoryStore(),Sources(),Model(),clock=lambda:clock[0])) as client:
        state=configure(client);body=lambda s,**v:{'expected_version':s['version'],'mutation_id':str(uuid4()),**v}
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',json=body(state),headers=H).status_code==202
        state=finish(client);oid=state['planner']['outline_candidate']['id']
        state=client.post(f'/api/v1/roadmaps/planner/outlines/{oid}/accept',json=body(state),headers=H).json()
        assert client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H).status_code==202
        time.sleep(.01);state=finish(client);preview=state['planner']['month_candidate']['id']
        clock[0]=datetime(2030,1,10,0,0,tzinfo=timezone.utc)
        response=client.post(f'/api/v1/roadmaps/planner/months/{preview}/accept',json=body(state),headers=H)
        assert response.status_code==409 and response.json()['code']=='month_stale'
        response=client.post(f'/api/v1/roadmaps/planner/months/{preview}/discard',json=body(state),headers=H)
        assert response.status_code==200,response.text
        state=response.json();assert state['planner']['month_candidate'] is None
        assert client.post('/api/v1/roadmaps/planner/months/generate',json=body(state,month='2030-01'),headers=H).status_code==202
        time.sleep(.01);state=finish(client)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['month_candidate']['tasks'][0]['schedule'][0]['date']=='2030-01-14'

def test_routine_revision_keeps_protected_tasks_and_updates_only_future_occurrences():
    from app.planning.months import revision_basis
    old_outline=outline(routine_rules=[rule(start_date='2028-02-15',end_date='2028-02-18')])
    original=routine_occurrences(old_outline,date(2028,2,15),date(2028,2,19),NOW,None)
    original[0].update(status='completed',evidence_note='Kept note',completed_at='2028-02-15T01:00:00Z')
    original[1]['overrides']=['title'];original[1]['title']='My edited task'
    original[2]['removed']=True
    existing={'editable_tasks':copy.deepcopy(original),'milestones':copy.deepcopy(old_outline['milestones']),'assignments':[]}
    block={'id':'old-block','month':'2028-02','status':'accepted','revision':1,'task_ids':[t['id'] for t in original]}
    new_outline=outline(id='outline-2',revision=2,routine_rules=[rule(activity='Review one problem',start_date='2028-02-15',end_date='2028-02-18')])
    basis,replaced=revision_basis(existing,block,NOW,config())
    assert replaced==[original[3]['id']]
    generated=routine_occurrences(new_outline,date(2028,2,15),date(2028,2,19),NOW,basis)
    assert [t['id'] for t in generated]==replaced
    assert generated[0]['title'].startswith('Review one problem')
    candidate={'id':'new-block','month':'2028-02','status':'preview','outline_id':'outline-2','outline_revision':2,
        'basis':digest(existing),'tasks':generated,'revision':2,'replaces_block_id':'old-block','replaced_task_ids':replaced}
    state={'active':existing,'outline_active':new_outline,'config':new_outline['config'],
        'month_candidate':candidate,'month_blocks':[block]}
    accept_month(state,{'ready':True,'input_hash':'source'},'new-block',NOW)
    tasks=state['active']['editable_tasks'];assert len(tasks)==4
    assert tasks[0]['evidence_note']=='Kept note' and tasks[1]['title']=='My edited task' and tasks[2]['removed']
    assert tasks[3]['id']==original[3]['id'] and tasks[3]['title'].startswith('Review one problem')
    assert len(state['month_blocks'])==1 and state['month_blocks'][0]['revision']==2
    assert state['month_blocks'][0]['task_ids']==[t['id'] for t in tasks]
    assert state['month_history'][0]['id']=='old-block'

def test_model_work_reserves_later_routine_effort():
    o=outline(routine_rules=[rule(weekdays=[3],start_date='2028-03-02',end_date='2028-03-09')])
    o['milestones'][0]['estimated_minutes']=90
    draft=MonthDraft.model_validate({'tasks':[{'key':'work','milestone_key':'m','title':'Build a prototype',
        'instructions':'Build the prototype.','completion_outcome':'Save a working prototype.',
        'date':'2028-02-15','start_time':'19:00','duration_minutes':60}]})
    assert any('estimated effort' in e for e in check_tasks(draft,o,date(2028,2,15),date(2028,3,1),NOW,None,[]))

def test_model_uses_preferred_windows_before_backup():
    cfg=config(use_backup=True,blocks=[{'day':1,'start_time':'19:00','duration_minutes':60,'kind':'preferred'},
        {'day':2,'start_time':'19:00','duration_minutes':60,'kind':'backup'}])
    o=outline(config=cfg.model_dump(mode='json'))
    draft=MonthDraft.model_validate({'tasks':[{'key':'work','milestone_key':'m','title':'Build a prototype',
        'instructions':'Build the prototype.','completion_outcome':'Save a working prototype.',
        'date':'2028-02-16','start_time':'19:00','duration_minutes':30}]})
    assert any('preferred window' in e for e in check_tasks(draft,o,date(2028,2,15),date(2028,3,1),NOW,None,[]))
