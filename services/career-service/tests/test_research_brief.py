"""Version 2 research briefs: schema validation, word limits, citations, source numbering, persistence and routes (synthetic data)."""
import asyncio
import json
from datetime import datetime,timezone
from types import SimpleNamespace as NS
import pytest
from pydantic import ValidationError
from app.ai.errors import AIError
from app.ai.brief_contracts import InterviewBriefOutput,RoleBriefOutput,brief_schema
from app.repositories.goals import GoalError
from app.schemas.research_brief import WORD_LIMITS,RoleBrief
from app.workflows import research_brief as briefs

STAMP=datetime(2026,11,21,8,0,tzinfo=timezone.utc)


def finding(fid,field,value,sources,conflict=None,round_number=None):
    return NS(finding_id=fid,field=field,value=value,source_ids=sources,evidence_type='candidate_reported',conflict_group=conflict,round_number=round_number,round_name=None)


def page(sid,url,title,platform='other'):
    return NS(source_id=sid,url=url,title=title,platform=platform)


def record(research_id='r1'):
    categories={
        'internship_insights':NS(researched_at=STAMP,findings=[finding('f1','mentorship','Busy staff had little time to mentor.',['p2']),
                                                              finding('f2','mentorship','Supervisors gave career advice.',['p3'],conflict='mentor')]),
        'company_intelligence':NS(researched_at=STAMP.replace(hour=6),findings=[finding('f3','management','Reviews cite weak delegation.',['p4'])]),
        'interview_intelligence':NS(researched_at=STAMP,findings=[finding('f9','interview_questions','Asked about past projects.',['p5'],round_number=1)])}
    sources=[page('p2','https://www.glassdoor.sg/intern-reviews','Synapse intern reviews | Glassdoor','glassdoor'),
             page('p3','https://example.test/linkedin-post','Internship post - LinkedIn'),
             page('p4','https://www.indeed.com/management','Employee reviews about management'),
             page('p5','https://www.glassdoor.sg/interview','Intern interview questions','glassdoor')]
    return NS(id=research_id,sources=sources,updated_at=STAMP,intelligence=NS(categories=categories))


def goal(version=3):
    return NS(id='a'*24,version=version,role='GenAI Intern',company='Example Health',field='Data',location='Singapore',employment_type='internship',
              seniority_level=None,summary='Coordinate GenAI projects.',responsibilities=['Coordinate project timelines','Run workshops'],
              non_skill_requirements=[NS(requirement_id='grad',description='Graduating Dec 2026 or May 2027.',source_urls=['https://jobs.example.test/123'])],
              job_url='https://jobs.example.test/123')


class Collection:
    def __init__(self):self.rows={}
    def replace_one(self,query,row,upsert=False):self.rows[query['_id']]=row
    def find_one(self,query):return self.rows.get(query['_id'])


def request(*outputs):
    calls=[]
    async def generate(req,operation,**kwargs):
        from app.ai.recovery import validation_feedback
        calls.append((req,validation_feedback.get()))
        output=outputs[min(len(calls),len(outputs))-1]
        kwargs['validate_output'](output)
        return NS(data=output)
    saved=goal()
    store=NS(current=lambda owner:{'goal':saved},goals=NS(database={'research_briefs':Collection()}))
    return NS(app=NS(state=NS(ai=NS(generate=generate,context_enabled=True),goal_store=store,brief_tasks={}))),calls


def role_output(**changes):
    data={'summary':'A hybrid GenAI delivery internship with mixed mentorship and weak management reviews.',
          'facts':[{'label':'Who can apply','value':'Graduating 2026 or 2027','note':'From the job description','citations':['S1']},
                   {'label':'Work setup','value':'Hybrid','note':None,'citations':[]},
                   {'label':'Reviews','value':'Mixed','note':'Strong teams, weak management','citations':['S4','S2']},
                   {'label':'After the internship','value':'Return offer possible','note':None,'citations':[]}],
          'duties':['Coordinate GenAI project timelines','Run workshops on AI solutions','Run workshops on AI solutions'],
          'topics':[{'id':'management','title':'Management','tone':'negative','takeaway':'Delegation is the main complaint.','estimated':False,'conflicting':False,
                     'reports':[{'text':'A review cited weak delegation.','citations':['S4']}]},
                    {'id':'mentorship','title':'Mentorship','tone':'mixed','takeaway':'Good when the team has time.','estimated':False,'conflicting':True,
                     'reports':[{'text':'Busy staff had little time to mentor.','citations':['S2']},{'text':'Supervisors gave career advice.','citations':['S3','S2']}]},
                    {'id':'benefits','title':'Benefits','tone':'mixed','takeaway':'Typical intern leave.','estimated':False,'conflicting':False,'reports':[]}],
          'pay':[{'label':'Intern pay','value':'S$1,799/mo','caveat':None,'citations':[]}],
          'not_found':['Benefits','Intake size','benefits'],
          'sources':[{'key':'S4','title':'Employee reviews about management','domain':'Indeed'},{'key':'S2','title':'Intern reviews','domain':'Glassdoor'}]}
    data.update(changes)
    return RoleBriefOutput.model_validate(data)


