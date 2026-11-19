"""Synthetic outline validation and publication: no provider or database calls."""
import copy
from datetime import date
from planner_fixtures import NOW, assessment, assignment, draft, gap, milestone, settings
from app.planning.capacity import Capacity
from app.planning.outlines import build_outline, clamp_to_start, draft_from_outline, validate_outline
from app.schemas.outlines import OutlineDraft
from app.schemas.roadmap import PlannerConfig
from app.schemas.weeks import WeekDraft

def outline(**changes):
    data=draft();data.pop('assignments');data['routine_rules']=[];data.update(changes)
    return OutlineDraft.model_validate(data)

def with_weeks(value,context):
    """The outline as the model must return it: a weekly objective for each week a milestone covers."""
    from test_planner_flow import objectives
    data=value.model_dump(mode='json');data['weeks']=objectives(data,context)
    return OutlineDraft.model_validate(data)
def first_week():
    from test_planner_flow import week_draft
    return WeekDraft.model_validate(week_draft([assignment()]))

def codes(value,config=None):
    capacity=Capacity(PlannerConfig.model_validate(config or settings()),NOW)
    return {e['code'] for e in validate_outline(value,capacity,assessment(),{})}

def test_outline_allows_diagnostic_intent_without_premature_task():
    unknown=gap('sql',name='SQL',requirement_ref='job:sql',status='unknown',resolution='diagnostic')
    value=outline(gaps=[gap(),unknown],milestones=[milestone(gap_ids=['python','sql'])])
    assert not codes(value)

def test_outline_rejects_dependency_cycles_and_overloaded_milestones():
    value=outline(milestones=[milestone(prerequisite_keys=['m2']),milestone('m2',prerequisite_keys=['m1'],estimated_minutes=600)])
    assert {'prerequisite_cycle','milestone_capacity_exceeded'} <= codes(value)

def test_routine_conflicts_are_explicit_and_effort_is_in_milestone():
    routine={'id':'daily','milestone_key':'m1','activity':'Solve one array problem','weekdays':[0,1,2,3,4,5,6],
        'duration_minutes':60,'start_date':'2030-01-09','end_date':'2030-01-15'}
    result=codes(outline(routine_rules=[routine]))
    assert 'routine_conflict' in result
    assert 'routine_effort_exceeds_milestone' in result

def test_revision_preserves_outcomes_and_increments_changed_routine():
    config=PlannerConfig.model_validate(settings())
    rule={'id':'r1','milestone_key':'m1','activity':'Practise arrays','weekdays':[2],
        'duration_minutes':30,'start_date':'2030-01-09','end_date':'2030-01-09'}
    value=outline(routine_rules=[rule])
    first=build_outline(value,assessment(),config,'2030-01-07','operation-1',1,None,{})
    first['milestones'][0]['outcome']={'demonstrated':True}
    changed=value.model_dump(mode='json');changed['routine_rules'][0]['duration_minutes']=40
    changed['milestones'][0]['demonstrable_outcome']='A different observable result.'
    second=build_outline(OutlineDraft.model_validate(changed),assessment(),config,'2030-01-07','operation-2',1,first,{})
    assert second['revision']==2 and second['base_active_id']==first['id']
    assert second['routine_rules'][0]['revision']==2
    assert second['milestones'][0]['outcome']['definition_review_required']
    assert draft_from_outline(second).routine_rules[0].revision==2

