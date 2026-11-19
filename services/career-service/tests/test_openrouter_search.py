"""OpenRouter model-native web search with a Brave LLM Context fallback (synthetic transports only)."""
import asyncio
import json
import httpx
import pytest
from app.clients import search_sources
from app.clients.search_sources import SourceAPIs, SourceRateLimit, SearchBackendError, cited_line
from app.repositories.goals import GoalError
from app.schemas.analysis import ResearchContext

SG=ResearchContext(role='Analyst',field='Data',location='Singapore')
ANSWER=('- The process has three interview rounds, including an SQL assessment ([example.test](https://example.test/a)).\n'
        '- Candidates report a behavioural interview with a hiring manager ([example.test](https://example.test/b)).')


def completion(text=ANSWER,annotations=None):
    if annotations is None:
        first=text.index('([example.test](https://example.test/a))')
        second=text.index('([example.test](https://example.test/b))')
        annotations=[
            {'type':'url_citation','url_citation':{'url':'https://example.test/a','title':'Interview report','start_index':first,'end_index':first+40}},
            {'type':'url_citation','url_citation':{'url':'https://example.test/b','title':'Second report','start_index':second,'end_index':second+40,
                                                  'content':'A behavioural interview with the hiring manager is reported by candidates.'}},
            {'type':'url_citation','url_citation':{'url':'http://127.0.0.1/private','content':'An interview is reported.'}}]
    return {'id':'gen-synthetic','model':'openai/gpt-4.1-mini','choices':[{'index':0,'finish_reason':'stop',
        'message':{'role':'assistant','content':text,'annotations':annotations}}],
        'usage':{'prompt_tokens':10,'completion_tokens':20,'server_tool_use_details':{'web_search_requests':1}}}


BRAVE={'grounding':{'generic':[{'url':'https://brave.test/c','title':'Brave report','snippets':['A case study interview is reported.']}]}}


def transport(openrouter,calls):
    def handler(request):
        calls.append(request)
        if request.url.host=='openrouter.ai':
            return openrouter(request) if callable(openrouter) else openrouter
        assert request.url.host=='api.search.brave.com'
        return httpx.Response(200,json=BRAVE)
    return httpx.MockTransport(handler)


def sources_for(openrouter,*,fallback='brave',brave_key='synthetic-brave',openrouter_key='synthetic-openrouter',**kwargs):
    async def run():
        calls=[]
        async with httpx.AsyncClient(transport=transport(openrouter,calls)) as client:
            api=SourceAPIs(client,backend='openrouter',fallback=fallback,brave_key=brave_key,openrouter_key=openrouter_key,**kwargs)
            return await api.collect_query(SG,'Analyst Singapore interview'),calls
    return asyncio.run(run())


def test_openrouter_request_asks_the_model_to_search_natively_and_keeps_cited_public_sources():
    seen=[]
    def reply(request):
        seen.append(json.loads(request.content))
        assert request.url.path=='/api/v1/chat/completions'
        assert request.headers['Authorization']=='Bearer synthetic-openrouter'
        return httpx.Response(200,json=completion())
    sources,calls=sources_for(reply,max_tool_calls=2)
    assert [c.url.host for c in calls]==['openrouter.ai']
    body=seen[0]
    assert body['model']=='openai/gpt-4.1-mini' and body['max_tokens']==search_sources.SEARCH_OUTPUT_TOKENS
    assert body['max_tool_calls']==2
    tool=body['tools'][0]
    assert tool['type']=='openrouter:web_search' and tool['parameters']['engine']=='native'
    assert tool['parameters']['max_results']==6
    assert tool['parameters']['user_location']['country']=='SG'
    assert 'Analyst Singapore interview' in body['messages'][1]['content']
    assert {s.url for s in sources}=={'https://example.test/a','https://example.test/b'}
    first=next(s for s in sources if s.url=='https://example.test/a')
    second=next(s for s in sources if s.url=='https://example.test/b')
    # Without a provider excerpt, the cited answer line (minus link markup) is the evidence,
    # labelled as model wording so it is never mistaken for a page quote.
    assert first.evidence.startswith(search_sources.SUMMARY_LABEL)
    assert 'three interview rounds' in first.evidence and 'https://' not in first.evidence and '](' not in first.evidence
    assert first.title=='Interview report' and first.source_id.startswith('brave-')
    assert 'hiring manager is reported by candidates' in second.evidence
    # A provider excerpt is used on its own, without the model's answer line.
    assert search_sources.SUMMARY_LABEL not in second.evidence and 'behavioural interview with a hiring manager' not in second.evidence


