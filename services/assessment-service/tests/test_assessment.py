import asyncio
import copy
import time
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem, Upstream, Model, begin
from elo_shared.skills import resolve
from app.domain import aggregate, validate_batch
from app.schemas import Batch, Generate
from app.main import create_app
from app.inputs import capture

OWNER='11111111-1111-4111-8111-111111111111'
H={'Authorization':'Bearer synthetic'}
class Sources:
    def __init__(self):
        self.owner=OWNER
        self.goal={'_id':'012345678901234567890123','version':1,'role':'Developer','target_type':'specific_job','job_dates':[],
            'skills':[{'item_id':'req1','name':'Python','category':'Technical','priority':'required','origin':'employer','evidence':'Python required','group_operator':'all'}],'non_skill_requirements':[]}
        evidence=[{'id':'e1','excerpt':'I used Python in my project. I have not used SQL.','location':'answer'}]
        self.source={'cv_id':'cv1','cv_version':1,'effective_version':1,'extraction_version':1,'selection_version':1,'declarations_version':0,'skills':[],'declarations':[],
            'items':[{'id':'item1','kind':'project','title':'Synthetic project','description':'I used Python in my project.', 'provenance':'user_clarified','evidence':evidence,'removed':False,
                'skill_claims':[{'name':'Python','attribution':'personal','assistance':'independent','proficiency':None,'experience_months':None,'support_uncertain':False,'evidence_type':'user_clarified','evidence':evidence}]}]}
    async def account(self,token):return {'id':self.owner,'token':token,'profile':{'version':1,'education':None,'onboarding_complete':True}}
    async def read(self,service,path,token,params=None):
        if service=='career':return {'ready':True,'goal':self.goal,'selection_version':1,'research':None}
        if path=='/api/v1/cv':return {'selection':{'cv_id':'cv1','version':1}}
        if path=='/api/v1/profile/capabilities':return {'version':0,'declarations':[]}
        if path.endswith('/assessment-input'):return copy.deepcopy(self.source)
        return {'id':'cv1','version':self.source['cv_version'],'status':'ready','file_name':'synthetic.docx'}
class Interpreter:
    configured=True
    def __init__(self,sources=None):self.calls=0;self.sources=sources
    async def generate(self,schema,instructions,context):
        self.calls+=1
        if self.sources:self.sources.source['cv_version']+=1
        return Batch(outcomes=[{'requirement_ref':r['ref'],'components':[{'dimension':'capability','status':'supported','explanation':'Declared personal project use.','evidence_refs':['cv:item1:claim:0']}],
            'recommendation':'Practise explaining your project decisions.','mapping_method':'canonical','mapping_reason':'Same Python identity.'} for r in context['requirements']])
def finish(client):
    for _ in range(100):
        response=client.get('/api/v1/assessments/current',headers=H);assert response.status_code==200,response.text
        state=response.json()
        if (state['operation'] or {}).get('status') in ('succeeded','failed'):return state
        time.sleep(.01)
    raise AssertionError('operation did not finish')
@pytest.mark.parametrize('values,operator,expected',[
    (['supported','uncertain'],'all','partial'),(['confirmed_shortfall','uncertain'],'all','confirmed_shortfall'),
    (['supported','uncertain'],'any','supported'),(['confirmed_shortfall','uncertain'],'any','uncertain'),
    (['confirmed_shortfall','confirmed_shortfall'],'any','confirmed_shortfall'),(['uncertain'],'all','uncertain')])
def test_decision_table(values,operator,expected):assert aggregate(values,operator)==expected

def test_shared_aliases_and_unknowns():
    assert resolve(' Structured Query Language ','unspecified')==resolve('SQL','Technical')=='language.sql'
    assert resolve('ReactJS')==resolve('React.js')
    assert resolve('Unsupported niche skill') is None

def test_consistent_snapshot_pins_current_source_versions_and_personal_evidence():
    sources=Sources()
    result=asyncio.run(capture(sources,asyncio.run(sources.account('synthetic'))))
    assert result['inputs']['cv_version']==result['inputs']['profile_version']==1
    assert result['research_coverage']=='unavailable'
    assert result['requirements'][0]['canonical_skill_id']=='language.python'
    assert result['evidence']['cv:item1:claim:0']['attribution']=='personal'

