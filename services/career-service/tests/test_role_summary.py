"""About the role digest: card building, cited bullets, provenance limits, persistence and routes (synthetic data)."""
import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.role_summary import RoleDigest,role_summary_schema
from app.repositories.goals import GoalError
from app.workflows import role_summary as digest


def finding(fid,field,value):
    return NS(finding_id=fid,field=field,value=value,round_number=None,round_name=None)


def record(research_id='r1'):
    categories={'internship_insights':NS(findings=[finding('f1','compensation','Interns report SGD 1500 per month.'),finding('f2','mentorship','Each intern has a named buddy.')]),
                'interview_intelligence':NS(findings=[finding('f9','interview_questions','Explain joins.')]),
                'company_intelligence':NS(findings=[finding('f3','work_life_balance','Teams mostly leave by 6pm.')])}
    return NS(id=research_id,intelligence=NS(categories=categories))


def goal(version=3):
    return NS(id='a'*24,version=version,role='Analyst',company='Example',field='Data',location='Singapore',employment_type='internship',seniority_level=None,summary='Build reporting for the finance team.',
              responsibilities=['Maintain dashboards','Clean source data'],non_skill_requirements=[NS(requirement_id='visa',description='Must be eligible to work in Singapore.')])


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
    store=NS(current=lambda owner:{'goal':saved},goals=NS(database={'role_summaries':Collection()}))
    return NS(app=NS(state=NS(ai=NS(generate=generate,context_enabled=True),goal_store=store))),calls


def output(*cards,fills=()):
    return RoleDigest.model_validate({'cards':[{'card_id':c,'headline':'Key takeaway','bullets':[{'text':t,'refs':r} for t,r in bullets]} for c,bullets in cards],
        'fills':[{'card_id':c,'headline':'Not public','bullets':b} for c,b in fills]})


def good():
    return output(('work',[('Builds finance reporting dashboards',['summary','resp:0','resp:0'])]),
                  ('compensation',[('About **SGD 1500** per month (reported)',['f1'])]),
                  fills=(('conversion_rate',['Not publicly reported; typically **40 to 60%** here']),))


def run(coro):return asyncio.run(coro)


def test_cards_follow_page_order_and_skip_interview_research():
    cards=digest.build_cards(goal(),record())
    assert [c['card_id'] for c in cards]==['eligibility','work','compensation','mentorship','work_life_balance']
    assert cards[0]['items']==[{'ref':'req:visa','text':'Must be eligible to work in Singapore.'}]
    assert [i['ref'] for i in cards[1]['items']]==['summary','resp:0','resp:1']


def test_digest_keeps_cited_bullets_and_sends_no_account_data():
    req,calls=request(good())
    result=run(digest.generate(req,'owner',goal(),record()))
    assert [(c.card_id,[b.text for b in c.bullets]) for c in result.cards]==[('work',['Builds finance reporting dashboards']),('compensation',['About **SGD 1500** per month (reported)'])]
    assert result.cards[0].bullets[0].refs==['summary','resp:0']
    assert [(g.card_id,g.bullets) for g in result.generated]==[('conversion_rate',['Not publicly reported; typically **40 to 60%** here'])]
    sent=json.loads(calls[0].context)
    assert [m['card_id'] for m in sent['missing']][:3]==['benefits','projects','full_time_role'] and 'compensation' not in [m['card_id'] for m in sent['missing']]
    assert calls[0].stage=='role_summary' and 'owner' not in calls[0].context
    assert 'Explain joins.' not in json.loads(calls[0].context).__repr__()


def test_refs_from_other_cards_unknown_cards_and_invented_numbers_are_rejected():
    for bad,issue in ((output(('work',[('Pays well',['f1'])])),'ref_outside_card'),
                      (output(('salary',[('Pays well',['f1'])])),'unknown_or_repeated_card'),
                      (output(('mentorship',[('2 buddies per intern',['f2'])])),'unsupported_number'),
                      (output(fills=(('compensation',['Likely well paid']),)),'unknown_or_repeated_card')):
        req,_=request(bad)
        with pytest.raises(AIError) as error:run(digest.generate(req,'owner',goal(),record()))
        assert error.value.violations[0]['issue']==issue


