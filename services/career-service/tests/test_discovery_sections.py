"""Constrained provider requests and bounded recovery of independent sections."""
import asyncio
import json

import httpx
import pytest

from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.discovery_contracts import OUTPUTS


def settings(provider='local',**updates):
    return AISettings(**{'enabled':True,'provider':provider,'api_key':'synthetic' if provider!='local' else '',
        'base_url':'http://127.0.0.1:11434/v1' if provider=='local' else 'https://example.test/v1',
        'model':'synthetic','response_mode':'json_object','context_tokens':32768,**updates})


def generate(stage,context,responses,provider='local',**overrides):
    calls=[]
    def handler(request):
        calls.append((str(request.url),json.loads(request.content)))
        result=responses[min(len(calls)-1,len(responses)-1)]
        if isinstance(result,httpx.Response):return result
        if isinstance(result,int):return httpx.Response(result)
        if provider=='deepseek':
            return httpx.Response(200,json={'object':'response','status':'completed','output':[
                {'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(result)}]}],
                'usage':{'input_tokens':200,'output_tokens':30,'total_tokens':230}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(provider,**overrides),client)
            request=AIInput(stage=stage,context=json.dumps(context),conversation=[{'role':'user','content':'Compare career directions.'}] if stage=='discovery_turn' else [])
            return await adapter.generate(request,Operation('synthetic-owner','1',stage),current_revision=lambda:'1')
    return asyncio.run(run()),calls


@pytest.mark.parametrize('provider',['local','gemini','deepseek'])
@pytest.mark.parametrize('stage',list(OUTPUTS))
def test_every_discovery_stage_uses_schema_constraints(provider,stage):
    payload=AIAdapter(settings(provider),None)._payload(AIInput(stage=stage,context='{}'))
    response=payload['response_format']
    assert response['type']=='json_schema'
    schema=response['json_schema']['schema']
    assert schema['additionalProperties'] is False
    assert set(schema['required'])==set(schema['properties'])


def test_bad_scope_does_not_discard_reply_and_has_only_two_targeted_retries():
    first={'action':'ANSWER','scope':42,'question':None,'reply':'Analysts interpret information to help decisions.'}
    result,calls=generate('discovery_turn',{},[first,{'scope':False,'reply':'OVERWRITE'}, {'scope':False}])
    assert result.data.reply==first['reply'] and result.data.scope is None
    assert result.failed_sections==('scope',) and len(calls)==3
    for _,payload in calls[1:]:
        assert set(payload['response_format']['json_schema']['schema']['properties'])=={'scope'}
    assert 'OVERWRITE' not in json.dumps(calls)


def test_each_understanding_answer_and_memory_list_can_recover_independently():
    previous={'preferences':['Work indoors'],'interests':['Data']}
    first={'action':'START_RESEARCH','scope':{'field':'Finance','area':'Finance'},'question':None,'reply':'We can explore finance.',
        'memory':{'interests':['Finance'],'preferences':42},
        'understanding':{'field':{'status':'known','value':'Finance','evidence':'Finance'},'career_stage':{'status':'invented'}}}
    result,calls=generate('discovery_turn',{'memory':previous},[first,
        {'memory.preferences':['Flexible hours'],'understanding.career_stage':False},
        {'understanding.career_stage':False,'memory.preferences':['OVERWRITE']}])
    assert len(calls)==3 and result.failed_sections==('understanding.career_stage',)
    assert result.data.memory.preferences==['Flexible hours'] and result.data.memory.interests==['Finance']
    assert result.data.understanding.field.value=='Finance'
    assert result.data.understanding.career_stage.status=='unanswered'
    assert result.data.action=='ANSWER' # Incomplete control context cannot start research.
    assert set(calls[-1][1]['response_format']['json_schema']['schema']['properties'])=={'understanding.career_stage'}


def skill(name='SQL',ref=0):
    return {'name':name,'skill_refs':[ref],'requirement_type':'core','learning_priority':'high','relevance':'Useful for data work.'}


@pytest.mark.parametrize('fixed',[False,True])
def test_valid_recommendations_survive_another_invalid_recommendation(fixed):
    context={'skills':[{'name':'SQL'},{'name':'Python'}],'responsibilities':[{'name':'Build APIs'}]}
    first={'responsibility_refs':[0],'skills':[skill(),skill('Python',99)],'specialisations':['Data work'],'question':None}
    repair={'skills.1':skill('Python',1 if fixed else 99),'skills.0':skill('OVERWRITE')}
    result,calls=generate('discovery_summary',context,[first,repair])
    assert result.data.skills[0].name=='SQL' and result.data.responsibility_refs==[0]
    assert result.data.specialisations==['Data work']
    assert len(result.data.skills)==(2 if fixed else 1)
    assert len(calls)==(2 if fixed else 3)
    assert result.failed_sections==(() if fixed else ('skills.1',))
    assert set(calls[1][1]['response_format']['json_schema']['schema']['properties'])=={'skills.1'}


def test_valid_assessment_survives_rejected_sibling_without_inventing_relevance():
    first={'sources':[{'ref':0,'relevant':True,'score':3,'quote':'Data work.'},
        {'ref':99,'relevant':True,'score':3,'quote':'Data work.'}]}
    result,calls=generate('discovery_assess',{'sources':[{},{}]},[first,{'sources.1':False}])
    assert len(calls)==3 and result.failed_sections==('sources.1',)
    assert result.data.sources[0].relevant is True
    assert result.data.sources[1].ref==1 and result.data.sources[1].relevant is False
    assert result.data.sources[1].quote is None


def test_omitted_assessment_gets_two_retries_without_discarding_the_completed_one():
    first={'sources':[{'ref':1,'relevant':True,'score':3,'quote':'Data work.'}]}
    result,calls=generate('discovery_assess',{'sources':[{},{}]},[first,{'sources.1':False}])
    assert len(calls)==3 and result.failed_sections==('sources.1',)
    assert result.data.sources[0].ref==1 and result.data.sources[0].relevant
    assert result.data.sources[1].ref==0 and not result.data.sources[1].relevant


def test_invalid_question_references_do_not_discard_extracted_listing():
    listing={'ref':0,'job_title':'Analyst','location':None,'career_stage':'unspecified','relevant':True,
        'requirements':[{'kind':'skill','name':'SQL','quote':'SQL required.'}]}
    first={'listings':[listing],'question':'Which work appeals?','question_refs':[42]}
    result,calls=generate('discovery_extract',{'sources':[{'title':'Analyst','excerpt':'SQL required.'}]},[first,{'question_refs':[42]}])
    assert len(calls)==3 and result.data.listings[0].job_title=='Analyst'
    assert result.data.question is None and result.data.question_refs==[]
    assert result.failed_sections==('question_refs',)


def test_repair_provider_failure_keeps_valid_sections():
    result,calls=generate('discovery_turn',{},[
        {'action':'ANSWER','scope':42,'question':None,'reply':'We can compare careers.'},429])
    assert len(calls)==2 and result.data.reply=='We can compare careers.'
    assert result.failed_sections==('scope',)


def test_truncated_repairs_do_not_discard_the_initial_valid_reply():
    truncated=httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{"scope":'}}]})
    result,calls=generate('discovery_turn',{},[
        {'action':'ANSWER','scope':42,'question':None,'reply':'We can compare careers.'},truncated])
    assert len(calls)==3 and result.failed_sections==('scope',)
    assert result.data.reply=='We can compare careers.'


def test_deepseek_uses_responses_schema_transport_not_json_only_chat():
    result,calls=generate('discovery_turn',{},[
        {'action':'ANSWER','scope':None,'question':None,'reply':'We can explore careers.'}],provider='deepseek')
    assert result.data.reply=='We can explore careers.' and len(calls)==1
    url,payload=calls[0]
    assert url=='https://example.test/v1/responses'
    assert payload['text']['format']['type']=='json_schema'
    assert payload['text']['format']['schema']['additionalProperties'] is False
    assert 'response_format' not in payload and 'messages' not in payload


def test_official_deepseek_v1_alias_uses_documented_responses_root():
    _,calls=generate('discovery_turn',{},[
        {'action':'ANSWER','scope':None,'question':None,'reply':'We can explore careers.'}],
        provider='deepseek',base_url='https://api.deepseek.com/v1')
    assert calls[0][0]=='https://api.deepseek.com/responses'


def test_unresolved_classification_cannot_publish_an_unrelated_answer():
    result,calls=generate('discovery_turn',{},[
        {'action':'invented','scope':None,'question':None,'reply':'Here is a recipe.'},{'action':'invented'}])
    assert len(calls)==3 and 'recipe' not in result.data.reply
    assert result.data.action=='ANSWER' and result.failed_sections==('action',)


def test_rejected_request_does_not_spend_retries_on_unused_sections():
    result,calls=generate('discovery_turn',{},[{'action':'REJECT_OUT_OF_SCOPE'}])
    assert len(calls)==1 and result.data.action=='REJECT_OUT_OF_SCOPE'


def test_unresolved_scope_preserves_previous_goal_and_skill_exclusions():
    context={'scope':{'field':'Finance','area':'Finance'},'previous':{'excluded_skills':['Sales']}}
    result,_=generate('discovery_turn',context,[{'action':'REFINE_SKILLS','scope':False,'question':None,
        'reply':'We can refine this direction.','excluded_skills':False}, {'scope':False,'excluded_skills':False}])
    assert result.data.scope.field=='Finance' and result.data.excluded_skills==['Sales']
    assert result.data.action=='ANSWER'


def test_partial_plan_keeps_valid_titles_without_inventing_search_queries():
    result,calls=generate('discovery_plan',{},[{'related_roles':['Analyst'],'queries':42},{'queries':False}])
    assert len(calls)==3 and result.data.related_roles==['Analyst'] and result.data.queries==[]


def test_whole_collection_repair_still_checks_each_source_reference():
    result,calls=generate('discovery_assess',{'sources':[{}]},[
        {'sources':42},{'sources':[{'ref':99,'relevant':True,'score':3,'quote':'Data work.'}]}])
    assert len(calls)==3 and result.failed_sections==('sources',)
    assert result.data.sources[0].ref==0 and not result.data.sources[0].relevant


def test_empty_citation_list_is_retried_when_a_question_requires_sources():
    result,calls=generate('discovery_extract',{'sources':[{}]},[
        {'listings':[],'question':'What work interests you?','question_refs':[]},{'question_refs':[]}])
    assert len(calls)==3 and result.failed_sections==('question_refs',)
    assert result.data.question is None


def test_no_correction_starts_after_the_remaining_time_budget_is_too_small():
    calls=[];clock=[0]
    def handler(request):
        calls.append(request)
        clock[0]=59
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'action':'ANSWER','scope':42,'question':None,'reply':'We can explore careers.'})}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(timeout_seconds=60),client,clock=lambda:clock[0])
            return await adapter.generate(AIInput(stage='discovery_turn',context='{}'),
                Operation('synthetic-owner','1','discovery_turn'),current_revision=lambda:'1')
    result=asyncio.run(run())
    assert len(calls)==1 and result.failed_sections==('scope',)
    assert result.data.reply=='We can explore careers.'


def test_stale_input_is_not_hidden_by_a_partial_result():
    revision=['1'];calls=[]
    def handler(request):
        calls.append(request);revision[0]='2'
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'action':'ANSWER','scope':42,'question':None,'reply':'We can explore careers.'})}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AIError,match='stale_input'):
                await AIAdapter(settings(),client).generate(AIInput(stage='discovery_turn',context='{}'),
                    Operation('synthetic-owner','1','discovery_turn'),current_revision=lambda:revision[0])
    asyncio.run(run())
    assert len(calls)==1


def test_operation_deadline_during_repair_keeps_valid_sections():
    calls=[]
    async def handler(request):
        calls.append(request)
        if len(calls)>1:await asyncio.sleep(2)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'action':'ANSWER','scope':42,'question':None,'reply':'We can compare careers.'})}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AIAdapter(settings(timeout_seconds=1),client).generate(AIInput(stage='discovery_turn',context='{}'),
                Operation('synthetic-owner','1','discovery_turn'),current_revision=lambda:'1')
    result=asyncio.run(run())
    assert len(calls)==2 and result.failed_sections==('scope',)
    assert result.data.reply=='We can compare careers.'
