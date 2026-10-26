import asyncio
import json
import httpx
import pytest
from app.clients.search_sources import SourceAPIs
from app.repositories.goals import GoalError
from app.schemas.analysis import ResearchContext

def test_brave_only_uses_public_scope_and_never_calls_other_apis():
    async def run():
        calls=[]
        def handler(req):
            calls.append(req)
            assert req.url.host=='api.search.brave.com'
            assert req.method=='GET' and req.headers['X-Subscription-Token']=='fixture-key'
            assert 'Example Analyst Singapore interview' in req.url.params['q']
            return httpx.Response(200,json={'web':{'results':[{'url':'https://www.reddit.com/r/test/comments/abc/interview/','title':'Interview','description':'SQL interview exercise'}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            values=await SourceAPIs(client,brave_key='fixture-key',brave_mode='search').collect(ResearchContext(company='Example',role='Analyst',field='Data',location='Singapore'))
            assert len(calls)==1 and len(values)==1
            assert values[0].source_id.startswith('brave-')
            assert values[0].platform=='reddit' and values[0].reliability=='anecdotal'
            assert values[0].report_group is None
    asyncio.run(run())

def test_other_acquisition_platforms_are_rejected_without_network():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('No network allowed'))) as client:
            with pytest.raises(GoalError,match='Unsupported research platform'):
                await SourceAPIs(client,brave_key='fixture',brave_mode='answers').collect_platform(ResearchContext(role='Analyst',field='Data'),'reddit')
    asyncio.run(run())

def test_brave_answers_keeps_summary_and_attributed_claims_separate_from_excerpts():
    async def run():
        answer='Candidates report a technical interview and SQL assessment.'
        citation='<citation>'+json.dumps({'url':'https://example.test/report','snippet':'Reported SQL assessment','start_index':0,'end_index':len(answer)})+'</citation>'
        chunks=[answer,citation[:20],citation[20:],'<usage>{"X-Request-Tokens-Out":70}</usage>']
        wire=''.join('data: '+json.dumps({'choices':[{'delta':{'content':v}}]})+'\n\n' for v in chunks)+'data: [DONE]\n\n'
        def handler(req):
            payload=json.loads(req.content);assert payload['enable_citations'] and not payload['enable_research'] and payload['max_completion_tokens']==1536
            return httpx.Response(200,text=wire)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            batch=await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('analyst interview')
            assert len(batch.sources)==1 and batch.sources[0].evidence=='Reported SQL assessment'
            summary=batch.summaries[0];assert summary.text==answer
            assert summary.claims[0].text==answer and summary.claims[0].source_ids==[batch.sources[0].source_id]
            assert 'X-Request' not in summary.text and answer not in batch.sources[0].evidence
    asyncio.run(run())


def test_unconfigured_platforms_do_not_make_network_calls():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('No network allowed'))) as client:
            with pytest.raises(GoalError):await SourceAPIs(client).collect(ResearchContext(role='Analyst',field='Data'))
    asyncio.run(run())


def answer_wire(answer,citations,done=True,finish=None):
    chunks=[answer,*('<citation>'+json.dumps(c)+'</citation>' for c in citations)]
    wire=''.join('data: '+json.dumps({'choices':[{'delta':{'content':v}}]})+'\n\n' for v in chunks)
    if finish:wire+='data: '+json.dumps({'choices':[{'finish_reason':finish,'delta':{}}]})+'\n\n'
    return wire+('data: [DONE]\n\n' if done else '')


def test_llm_context_is_default_and_answers_remains_an_explicit_separate_cache_policy():
    assert SourceAPIs(None).brave_mode=='llm_context'
    api=SourceAPIs(None,brave_mode='answers')
    context=ResearchContext(company='Example',role='Analyst',field='Data',location='Singapore',seniority_level='Junior')
    first=api.query(context,0);broader=api.query(context,1)
    assert api.brave_mode=='answers' and 'What interview stages' in first
    assert 'Junior Analyst at Example in Singapore' in first and 'Cite sources for each finding' in first
    assert 'Example' not in broader and 'Data' in broader
    assert api.cache_policy!=SourceAPIs(None,brave_mode='search').cache_policy


@pytest.mark.parametrize('done,finish',[(False,None),(True,'length'),(True,'content_filter')])
def test_incomplete_answer_streams_do_not_publish_partial_research(done,finish):
    async def run():
        wire=answer_wire('Partial answer',[],done=done,finish=finish)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=wire))) as client:
            with pytest.raises(GoalError,match='incomplete'):
                await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
    asyncio.run(run())


