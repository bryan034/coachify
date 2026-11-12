"""Saved evaluations are reusable only against the exact current evidence and goal."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from app.freshness import evaluation_status
from app.main import create_app
from tests.test_assessment import Sources, Interpreter, H, finish


def evaluated(client):
    client.post('/api/v1/assessments',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True})
    state=finish(client)
    assert state['operation']['status']=='succeeded'
    return state


def test_status_reuses_saved_result_and_reports_partial_research_without_staleness():
    model=Interpreter()
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        assert client.get('/api/v1/assessments/current',headers=H).json()['evaluation']['freshness']=='missing'
        state=evaluated(client)
        status=state['evaluation']
        assert status=={'freshness':'current','processing':'idle','completeness':'partial','evaluated_at':state['result']['created_at'],'reasons':[]}
        calls=(model.calls,model.skill_calls)
        for route in ('current','context','dashboard-source'):
            assert client.get('/api/v1/assessments/'+route,headers=H).json()['evaluation']==status
        assert (model.calls,model.skill_calls)==calls


@pytest.mark.parametrize('change,reason',[
    ('cv','cv_changed'),('goal','goal_changed'),('level','evidence_changed'),('evidence','evidence_changed')])
def test_cv_goal_and_review_overlay_changes_make_the_saved_evaluation_outdated(change,reason):
    sources=Sources()
    with TestClient(create_app(MemoryStore(),sources,Interpreter())) as client:
        state=evaluated(client)
        if change=='cv':sources.source['cv_version']+=1
        if change=='goal':sources.goal['version']+=1
        if change=='level':sources.source['items'][0]['skill_claims'][0]['skill_level']={'level':3}
        if change=='evidence':sources.source['items'][0]['description']='Changed personal evidence.'
        current=client.get('/api/v1/assessments/current',headers=H).json()
        assert current['stale'] and current['result']['id']==state['result']['id']
        assert current['evaluation']['freshness']=='outdated' and reason in current['evaluation']['reasons']


def test_source_outage_retains_result_but_never_reports_current():
    class Unavailable(Sources):
        unavailable=False
        async def read(self,*args,**kwargs):
            if self.unavailable:raise Problem('Synthetic upstream unavailable.',503,'upstream')
            return await super().read(*args,**kwargs)
    sources=Unavailable()
    with TestClient(create_app(MemoryStore(),sources,Interpreter())) as client:
        saved=evaluated(client)
        sources.unavailable=True
        current=client.get('/api/v1/assessments/current',headers=H).json()
        assert current['stale'] and not current['ready'] and current['result']['id']==saved['result']['id']
        assert current['evaluation']['freshness']=='unavailable'


def test_outdated_and_evaluating_are_independent_and_old_scoring_is_not_reused():
    snapshot={'ready':True,'inputs':{'goal_version':2},'input_hash':'new'}
    row={'result':{'inputs':{'goal_version':1},'input_hash':'old','skill_profile':{'status':'evaluated','rubric_version':'old'}},'pending':{'status':'running'}}
    status=evaluation_status(row,snapshot)
    assert status['freshness']=='outdated' and status['processing']=='evaluating'
    assert set(status['reasons'])=={'goal_changed','evaluation_update_required'}


def test_review_rating_change_during_evaluation_cannot_publish_an_old_snapshot():
    sources=Sources()
    class ChangedReview(Interpreter):
        async def generate(self,schema,instructions,context):
            value=await super().generate(schema,instructions,context)
            sources.source['items'][0]['skill_claims'][0]['skill_level']={'level':2}
            return value
    with TestClient(create_app(MemoryStore(),sources,ChangedReview())) as client:
        client.post('/api/v1/assessments',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True})
        state=finish(client)
    assert state['result'] is None and state['operation']['error']['code']=='inputs_changed'
