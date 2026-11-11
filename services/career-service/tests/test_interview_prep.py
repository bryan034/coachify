"""AI fills for empty interview slots: gap detection, provenance limits, persistence and routes (synthetic data)."""
import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.interview_prep import PrepSuggestions,prep_schema
from app.repositories.goals import GoalError
from app.workflows import interview_prep as prep


def finding(field,value,round_number=None,round_name=None):
    return NS(field=field,value=value,evidence_type='candidate_reported',scope='exact',round_number=round_number,round_name=round_name,source_ids=['s1'])


def record(findings=None,research_id='r1'):
    if findings is None:
        findings=[finding('round_format','Online assessment',1,'Online assessment'),finding('interview_questions','Explain a SQL join',1),
                  finding('round_format','Panel',2,'Final panel'),finding('preparation_topics','Review past projects',2)]
    return NS(id=research_id,sources=[],intelligence=NS(categories={'interview_intelligence':NS(findings=findings)}))


def goal(version=3):
    return NS(id='a'*24,version=version,target_type='specific_job',role='Analyst',company='Example',field='Data',location='Singapore',seniority_level=None,
              employment_type='internship',responsibilities=['Build dashboards'],skills=[NS(name='SQL',priority='required',category='Data')])


class Collection:
    def __init__(self):self.rows={}
    def replace_one(self,query,row,upsert=False):self.rows[query['_id']]=row
    def find_one(self,query):return self.rows.get(query['_id'])


def request(output,saved=None):
    calls=[]
    async def generate(req,operation,**kwargs):
        calls.append(req)
        kwargs['validate_output'](output)
        return NS(data=output)
    saved=saved or goal()
    store=NS(current=lambda owner:{'goal':saved},goals=NS(database={'interview_prep_suggestions':Collection()}))
    return NS(app=NS(state=NS(ai=NS(generate=generate,context_enabled=True),goal_store=store))),calls


def fills(*items):
    return PrepSuggestions.model_validate({'fills':[{'round_number':n,'field':f,'items':v} for n,f,v in items]})


def good():
    return fills((1,'preparation_topics',['Practise timed SQL problems','Practise timed SQL problems']),
                 (2,'interview_questions',['Why this team?']))


def run(coro):return asyncio.run(coro)


def test_gaps_are_the_empty_slots_of_each_sourced_round():
    gaps=prep.find_gaps(record().intelligence.categories['interview_intelligence'].findings)
    assert [(g.round_number,g.round_name,g.field) for g in gaps]==[(None,None,'recruitment_stages'),(None,None,'application_timeline'),(None,None,'difficulty'),
        (1,'Online assessment','preparation_topics'),(2,'Final panel','interview_questions')]


def test_without_rounds_the_whole_process_is_filled():
    assert [g.field for g in prep.find_gaps([])]==['recruitment_stages','application_timeline','difficulty','interview_questions','preparation_topics']
    general=[finding('interview_questions','Tell me about yourself'),finding('difficulty','Moderate'),finding('recruitment_stages','Two stages'),finding('application_timeline','Four weeks')]
    assert [(g.round_number,g.field) for g in prep.find_gaps(general)]==[(None,'preparation_topics')]


def test_suggestions_fill_only_gaps_and_drop_duplicates():
    req,calls=request(good())
    result=run(prep.generate(req,'owner',goal(),record()))
    assert [(s.round_number,s.field,s.value) for s in result.items]==[(1,'preparation_topics','Practise timed SQL problems'),(2,'interview_questions','Why this team?')]
    assert calls[0].stage=='interview_prep'
    sent=json.loads(calls[0].context)
    assert 'owner' not in calls[0].context and len(sent['gaps'])==5 and sent['research'][1]['value']=='Explain a SQL join'


def test_unrequested_slots_and_multi_value_headlines_are_rejected():
    for output,issue in ((fills((1,'interview_questions',['Explain joins'])),'unrequested_gap'),
                         (fills((None,'difficulty',['Likely moderate','Likely hard'])),'one_item_expected')):
        req,_=request(output)
        with pytest.raises(AIError) as error:run(prep.generate(req,'owner',goal(),record()))
        assert error.value.violations[0]['issue']==issue


def test_no_gaps_skips_the_model_and_saves_per_goal_version_and_research():
    complete=[finding('interview_questions','Q',1),finding('preparation_topics','P',1),*(finding(f,'Known') for f in ('recruitment_stages','application_timeline','difficulty'))]
    req,calls=request(good())
    result=run(prep.generate(req,'owner',goal(),record(complete)))
    assert result.items==[] and not calls
    assert run(prep.read_saved(req,'owner',goal(),record(complete))) is not None
    assert run(prep.read_saved(req,'owner',goal(4),record(complete))) is None
    assert run(prep.read_saved(req,'owner',goal(),record(complete,'r2'))) is None


def test_provider_schema_binds_rounds_and_fields_to_the_gaps():
    schema=prep_schema({'gaps':[{'round_number':2,'field':'interview_questions'}]})
    fill=schema['$defs']['GapFill']['properties']
    assert fill['round_number']=={'anyOf':[{'type':'integer','enum':[2]}]} and fill['field']['enum']==['interview_questions']
    general=prep_schema({'gaps':[{'round_number':None,'field':'preparation_topics'}]})
    assert general['$defs']['GapFill']['properties']['round_number']=={'anyOf':[{'type':'null'}]}


def client(output,job):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from app.api.v1.goals import owner
    from app.api.v1.interview_prep import router
    req,calls=request(output)
    req.app.state.opportunities=NS(store=NS(latest=lambda *a:job,research=NS(records=NS(get_research=lambda i:record()))))
    app=FastAPI();app.include_router(router);app.state=req.app.state
    app.dependency_overrides[owner]=lambda:'owner'
    @app.exception_handler(GoalError)
    async def goal_error(request,error):return JSONResponse({'detail':error.message},error.status)
    return TestClient(app),calls


PATH=f'/api/v1/career/goals/{"a"*24}/interview-prep'


def test_estimates_with_numbers_are_allowed_because_they_are_labelled_ai_made():
    req,_=request(fills((None,'application_timeline',['Typically 3 to 6 weeks from application to offer'])))
    result=run(prep.generate(req,'owner',goal(),record()))
    assert result.items[0].value.startswith('Typically 3')


def test_route_generates_once_then_serves_the_saved_suggestions():
    http,calls=client(good(),{'research_id':'r1','finished':True})
    assert http.get(PATH).json()=={'status':'missing','suggestions':None}
    first=http.post(PATH,json={'expected_version':3})
    assert first.status_code==200 and first.json()['suggestions']['research_id']=='r1'
    assert http.post(PATH,json={'expected_version':3}).json()['status']=='ready' and len(calls)==1
    http.post(PATH,json={'expected_version':3,'refresh':True})
    assert len(calls)==2 and http.get(PATH).json()['status']=='ready'


def test_route_waits_for_research_and_refuses_stale_versions():
    http,calls=client(good(),{'research_id':'r1','finished':False})
    assert http.get(PATH).json()['status']=='researching'
    assert http.post(PATH,json={'expected_version':3}).status_code==409 and not calls
    http,calls=client(good(),{'research_id':'r1','finished':True})
    assert http.post(PATH,json={'expected_version':2}).status_code==409 and not calls