def test_summary_without_citations_is_not_evidence_and_missing_offsets_are_not_guessed():
    async def run():
        for citations in ([],[{'url':'https://example.test/report','snippet':'SQL exercise.'}]):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=answer_wire('An unsupported hiring stage.',citations)))) as client:
                batch=await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
                if not citations:assert batch.summaries==[] and batch.sources==[]
                else:assert batch.summaries[0].claims==[] and batch.sources[0].evidence=='SQL exercise.'
    asyncio.run(run())


def test_answers_retains_at_most_six_citations_and_strips_usage_metadata():
    async def run():
        answer='Technical interview.'
        citations=[{'url':f'https://example.test/{i}','snippet':f'Public interview report {i}','start_index':0,'end_index':len(answer)} for i in range(8)]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=answer_wire(answer,citations)))) as client:
            batch=await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert len(batch.sources)==6 and len(batch.summaries[0].source_ids)==6
            assert len(batch.summaries[0].claims[0].source_ids)==6
    asyncio.run(run())


def test_answers_plan_rejection_has_an_actionable_message_without_provider_body():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(403,text='PRIVATE PROVIDER DETAILS'))) as client:
            with pytest.raises(GoalError,match='Answers plan') as error:await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert 'PRIVATE' not in str(error.value.message)
    asyncio.run(run())


def test_answers_uses_singapore_scope_without_defaulting_other_locations_to_us():
    async def run():
        countries=[]
        def handler(req):countries.append(json.loads(req.content)['country']);return httpx.Response(200,text=answer_wire('',[]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api=SourceAPIs(client,brave_key='fixture',brave_mode='answers')
            await api.collect(ResearchContext(role='Analyst',field='Data',location='Singapore'))
            await api.collect(ResearchContext(role='Analyst',field='Data',location='London'))
        assert countries==['SG','ALL']
    asyncio.run(run())


@pytest.mark.parametrize('status,expected',[(400,'request parameters'),(402,'billing'),(422,'request parameters'),(429,'rate limit'),(503,'temporarily unavailable')])
def test_brave_http_failures_report_safe_actionable_categories(status,expected):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,text='PRIVATE KEY OR PROVIDER CONTENT'))) as client:
            with pytest.raises(GoalError,match=expected) as error:
                await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert f'HTTP {status}' in error.value.message
            assert 'PRIVATE' not in error.value.message
    asyncio.run(run())


@pytest.mark.parametrize('failure,expected',[(httpx.ReadTimeout,'timed out'),(httpx.ConnectError,'network connection')])
def test_brave_transport_failures_do_not_blame_credentials(failure,expected):
    async def run():
        def handler(request):raise failure('PRIVATE transport details',request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(GoalError,match=expected) as error:
                await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert 'PRIVATE' not in error.value.message
    asyncio.run(run())


@pytest.mark.parametrize('code,expected',[
    ('RESOURCE_NOT_ALLOWED','Answers API access'),
    ('OPTION_NOT_IN_PLAN','not included'),
    ('SUBSCRIPTION_NOT_FOUND','no subscription'),
    ('SUBSCRIPTION_TOKEN_INVALID','rejected the subscription token'),
])
def test_brave_400_preserves_known_subscription_error_code_without_private_details(code,expected):
    async def run():
        payload={'error':{'code':code,'detail':'PRIVATE TOKEN AND USER QUERY','id':'PRIVATE ID','meta':{'secret':'PRIVATE'}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(400,json=payload))) as client:
            with pytest.raises(GoalError) as error:await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert code in error.value.message and expected in error.value.message
            assert 'PRIVATE' not in error.value.message
    asyncio.run(run())


@pytest.mark.parametrize('payload',[
    {'error':{'code':'PRIVATE','detail':'PRIVATE','meta':{'errors':[{'loc':['body','country'],'input':'PRIVATE'},{'loc':['PRIVATE'],'msg':'PRIVATE'}]}}},
    {'error':{'meta':{'errors':[{'loc':['body','country']},None,{'loc':'PRIVATE'}]}}},
])
def test_brave_validation_only_reports_known_field_names(payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(400,json=payload))) as client:
            with pytest.raises(GoalError) as error:await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert 'Rejected fields: country.' in error.value.message and 'PRIVATE' not in error.value.message
    asyncio.run(run())


