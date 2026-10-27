"""Brave summary context retains original-source attribution and fits model budgets."""
import json
import pytest
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.usage import input_tokens
from app.clients.research import normalize_batch
from app.domain.interview import topics_from
from app.repositories.goals import GoalError
from app.schemas.analysis import ResearchSource,BraveAnswer,AnswerClaim
from app.schemas.research import SourcedTopics,ResearchBatch

TEXT='Candidates report a technical interview and SQL assessment.'

def evidence():
    source=ResearchSource(source_id='s1',platform='other',url='https://example.test/interview',evidence='SQL exercise was reported.')
    summary=BraveAnswer(summary_id='answer1',text=TEXT,source_ids=['s1'],claims=[AnswerClaim(text=TEXT,source_ids=['s1'])])
    return source,summary

def topic(**changes):
    return {'name':'SQL','category':'Technical','interview_stage':'technical interview','assessment_type':'SQL assessment',
        'source_ids':['s1'],'quotes':[TEXT],'evidence_origin':'brave_summary','summary_id':'answer1',**changes}


def test_cited_summary_can_supply_a_stage_without_masquerading_as_a_source_quote():
    source,summary=evidence()
    skills=topics_from(SourcedTopics(topics=[topic()]),[source],[summary])
    assert skills[0].interview_stage=='technical interview' and skills[0].assessment_type=='SQL assessment'
    assert skills[0].evidence_origin=='brave_summary' and skills[0].summary_id==summary.summary_id
    assert skills[0].independent_report_count==0
    with pytest.raises(AIError):topics_from(SourcedTopics(topics=[topic(evidence_origin='source_excerpt',summary_id=None)]),[source],[summary])


@pytest.mark.parametrize('change',[{'summary_id':'invented'},{'source_ids':['invented']},{'quotes':['Invented interview claim.']},{'question_patterns':['Invented question?']}])
def test_model_cannot_invent_summary_citations_or_quotes(change):
    source,summary=evidence()
    with pytest.raises(AIError):topics_from(SourcedTopics(topics=[topic(**change)]),[source],[summary])


def test_uncited_summary_prose_cannot_establish_a_stage():
    source,summary=evidence();summary.claims=[]
    with pytest.raises(AIError):topics_from(SourcedTopics(topics=[topic()]),[source],[summary])


def test_connector_summary_claims_must_match_text_and_real_source_references():
    source,summary=evidence();summary.claims[0].text='Made up claim'
    with pytest.raises(GoalError):normalize_batch(ResearchBatch(sources=[source],summaries=[summary]))


def test_summary_rich_synthesis_stays_below_4000_input_tokens_and_keeps_claims():
    text=('Public reports describe technical interviews, SQL assessments and coding exercises. '*40)[:2400]
    sources=[ResearchSource(source_id=f's{i}',platform='other',url=f'https://example.test/{i}',evidence=(f'Interview {i} SQL coding assessment. '*30)[:600]) for i in range(6)]
    summaries=[BraveAnswer(summary_id=f'a{i}',text=text,source_ids=[s.source_id for s in sources],claims=[AnswerClaim(text=text[j:j+500],source_ids=['s0']) for j in (0,500,1000,1500)]) for i in range(2)]
    adapter=AIAdapter(AISettings(enabled=True,model='gemini-3.5-flash-lite',api_key='fixture'),None)
    payload=adapter._payload(AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=sources,summaries=summaries))
    assert input_tokens(payload)<=4000 and payload['max_tokens']==2048
    sent=json.loads(payload['messages'][1]['content'])
    assert any(v['origin']=='brave_summary' and v['text']==summaries[0].claims[0].text for v in sent['evidence'])
    assert 'summaries' not in sent and 'sources' not in sent


@pytest.mark.parametrize('mode',['json_object','json_schema_strict'])
def test_answers_findings_round_trip_through_provider_contract_and_backend_attribution(mode):
    import asyncio
    import httpx
    from app.ai.adapter import Operation
    async def run():
        source,summary=evidence()
        request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=[source],summaries=[summary])
        def handler(req):
            payload=json.loads(req.content)
            sent=json.loads(payload['messages'][1]['content'])
            assert sent['evidence']==[
                {'ref':'e1','origin':'source_excerpt','text':source.evidence},
                {'ref':'e2','origin':'brave_summary','text':TEXT}]
            assert 'source_ids' not in payload['messages'][1]['content']
            schema=(json.loads(payload['messages'][0]['content'].rsplit('\nJSON schema: ',1)[1])
                    if mode=='json_object' else payload['response_format']['json_schema']['schema'])
            finding=(schema['$defs']['Finding'] if mode=='json_object' else schema['properties']['topics']['items'])['properties']
            assert 'evidence_ref' in finding and 'quotes' not in finding and 'summary_id' not in finding
            output={'topics':[{'name':'SQL','category':'Technical','interview_stage':'technical interview',
                'assessment_type':'SQL assessment','difficulty':'unknown','question_patterns':[],'evidence_ref':'e2'}]}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(AISettings(enabled=True,model='gemini-3.5-flash-lite',api_key='fixture',response_mode=mode),client)
            result=await adapter.generate(request,Operation('owner','r1',request.stage),current_revision=lambda:'r1')
        topic=result.data.topics[0]
        assert topic.source_ids==['s1'] and topic.summary_id=='answer1'
        assert topic.quotes==[TEXT] and topic.evidence_origin=='brave_summary'
        assert topics_from(result.data,[source],[summary])[0].interview_stage=='technical interview'
    asyncio.run(run())


