"""Full JD prompt/token admission, including schema and repair overhead."""
import json
import pytest
from pydantic import ValidationError
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.recovery import validation_feedback
from app.ai.usage import input_tokens


def jd_text():
    sentence='Software Engineer Intern in Singapore. Build Python services, write SQL queries, test APIs and document changes. '
    return (sentence*100)[:7999]+'X'


def settings(mode='json_object',**overrides):
    return AISettings(**{'provider':'local','base_url':'http://host.docker.internal:11434/v1',
        'response_mode':mode,'context_tokens':16384,**overrides})


@pytest.mark.parametrize('stage,cap',[('jd_scope',8192),('jd_extraction',8192)])
@pytest.mark.parametrize('mode',['json_object','json_schema','json_schema_strict'])
@pytest.mark.parametrize('repair',[False,True])
def test_full_8000_character_jd_fits_with_instructions_schema_output_and_margin(stage,cap,mode,repair):
    source=jd_text();assert len(source)==8000
    token=validation_feedback.set({'reason':'schema_validation','fields':['role'],
        'violations':[{'field':'role','issue':'missing'}]} if repair else None)
    try:
        payload=AIAdapter(settings(mode),None)._payload(AIInput(stage=stage,source_text=source))
    finally:validation_feedback.reset(token)
    assert json.loads(payload['messages'][1]['content'])['source_text']==source
    assert payload['max_tokens']==cap
    margin=max(1024,16384//10)
    assert input_tokens(payload)+cap+margin<=16384
    if stage=='jd_extraction':
        # This complete request was rejected when byte counts were compared to
        # the available token budget, despite fitting in the model window.
        byte_count=sum(len(message['content'].encode()) for message in payload['messages'])+len(json.dumps(payload['response_format']).encode())
        assert byte_count>16384-cap-margin
    if repair:assert 'Latest validation issues:' in payload['messages'][0]['content']


@pytest.mark.parametrize('stage,cap',[('jd_scope',8192),('jd_extraction',8192)])
@pytest.mark.parametrize('mode',['json_object','json_schema','json_schema_strict'])
def test_context_boundary_uses_the_entire_prompt_not_just_the_jd(stage,cap,mode):
    request=AIInput(stage=stage,source_text=jd_text())
    payload=AIAdapter(settings(mode),None)._payload(request)
    count=input_tokens(payload)
    low,high=2048,16384
    while low<high:
        candidate=(low+high)//2
        if count+cap+max(1024,candidate//10)<=candidate:high=candidate
        else:low=candidate+1
    boundary=low
    fitting=AIAdapter(settings(mode,context_tokens=boundary),None)._payload(request)
    assert fitting['max_tokens']==cap
    assert json.loads(fitting['messages'][1]['content'])['source_text']==request.source_text
    with pytest.raises(AIError,match='context_limit'):
        AIAdapter(settings(mode,context_tokens=boundary-1),None)._payload(request)


def test_dense_unicode_fails_context_admission_without_truncating_a_legal_jd():
    request=AIInput(stage='jd_extraction',source_text='🧭'*8000)
    with pytest.raises(AIError,match='context_limit'):AIAdapter(settings(),None)._payload(request)
    assert request.source_text=='🧭'*8000
    payload=AIAdapter(settings(context_tokens=65536),None)._payload(request)
    assert json.loads(payload['messages'][1]['content'])['source_text']==request.source_text
    with pytest.raises(ValidationError):AIInput(stage='jd_extraction',source_text='🧭'*8001)


def test_explicit_global_output_ceiling_is_still_respected():
    adapter=AIAdapter(settings(max_output_tokens=2048),None)
    for stage in ('jd_scope','jd_extraction'):
        assert adapter._payload(AIInput(stage=stage,source_text=jd_text()))['max_tokens']==2048


@pytest.mark.parametrize('provider',['gemini','deepseek','compatible'])
def test_cloud_identification_keeps_its_existing_output_budget(provider):
    adapter=AIAdapter(AISettings(provider=provider,response_mode='json_object'),None)
    assert adapter._payload(AIInput(stage='jd_scope',source_text=jd_text()))['max_tokens']==4096