def interview_output(**changes):
    data={'summary':'One short, friendly call with the team manager.',
          'process':[{'title':'Apply','when':'Six months before start','detail':None,'citations':[]},
                     {'title':'Manager interview','when':'Reported','detail':'Short and online.','citations':['S2']}],
          'difficulty':{'level':'average','estimated':True,'reason':'Coordination and communication scenarios.'},
          'questions':[{'question':'Tell me about a past project.','prep':'Outline your role, actions and result.','estimated':False}],
          'candidate_reports':{'asked_about':[{'label':'Past projects','citations':['S2']}],'situational':None,
                               'tone':{'text':'Quick and informal.','citations':['S2']},
                               'reports':[{'text':'A candidate was asked about past projects.','citations':['S2']}]},
          'not_found':[],'sources':[]}
    data.update(changes)
    return InterviewBriefOutput.model_validate(data)


def run(coro):return asyncio.run(coro)


def test_context_lists_the_job_description_first_and_keeps_tabs_apart():
    context,entries=briefs.context_for(goal(),record(),'role')
    assert [e['url'] for e in entries]==['https://jobs.example.test/123','https://www.glassdoor.sg/intern-reviews','https://example.test/linkedin-post','https://www.indeed.com/management']
    assert context['goal']['job_description_source']=='S1' and context['sources'][1]=={'key':'S2','title':'Synapse intern reviews | Glassdoor','site':'Glassdoor'}
    assert [f['topic'] for f in context['findings']]==['mentorship','mentorship','management'] and context['findings'][1]['conflicting'] is True
    assert 'compensation' in context['uncovered_topics'] and 'mentorship' not in context['uncovered_topics']
    interview,_=briefs.context_for(goal(),record(),'interview')
    assert [f['topic'] for f in interview['findings']]==['interview_questions'] and interview['findings'][0]['round']==1


def test_malformed_provider_output_is_rejected():
    with pytest.raises(ValidationError):role_output(facts=role_output().model_dump()['facts'][:3])
    with pytest.raises(ValidationError):role_output(extra='prose')
    with pytest.raises(ValidationError):role_output(topics=[{**role_output().model_dump()['topics'][0],'tone':'great'}])
    with pytest.raises(ValidationError):interview_output(candidate_reports={'asked_about':[{'label':'Teamwork','citations':[]}],'situational':None,'tone':None,'reports':[]})
    with pytest.raises(ValidationError):RoleBrief.model_validate({'researchedAt':STAMP,'sourceCount':0,'summary':'x','sources':[],'prose':'Some details may be wrong.'})


def test_provider_schema_binds_citations_and_labels_to_catalogue_keys():
    schema=brief_schema('role_brief',{'sources':[{'key':'S1'},{'key':'S2'}]})
    assert schema['$defs']['Fact']['properties']['citations']['items']=={'type':'string','enum':['S1','S2']}
    assert schema['$defs']['Report']['properties']['citations']['items']['enum']==['S1','S2']
    assert schema['$defs']['SourceLabel']['properties']['key']['enum']==['S1','S2'] and schema['properties']['sources']['maxItems']==2
    assert schema['properties']['facts']['minItems']==schema['properties']['facts']['maxItems']==4
    interview=brief_schema('interview_brief',{'sources':[]})
    assert interview['$defs']['Cited']['properties']['citations']['items']['enum']==['none']


def test_role_brief_numbers_sources_in_first_cited_order_with_no_gaps():
    req,calls=request(role_output())
    brief=run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert [s.index for s in brief.sources]==[1,2,3,4] and brief.source_count==4
    assert [str(s.url) for s in brief.sources]==['https://jobs.example.test/123','https://www.indeed.com/management','https://www.glassdoor.sg/intern-reviews','https://example.test/linkedin-post']
    assert [f.citations for f in brief.facts]==[[1],[],[2,3],[]]
    assert [r.citations for r in brief.topics[1].reports]==[[3],[3,4]]
    every={n for f in brief.facts for n in f.citations}|{n for t in brief.topics for r in t.reports for n in r.citations}|{n for p in brief.pay for n in p.citations}
    assert every=={s.index for s in brief.sources}
    assert [(s.title,s.domain) for s in brief.sources]==[('GenAI Intern job description','Example'),('Employee reviews about management','Indeed'),('Intern reviews','Glassdoor'),('Internship post','Example')]
    assert brief.researched_at==STAMP and calls[0][0].stage=='role_brief' and 'owner' not in calls[0][0].context
    assert brief.duties==['Coordinate GenAI project timelines','Run workshops on AI solutions'] and brief.not_found==['Benefits','Intake size']
    assert brief.topics[2].estimated is True and brief.topics[1].conflicting is True and len(calls)==1


