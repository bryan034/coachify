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
from app.schemas import Batch, Generate, SkillBatch
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
def judge(context):
    """A deterministic per-skill judgement citing each skill's first source."""
    return SkillBatch(skills=[{'skill_key':skill['key'],'category':'Technical coding','subcategory':'Languages','relevance':'high',
        'competence_score':6,'required_score':7,'explanation':'Used independently in a project.','evidence_refs':[skill['sources'][0]['ref']],
        'requirement_refs':[r['ref'] for r in context['goal']['requirements']][:1]} for skill in context['skills']])
class Interpreter:
    configured=True
    # `calls` counts requirement comparisons; per-skill judgements are counted separately.
    def __init__(self,sources=None):self.calls=0;self.skill_calls=0;self.sources=sources
    async def generate(self,schema,instructions,context):
        if schema is SkillBatch:
            self.skill_calls+=1;return judge(context)
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

def test_context_exposes_evidence_for_a_preview_without_a_model_call():
    model=Interpreter()
    with TestClient(create_app(MemoryStore(),Sources(),model)) as client:
        response=client.get('/api/v1/assessments/context',headers=H);assert response.status_code==200,response.text
    assert response.json()['evidence']['cv:item1:claim:0']['attribution']=='personal' and model.calls==0

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
            if schema is SkillBatch:return judge(context)
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
PATH='/api/v1/assessments/dashboard-source'