def test_outline_preview_edit_and_accept_are_versioned_and_preserve_work():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from test_planner_flow import H, Sources, configure, finish, read
    class Model:
        configured=True
        def __init__(self):self.calls=0
        async def generate(self,schema,instructions,context,max_tokens=8192):
            if schema is WeekDraft:return first_week()
            assert schema is OutlineDraft
            self.calls+=1
            return with_weeks(outline(),context)
    model=Model()
    with TestClient(create_app(MemoryStore(),Sources(),model,clock=lambda:NOW)) as client:
        state=configure(client)
        body={'expected_version':state['version'],'mutation_id':str(uuid4()),'allow_partial_assessment':False}
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',json=body,headers=H).status_code==202
        state=finish(client)
        assert state['operation']['status']=='succeeded',state['operation']
        candidate=state['planner']['outline_candidate']
        assert state['planner']['active'] is None and state['planner']['outline_active'] is None
        assert model.calls==1 and 'assignments' not in candidate and len(candidate['weeks'])==3
        assert state['planner']['week_candidate']['outline_id']==candidate['id']
        path='/api/v1/roadmaps/planner/outlines/'+candidate['id']
        invalid=draft_from_outline(candidate).model_dump(mode='json')
        invalid['milestones'][0]['prerequisite_keys']=['missing']
        response=client.patch(path,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'outline':invalid},headers=H)
        assert response.status_code==422
        assert read(client)['planner']['outline_candidate']['id']==candidate['id']
        edited=draft_from_outline(candidate).model_dump(mode='json');edited['summary']='Edited outline.'
        response=client.patch(path,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'outline':edited},headers=H)
        assert response.status_code==200,response.text
        state=response.json();candidate=state['planner']['outline_candidate']
        assert state['planner']['week_candidate'] is None
        path='/api/v1/roadmaps/planner/outlines/'+candidate['id']+'/accept'
        body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        response=client.post(path,json=body,headers=H);assert response.status_code==200,response.text
        state=response.json();assert state['planner']['outline_active']['summary']=='Edited outline.'
        assert state['planner']['outline_candidate'] is None and state['planner']['active']['editable_tasks']==[]
        assert state['planner']['week_planning']['action']=='plan_this'
        assert client.post(path,json=body,headers=H).status_code==200
        assert model.calls==1

def test_outline_revision_does_not_double_count_existing_routine():
    from uuid import NAMESPACE_URL, uuid5
    from app.planning.outlines import outline_reservations
    config=PlannerConfig.model_validate(settings())
    rule={'id':'r1','milestone_key':'m1','activity':'Practise arrays','weekdays':[2],
        'duration_minutes':60,'start_date':'2030-01-09','end_date':'2030-01-09'}
    value=outline(milestones=[milestone(estimated_minutes=60,projected_end='2030-01-09')],routine_rules=[rule])
    ident=str(uuid5(NAMESPACE_URL,'roadmap:routine:r1:2030-01-09'))
    existing={'editable_tasks':[{'id':ident,'milestone_key':'m1','estimated_minutes':60,'removed':False,
        'schedule':[{'date':'2030-01-09','start_time':'19:00','duration_minutes':60}]}]}
    capacity=Capacity(config,NOW,outline_reservations(existing))
    assert not validate_outline(value,capacity,assessment(),{},existing=existing)

def test_outline_payload_is_bounded_below_gateway_limit():
    import pytest
    from pydantic import ValidationError
    very_large=[gap(str(n),name='Synthetic',rationale='x'*3999) for n in range(15)]
    with pytest.raises(ValidationError,match='outline is too large'):
        outline(gaps=very_large)

def test_operation_key_cannot_be_reused_across_generate_routes():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from test_planner_flow import H, Sources, configure, finish
    class Model:
        configured=True
        async def generate(self,schema,instructions,context,max_tokens=8192):return first_week() if schema is WeekDraft else with_weeks(outline(),context)
    with TestClient(create_app(MemoryStore(),Sources(),Model(),clock=lambda:NOW)) as client:
        state=configure(client)
        body={'expected_version':state['version'],'mutation_id':str(uuid4()),'allow_partial_assessment':False}
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',json=body,headers=H).status_code==202
        assert finish(client)['operation']['status']=='succeeded'
        reused={'expected_version':body['expected_version'],'mutation_id':body['mutation_id'],'week_start':'2030-01-07'}
        assert client.post('/api/v1/roadmaps/planner/weeks/generate',json=reused,headers=H).status_code==409