def test_public_brief_uses_camel_case_keys():
    req,_=request(role_output())
    data=run(briefs.generate(req,'owner',goal(),record(),'role')).model_dump(mode='json',by_alias=True)
    assert {'researchedAt','sourceCount','summary','facts','duties','topics','pay','notFound','sources'}<=set(data)
    assert data['sources']==sorted(data['sources'],key=lambda s:s['index'])


def test_interview_brief_numbers_steps_and_sources():
    req,calls=request(interview_output())
    brief=run(briefs.generate(req,'owner',goal(),record(),'interview'))
    assert [s.step for s in brief.process]==[1,2] and brief.process[1].citations==[1]
    assert [(s.index,str(s.url)) for s in brief.sources]==[(1,'https://www.glassdoor.sg/interview')]
    assert brief.sources[0].title=='Intern interview questions' and brief.sources[0].domain=='Glassdoor'
    assert brief.candidate_reports.tone.citations==[1] and calls[0][0].stage=='interview_brief'


def test_unknown_citation_keys_are_rejected():
    bad=role_output(pay=[{'label':'Intern pay','value':'S$1,799/mo','caveat':None,'citations':['S9']}])
    req,_=request(bad)
    with pytest.raises(AIError) as error:run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert error.value.violations[0]['issue']=='unknown_source'
    req,_=request(role_output(sources=[{'key':'S7','title':'Elsewhere','domain':'Other'}]))
    with pytest.raises(AIError):run(briefs.generate(req,'owner',goal(),record(),'role'))


def test_repeated_topics_and_facts_are_rejected():
    topics=role_output().model_dump()['topics']
    req,_=request(role_output(topics=[topics[0],topics[0]]))
    with pytest.raises(AIError) as error:run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert error.value.violations[0]['issue']=='repeated_topic'
    facts=role_output().model_dump()['facts']
    req,_=request(role_output(facts=[facts[0],facts[1],facts[2],{**facts[3],'label':'who can apply'}]))
    with pytest.raises(AIError):run(briefs.generate(req,'owner',goal(),record(),'role'))


LONG_SUMMARY=' '.join(['word']*30)+'.'


def test_word_limits_retry_once_with_feedback_then_accept_a_compliant_answer():
    req,calls=request(role_output(summary=LONG_SUMMARY),role_output())
    brief=run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert len(calls)==2 and calls[0][1] is None
    feedback=calls[1][1]
    assert feedback['reason']=='word_limit' and {'field':'summary','issue':'over_25_words'} in feedback['violations']
    assert brief.summary.startswith('A hybrid')


def test_word_limits_truncate_at_a_word_boundary_after_the_retry():
    long_takeaway='Good when the team has time, thin when it is busy and the deadlines pile up and up.'
    topics=role_output().model_dump()['topics'];topics[0]['takeaway']=long_takeaway
    still=role_output(summary=LONG_SUMMARY,topics=topics,duties=['Coordinate timelines, stand-ups and reviews across the whole programme with partners and vendors'])
    req,calls=request(still)
    brief=run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert len(calls)==2
    assert brief.summary==' '.join(['word']*25)+'.'
    assert brief.topics[0].takeaway=='Good when the team has time, thin when it is busy.'
    assert brief.duties[0]=='Coordinate timelines, stand-ups and reviews across the whole programme'
    for text,limit in ((brief.summary,'summary'),(brief.topics[0].takeaway,'topic.takeaway'),(brief.duties[0],'duty')):
        assert len(text.split())<=WORD_LIMITS[limit]


def test_hedging_filler_and_copied_report_wording_are_retried_then_stripped():
    topics=role_output().model_dump()['topics'];topics[0]['takeaway']='A review cited weak delegation by managers.'
    req,calls=request(role_output(summary='It is worth noting that this is a hybrid internship.',topics=topics))
    brief=run(briefs.generate(req,'owner',goal(),record(),'role'))
    issues={(v['field'],v['issue']) for v in calls[1][1]['violations']}
    assert ('summary','hedging_filler') in issues and ('topics.0.takeaway','repeats_report_wording') in issues
    assert brief.summary=='This is a hybrid internship.'


def test_truncate_keeps_short_text_and_drops_dangling_words():
    assert briefs.truncate('Short and sweet.',5)=='Short and sweet.'
    assert briefs.truncate('Flexible days with about two office days each week',4)=='Flexible days'
    assert briefs.truncate('Is it hard to get in and stay?',5)=='Is it hard to get?'


