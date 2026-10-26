"""Provider-boundary regressions: compact payloads, proposal identity and safe usage."""
import asyncio
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.ai.adapter import AIAdapter, AIError, Operation, compact_schema
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.jd_contracts import ExtractedJD, ExtractedSkill
from app.api.v1.jd import validate_skills
from app.schemas.jd import JDExtraction


SKILL = {'item_id':'saved-sql','skill_id':'language.sql','name':'SQL','category':'Technical',
         'priority':'required','origin':'employer','evidence':'SQL required','context':'Query relational data',
         'source_urls':['https://example.test/job']}
GOAL = {'role':'Analyst','field':'Data','company':None,'skills':[SKILL]}


def config():
    return AISettings(enabled=True,model='openai/gpt-oss-120b',api_key='synthetic',max_output_tokens=512)


def completion(output, usage=None):
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}],
        'usage':usage or {'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}})


def chat_input(message='Explain SQL'):
    return AIInput(stage='jd_chat',context=json.dumps({'career_goal':GOAL}),
                   conversation=[{'role':'user','content':message}])


def test_each_operation_has_only_its_own_prompt_and_schema():
    async def invoke():
        async with httpx.AsyncClient() as client:
            adapter=AIAdapter(config(),client)
            extract=adapter._payload(AIInput(stage='jd_extraction',source_text='SQL required'))
            chat=adapter._payload(chat_input())
            edit=adapter._payload(chat_input().model_copy(update={'stage':'jd_edit'}))
            extract_prompt=extract['messages'][0]['content']
            assert 'Read and understand the whole JD' in extract_prompt
            assert 'edit_requested' not in extract_prompt and 'Return keep' not in extract_prompt
            assert 'Read and understand the whole JD' not in chat['messages'][0]['content']
            assert 'Return keep' not in chat['messages'][0]['content']
            assert 'Return keep' in edit['messages'][0]['content']
            chat_schema=chat['response_format']['json_schema']['schema']
            assert set(chat_schema['properties'])=={'reply','edit_requested'}
            assert '$defs' not in chat_schema
            schema=extract['response_format']['json_schema']['schema']
            assert schema['additionalProperties'] is False
            assert schema['required']==list(schema['properties'])
            assert len(json.dumps(schema)) < len(json.dumps(JDExtraction.model_json_schema()))
            assert 'job_url' not in schema['properties']
            properties=schema['$defs']['ExtractedSkill']['properties']
            assert not {'skill_id','item_id','correction','source_urls'} & properties.keys()
            conditions=schema['$defs']['ExtractedCondition']['properties']
            assert not {'requirement_id','correction','source_urls'} & conditions.keys()
            for payload in (extract,chat,edit):
                assert 'JSON schema:' not in payload['messages'][0]['content']
    asyncio.run(invoke())


def test_annotations_removed_without_losing_properties_named_title_or_constraints():
    value={'title':'Top','type':'object','properties':{'title':{'title':'Title','type':'string','maxLength':10}},'required':['title']}
    compact=compact_schema(value)
    assert compact=={'type':'object','properties':{'title':{'type':'string','maxLength':10}},'required':['title']}


def test_compact_extraction_adds_backend_defaults_and_validates_duration_ranges():
    value={**GOAL,'skills':[{k:v for k,v in SKILL.items() if k not in ('item_id','skill_id','source_urls')}],
        'non_skill_requirements':[{'category':'experience','description':'One to two years of work',
          'priority':'preferred','evidence':'1–2 years','minimum_months':12,'maximum_months':24}]}
    result=ExtractedJD.model_validate(value).to_domain()
    assert result.skills[0].item_id is None and result.skills[0].skill_id is None
    assert result.skills[0].correction=='extracted' and result.skills[0].source_urls==[]
    assert result.non_skill_requirements[0].requirement_id=='condition-1'
    value['non_skill_requirements'][0]['minimum_months']=36
    with pytest.raises(ValidationError): ExtractedJD.model_validate(value).to_domain()
    with pytest.raises(ValidationError): ExtractedSkill.model_validate({**SKILL})


def test_explanation_uses_one_call_without_edit_schema_or_machine_metadata(caplog):
    calls=[]
    async def invoke():
        def handler(req):
            calls.append(json.loads(req.content))
            return completion({'reply':'SQL queries relational data.','edit_requested':False})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(config(),client)
            result=await adapter.generate(chat_input(),Operation('owner','1','jd_chat'),current_revision=lambda:'1')
            assert result.data.proposed_skills is None
    with caplog.at_level(logging.INFO,logger='uvicorn.error.ai_usage'):
        asyncio.run(invoke())
    assert len(calls)==1
    context=json.loads(calls[0]['messages'][1]['content'])['context']
    skill=context['career_goal']['skills'][0]
    assert not {'skill_id','item_id','source_urls','correction','evidence'} & skill.keys()
    assert skill['context']=='Query relational data'
    assert '"prompt_tokens":100' in caplog.text
    assert 'stage=jd_chat attempt=1 provider_attempt=1' in caplog.text
    assert 'relational data' not in caplog.text and 'synthetic' not in caplog.text


@pytest.mark.parametrize('defect',[None,'reference','duplicate_reference','employer_addition','missing_quote'])
def test_edit_second_call_preserves_existing_identity_and_validates_new_items(defect):
    calls=[]
    async def invoke():
        def handler(req):
            calls.append(json.loads(req.content))
            if len(calls)==1: return completion({'reply':'Review this proposed addition.','edit_requested':True})
            addition={'name':'Python','category':'Technical','priority':'suggested',
                      'origin':'user_declaration','evidence':'Add Python'}
            keep=['0']
            if defect=='reference': keep=['invented']
            if defect=='duplicate_reference': keep=['0','0']
            if defect=='employer_addition': addition.update(origin='employer',priority='required')
            if defect=='missing_quote': addition['evidence']='Fabricated quote'
            return completion({'keep':keep,'add':[addition]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(config(),client)
            def validate(output):
                validate_skills(output.proposed_skills,'Add Python',JDExtraction.model_validate(GOAL).skills)
            pending=adapter.generate(chat_input('Add Python'),Operation('owner','1','jd_chat'),current_revision=lambda:'1',validate_output=validate)
            if defect:
                with pytest.raises(AIError,match='invalid_output'): await pending
            else:
                result=await pending
                assert result.data.proposed_skills[0]==JDExtraction.model_validate(GOAL).skills[0]
                assert result.data.proposed_skills[1].origin=='user_declaration'
            assert len(calls)==2  # One operation, two provider calls.
    asyncio.run(invoke())
    assert len(calls)==2
    assert calls[1]['response_format']['json_schema']['name']=='jd_edit'
    goal=json.loads(calls[1]['messages'][1]['content'])['context']['career_goal']
    assert goal['skills'][0]['ref']=='0'
    assert 'saved-sql' not in json.dumps(calls)


def test_edit_cooldown_and_stale_response_cannot_publish():
    async def invoke(stale):
        calls=[];revision=['1']
        def handler(req):
            calls.append(req)
            if len(calls)==1: return completion({'reply':'Review a change.','edit_requested':True})
            if stale:
                revision[0]='2'
                return completion({'keep':['0'],'add':[]})
            return httpx.Response(429,headers={'retry-after':'40'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(config(),client)
            operation=Operation('owner','1','jd_chat')
            with pytest.raises(AIError,match='stale_input' if stale else 'rate_limited'):
                await adapter.generate(chat_input('Add Python'),operation,current_revision=lambda:revision[0])
            assert operation.status=='failed' and len(calls)==2
    asyncio.run(invoke(False));asyncio.run(invoke(True))


def test_numeric_usage_is_logged_for_invalid_output_and_correction(caplog):
    async def invoke():
        calls=[]
        def handler(req):
            calls.append(req)
            return completion({'role':'private invalid output'} if len(calls)==1 else {'role':None,'field':None,'company':None,'skills':[]},
                {'prompt_tokens':100,'completion_tokens':50,'total_tokens':150,'private':'secret'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(config(),client)
            await adapter.generate(AIInput(stage='jd_extraction',source_text='PRIVATE JD'),Operation('owner','1','jd_extraction'),current_revision=lambda:'1')
    with caplog.at_level(logging.INFO,logger='uvicorn.error.ai_usage'):
        asyncio.run(invoke())
    assert len(caplog.records)==2
    assert 'attempt=1 provider_attempt=1' in caplog.records[0].getMessage()
    assert 'attempt=2 provider_attempt=1' in caplog.records[1].getMessage()
    assert 'private' not in caplog.text.lower() and 'secret' not in caplog.text



def test_combined_edit_limit_is_rejected_before_public_response_validation():
    from app.ai.jd_contracts import SkillEdits, apply_edits
    existing=[JDExtraction.model_validate(GOAL).skills[0]]*60
    edit=SkillEdits(keep=[str(index) for index in range(60)],add=[{'name':'Python','category':'Technical',
        'priority':'suggested','origin':'generated_guidance'}])
    with pytest.raises(ValueError,match='Too many'):
        apply_edits(edit,existing)


@pytest.mark.parametrize('usage',[None,[],{'prompt_tokens':'private text','completion_tokens':True,'total_tokens':-1}])
def test_invalid_usage_does_not_log_content_or_break_generation(usage,caplog):
    from app.ai.adapter import record_usage
    raw=json.dumps({'usage':usage,'private':'DO NOT LOG'}).encode()
    with caplog.at_level(logging.INFO,logger='uvicorn.error.ai_usage'):
        record_usage(raw,'jd_extraction',1,1)
    assert not caplog.records


@pytest.mark.parametrize('fence',['```json','```'])
def test_json_fence_is_removed_locally_without_regenerating_extraction(fence):
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            content=fence+'\n'+json.dumps({'role':'Analyst','field':'Data','company':None,'skills':[]})+'\n```'
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':content}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(config(),client)
            result=await adapter.generate(AIInput(stage='jd_extraction',source_text='Synthetic analyst job'),Operation('owner','1','jd_extraction'),current_revision=lambda:'1')
        assert result.data.role=='Analyst' and len(calls)==1
    asyncio.run(run())


def test_json_fence_does_not_accept_duplicate_keys_or_trailing_prose():
    adapter=AIAdapter(config(),None)
    for content in ['```json\n{"role":"A","role":"B"}\n```','```json\n{}\n```\nUntrusted extra prose']:
        raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':content}}]}).encode()
        with pytest.raises(AIError,match='invalid_output'):adapter._content(raw)