def create_result(client):
    response=client.post('/api/v1/assessments',headers=H,json={
        'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True})
    assert response.status_code==202
    state=finish(client)
    assert state['result']
    return state


def test_dashboard_read_does_not_resume_pending_operation_or_write():
    store=MemoryStore();model=Interpreter();sources=Sources()
    begin(store,OWNER,Generate(expected_version=0,mutation_id=uuid4(),allow_partial=True),'assessment')
    before=store.load(OWNER)
    with TestClient(create_app(store,sources,model)) as client:
        response=client.get(PATH,headers=H)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['freshness']=='missing' and result['ready'] is True
        assert result['operation']['status']=='pending'
        assert model.calls==0 and store.load(OWNER)==before


def test_source_reports_current_stale_and_owner_isolation():
    store=MemoryStore();model=Interpreter();sources=Sources()
    with TestClient(create_app(store,sources,model)) as client:
        saved=create_result(client)
        current=client.get(PATH,headers=H).json()
        assert current['freshness']=='current' and current['result']['id']==saved['result']['id']
        assert current['input_hash']==saved['result']['input_hash']
        assert current['inputs']['goal_id']==sources.goal['_id']
        assert current['workspace_updated_at'] and current['result']['created_at']
        sources.goal['version']+=1
        stale=client.get(PATH,headers=H).json()
        assert stale['freshness']=='stale' and stale['result']['id']==saved['result']['id']
        sources.owner='22222222-2222-4222-8222-222222222222'
        other=client.get(PATH,headers=H).json()
        assert other['freshness']=='missing' and other['result'] is None
        assert client.get(PATH).status_code==401
        assert model.calls==1


def test_unready_inputs_are_not_reported_as_current():
    sources=Sources();store=MemoryStore()
    with TestClient(create_app(store,sources,Interpreter())) as client:
        create_result(client)
        old_read=sources.read
        async def unready(service,path,token,params=None):
            if service=='career':return {'ready':False,'goal':None}
            return await old_read(service,path,token,params)
        sources.read=unready
        response=client.get(PATH,headers=H)
        assert response.status_code==200,response.text
        view=response.json()
        assert view['freshness']=='not_ready' and view['ready'] is False and view['result']
        assert view['input_hash'] is None


@pytest.mark.parametrize('status,expected',[(503,'unavailable'),(409,'conflict')])
def test_unavailable_or_racing_sources_keep_saved_result_but_not_freshness(status,expected):
    sources=Sources();store=MemoryStore()
    with TestClient(create_app(store,sources,Interpreter())) as client:
        saved=create_result(client)
        async def fail(*args,**kwargs):raise Problem('Synthetic failure.',status,'upstream')
        sources.read=fail
        response=client.get(PATH,headers=H)
        assert response.status_code==200,response.text
        view=response.json()
        assert view['freshness']==expected and view['ready'] is None
        assert view['result']['id']==saved['result']['id'] and view['input_hash'] is None


def test_source_change_during_capture_returns_conflict(monkeypatch):
    import app.main as main
    store=MemoryStore();sources=Sources();real_capture=main.capture
    with TestClient(create_app(store,sources,Interpreter())) as client:
        create_result(client)
        async def changing(upstream,account):
            snapshot=await real_capture(upstream,account)
            row=store.load(OWNER)
            row['result']=copy.deepcopy(row['result']);row['result']['id']='new-result'
            store.cas(OWNER,row['version'],row)
            return snapshot
        monkeypatch.setattr(main,'capture',changing)
        response=client.get(PATH,headers=H)
        assert response.status_code==409 and response.json()['code']=='source_changed'


@pytest.mark.parametrize('status',[401,403])
def test_dashboard_source_does_not_hide_revoked_access(status):
    sources=Sources();store=MemoryStore()
    with TestClient(create_app(store,sources,Interpreter())) as client:
        async def fail(*args,**kwargs):raise Problem('Sign in again.',status,'session')
        sources.read=fail
        assert client.get(PATH,headers=H).status_code==status


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_evidence_repair_is_bounded_and_never_publishes_rejected_batch(repair_succeeds):
    class Repairing(Interpreter):
        def __init__(self):
            super().__init__()
            self.contexts = []

        async def generate(self, schema, instructions, context):
            if schema is SkillBatch:
                return await super().generate(schema, instructions, context)
            self.contexts.append(copy.deepcopy(context))
            value = await super().generate(schema, instructions, context)
            if self.calls == 1 or not repair_succeeds:
                value.outcomes[0].components[0].evidence_refs = ['cv:item1']
            return value

    model = Repairing()
    with TestClient(create_app(MemoryStore(), Sources(), model)) as client:
        response = client.post('/api/v1/assessments', json={
            'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True,
        }, headers=H)
        assert response.status_code == 202
        state = finish(client)
    assert model.calls == 2
    assert 'source-scoped' in model.contexts[1]['validation_feedback']
    rejected = model.contexts[1]['previous_output']['outcomes'][0]
    assert rejected['components'][0]['evidence_refs'] == ['cv:item1']
    assert model.contexts[1]['evidence'] == model.contexts[0]['evidence']
    assert model.contexts[1]['requirements'] == model.contexts[0]['requirements']
    if repair_succeeds:
        assert state['operation']['status'] == 'succeeded'
        assert state['result']['job_skill_gaps'][0]['components'][0]['evidence_refs'] == ['cv:item1:claim:0']
    else:
        assert state['operation']['status'] == 'failed' and state['result'] is None
        assert state['operation']['error']['code'] == 'assessment_output'


def test_unknown_evidence_ref_repair_names_the_exact_reference_without_leaking_it_to_the_user():
    class Repairing(Interpreter):
        def __init__(self):
            super().__init__()
            self.contexts = []

        async def generate(self, schema, instructions, context):
            if schema is SkillBatch:
                return await super().generate(schema, instructions, context)
            self.contexts.append(copy.deepcopy(context))
            value = await super().generate(schema, instructions, context)
            if self.calls == 1:
                value.outcomes[0].components[0].evidence_refs = ['cv:item1:claim:0', 'b12']
            return value

    model = Repairing()
    with TestClient(create_app(MemoryStore(), Sources(), model)) as client:
        response = client.post('/api/v1/assessments', json={
            'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True,
        }, headers=H)
        assert response.status_code == 202
        state = finish(client)
    feedback = model.contexts[1]['validation_feedback']
    assert "'b12'" in feedback and "'job:req1'" in feedback and 'component 0 (capability)' in feedback
    assert "'cv:item1:claim:0'" not in feedback
    assert state['operation']['status'] == 'succeeded'
    assert state['result']['job_skill_gaps'][0]['components'][0]['evidence_refs'] == ['cv:item1:claim:0']


def test_unrepaired_unknown_evidence_ref_keeps_a_generic_user_error():
    class Forging(Interpreter):
        async def generate(self, schema, instructions, context):
            value = await super().generate(schema, instructions, context)
            if schema is SkillBatch:
                return value
            value.outcomes[0].components[0].evidence_refs = ['invented-ref']
            return value

    with TestClient(create_app(MemoryStore(), Sources(), Forging())) as client:
        client.post('/api/v1/assessments', json={
            'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True,
        }, headers=H)
        state = finish(client)
    assert state['operation']['status'] == 'failed'
    assert state['operation']['error']['detail'] == 'The assessment referenced unavailable evidence.'
    assert 'invented-ref' not in str(state['operation']['error'])


def test_repeated_evidence_ref_is_collapsed_instead_of_rejected():
    output = Batch(outcomes=[{'requirement_ref': 'python', 'components': [{'dimension': 'capability', 'status': 'supported',
        'explanation': 'Declared use.', 'evidence_refs': ['a', 'a']}], 'mapping_method': 'semantic', 'mapping_reason': 'Same skill.'}])
    result = validate_batch(output, [{'ref': 'python'}], {'a': {'text': 'I used Python.', 'attribution': 'personal'}})
    assert result[0]['components'][0]['evidence_refs'] == ['a']


def test_manual_only_snapshot_uses_published_declarations_and_tracks_revision():
    class ManualSources(Sources):
        revision=2
        async def read(self,service,path,token,params=None):
            if path=='/api/v1/cv':return {'selection':{'cv_id':None,'version':3}}
            if path=='/api/v1/profile/capabilities':return {'version':self.revision,'declarations':[{'id':'manual1','name':'Python','description':'I used Python myself.','contributions':[]}]}
            if service=='cv':raise AssertionError('Manual-only comparison must not read a CV')
            return await super().read(service,path,token,params)
    source=ManualSources()
    account=asyncio.run(source.account('synthetic'))
    snapshot=asyncio.run(capture(source,account))
    assert snapshot['ready'] and snapshot['cv'] is None
    assert snapshot['inputs']['source_mode']=='profile_only'
    assert snapshot['inputs']['cv_id'] is None
    assert snapshot['evidence']['declaration:manual1']['attribution']=='personal'
    source.revision+=1
    assert asyncio.run(capture(source,account))['input_hash']!=snapshot['input_hash']


def test_independence_without_success_gets_a_conservative_level_against_role_target():
    sources=Sources()
    snapshot=asyncio.run(capture(sources,asyncio.run(sources.account('synthetic'))))
    output=asyncio.run(Interpreter().generate(Batch,'',snapshot))
    outcome=validate_batch(output,snapshot['requirements'],snapshot['evidence'])[0]
    assert outcome['competence_score']==5
    assert outcome['demonstrated_score']==4 and outcome['required_score']==8
    assert outcome['relevance']=='high'
    assert outcome['scoring_rubric_version']=='evidence-role-v2'
    assert outcome['score_status']=='estimated'


def test_manual_only_assessment_publishes_a_versioned_result_without_cv():
    class ManualSources(Sources):
        async def read(self,service,path,token,params=None):
            if path=='/api/v1/cv':return {'selection':{'cv_id':None,'version':1}}
            if path=='/api/v1/profile/capabilities':return {'version':2,'declarations':[{'id':'m','name':'Python','description':'I used Python myself.','contributions':[]}]}
            return await super().read(service,path,token,params)
    class ManualModel(Interpreter):
        async def generate(self,schema,instructions,context):
            output=await super().generate(schema,instructions,context)
            if schema is SkillBatch:return output
            for outcome in output.outcomes:
                outcome.components[0].evidence_refs=['declaration:m']
            return output
    with TestClient(create_app(MemoryStore(),ManualSources(),ManualModel())) as client:
        response=client.post('/api/v1/assessments',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True})
        assert response.status_code==202
        state=finish(client)
        assert state['operation']['status']=='succeeded',state
        assert not state['stale']
        assert state['result']['inputs']['cv_id'] is None
        # The declaration supplies basic personal use, not evidence of independent successful delivery.
        python=state['result']['job_skill_gaps'][0]
        assert python['scoring_rubric_version']=='evidence-role-v2' and python['competence_score']==3.7
        assert python['profile_skills'][0]['name']=='Python'


def test_selected_failed_cv_does_not_fall_back_to_saved_declarations():
    class FailedSources(Sources):
        async def read(self,service,path,token,params=None):
            if path=='/api/v1/profile/capabilities':return {'version':1,'declarations':[{'id':'m','name':'Python','description':'Saved evidence.'}]}
            if path=='/api/v1/cv/cv1':return {'status':'failed','id':'cv1'}
            return await super().read(service,path,token,params)
    sources=FailedSources()
    result=asyncio.run(capture(sources,asyncio.run(sources.account('synthetic'))))
    assert not result['ready'] and result['cv']['status']=='failed'


def test_reserved_score_contract_rejects_out_of_range_values():
    from pydantic import ValidationError
    from app.schemas import Outcome
    sources=Sources()
    snapshot=asyncio.run(capture(sources,asyncio.run(sources.account('synthetic'))))
    output=asyncio.run(Interpreter().generate(Batch,'',snapshot))
    outcome=validate_batch(output,snapshot['requirements'],snapshot['evidence'])[0]
    with pytest.raises(ValidationError):Outcome.model_validate({**outcome,'competence_score':11})


def test_previous_rubric_results_are_stale_without_rewriting_history():
    from elo_shared.runtime import digest
    store=MemoryStore();model=Interpreter()
    with TestClient(create_app(store,Sources(),model)) as client:
        client.post('/api/v1/assessments',headers=H,json={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True})
        saved=finish(client)
        row=store.load(OWNER)
        row['result']['input_hash']=digest(row['result']['inputs'])
        row['result']['job_skill_gaps'][0]['competence_score']=10
        store.cas(OWNER,row['version'],row)
        current=client.get('/api/v1/assessments/current',headers=H).json()
        assert current['stale'] and current['result']['job_skill_gaps'][0]['competence_score']==10
        assert model.calls==1


def test_retry_discards_pre_v2_scores_only_when_source_revisions_still_match():
    from elo_shared.runtime import digest
    class Failing(Interpreter):
        fail=True
        async def generate(self,schema,instructions,context):
            if schema is SkillBatch and self.fail: raise Problem('Synthetic failure.',503,'model_provider')
            return await super().generate(schema,instructions,context)
    model=Failing();store=MemoryStore()
    body={'expected_version':0,'mutation_id':str(uuid4()),'allow_partial':True}
    with TestClient(create_app(store,Sources(),model)) as client:
        client.post('/api/v1/assessments',headers=H,json=body)
        assert finish(client)['operation']['status']=='failed'
        row=store.load(OWNER)
        checkpoint=row['last_operation']['checkpoint']
        checkpoint.pop('scoring_rubric')
        checkpoint['input_hash']=digest(checkpoint['snapshot']['inputs'])
        checkpoint['outcomes'][0]['competence_score']=10
        # Preserve the failed-at version, just as loading an existing saved row would.
        with store.lock: store.data[OWNER]=copy.deepcopy(row)
        model.fail=False
        client.post('/api/v1/assessments',headers=H,json=body)
        current=finish(client)
        assert current['operation']['status']=='succeeded'
        assert current['result']['job_skill_gaps'][0]['competence_score']==5
        assert model.calls==2