def test_chat_revision_refines_outline_without_legacy_tasks():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from app.schemas.roadmap import ChatTurn
    from test_planner_flow import H, Sources, configure, finish
    class Model:
        configured=True
        def __init__(self):self.schemas=[]
        async def generate(self,schema,instructions,context,max_tokens=8192):
            self.schemas.append(schema)
            if schema is ChatTurn:return ChatTurn(reply='I will revise the outline.',revision_instruction='Practise arrays weekly.')
            if schema is WeekDraft:return first_week()
            assert schema is OutlineDraft
            return with_weeks(outline(summary='Revised outline.' if context.get('instruction') else 'Initial outline.'),context)
    model=Model()
    with TestClient(create_app(MemoryStore(),Sources(),model,clock=lambda:NOW)) as client:
        state=configure(client)
        body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',json=body,headers=H).status_code==202
        state=finish(client)
        accept='/api/v1/roadmaps/planner/outlines/'+state['planner']['outline_candidate']['id']+'/accept'
        state=client.post(accept,json={'expected_version':state['version'],'mutation_id':str(uuid4())},headers=H).json()
        message={'expected_version':state['version'],'mutation_id':str(uuid4()),'message':'Practise arrays weekly.'}
        assert client.post('/api/v1/roadmaps/messages',json=message,headers=H).status_code==202
        state=finish(client)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['outline_candidate']['summary']=='Revised outline.'
        assert len(state['planner']['active']['editable_tasks'])==1 and state['planner']['week_candidate'] is None
        assert model.schemas==[OutlineDraft,WeekDraft,ChatTurn,OutlineDraft]

def test_legacy_generation_month_and_roll_forward_routes_are_gone():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from test_planner_flow import H, Sources, configure
    class Model:
        configured=True
        async def generate(self,schema,instructions,context,max_tokens=8192):raise AssertionError('no model call')
    with TestClient(create_app(MemoryStore(),Sources(),Model(),clock=lambda:NOW)) as client:
        state=configure(client);body={'expected_version':state['version'],'mutation_id':str(uuid4())}
        for path in ('/planner/generate','/planner/accept','/planner/discard','/planner/roll-forward','/planner/tasks/reconcile','/planner/months/generate','/planner/months/x/accept','/planner/months/x/discard'):
            assert client.post('/api/v1/roadmaps'+path,json=body,headers=H).status_code==404,path


def test_milestone_outcome_cannot_be_a_generic_learning_goal():
    assert 'milestone_outcome_generic' in codes(outline(milestones=[milestone(demonstrable_outcome='Learn Python.')]))


def test_user_quoted_exclusion_survives_edit_and_accept_without_allowing_a_new_quote():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from elo_shared.runtime import MemoryStore
    from app.main import create_app
    from app.schemas.roadmap import ChatTurn
    from test_planner_flow import H, Sources, configure, finish
    quote='Please exclude Python for now.'
    class Model:
        configured=True
        async def generate(self,schema,instructions,context,max_tokens=8192):
            if schema is ChatTurn:return ChatTurn(reply='I will revise the outline.',revision_instruction=quote)
            if schema is WeekDraft:return first_week()
            if context.get('instruction'):
                return with_weeks(outline(milestones=[milestone(gap_ids=[])],exclusions=[{'requirement_ref':'job:python','reason':'User request','quote':quote}]),context)
            return with_weeks(outline(),context)
    with TestClient(create_app(MemoryStore(),Sources(),Model(),clock=lambda:NOW)) as client:
        state=configure(client)
        def body(state,**values):return {'expected_version':state['version'],'mutation_id':str(uuid4()),**values}
        assert client.post('/api/v1/roadmaps/planner/outlines/generate',json=body(state),headers=H).status_code==202
        state=finish(client);oid=state['planner']['outline_candidate']['id']
        state=client.post(f'/api/v1/roadmaps/planner/outlines/{oid}/accept',json=body(state),headers=H).json()
        assert client.post('/api/v1/roadmaps/messages',json=body(state,message=quote),headers=H).status_code==202
        state=finish(client);assert state['operation']['status']=='succeeded',state['operation']
        candidate=state['planner']['outline_candidate'];oid=candidate['id']
        changed=draft_from_outline(candidate).model_dump(mode='json');changed['summary']='Updated summary.'
        invalid=copy.deepcopy(changed);invalid['exclusions'][0]['quote']='A different request.'
        response=client.patch(f'/api/v1/roadmaps/planner/outlines/{oid}',json=body(state,outline=invalid),headers=H)
        assert response.status_code==422 and response.json()['code']=='exclusion_without_quote'
        response=client.patch(f'/api/v1/roadmaps/planner/outlines/{oid}',json=body(state,outline=changed),headers=H)
        assert response.status_code==200,response.text
        state=response.json();oid=state['planner']['outline_candidate']['id']
        response=client.post(f'/api/v1/roadmaps/planner/outlines/{oid}/accept',json=body(state),headers=H)
        assert response.status_code==200,response.text
        assert response.json()['planner']['outline_active']['exclusions'][0]['quote']==quote


