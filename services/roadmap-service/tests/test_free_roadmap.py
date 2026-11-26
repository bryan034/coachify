from uuid import uuid4
import pytest
from elo_shared.runtime import MemoryStore, Problem
from fastapi.testclient import TestClient
from planner_fixtures import NOW, OWNER, draft
from app.main import create_app
from app.planning.outlines import draft_from_outline
from test_planner_flow import H, PREFIX, Scripted, Sources, chat, configure, finish, read, request, task, week_draft

def start(client,state,**body):
    payload={'expected_version':state['version'],'mutation_id':str(uuid4()),**body}
    return client.post(PREFIX+'/outlines/generate',headers=H,json=payload),payload

def generated(client,state,**body):
    response,payload=start(client,state,**body)
    assert response.status_code==202,response.text
    return finish(client),payload

def harness(model,plan='free',store=None):
    store=store or MemoryStore()
    return TestClient(create_app(store,Sources(plan),model,clock=lambda:NOW)),store

def test_a_free_account_generates_one_roadmap_and_keeps_editing_it():
    model=Scripted([draft(),draft()])
    client,_=harness(model)
    with client:
        state,payload=generated(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['outline_generated'] is True
        replay=client.post(PREFIX+'/outlines/generate',headers=H,json=payload)
        assert replay.status_code==202 and read(client)['version']==state['version']
        candidate=state['planner']['outline_candidate']
        edited=draft_from_outline(candidate).model_dump(mode='json');edited['summary']='Edited outline.'
        response=client.patch(PREFIX+'/outlines/'+candidate['id'],headers=H,json={'expected_version':state['version'],'mutation_id':str(uuid4()),'outline':edited})
        assert response.status_code==200,response.text
        state=response.json()
        response=request(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/discard',state)
        assert response.status_code==200,response.text
        state=response.json()
        assert state['planner']['outline_candidate'] is None and state['planner']['outline_generated'] is True
        blocked,_=start(client,state)
        assert blocked.status_code==402 and blocked.json()['code']=='premium_required'
        assert model.schemas==['OutlineDraft','WeekDraft']

@pytest.mark.parametrize('auto_accept',[False,True])
def test_a_free_account_cannot_replace_its_roadmap(auto_accept):
    model=Scripted([draft(),draft()])
    client,_=harness(model)
    with client:
        state,_=generated(client,configure(client),auto_accept=True)
        assert state['planner']['active'] is not None
        blocked,_=start(client,state,auto_accept=auto_accept)
        assert blocked.status_code==402 and blocked.json()['code']=='premium_required'
        assert read(client)['planner']['active']==state['planner']['active']
        assert model.schemas==['OutlineDraft','WeekDraft']

def test_a_premium_account_generates_again():
    model=Scripted([draft(),draft()])
    client,_=harness(model,'premium')
    with client:
        state,_=generated(client,configure(client),auto_accept=True)
        state,_=generated(client,state)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['outline_candidate'] is not None and model.schemas.count('OutlineDraft')==2

def test_a_free_account_retries_a_failed_first_roadmap():
    model=Scripted([draft(),draft()],weeks=[Problem('Synthetic unavailable provider.',503,'model_provider'),week_draft([task('new','Write endpoint tests')])])
    client,_=harness(model)
    with client:
        state,_=generated(client,configure(client),auto_accept=True)
        assert state['operation']['status']=='failed' and state['planner']['outline_generated'] is False
        state,_=generated(client,state,auto_accept=True)
        assert state['operation']['status']=='succeeded',state['operation']

def test_a_roadmap_saved_before_the_marker_counts_for_a_free_account():
    store=MemoryStore()
    client,_=harness(Scripted([draft()]),'premium',store)
    with client:
        generated(client,configure(client),auto_accept=True)
    store.data[OWNER]['planner'].pop('first_outline_operation')
    model=Scripted([draft()])
    client,_=harness(model,'free',store)
    with client:
        state=read(client)
        assert state['planner']['outline_generated'] is True
        blocked,_=start(client,state,auto_accept=True)
        assert blocked.status_code==402 and blocked.json()['code']=='premium_required'
        assert model.schemas==[]

def test_the_adviser_chat_does_not_revise_a_free_roadmap():
    model=Scripted([draft(),draft()],chats=[{'reply':'I will make it lighter.','settings':{},'revision_instruction':'Make the plan lighter.'}])
    client,_=harness(model)
    with client:
        state,_=generated(client,configure(client),auto_accept=True)
        state=chat(client,state,'Make the plan lighter.')
        assert state['operation']['status']=='failed' and state['operation']['error']['code']=='premium_required'
        assert state['planner']['outline_candidate'] is None
        assert model.schemas==['OutlineDraft','WeekDraft','ChatTurn']
