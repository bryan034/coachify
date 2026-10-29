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
    assert all(f'[Source](<{SOURCES[ref]}>)' in rendered for ref in expected)


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


def test_summary_resolves_a_finding_to_its_saved_corroborating_sources():
    async def run():
        request,body,_,calls,record=environment('Reported interview.')
        record.sources.append(ResearchSource(source_id='s2',platform='other',url=SOURCES['s2'],evidence='A corroborating account.'))
        record.intelligence.categories={'interviews':NS(findings=[NS(source_ids=['s1','s2'])])}
        reply=(await summarize(request,'owner',body))['reply']
        assert '[Source](<https://example.test/job>)' in reply and '[Source](<https://example.test/account>)' in reply
        assert len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('refs,issue',[
    (['missing_fact'],'unknown_fact_reference'),
    (['goal'],'missing_research_reference'),
    (['https://unapproved.test'],'unknown_fact_reference'),
])
def test_async_summary_repairs_only_presentation_and_rechecks_the_goal(caplog,refs,issue):
    async def run():
        request,body,checks,_,record=environment()
        calls=[];feedback=[]
        async def generate(payload,operation,**kwargs):
            calls.append(payload);feedback.append(validation_feedback.get())
            output=GoalSummary(blocks=[{'text':'PRIVATE_DISCARDED_VALUE' if len(calls)==1 else 'Reported interview.',
                                       'references':refs if len(calls)==1 else ['research_0']}])
            kwargs['validate_output'](output)
            return NS(data=output)
        request.app.state.ai=NS(generate=generate)
        jobs=Operations()
        accepted=jobs.submit('owner','key','snapshot','summary',lambda:summarize(request,'owner',body))
        await jobs.jobs[accepted['operation_id']].task
        result=jobs.read('owner',accepted['operation_id'])
        assert result['status']=='succeeded' and '[Source]' in result['result']['reply']
        assert len(calls)==2 and len(checks)==4
        assert feedback[1]['violations']==[{'field':'blocks' if issue=='missing_research_reference' else 'blocks.0.references','issue':issue}]
        assert calls[0].context==calls[1].context and 'PRIVATE_DISCARDED_VALUE' not in json.dumps(result)
        assert 'PRIVATE_DISCARDED_VALUE' not in caplog.text
        await jobs.close()
    asyncio.run(run())


def test_repeated_summary_failure_is_bounded_and_retains_safe_feedback():
    async def run():
        request,body,_,calls,_=environment('PRIVATE_DISCARDED_VALUE',references=('missing_fact',))
        jobs=Operations();accepted=jobs.submit('owner','key','snapshot','summary',lambda:summarize(request,'owner',body))
        job=jobs.jobs[accepted['operation_id']];await job.task
        assert job.status=='failed' and len(calls)==7
        assert job.validation_feedback['violations']==[{'field':'blocks.0.references','issue':'unknown_fact_reference'}]
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


def test_concise_overview_can_select_key_findings_without_repeating_every_citation():
    async def run():
        request,body,_,calls,record=environment('The main takeaway is an interview.')
        record.sources.append(ResearchSource(source_id='s2',platform='other',url=SOURCES['s2'],evidence='A secondary detail.'))
        record.intelligence.categories={'interviews':NS(status='completed',findings=[
            NS(source_ids=['s1'],value='The main takeaway.',quotes=['ORIGINAL_QUOTATION']),
            NS(source_ids=['s2'],value='A secondary detail.',quotes=['SECOND_QUOTATION'])])}
        result=await summarize(request,'owner',body)
        context=json.loads(calls[0].context)
        assert len(context['categories']['interviews']['findings'])==2
        assert 'ORIGINAL_QUOTATION' not in calls[0].context and 'quotes' not in calls[0].context
        assert 'A secondary detail' not in result['reply']
        assert result['reply'].endswith('Ask me anything about this goal set!')
    asyncio.run(run())


@pytest.mark.parametrize('ending',['','Ask me anything about this goal set!','Ask me anything about this goal set!\nAsk me anything about this goal set!'])
def test_overview_ends_with_the_exact_invitation_once(ending):
    async def run():
        request,body,*_=environment('Main takeaway.\n\n'+ending)
        result=await summarize(request,'owner',body)
        assert result['reply'].endswith('Ask me anything about this goal set!')
        assert result['reply'].count('Ask me anything about this goal set!')==1
    asyncio.run(run())


def test_finished_partial_research_is_summarised_with_its_limitations():
    async def run():
        request,body,_,calls,record=environment('Saved interview information. Other research is incomplete.')
        original=request.app.state.workspace_store.check
        def check(*args):
            row=original(*args);row['workspace']['phase']='research_failed';return row
        request.app.state.workspace_store.check=check
        record.intelligence.status='partial'
        record.intelligence.categories={'interviews':NS(status='completed',findings=[NS(source_ids=['s1'])]),
            'culture':NS(status='failed',findings=[],warnings=['Source unavailable'])}
        result=await summarize(request,'owner',body)
        assert 'Other research is incomplete' in result['reply']
        assert json.loads(calls[0].context)['categories']['culture']['status']=='failed'
        assert len(calls)==1
    asyncio.run(run())