@pytest.mark.parametrize('payload',[[],{'error':[]},{'error':{'code':[]}}, {'error':{'meta':{'errors':'PRIVATE'}}}])
def test_brave_malformed_error_body_keeps_safe_http_failure(payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(400,json=payload))) as client:
            with pytest.raises(GoalError,match='HTTP 400') as error:await SourceAPIs(client,brave_key='fixture',brave_mode='answers').brave('interview')
            assert 'PRIVATE' not in error.value.message
    asyncio.run(run())


def test_search_uses_alternative_snippets_without_answers_calls_or_duplicate_urls():
    async def run():
        calls=[]
        def handler(req):
            calls.append(req)
            assert req.method=='GET' and req.url.path.endswith('/web/search')
            assert req.url.params['count']=='3' and req.url.params['extra_snippets']=='true'
            assert req.url.params['country']=='ALL' and 'enable_citations' not in req.url.params
            return httpx.Response(200,json={'web':{'results':[
                {'url':'https://example.test/a','description':'Welcome to our careers website.',
                 'extra_snippets':['Three interview rounds include a technical assessment.','Three interview rounds include a technical assessment.']},
                {'url':'https://example.test/a','description':'Duplicate result'},
                {'url':'https://example.test/b','extra_snippets':['A behavioural interview is reported.']}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            values=await SourceAPIs(client,brave_key='fixture',brave_mode='search').collect(ResearchContext(role='Analyst',field='Data',location='Singapore'))
        assert len(calls)==1 and len(values)==2
        assert values[0].evidence.startswith('Three interview rounds')
        assert values[0].evidence.count('Three interview rounds')==1
        assert 'behavioural interview' in values[1].evidence
        assert all(len(v.evidence)<=600 for v in values)
    asyncio.run(run())


@pytest.mark.parametrize('payload',[
    {'web':{'results':[{'url':'https://example.test/interview','title':'Interview',
        'extra_snippets':[{'snippet':'Three interview rounds are reported.'}]}]}},
    {'results':[{'url':'https://example.test/interview','title':'Interview',
        'snippet':'Three interview rounds are reported.'}]},
])
def test_search_accepts_search_result_envelope_variants(payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _:httpx.Response(200,json=payload)
        )) as client:
            values=await SourceAPIs(client,brave_key='fixture',brave_mode='search').brave('interview')
        assert len(values)==1
        assert values[0].evidence=='Three interview rounds are reported.'
    asyncio.run(run())


def test_search_rejects_results_without_usable_urls_or_fields():
    async def run():
        payload={'web':{'results':[{'url':'not-a-public-url','description':'An interview is reported.'}]}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _:httpx.Response(200,json=payload)
        )) as client:
            with pytest.raises(GoalError,match='URLs or fields were not usable'):
                await SourceAPIs(client,brave_key='fixture',brave_mode='search').brave('interview')
    asyncio.run(run())


@pytest.mark.parametrize('description,extras',[
    ('Technical interview '+'x'*700,['Additional SQL assessment.']),
    ('A'*300,['B'*299,'C'*200]),
    ('A'*599,['B'*200,'C'*200]),
])
def test_search_evidence_at_exact_budget_never_appends_a_negative_slice(description,extras):
    from app.clients.search_sources import search_evidence
    async def run():
        value={'url':'https://example.test/interview','title':'Interview','description':description,'extra_snippets':extras}
        text=search_evidence(value)
        assert len(text)<=600
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _:httpx.Response(200,json={'web':{'results':[value]}})
        )) as client:
            sources=await SourceAPIs(client,brave_key='fixture',brave_mode='search').brave('interview')
        assert len(sources)==1 and sources[0].evidence==text
        from app.clients.research import normalize_batch
        assert normalize_batch(sources).sources[0].evidence==text
    asyncio.run(run())


@pytest.mark.parametrize('country,expected',[('SG','ALL'),('GB','GB'),('ALL','ALL')])
def test_search_sends_only_supported_country_enum_and_keeps_query_location(country,expected):
    async def run():
        def handler(request):
            assert request.url.params['country']==expected
            assert 'Singapore' in request.url.params['q']
            return httpx.Response(200,json={'web':{'results':[]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await SourceAPIs(client,brave_key='fixture',brave_mode='search').brave('DBS internship Singapore interview',country=country)==[]
    asyncio.run(run())
