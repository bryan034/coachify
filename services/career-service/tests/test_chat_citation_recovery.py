"""Presentation format repairs preserve approved-source and owner boundaries."""
import asyncio
import json
from types import SimpleNamespace as NS
import httpx
import pytest
from app.ai.adapter import AIError
from app.ai.goal_summary import GoalSummary
from app.ai.recovery import validation_feedback
from app.schemas.analysis import ResearchSource
from app.workflows.citations import normalize_citations, render_citations
from app.workflows.goal_summary import summarize
from app.workflows.operations import Operations
from tests.test_goal_chat_presentation import environment

SOURCES={'s1':'https://example.test/job','s2':'https://example.test/account'}


@pytest.mark.parametrize('reply,expected',[
    ('Reported [s1, s2].',{'s1','s2'}),
    ('Reported [s1; s2].',{'s1','s2'}),
    ('Reported [Source](https://example.test/job).',{'s1'}),
    ('Reported https://example.test/job.',{'s1'}),
])
def test_known_citation_formats_normalize_without_a_paid_repair(reply,expected):
    normalized,cited=normalize_citations(reply,SOURCES)
    assert cited==expected
    rendered=render_citations(normalized,SOURCES)
    assert all(f'[Source]({SOURCES[ref]})' in rendered for ref in expected)


@pytest.mark.parametrize('reply,issue',[
    ('Reported [s999].','unknown_source_reference'),
    ('Reported [s1, s999].','unknown_source_reference'),
    ('[Source](https://example.test/job/forged)','unapproved_source_url'),
    ('https://example.test/job?private=true','unapproved_source_url'),
    ('[Source](javascript:alert(1))','unapproved_source_url'),
])
def test_unknown_sources_remain_rejected_with_content_free_diagnostics(reply,issue):
    with pytest.raises(AIError) as caught:normalize_citations(reply,SOURCES)
    assert caught.value.violations==({'field':'reply','issue':issue},)
    assert 'forged' not in str(caught.value) and 'private' not in json.dumps(caught.value.violations)


def test_followup_bracketed_prose_is_preserved():
    text='Use the optional items [Python, SQL]. [Source](https://example.test/job)'
    normalized,cited=normalize_citations(text,SOURCES,strict_markers=False)
    assert '[Python, SQL]' in render_citations(normalized,SOURCES) and cited=={'s1'}


def test_summary_accepts_one_corroborating_source_for_each_finding():
    async def run():
        request,body,_,calls,record=environment('Reported [s1].')
        record.sources.append(ResearchSource(source_id='s2',platform='other',url=SOURCES['s2'],evidence='A corroborating account.'))
        record.intelligence.categories={'interviews':NS(findings=[NS(source_ids=['s1','s2'])])}
        assert '[Source]' in (await summarize(request,'owner',body))['reply'] and len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('invalid,issue',[
    ('PRIVATE_DISCARDED_VALUE [unknown]','unknown_source_reference'),
    ('PRIVATE_DISCARDED_VALUE without citation','missing_finding_citation'),
    ('PRIVATE_DISCARDED_VALUE https://unapproved.test','unapproved_source_url'),
])
def test_async_summary_repairs_only_presentation_and_rechecks_the_goal(caplog,invalid,issue):
    async def run():
        request,body,checks,_,record=environment()
        record.intelligence.categories={'interviews':NS(findings=[NS(source_ids=['s1'])])}
        calls=[];feedback=[]
        async def generate(payload,operation,**kwargs):
            calls.append(payload);feedback.append(validation_feedback.get())
            output=GoalSummary(reply=invalid if len(calls)==1 else 'Reported [s1].')
            kwargs['validate_output'](output)
            return NS(data=output)
        request.app.state.ai=NS(generate=generate)
        jobs=Operations()
        accepted=jobs.submit('owner','key','snapshot','summary',lambda:summarize(request,'owner',body))
        await jobs.jobs[accepted['operation_id']].task
        result=jobs.read('owner',accepted['operation_id'])
        assert result['status']=='succeeded' and '[Source]' in result['result']['reply']
        assert len(calls)==2 and len(checks)==4
        assert feedback[1]['violations']==[{'field':'reply','issue':issue}]
        assert calls[0].context==calls[1].context and 'PRIVATE_DISCARDED_VALUE' not in json.dumps(result)
        assert 'PRIVATE_DISCARDED_VALUE' not in caplog.text
        await jobs.close()
    asyncio.run(run())


def test_repeated_summary_failure_is_bounded_and_retains_safe_feedback():
    async def run():
        request,body,_,calls,_=environment('PRIVATE_DISCARDED_VALUE [unknown]')
        jobs=Operations();accepted=jobs.submit('owner','key','snapshot','summary',lambda:summarize(request,'owner',body))
        job=jobs.jobs[accepted['operation_id']];await job.task
        assert job.status=='failed' and len(calls)==7
        assert job.validation_feedback['violations']==[{'field':'reply','issue':'unknown_source_reference'}]
        assert 'PRIVATE_DISCARDED_VALUE' not in json.dumps(job.view())
        with pytest.raises(AIError):jobs.read('owner',job.id)
        await jobs.close()
    asyncio.run(run())


def test_failed_operation_response_includes_id_and_only_safe_validation_details():
    from app.main import create_app
    from app.api.v1.goals import owner
    async def run():
        app=create_app();jobs=Operations();app.state.operations=jobs
        app.dependency_overrides[owner]=lambda:'owner'
        async def fail():
            raise AIError('invalid_output',True,reason='provenance',fields=('reply',),
                          violations=({'field':'reply','issue':'missing_finding_citation'},))
        accepted=jobs.submit('owner','key','digest','summary',fail)
        await jobs.jobs[accepted['operation_id']].task
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            path='/api/v1/career/workspace/operations/'+accepted['operation_id']
            result=await client.get(path)
            assert result.status_code==503 and result.json()['operation_id']==accepted['operation_id']
            assert result.json()['diagnostic']['violations']==[{'field':'reply','issue':'missing_finding_citation'}]
            assert 'unsupported source claims' not in result.json()['detail']
            app.dependency_overrides[owner]=lambda:'other'
            assert (await client.get(path)).status_code==404
        await jobs.close()
    asyncio.run(run())