@pytest.mark.parametrize('response,reason',[
    (httpx.Response(429,headers={'retry-after':'7'},json={'error':{'message':'synthetic'}}),'rate_limited'),
    (httpx.Response(402,json={'error':{'message':'synthetic'}}),'quota'),
    (httpx.Response(403,json={'error':{'message':'synthetic'}}),'access'),
    (httpx.Response(503,json={'error':{'message':'synthetic'}}),'unavailable'),
    (httpx.Response(200,json=completion(text='No search was run.',annotations=[])),'no_sources'),
    (httpx.Response(200,content=b'not json'),'invalid_response'),
])
def test_openrouter_limits_and_failures_fall_back_to_brave_without_a_second_charge(monkeypatch,caplog,response,reason):
    charged=[]
    async def charge(owner,limit):charged.append(owner)
    monkeypatch.setattr(search_sources,'charge_search',charge)
    monkeypatch.setattr(search_sources,'current_budget_owner',lambda:'owner-synthetic')
    with caplog.at_level('WARNING',logger='uvicorn.error.research_search'):
        sources,calls=sources_for(response,metered=True)
    assert [c.url.host for c in calls]==['openrouter.ai','api.search.brave.com']
    assert [s.url for s in sources]==['https://brave.test/c']
    assert charged==['owner-synthetic']
    assert f'reason={reason}' in caplog.text and 'synthetic-openrouter' not in caplog.text


def test_server_errors_use_the_retryable_phrase_without_a_fallback():
    with pytest.raises(SearchBackendError) as error:sources_for(httpx.Response(503),fallback=None)
    assert 'temporarily unavailable' in str(error.value).casefold()


def test_a_slowly_streamed_response_hits_the_total_deadline_and_falls_back():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200,json=completion())
    sources,calls=sources_for(slow,search_timeout=0.05)
    assert [s.url for s in sources]==['https://brave.test/c'] and calls[-1].url.host=='api.search.brave.com'


def test_the_brave_fallback_has_a_total_deadline(monkeypatch):
    monkeypatch.setattr(search_sources,'SEARCH_DEADLINE_SECONDS',0.1)
    async def handler(request):
        if request.url.host=='openrouter.ai':return httpx.Response(503)
        await asyncio.sleep(1)
        return httpx.Response(200,json=BRAVE)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api=SourceAPIs(client,backend='openrouter',fallback='brave',brave_key='b',openrouter_key='o')
            return await api.collect_query(SG,'query')
    with pytest.raises(GoalError) as error:asyncio.run(run())
    assert 'timed out' in str(error.value)


def test_openrouter_timeout_is_capped_to_leave_the_fallback_time():
    api=SourceAPIs(None,backend='openrouter',openrouter_key='k',search_timeout=25)
    assert api.search_timeout==search_sources.SEARCH_DEADLINE_SECONDS-search_sources.MIN_FALLBACK_SECONDS


def test_cache_policy_differs_by_backend():
    brave=SourceAPIs(None,brave_key='k')
    openrouter=SourceAPIs(None,backend='openrouter',openrouter_key='k')
    assert brave.cache_policy=='public-interview-brave-context-v9:llm_context'
    assert openrouter.cache_policy!=brave.cache_policy and 'openrouter' in openrouter.cache_policy


def test_close_releases_the_sdk_client():
    async def run():
        async with httpx.AsyncClient(transport=transport(httpx.Response(200,json=completion()),[])) as client:
            api=SourceAPIs(client,backend='openrouter',openrouter_key='o')
            await api.collect_query(SG,'query')
            sdk=api.sdk
            await api.aclose()
            assert api.sdk is None and sdk._client.is_closed and not client.is_closed
            await api.aclose()
    asyncio.run(run())


def test_timeouts_fall_back_to_brave():
    def timeout(request):raise httpx.ReadTimeout('synthetic',request=request)
    sources,calls=sources_for(timeout)
    assert [s.url for s in sources]==['https://brave.test/c'] and calls[-1].url.host=='api.search.brave.com'


def test_without_a_fallback_rate_limits_stay_resumable_and_empty_searches_return_nothing():
    with pytest.raises(SourceRateLimit) as error:
        sources_for(httpx.Response(429,headers={'retry-after':'9'}),fallback=None)
    assert error.value.retry_after==9
    sources,calls=sources_for(httpx.Response(200,json=completion(text='Nothing.',annotations=[])),fallback=None)
    assert sources==[] and len(calls)==1
    with pytest.raises(SearchBackendError):sources_for(httpx.Response(402),fallback=None)


def test_a_blank_brave_key_disables_the_fallback():
    with pytest.raises(SourceRateLimit):sources_for(httpx.Response(429),brave_key='')


def test_missing_openrouter_key_uses_brave_directly_when_configured(caplog):
    with caplog.at_level('WARNING',logger='uvicorn.error.research_search'):
        sources,calls=sources_for(httpx.Response(500),openrouter_key='')
    assert [c.url.host for c in calls]==['api.search.brave.com'] and len(sources)==1
    assert 'research_search_fallback' not in caplog.text


