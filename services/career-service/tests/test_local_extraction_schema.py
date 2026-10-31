"""Local extraction uses its full native schema and retains backend validation."""
import asyncio
import json
import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.api.v1.jd import validate_extraction

SOURCE='ExampleCo is hiring a Software Engineer Intern. Python is required. Git is preferred.'


def settings(**values):
    return AISettings(**{'enabled':True,'provider':'local','model':'synthetic',
        'base_url':'http://127.0.0.1:11434/v1','response_mode':'json_object',
        'context_tokens':16384,'timeout_seconds':45,**values})


def test_local_extraction_constrains_the_complete_nested_contract():
    payload=AIAdapter(settings(),None)._payload(AIInput(stage='jd_extraction',source_text=SOURCE))
    response=payload['response_format']
    assert response['type']=='json_schema' and response['json_schema']['strict']
    schema=response['json_schema']['schema']
    assert 'skills' in schema['properties'] and 'text' not in schema['properties']
    assert set(schema['required'])==set(schema['properties'])
    assert schema['additionalProperties'] is False
    job_date=schema['$defs']['ExtractedJobDate']
    assert set(job_date['properties'])=={'kind','text','evidence'}
    assert 'exact date wording' in job_date['properties']['text']['description']
    assert 'contains text verbatim' in job_date['properties']['evidence']['description']
    assert set(job_date['required'])==set(job_date['properties'])
    skill=schema['$defs']['ExtractedSkill']
    assert skill['additionalProperties'] is False
    assert set(skill['required'])==set(skill['properties'])
    assert 'priority' in skill['properties'] and 'evidence' in skill['properties']
    assert skill['properties']['origin']['enum']==['employer','generated_guidance']
    assert schema['$defs']['ExtractedCondition']['properties']['origin']['enum']==['employer','generated_guidance']
    assert payload['temperature']==0
    assert json.loads(payload['messages'][1]['content'])['source_text']==SOURCE


@pytest.mark.parametrize('provider',['deepseek','compatible'])
def test_cloud_extraction_retains_its_configured_json_mode(provider):
    payload=AIAdapter(settings(provider=provider,base_url='https://api.deepseek.com/v1',api_key='synthetic'),None)._payload(AIInput(stage='jd_extraction',source_text=SOURCE))
    assert payload['response_format']=={'type':'json_object'}
    schema=json.loads(payload['messages'][0]['content'].split('JSON schema: ',1)[1])
    job_date=schema['$defs']['ExtractedJobDate']
    assert set(job_date['properties'])=={'kind','text','evidence'}
    assert 'contains text verbatim' in job_date['properties']['evidence']['description']


@pytest.mark.parametrize('defect',[None,'flat_shape','bad_priority','wrong_origin'])
def test_local_extraction_still_rejects_bad_provider_output(defect):
    async def run():
        output={'role':'Software Engineer Intern','field':'Software','company':'ExampleCo',
            'employment_type':'internship','skills':[
                {'name':'Python','category':'Technical','priority':'required','origin':'employer','evidence':'Python is required.'},
                {'name':'Git','category':'Technical','priority':'preferred','origin':'employer','evidence':'Git is preferred.'}]}
        if defect=='flat_shape':output={'text':'PRIVATE output','category':'Technical','priority':'required','origin':'employer','field':'Software'}
        if defect=='bad_priority':output['skills'][0]['priority']='PRIVATE invalid enum'
        if defect=='wrong_origin':output['skills'][0]['origin']='generated_guidance'
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client)
            invoke=lambda:adapter.generate(AIInput(stage='jd_extraction',source_text=SOURCE),
                Operation('synthetic-owner','transient','jd_extraction'),current_revision=lambda:'transient',
                validate_output=lambda value:validate_extraction(value,None))
            if defect:
                with pytest.raises(AIError) as caught:await invoke()
                expected_reason='unexpected_origin' if defect=='wrong_origin' else 'schema_validation'
                assert caught.value.reason==expected_reason
                assert 'PRIVATE' not in str(caught.value.violations)
            else:
                result=await invoke()
                assert [(s.name,s.priority) for s in result.data.skills]==[('Python','required'),('Git','preferred')]
                assert result.data.employment_type=='internship'
        assert all(call['response_format']['type']=='json_schema' for call in calls)
        assert 'PRIVATE' not in json.dumps(calls)
    asyncio.run(run())


def test_extraction_repairs_job_date_evidence_and_derives_normalized_date():
    async def run():
        source='Start date: 1 April 2030. Python is required.'
        output={'job_dates':[{'kind':'job_start','text':'1 April 2030','evidence':'Start date:'}],
            'role':'Software Engineer Intern','field':'Software','employment_type':'internship',
            'company':'ExampleCo','location':None,'seniority_level':None,'summary':None,
            'responsibilities':[],'non_skill_requirements':[],'skills':[]}
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            if len(calls)>1:
                output['job_dates'][0]['evidence']='Start date: 1 April 2030.'
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop',
                'message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client)
            result=await adapter.generate(AIInput(stage='jd_extraction',source_text=source),
                Operation('synthetic-owner','transient','jd_extraction'),
                current_revision=lambda:'transient')
        assert len(calls)==2
        assert 'must contain text verbatim' in calls[0]['messages'][0]['content']
        assert result.data.job_dates[0].text=='1 April 2030'
        assert result.data.job_dates[0].date=='2030-04-01'
    asyncio.run(run())
