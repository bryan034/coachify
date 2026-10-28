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
            return httpx.Response(200,json={'grounding':{'generic':[{'url':'https://www.reddit.com/r/test/comments/abc/interview/','title':'Interview','snippets':['SQL interview exercise']}]}})
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

def test_unconfigured_platforms_do_not_make_network_calls():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('No network allowed'))) as client:
            with pytest.raises(GoalError):await SourceAPIs(client).collect(ResearchContext(role='Analyst',field='Data'))
    asyncio.run(run())


@pytest.mark.parametrize('mode',['search','answers','llm_context'])
@pytest.mark.parametrize('method',['collect','collect_platform','collect_query','collect_opportunity_query'])
def test_all_legacy_modes_and_workflows_use_llm_context(mode,method):
    async def run():
        def handler(request):
            assert request.method=='GET' and request.url.path=='/res/v1/llm/context'
            return httpx.Response(200,json={'grounding':{'generic':[]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api=SourceAPIs(client,brave_key='fixture',brave_mode=mode)
            context=ResearchContext(company='Example',role='Analyst',field='Data',location='Singapore')
            args={'collect':(), 'collect_platform':('brave',), 'collect_query':('Analyst Singapore interview',), 'collect_opportunity_query':('Analyst Singapore interview',)}[method]
            assert await getattr(api,method)(context,*args)==[]
            assert api.brave_mode=='llm_context'
            assert api.cache_policy==SourceAPIs(None).cache_policy
            assert 'Example' in api.query(context,1) and 'Singapore' in api.query(context,1)
    asyncio.run(run())


def test_old_environment_mode_cannot_restore_web_or_answers(monkeypatch):
    monkeypatch.setenv('BRAVE_SEARCH_MODE','search')
    monkeypatch.setenv('BRAVE_API_KEY','synthetic')
    assert SourceAPIs.from_environment(None).brave_mode=='llm_context'


@pytest.mark.parametrize('payload',['data: [DONE]\n\n',{'web':{'results':[]}}, {'results':[]}])
def test_old_answer_streams_and_web_envelopes_are_not_published(payload):
    async def run():
        def handler(request):
            return httpx.Response(200,text=payload) if isinstance(payload,str) else httpx.Response(200,json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(GoalError):await SourceAPIs(client,brave_key='fixture').brave('interview')
    asyncio.run(run())


@pytest.mark.parametrize('status',[401,403])
def test_context_plan_rejection_does_not_expose_provider_body(status):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,text='PRIVATE PROVIDER DETAILS'))) as client:
            with pytest.raises(GoalError,match='LLM Context API credentials') as error:
                await SourceAPIs(client,brave_key='fixture').brave('interview')
            assert 'PRIVATE' not in error.value.message
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
    ('RESOURCE_NOT_ALLOWED','LLM Context API access'),
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


def test_context_deduplicates_url_and_snippets():
    async def run():
        payload={'grounding':{'generic':[
            {'url':'https://example.test/a','snippets':['Three interview rounds include a technical assessment.']*2},
            {'url':'https://example.test/a','snippets':['Three interview rounds include a technical assessment.']},
            {'url':'https://example.test/b','snippets':['A behavioural interview is reported.']}]}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            values=await SourceAPIs(client,brave_key='fixture').brave('interview')
        assert len(values)==2
        assert values[0].evidence.count('Three interview rounds')==1
    asyncio.run(run())


@pytest.mark.parametrize('description,extras',[
    ('Technical interview '+'x'*700,['Additional SQL assessment.']),
    ('A'*300,['B'*299,'C'*200]),
    ('A'*599,['B'*200,'C'*200]),
    ('Technical interview '+'x'*3000,['Additional SQL assessment.']),
    ('A'*2399,['B'*200,'C'*200]),
])
def test_search_evidence_at_exact_budget_never_appends_a_negative_slice(description,extras):
    from app.clients.search_sources import search_evidence
    async def run():
        value={'url':'https://example.test/interview','title':'Interview','description':description,'extra_snippets':extras}
        text=search_evidence(value,budget=2400)
        assert len(text)<=2400
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _:httpx.Response(200,json={'grounding':{'generic':[{'url':value['url'],'title':value['title'],'snippets':[description,*extras]}]}})
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
            return httpx.Response(200,json={'grounding':{'generic':[]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await SourceAPIs(client,brave_key='fixture',brave_mode='search').brave('DBS internship Singapore interview',country=country)==[]
    asyncio.run(run())