def test_reached_checkpoint_is_preserved_and_cannot_be_silently_rewritten():
    config=PlannerConfig.model_validate(settings())
    checkpoint={'key':'c1','title':'Show a test','date':'2030-01-15'}
    value=outline(milestones=[milestone(checkpoints=[checkpoint])])
    saved=build_outline(value,assessment(),config,'2030-01-07','first',1,None,{})
    saved['milestones'][0]['checkpoints'][0]['reached_at']='2030-01-15T00:00:00Z'
    existing={'milestones':copy.deepcopy(saved['milestones']),'editable_tasks':[]}
    assert not validate_outline(value,Capacity(config,NOW),assessment(),{},existing=existing)
    second=build_outline(value,assessment(),config,'2030-01-07','second',1,saved,{},existing)
    assert second['milestones'][0]['checkpoints'][0]['reached_at']=='2030-01-15T00:00:00Z'
    assert draft_from_outline(second).milestones[0].checkpoints[0].key=='c1'
    changed=outline(milestones=[milestone(checkpoints=[{**checkpoint,'title':'Different work'}])])
    assert 'checkpoint_progress_conflict' in {e['code'] for e in validate_outline(changed,Capacity(config,NOW),assessment(),{},existing=existing)}


def test_outline_rejects_routine_titles_that_cannot_be_materialised():
    routine={'id':'r1','milestone_key':'m1','activity':'word '*20,'weekdays':[2],
        'duration_minutes':30,'start_date':'2030-01-09','end_date':'2030-01-09'}
    assert 'routine_title' in codes(outline(routine_rules=[routine]))

def test_milestone_dated_from_an_earlier_week_start_is_moved_to_the_planning_start():
    capacity=Capacity(PlannerConfig.model_validate(settings()),NOW)
    routine={'id':'r1','milestone_key':'m1','activity':'Practise arrays','weekdays':[0],
        'duration_minutes':30,'start_date':'2030-01-07','end_date':'2030-01-14'}
    value=outline(milestones=[milestone(projected_start='2030-01-07',checkpoints=[{'key':'c1','title':'First endpoint','date':'2030-01-08'}])],routine_rules=[routine])
    assert 'milestone_before_start' in {e['code'] for e in validate_outline(value,capacity,assessment(),{})}
    fixed=clamp_to_start(value,capacity)
    assert str(fixed.milestones[0].projected_start)=='2030-01-09' and str(fixed.milestones[0].checkpoints[0].date)=='2030-01-09'
    assert str(fixed.routine_rules[0].start_date)=='2030-01-09'
    assert 'milestone_before_start' not in {e['code'] for e in validate_outline(fixed,capacity,assessment(),{})}
    kept=clamp_to_start(outline(milestones=[milestone(projected_start='2030-01-07')]),capacity,[{'milestone_key':'m1','duration_minutes':60}])
    assert str(kept.milestones[0].projected_start)=='2030-01-07'