def test_saved_digest_is_scoped_to_goal_version_and_research():
    req,_=request(good())
    run(digest.generate(req,'owner',goal(),record()))
    assert run(digest.read_saved(req,'owner',goal(),record())) is not None
    assert run(digest.read_saved(req,'owner',goal(4),record())) is None
    assert run(digest.read_saved(req,'owner',goal(),record('r2'))) is None


def test_provider_schema_binds_cards_and_refs():
    schema=role_summary_schema({'cards':[{'card_id':'work','items':[{'ref':'summary'}]}]})
    assert schema['$defs']['DigestCard']['properties']['card_id']['enum']==['work']
    assert schema['$defs']['DigestBullet']['properties']['refs']['items']['enum']==['summary']
    filled=role_summary_schema({'cards':[],'missing':[{'card_id':'benefits'}]})
    assert filled['$defs']['FillCard']['properties']['card_id']['enum']==['benefits'] and filled['properties']['fills']['maxItems']==1


def client(job):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from app.api.v1.goals import owner
    from app.api.v1.role_summary import router
    req,calls=request(good())
    req.app.state.opportunities=NS(store=NS(latest=lambda *a:job,research=NS(records=NS(get_research=lambda i:record()))))
    app=FastAPI();app.include_router(router);app.state=req.app.state
    app.dependency_overrides[owner]=lambda:'owner'
    @app.exception_handler(GoalError)
    async def goal_error(request,error):return JSONResponse({'detail':error.message},error.status)
    return TestClient(app),calls


PATH=f'/api/v1/career/goals/{"a"*24}/role-summary'


def test_route_generates_once_and_waits_for_research():
    http,calls=client({'research_id':'r1','finished':True})
    assert http.get(PATH).json()=={'status':'missing','summary':None}
    assert http.post(PATH,json={'expected_version':3}).json()['summary']['cards'][0]['card_id']=='work'
    assert http.post(PATH,json={'expected_version':3}).json()['status']=='ready' and len(calls)==1
    assert http.post(PATH,json={'expected_version':2}).status_code==409
    http,calls=client({'research_id':'r1','finished':False})
    assert http.get(PATH).json()['status']=='researching'
    assert http.post(PATH,json={'expected_version':3}).status_code==409 and not calls


def test_bold_rules_headline_and_length_are_enforced():
    for text,issue in (('Pays **SGD 1500** **a** **month** **often**','too_much_bold'),('Pays *SGD 1500* monthly','unsupported_markup'),
                       ('**Pays SGD 1500 monthly**','bold_dominates'),('# Pays SGD 1500','unsupported_markup'),('Pays **SGD 1500** in [a](http://x)','unsupported_markup')):
        req,_=request(output(('compensation',[(text,['f1'])])))
        with pytest.raises(AIError) as error:run(digest.generate(req,'owner',goal(),record()))
        assert error.value.violations[0]['issue']==issue
    with pytest.raises(Exception):RoleDigest.model_validate({'cards':[{'card_id':'work','headline':'**Bold**','bullets':[{'text':'Ok fact','refs':['summary']}]}]})
    with pytest.raises(Exception):output(('work',[('x'*111,['summary'])]))
    with pytest.raises(Exception):output(('work',[('One fact',['summary'])]*4))


def test_headline_cannot_invent_numbers_and_is_saved():
    bad=RoleDigest.model_validate({'cards':[{'card_id':'mentorship','headline':'5 buddies each','bullets':[{'text':'Named buddy','refs':['f2']}]}]})
    req,_=request(bad)
    with pytest.raises(AIError) as error:run(digest.generate(req,'owner',goal(),record()))
    assert error.value.violations[0]['issue']=='unsupported_number'
    req,_=request(good())
    result=run(digest.generate(req,'owner',goal(),record()))
    assert result.cards[0].headline=='Key takeaway' and result.generated[0].headline=='Not public'


def test_digest_saved_in_an_older_format_is_regenerated():
    req,_=request(good())
    run(digest.generate(req,'owner',goal(),record()))
    row=req.app.state.goal_store.goals.database['role_summaries'].rows[f"owner:{'a'*24}"]
    del row['summary']['format']
    assert run(digest.read_saved(req,'owner',goal(),record())) is None
