"""Keyword-only interview guide: gating, evidence labels, provenance and planning (synthetic data)."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace as NS
import pytest
from pydantic import ValidationError
from app.ai.adapter import AIError
from app.ai.interview_prep import PrepKeywords,prep_schema
from app.repositories.goals import GoalError
from app.schemas.interview_prep import Keyword,Stage
from app.workflows import interview_prep as prep


def finding(value,evidence_type,source='s1',round_number=None,field='recruitment_stages'):
    return NS(field=field,value=value,evidence_type=evidence_type,scope='exact',round_number=round_number,round_name=None,source_ids=[source])


def record():
    categories={'interview_intelligence':NS(findings=[finding('Online assessment then panel','official',round_number=1),
                                                       finding('Case study reported','candidate_reported','s2',2)]),
                'company_intelligence':NS(findings=[])}
    return NS(id='r1',sources=[NS(source_id='s1',url='https://example.test/careers',title='Careers'),
                               NS(source_id='s2',url='https://example.test/report',title='Report')],intelligence=NS(categories=categories))


def goal(target='specific_job'):
    return NS(id='g1',version=3,target_type=target,role='Analyst',company='Example',field='Data',location='Singapore',seniority_level=None,
              employment_type='internship',source_cv_id=None,responsibilities=['Build dashboards'],skills=[NS(name='SQL',priority='required',category='Data')])


def cv():
    return NS(skills=[NS(name='SQL',experience_months=12,context='Reporting database queries')])


class Collection:
    def __init__(self):self.rows={}
    def replace_one(self,query,row,upsert=False):self.rows[query['_id']]=row
    def find_one(self,query):return self.rows.get(query['_id'])


def request(output):
    calls=[]
    async def generate(req,operation,**kwargs):
        calls.append(req)
        kwargs['validate_output'](output)
        return NS(data=output)
    saved=goal()
    store=NS(current=lambda owner:{'goal':saved},goals=NS(database={'interview_prep_guides':Collection()}))
    return NS(app=NS(state=NS(ai=NS(generate=generate,context_enabled=True),goal_store=store))),calls


def good():
    return PrepKeywords.model_validate({'role':['SQL','Dashboards'],'success':['Accuracy'],
        'process':[{'round':2,'name':'Case study','format':['case'],'refs':['research_1']},
                   {'round':1,'name':'Online assessment','format':['timed'],'refs':['research_0']}],
        'resume':[{'competency':'Data querying','skill':'SQL','signals':['Reporting']},{'competency':'Stakeholder mgmt','skill':None}],
        'syllabus':[{'name':'Statistics','priority':'low','depth':'awareness','terms':['Mean']},
                    {'name':'SQL joins','priority':'high','depth':'deep','terms':['INNER','LEFT'],'refs':['research_0']}],
        'questions':[{'text':'Why this company?','kind':'behavioural'}]})


def run(coro):return asyncio.run(coro)


def test_keywords_reject_sentences_and_long_phrases():
    for bad in ('Tell me about a time you led a team','Ends with a stop.'):
        with pytest.raises(ValidationError):Stage(name=bad,basis='prediction')
    assert Stage(name='Case study',basis='prediction').name=='Case study'


def test_guide_labels_evidence_from_stored_findings_not_the_model():
    req,calls=request(good())
    guide=run(prep.generate(req,'owner',goal(),record(),cv(),date(2026,11,20),today=date(2026,11,11)))
    assert [(s.round,s.basis) for s in guide.process]==[(1,'confirmed'),(2,'candidate_report')]
    assert [t.name for t in guide.syllabus]==['SQL joins','Statistics']  # high priority first
    assert guide.syllabus[0].basis=='confirmed' and guide.syllabus[1].basis=='prediction'
    assert guide.questions[0].basis=='prediction'
    assert [(r.skill,r.status) for r in guide.resume]==[('SQL','strength'),(None,'gap')]
    assert {s.source_id for s in guide.sources}=={'s1','s2'}
    assert 'recent news' in guide.not_covered
    assert calls[0].stage=='interview_prep'
    sent=json.loads(calls[0].context)
    assert 'owner' not in calls[0].context and sent['cv'][0]['name']=='SQL'


def test_guide_is_saved_per_goal_version():
    req,_=request(good())
    run(prep.generate(req,'owner',goal(),record(),cv(),None))
    assert run(prep.read_saved(req,'owner',goal())).goal_version==3
    other=goal();other.version=4
    assert run(prep.read_saved(req,'owner',other)) is None


def test_exploration_goals_are_rejected():
    req,_=request(good())
    with pytest.raises(GoalError) as error:run(prep.generate(req,'owner',goal('career_exploration'),record(),cv(),None))
    assert error.value.status==409


def test_unknown_reference_unknown_skill_and_invented_numbers_are_rejected():
    for patch,issue in (({'process':[{'name':'Case','refs':['research_9']}]},'unknown_research_reference'),
                        ({'resume':[{'competency':'Python','skill':'Python'}]},'unknown_cv_skill'),
                        ({'role':['Led 40 engineers']},'unsupported_number')):
        req,_=request(PrepKeywords.model_validate(patch))
        with pytest.raises(AIError) as error:run(prep.generate(req,'owner',goal(),record(),cv(),None))
        assert error.value.violations[0]['issue']==issue


def test_schedule_uses_days_left_or_a_default_week():
    topics=[NS(name='SQL',priority='high'),NS(name='Stats',priority='low')]
    process=[NS(name='Panel')];resume=[NS(competency='Data',status='strength')]
    dated=prep.make_schedule(topics,process,resume,date(2026,11,11),date(2026,11,20))
    assert dated[0].when=='Nov 11' and dated[-1].focus[0]=='Final review' and len(dated)==6
    today_only=prep.make_schedule(topics,process,resume,date(2026,11,11),date(2026,11,11))
    assert len(today_only)==1 and today_only[0].focus[0]=='Final review'
    default=prep.make_schedule(topics,process,resume,date(2026,11,11),None)
    assert default[0].when=='Day 1'


def test_provider_schema_binds_refs_and_cv_skills_to_this_snapshot():
    schema=prep_schema({'research':[{'ref':'research_0'}],'cv':[{'name':'SQL'}]})
    assert schema['$defs']['PrepStage']['properties']['refs']['items']['enum']==['research_0']
    assert schema['$defs']['PrepResume']['properties']['skill']['anyOf'][0]['enum']==['SQL']
    empty=prep_schema({'research':[],'cv':[]})
    assert empty['$defs']['PrepTopic']['properties']['refs']['maxItems']==0



def client(output,target='specific_job'):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from app.api.v1.goals import owner
    from app.api.v1.interview_prep import router
    req,calls=request(output)
    saved=goal(target);saved.id='a'*24
    req.app.state.goal_store.current=lambda account:{'goal':saved}
    req.app.state.opportunities=NS(store=NS(latest=lambda *a:{'research_id':'r1'},research=NS(records=NS(get_research=lambda i:record()))))
    app=FastAPI();app.include_router(router);app.state=req.app.state
    app.dependency_overrides[owner]=lambda:'owner'
    @app.exception_handler(GoalError)
    async def goal_error(request,error):return JSONResponse({'detail':error.message},error.status)
    return TestClient(app),calls,saved


def without_cv():
    data=good().model_dump()
    data['resume']=[{'competency':'Data querying','skill':None,'signals':[]}]
    return PrepKeywords.model_validate(data)


def test_route_generates_once_then_serves_the_saved_guide():
    http,calls,goal_=client(without_cv())
    path=f'/api/v1/career/goals/{goal_.id}/interview-prep'
    assert http.get(path).json()=={'status':'missing','guide':None}
    first=http.post(path,json={'expected_version':3,'interview_date':'2026-11-20'})
    assert first.status_code==200 and first.json()['guide']['process'][0]['basis']=='confirmed'
    again=http.post(path,json={'expected_version':3,'interview_date':'2026-11-20'})
    assert again.json()['status']=='ready' and len(calls)==1
    http.post(path,json={'expected_version':3,'interview_date':'2026-11-20','refresh':True})
    assert len(calls)==2 and http.get(path).json()['status']=='ready'


def test_route_refuses_exploration_goals_and_stale_versions():
    http,calls,goal_=client(good(),'career_exploration')
    path=f'/api/v1/career/goals/{goal_.id}/interview-prep'
    assert http.get(path).status_code==409 and http.post(path,json={'expected_version':3}).status_code==409
    http,calls,goal_=client(good())
    path=f'/api/v1/career/goals/{goal_.id}/interview-prep'
    assert http.post(path,json={'expected_version':2}).status_code==409 and not calls