def test_saved_brief_is_scoped_to_tab_goal_version_and_research():
    req,_=request(role_output())
    run(briefs.generate(req,'owner',goal(),record(),'role'))
    assert run(briefs.read_saved(req,'owner',goal(),record(),'role')) is not None
    assert run(briefs.read_saved(req,'owner',goal(),record(),'interview')) is None
    assert run(briefs.read_saved(req,'owner',goal(4),record(),'role')) is None
    assert run(briefs.read_saved(req,'owner',goal(),record('r2'),'role')) is None


def client(job):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from app.api.v1.dependencies import owner
    from app.api.v1.research_brief import router
    req,calls=request(role_output(),interview_output())
    req.app.state.opportunities=NS(store=NS(latest=lambda *a:job,research=NS(records=NS(get_research=lambda i:record()))))
    app=FastAPI();app.include_router(router);app.state=req.app.state
    app.dependency_overrides[owner]=lambda:'owner'
    @app.exception_handler(GoalError)
    async def goal_error(request,error):return JSONResponse({'detail':error.message},error.status)
    return TestClient(app),calls


ROLE=f'/api/v1/career/goals/{"a"*24}/v2/role-research'
INTERVIEW=f'/api/v1/career/goals/{"a"*24}/v2/interview-research'


def test_routes_generate_once_and_wait_for_research():
    http,calls=client({'research_id':'r1','finished':True})
    assert http.get(ROLE).json()=={'status':'missing','brief':None}
    body=http.post(ROLE,json={'expected_version':3}).json()
    assert body['status']=='ready' and body['brief']['sourceCount']==4 and len(body['brief']['facts'])==4
    assert [s['index'] for s in body['brief']['sources']]==[1,2,3,4]
    assert http.post(ROLE,json={'expected_version':3}).json()['brief']==body['brief'] and len(calls)==1
    assert http.get(ROLE).json()['status']=='ready'
    assert http.post(ROLE,json={'expected_version':2}).status_code==409
    assert http.post(ROLE,json={'expectedVersion':3}).status_code==422
    http,calls=client({'research_id':'r1','finished':False})
    assert http.get(INTERVIEW).json()['status']=='researching'
    assert http.post(INTERVIEW,json={'expected_version':3}).status_code==409 and not calls


def test_concurrent_generation_shares_one_provider_call():
    from app.api.v1.research_brief import generate_once

    async def check():
        req,calls=request(role_output())
        entered,release=asyncio.Event(),asyncio.Event()
        original=req.app.state.ai.generate

        async def paused(*args,**kwargs):
            entered.set()
            await release.wait()
            return await original(*args,**kwargs)

        req.app.state.ai.generate=paused
        first=asyncio.create_task(generate_once(req,'owner',goal(),record(),'role'))
        await entered.wait()
        second=asyncio.create_task(generate_once(req,'owner',goal(),record(),'role'))
        await asyncio.sleep(0)
        release.set()
        a,b=await asyncio.gather(first,second)
        assert a==b and len(calls)==1 and not req.app.state.brief_tasks

    run(check())


def test_prompts_carry_the_word_limits():
    from app.ai.brief_contracts import INTERVIEW_BRIEF_PROMPT,ROLE_BRIEF_PROMPT
    assert 'summary at most 25 words' in ROLE_BRIEF_PROMPT and 'topic.takeaway at most 12 words' in ROLE_BRIEF_PROMPT
    assert 'prep at most 20 words' in INTERVIEW_BRIEF_PROMPT and 'json' in ROLE_BRIEF_PROMPT.lower()
    assert json.dumps(WORD_LIMITS)


def test_contract_artifacts_match_the_application():
    from pathlib import Path
    from app.main import create_app
    from app.schemas.research_brief import InterviewBrief
    root=Path(__file__).resolve().parents[3]/'contracts/api'
    saved=json.loads((root/'career.yaml').read_text())
    current=create_app().openapi()
    for path in ('/api/v1/career/goals/{goal_id}/v2/role-research','/api/v1/career/goals/{goal_id}/v2/interview-research'):
        assert saved['paths'][path]==current['paths'][path]
    for name in ('RoleBriefView','InterviewBriefView','RoleBrief','InterviewBrief','BriefCommand','BriefTopic','BriefSource','BriefCandidateReports'):
        assert saved['components']['schemas'][name]==current['components']['schemas'][name]
    for name,model in (('role-research-v2',RoleBrief),('interview-research-v2',InterviewBrief)):
        assert json.loads((root/f'models/{name}.schema.json').read_text())==model.model_json_schema(by_alias=True,mode='serialization')