def test_no_search_key_at_all_is_unconfigured():
    api=SourceAPIs(None,backend='openrouter',fallback='brave')
    assert not api.configured
    with pytest.raises(GoalError) as error:asyncio.run(api.collect_query(SG,'query'))
    assert 'OPENROUTER_API_KEY' in str(error.value)
    assert SourceAPIs(None,backend='openrouter',openrouter_key='k').configured
    assert SourceAPIs(None,backend='openrouter',fallback='brave',brave_key='k').configured
    assert not SourceAPIs(None,backend='openrouter',brave_key='k').configured


def test_configured_url_cap_limits_openrouter_results():
    seen=[]
    def reply(request):
        seen.append(json.loads(request.content));return httpx.Response(200,json=completion())
    sources,_=sources_for(reply,max_urls=1)
    assert seen[0]['tools'][0]['parameters']['max_results']==1 and len(sources)==1


def test_cited_line_strips_markup_and_rejects_bad_offsets():
    text='Intro\n1. **Two** rounds then an offer ([site](https://site.test/x)).\nOther'
    start=text.index('([site]')
    assert cited_line(text,start,start+5)=='Two rounds then an offer .'
    assert cited_line(text,-1,3)=='' and cited_line(text,5,2)=='' and cited_line(text,'1',3)==''
    for line,expected in [('3 technical interviews then a case study','3 technical interviews then a case study'),
                          ('- 2024 intake opens in March','2024 intake opens in March'),
                          ('2) 3.5 hours of assessments','3.5 hours of assessments')]:
        assert cited_line(line,0,len(line))==expected


def clear(monkeypatch):
    for name in ('CAREER_RESEARCH_PROVIDER','CAREER_RESEARCH_FALLBACK_PROVIDER','CAREER_RESEARCH_MODEL','CAREER_RESEARCH_API_KEY',
                 'BRAVE_API_KEY','OPENROUTER_API_KEY','CAREER_LLM_API_KEY','CAREER_LLM_BASE_URL',
                 'CAREER_RESEARCH_MAX_TOOL_CALLS','CAREER_RESEARCH_TIMEOUT_SECONDS'):
        monkeypatch.delenv(name,raising=False)


def test_environment_selects_openrouter_with_brave_fallback(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv('CAREER_RESEARCH_PROVIDER','openrouter')
    monkeypatch.setenv('CAREER_RESEARCH_FALLBACK_PROVIDER','brave')
    monkeypatch.setenv('CAREER_RESEARCH_API_KEY','synthetic-brave')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-shared')
    monkeypatch.setenv('CAREER_RESEARCH_MODEL','openai/gpt-5-mini')
    monkeypatch.setenv('CAREER_RESEARCH_MAX_TOOL_CALLS','4')
    monkeypatch.setenv('CAREER_RESEARCH_TIMEOUT_SECONDS','15')
    api=SourceAPIs.from_environment(None)
    assert (api.backend,api.fallback,api.brave_key,api.openrouter_key)==('openrouter','brave','synthetic-brave','synthetic-shared')
    assert (api.search_model,api.max_tool_calls,api.search_timeout)==('openai/gpt-5-mini',4,15)
    assert api.provider=='brave'  # persisted channel identifier is unchanged


def test_environment_defaults_match_the_template(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-shared')
    api=SourceAPIs.from_environment(None)
    assert (api.backend,api.fallback,api.openrouter_key)==('openrouter','brave','synthetic-shared')
    assert (api.search_model,api.max_tool_calls,api.search_timeout)==('openai/gpt-4.1-mini',3,15)


def test_a_blank_fallback_setting_disables_the_fallback(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv('CAREER_RESEARCH_FALLBACK_PROVIDER','')
    assert SourceAPIs.from_environment(None).fallback is None
    monkeypatch.setenv('CAREER_RESEARCH_PROVIDER','brave')
    assert SourceAPIs.from_environment(None).backend=='brave'


@pytest.mark.parametrize('base,expected',[('', 'synthetic-career'),('https://openrouter.ai/api/v1/','synthetic-career'),
                                          ('https://api.openai.com/v1','synthetic-shared')])
def test_career_key_is_reused_only_for_an_openrouter_model_endpoint(monkeypatch,base,expected):
    clear(monkeypatch)
    monkeypatch.setenv('CAREER_RESEARCH_PROVIDER','openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-shared')
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic-career')
    if base:monkeypatch.setenv('CAREER_LLM_BASE_URL',base)
    assert SourceAPIs.from_environment(None).openrouter_key==expected


@pytest.mark.parametrize('name,value',[('CAREER_RESEARCH_PROVIDER','exa'),('CAREER_RESEARCH_FALLBACK_PROVIDER','openrouter'),
                                       ('CAREER_RESEARCH_MAX_TOOL_CALLS','0'),('CAREER_RESEARCH_TIMEOUT_SECONDS','21')])
def test_invalid_search_settings_fail_startup_without_echoing_values(monkeypatch,name,value):
    clear(monkeypatch)
    monkeypatch.setenv('CAREER_RESEARCH_PROVIDER','openrouter')
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError) as error:SourceAPIs.from_environment(None)
    assert name in str(error.value)