def test_explicit_partial_analysis_retry_replay_history_and_owner_isolation():
    sources=Sources();store=MemoryStore();model=Interpreter()
    with TestClient(create_app(store,sources,model)) as client:
        body={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':False}
        assert client.post('/api/v1/assessments',json=body,headers=H).status_code==202
        failed=finish(client);assert failed['operation']['error']['code']=='research_partial' and failed['result'] is None
        body={'expected_version':failed['version'],'mutation_id':str(uuid4()),'allow_partial':True}
        client.post('/api/v1/assessments',json=body,headers=H);state=finish(client)
        assert state['operation']['status']=='succeeded' and state['result']['analysis_status']=='partial'
        identifier=state['result']['id'];assert model.calls==1
        assert client.post('/api/v1/assessments',json=body,headers=H).status_code==202
        assert finish(client)['result']['id']==identifier and model.calls==1
        assert client.get('/api/v1/assessments/'+identifier,headers=H).status_code==200
        sources.owner='22222222-2222-4222-8222-222222222222'
        assert client.get('/api/v1/assessments/'+identifier,headers=H).status_code==404

def test_changed_inputs_cannot_publish():
    sources=Sources()
    with TestClient(create_app(MemoryStore(),sources,Interpreter(sources))) as client:
        client.post('/api/v1/assessments',json={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True},headers=H)
        state=finish(client);assert state['result'] is None and state['operation']['error']['code']=='inputs_changed'

def outcome(status='confirmed_shortfall',quote='I have not used SQL.'):
    return Batch(outcomes=[{'requirement_ref':'sql','components':[{'dimension':'capability','status':status,'explanation':'Declared evidence.','evidence_refs':['a'],'limitation_quote':quote}],
        'recommendation':None,'mapping_method':'semantic','mapping_reason':'Explicit SQL wording.'}])
def test_explicit_shortfall_does_not_need_a_proficiency_label_but_needs_exact_limitation():
    result=validate_batch(outcome(),[{'ref':'sql'}],{'a':{'text':'I have not used SQL.','attribution':'personal'}})
    assert result[0]['match_status']=='confirmed_shortfall'
    with pytest.raises(Problem):validate_batch(outcome(quote=None),[{'ref':'sql'}],{'a':{'text':'Basic use.'}})

def test_forged_refs_missing_requirement_coverage_and_team_support_are_rejected():
    with pytest.raises(Problem):validate_batch(outcome('supported',None),[{'ref':'sql'}],{'a':{'text':'Team did this.','attribution':'team'}})
    with pytest.raises(Problem):validate_batch(outcome('supported',None),[{'ref':'sql'}],{})
    with pytest.raises(Problem):validate_batch(outcome('supported',None),[{'ref':'sql'},{'ref':'python'}],{'a':{'text':'Use'}})

def test_restart_recovers_accepted_operation_and_changed_key_body_is_rejected():
    store=MemoryStore();body=Generate(expected_version=0,mutation_id=uuid4(),allow_partial=True)
    begin(store,OWNER,body,'assessment')
    with TestClient(create_app(store,Sources(),Interpreter())) as client:
        assert finish(client)['operation']['status']=='succeeded'
        assert client.post('/api/v1/assessments',json={**body.model_dump(mode='json'),'allow_partial':False},headers=H).status_code==409

def test_http_auth_and_model_error_privacy(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/auth/session'):return httpx.Response(200,json={'id':OWNER,'email_verified':True})
        if request.method=='GET':return httpx.Response(200,json={'version':1,'onboarding_complete':True})
        return httpx.Response(401,json={'error':'private provider prose'})
    monkeypatch.setenv('ASSESSMENT_LLM_API_KEY','synthetic')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (await Upstream(client).account('Bearer synthetic'))['id']==OWNER
            with pytest.raises(Problem) as error:await Model(client,'ASSESSMENT').generate(Batch,'Assess.',{})
            assert 'private' not in error.value.detail
    asyncio.run(run())


def test_quota_retry_resumes_completed_batches_without_repeating_model_calls(monkeypatch):
    sources=Sources()
    sources.goal['skills']=[{**sources.goal['skills'][0],'item_id':'req'+str(i),'name':'Synthetic skill '+str(i)} for i in range(9)]
    class Batched:
        configured=True
        def __init__(self):self.calls=[];self.failed=False
        async def generate(self,schema,instructions,context):
            self.calls.append([r['ref'] for r in context['requirements']])
            if len(self.calls)==2 and not self.failed:
                self.failed=True;raise Problem('Provider capacity.',429,'model_quota',30)
            return Batch(outcomes=[{'requirement_ref':r['ref'],'components':[{'dimension':'capability','status':'uncertain','explanation':'No relevant evidence.','evidence_refs':[]}],
                'recommendation':None,'mapping_method':'unresolved','mapping_reason':'Unmapped synthetic skill.'} for r in context['requirements']])
    model=Batched();store=MemoryStore()
    with TestClient(create_app(store,sources,model)) as client:
        body={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True}
        client.post('/api/v1/assessments',json=body,headers=H);state=finish(client)
        assert state['operation']['status']=='failed' and len(model.calls)==2
        assert len(store.load(OWNER)['last_operation']['checkpoint']['outcomes'])==8
        original_time=time.time;future=original_time()+31
        monkeypatch.setattr('elo_shared.runtime.time.time',lambda:future)
        client.post('/api/v1/assessments',json=body,headers=H);state=finish(client)
        assert state['operation']['status']=='succeeded' and len(state['result']['job_skill_gaps'])==9
        assert len(model.calls)==3 and model.calls[1]==model.calls[2]
        assert len(model.calls[0])==8


def test_whole_source_item_cannot_bypass_its_denied_or_team_skill_claim():
    with pytest.raises(Problem):
        validate_batch(outcome('supported',None),[{'ref':'sql','kind':'job_skill','canonical_skill_id':'language.sql'}],
            {'a':{'text':'SQL mentioned in source item.','attribution':'unknown','unscoped_item':True}})


@pytest.mark.parametrize('remainder,expected',[('confirmed_shortfall','confirmed_shortfall'),('uncertain','partial')])
def test_or_routes_preserve_partial_support_but_every_proven_unmet_route_confirms_group_shortfall(remainder,expected):
    from app.domain import group_outcome
    items=[{'match_status':'partial','components':[{'status':'supported'},{'status':remainder}]},
        {'match_status':'confirmed_shortfall','components':[{'status':'confirmed_shortfall'}]}]
    assert group_outcome(items,'any')==expected