@pytest.mark.parametrize('ref,patterns',[('invented',[]),('e2',['Invented question?'])])
def test_compact_provider_findings_cannot_publish_fabricated_references_or_questions(ref,patterns):
    import asyncio
    import httpx
    from app.ai.adapter import Operation
    async def run():
        source,summary=evidence()
        request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=[source],summaries=[summary])
        output={'topics':[{'name':'SQL','category':'Technical','evidence_ref':ref,'question_patterns':patterns}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]}))) as client:
            adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client)
            with pytest.raises(AIError) as error:
                await adapter.generate(request,Operation('owner','r1',request.stage),current_revision=lambda:'r1')
            assert error.value.reason=='provenance'
    asyncio.run(run())


def test_compact_findings_restore_direct_excerpt_links_and_unknown_stages():
    from app.ai.interview_contracts import InterviewFindings
    source,summary=evidence()
    request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=[source],summaries=[summary])
    output=InterviewFindings(topics=[{'name':'SQL','category':'Technical','evidence_ref':'e1','interview_stage':'Final round'}]).to_domain(request)
    skills=topics_from(output,[source],[summary])
    assert skills[0].evidence_origin=='source_excerpt' and skills[0].summary_id is None
    assert skills[0].interview_stage is None and output.topics[0].quotes==[source.evidence]


def test_interview_round_count_and_stages_require_explicit_attributed_evidence():
    from app.ai.interview_contracts import InterviewFindings
    text='There are three interview rounds. The technical interview includes a SQL assessment.'
    source=ResearchSource(source_id='s1',platform='other',url='https://example.test/interview',evidence=text)
    request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=[source])
    output=InterviewFindings(topics=[],process={'round_count':3,'count_evidence_ref':'e1','stages':[{'name':'technical interview','assessment_type':'SQL assessment','evidence_ref':'e1'}]}).to_domain(request)
    assert output.process.round_count==3
    assert output.process.round_count_evidence.text==text
    assert output.process.stages[0].evidence.source_ids==['s1']
    assert output.process.stages[0].name=='technical interview'
    with pytest.raises(ValueError):InterviewFindings(topics=[],process={'round_count':4,'count_evidence_ref':'e1'}).to_domain(request)
    with pytest.raises(ValueError):InterviewFindings(topics=[],process={'round_count':3,'count_evidence_ref':'invented'}).to_domain(request)
    with pytest.raises(ValueError):InterviewFindings(topics=[],process={'stages':[{'name':'Final interview','evidence_ref':'e1'}]}).to_domain(request)


def test_round_count_is_not_derived_from_skill_or_question_counts():
    from app.ai.interview_contracts import InterviewFindings
    source=ResearchSource(source_id='s1',platform='other',url='https://example.test/interview',evidence='Three SQL skills and two practice questions are listed.')
    request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=[source])
    with pytest.raises(ValueError):InterviewFindings(topics=[],process={'round_count':3,'count_evidence_ref':'e1'}).to_domain(request)
    output=InterviewFindings(topics=[]).to_domain(request)
    assert output.process.round_count is None and output.process.stages==[]


def test_research_evidence_is_deduplicated_and_budgeted_with_stable_verified_refs():
    from app.ai.interview_contracts import evidence_items,interview_input,RESEARCH_EVIDENCE_TOKENS,InterviewFindings
    import tiktoken
    sources=[ResearchSource(source_id=f's{i}',platform='other',url=f'https://example.test/{i}',
        evidence=(f'Technical interview round {i}: SQL assessment. '+('Public role guidance. '*35))[:600]) for i in range(6)]
    claim='The technical interview includes a SQL assessment.'
    summaries=[BraveAnswer(summary_id=f'a{i}',text=claim,source_ids=['s0'],claims=[AnswerClaim(text=claim,source_ids=['s0'])]) for i in range(2)]
    request=AIInput(stage='interview_synthesis',public_context={'role':'Analyst','field':'Data'},sources=sources,summaries=summaries)
    items=evidence_items(request);sent=interview_input(request)['evidence']
    assert len(tiktoken.get_encoding('o200k_harmony').encode(json.dumps(sent,ensure_ascii=False,separators=(',',':'))))<=RESEARCH_EVIDENCE_TOKENS
    assert sum(v['text']==claim for v in sent)<=1
    assert all(v['text'] in [s.evidence for s in sources]+[claim] for v in sent)
    item=items[0]
    result=InterviewFindings(topics=[{'name':'SQL','category':'Technical','evidence_ref':item['ref']}]).to_domain(request)
    assert result.topics[0].source_ids==item['source_ids'] and result.topics[0].quotes[0]==item['text']
    adapter=AIAdapter(AISettings(enabled=True,model='gemini-3.5-flash-lite',api_key='fixture'),None)
    assert input_tokens(adapter._payload(request))<=4000