def test_summary_does_not_publish_while_a_category_is_still_running():
    async def run():
        request,body,_,calls,record=environment()
        record.intelligence.categories={'interviews':NS(status='running',findings=[])}
        from app.repositories.goals import GoalError
        with pytest.raises(GoalError):await summarize(request,'owner',body)
        assert not calls
    asyncio.run(run())


@pytest.mark.parametrize('text',[
    '[Source](https://example.test/team_(interns))',
    '[Source](<https://example.test/team_(interns)>)',
    'Read https://example.test/team_(interns).',
    'Read (https://example.test/team_(interns)).',
    '<https://example.test/team_(interns)>',
])
def test_approved_parenthesised_urls_are_not_rejected(text):
    sources={'s1':'https://example.test/team_(interns)'}
    normalized,cited=normalize_citations(text,sources)
    assert cited=={'s1'}
    assert '[Source](<https://example.test/team_(interns)>)' in render_citations(normalized,sources)


def test_structured_summary_places_each_points_citations_next_to_its_text():
    async def run():
        request,body,_,_,record=environment()
        request.app.state.workspace_store.goals.current=lambda owner:{'goal':NS(id='goal',role='Analyst',field='Data',company='Example',
            location='Singapore',job_url='https://example.test/jobs_(internship)',
            skills=[{'name':'SQL','source_urls':['https://example.test/qualifications_(SQL)']}])}
        payloads=[]
        async def generate(payload,operation,**kwargs):
            payloads.append(payload)
            output=GoalSummary(blocks=[
                {'text':'An Analyst internship.','references':['goal']},
                {'text':'SQL [required] for this role.','references':['skill_0']},
                {'text':'Reported interview experience.','references':['research_0','research_0']},
            ])
            kwargs['validate_output'](output)
            return NS(data=output)
        request.app.state.ai=NS(generate=generate)
        reply=(await summarize(request,'owner',body))['reply']
        assert reply.startswith('## Your career goal\n\n- An Analyst internship.')
        assert len([line for line in reply.splitlines() if line.startswith('- ')])==3
        assert 'An Analyst internship. [Source](<https://example.test/jobs_(internship)>)' in reply
        assert 'SQL \\[required\\] for this role. [Source](<https://example.test/qualifications_(SQL)>)' in reply
        assert 'Reported interview experience. [Source](<https://example.test/job>)' in reply
        assert reply.count('https://example.test/job>')==1
        assert reply.endswith('Ask me anything about this goal set!')
        context=json.loads(payloads[0].context)
        assert context['goal']['reference']=='goal'
        assert context['goal']['skills'][0]['reference']=='skill_0'
        assert 'source_urls' not in context['goal']['skills'][0]
        assert 'jobs_(internship)' not in payloads[0].context
        assert 'qualifications_(SQL)' not in payloads[0].context
        assert record.sources[0].url=='https://example.test/job'
    asyncio.run(run())


def test_model_prose_cannot_create_links_outside_structured_references():
    async def run():
        request,body,*_=environment('An [invented source](https://unapproved.test) and <https://unapproved.test>.')
        reply=(await summarize(request,'owner',body))['reply']
        assert '\\[invented source\\]\\(https://unapproved.test\\)' in reply
        assert '\\<https://unapproved.test\\>' in reply
        assert '[Source](<https://example.test/job>)' in reply
    asyncio.run(run())


def test_research_blocks_always_require_a_known_fact_reference():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GoalSummary(blocks=[{'text':'Unreferenced research','references':[]}])
    with pytest.raises(ValidationError):
        GoalSummary(blocks=[{'text':'Forged source','references':['research_0'],'url':'https://unapproved.test'}])


def test_real_adapter_accepts_structured_summary_points_and_supplies_json_context():
    from app.ai.adapter import AIAdapter
    from app.ai.config import AISettings
    async def run():
        request,body,*_=environment()
        calls=[]
        def provider(http_request):
            payload=json.loads(http_request.content);calls.append(payload)
            incoming=json.loads(payload['messages'][-1]['content'])
            assert isinstance(incoming['context'],dict)
            assert incoming['context']['categories']['interviews']['findings'][0]['reference']=='research_0'
            assert 'source_ids' not in incoming['context']['categories']['interviews']['findings'][0]
            schema=payload['response_format']['json_schema']['schema']
            assert 'blocks' in schema['properties'] and 'reply' not in schema['properties']
            output={'blocks':[{'text':'Reported interview experience.','references':['research_0']}]}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            request.app.state.ai=AIAdapter(AISettings(enabled=True,model='synthetic',api_key='synthetic'),client)
            reply=(await summarize(request,'owner',body))['reply']
        assert 'Reported interview experience. [Source](<https://example.test/job>)' in reply
        assert len(calls)==1
    asyncio.run(run())
