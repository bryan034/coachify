"""Request-bound decoding and recovery without publishing rejected model prose."""
import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIAdapter,AIError
from app.ai.goal_summary import summary_schema
from app.repositories.goals import GoalError
from app.workflows.goal_summary import summarize
from tests.test_goal_chat_presentation import environment
from tests.test_local_summary_schema import settings


@pytest.mark.parametrize('provider',['local','deepseek','compatible'])
def test_summary_schema_contains_only_references_from_this_snapshot(provider):
    context={'goal':{'reference':'goal','skills':[{'reference':'skill_0'}],
                     'non_skill_requirements':[{'reference':'condition_0'}]},
             'categories':{'interviews':{'reference':'coverage_interviews','findings':[{'reference':'research_0','source_ids':['not_a_fact']} ]}}}
    schema=summary_schema(context)
    assert schema['$defs']['SummaryBlock']['properties']['references']['items']['enum']==[
        'goal','skill_0','condition_0','coverage_interviews','research_0']
    adapter=AIAdapter(settings(provider=provider,base_url='https://example.test/v1',api_key='synthetic',response_mode='json_schema_strict'),None)
    from app.ai.contracts import AIInput
    payload=adapter._payload(AIInput(stage='goal_summary',context=json.dumps(context)))
    refs=payload['response_format']['json_schema']['schema']['$defs']['SummaryBlock']['properties']['references']['items']['enum']
    assert refs==schema['$defs']['SummaryBlock']['properties']['references']['items']['enum']


@pytest.mark.parametrize('code',['invalid_output','incomplete_output','context_limit'])
def test_summary_failure_uses_saved_findings_with_coverage_and_no_extra_model_calls(code):
    async def run():
        request,body,_,calls,record=environment()
        goal=request.app.state.workspace_store.goals.current('owner')['goal']
        goal.skills=[NS(name='Python',priority='required',source_urls=['https://example.test/requirement'])]
        record.intelligence.status='partial'
        record.intelligence.categories['interviews'].findings[0].scope='general'
        record.intelligence.categories['interviews'].findings[0].confidence='low'
        record.intelligence.categories['culture']=NS(status='failed',error_code='context_limit',findings=[],missing_fields=['team_culture'])
        async def fail(*args,**kwargs):calls.append(args);raise AIError(code)
        request.app.state.ai=NS(generate=fail)
        reply=(await summarize(request,'owner',body))['reply']
        assert '## Research findings' in reply and '**Role:** Analyst' in reply
        assert '**Required skills:** Python [Source](<https://example.test/requirement>)' in reply
        assert 'An interview is reported. (related context, low confidence) [Source](<https://example.test/job>)' in reply
        assert '**Coverage:** The research request exceeded' in reply
        assert '**Missing information:** team culture.' in reply
        assert reply.count('Ask me anything about this goal set!')==1 and len(calls)==1
    asyncio.run(run())


def test_summary_fallback_rechecks_goal_before_publishing():
    async def run():
        request,body,*_=environment()
        async def fail(*args,**kwargs):
            request.app.state.workspace_store.check=lambda *args:(_ for _ in ()).throw(GoalError('Goal changed',409))
            raise AIError('invalid_output')
        request.app.state.ai=NS(generate=fail)
        with pytest.raises(GoalError,match='Goal changed'):await summarize(request,'owner',body)
    asyncio.run(run())


def test_oversized_summary_context_uses_a_bounded_saved_digest_without_model_calls():
    async def run():
        request,body,_,calls,record=environment()
        from app.schemas.opportunity import CATEGORIES
        record.intelligence.categories={name:NS(status='completed',findings=[
            NS(value=f'Saved finding {index}. '+('Detail. '*70),source_ids=['s1'],scope='exact')
            for index in range(20)]) for name in CATEGORIES}
        reply=(await summarize(request,'owner',body))['reply']
        assert not calls
        assert reply.count('More findings are available')==5
        assert reply.count('[Source](<https://example.test/job>)')==10
        assert len(reply)<10000
    asyncio.run(run())


@pytest.mark.parametrize('code',['rate_limited','stale_input','provider_auth','unavailable'])
def test_summary_recovery_preserves_quota_staleness_and_provider_errors(code):
    async def run():
        request,body,*_=environment()
        async def fail(*args,**kwargs):raise AIError(code)
        request.app.state.ai=NS(generate=fail)
        with pytest.raises(AIError,match=code):await summarize(request,'owner',body)
    asyncio.run(run())
