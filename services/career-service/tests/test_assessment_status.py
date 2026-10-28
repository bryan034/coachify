"""Assessment routing uses owner-scoped CV API data, never the CV database."""
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.repositories.goals import GoalError

OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'

def row(identifier='a',status='succeeded',skills=None,owner=OWNER):
    return SimpleNamespace(id=identifier,user_id=owner,extraction_status=status,skills=skills or [])

class CV:
    def __init__(self,rows,failed=False):self.rows=rows;self.failed=failed;self.calls=[]
    async def list(self,token):
        assert token=='Bearer owner'
        if self.failed:raise GoalError('Unavailable',503)
        return self.rows
    async def get(self,identifier,token,owner):
        self.calls.append((identifier,token,owner))
        return next(value for value in self.rows if value.id==identifier and value.user_id==owner)

def check(cv):
    def profile(request):
        return httpx.Response(200,json={'id':OWNER,'email_verified':True} if request.url.path.endswith('/session') else {'onboarding_complete':True})
    with TestClient(create_app(cv_client=cv,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
        assert client.get('/api/v1/career/context/assessment').status_code==401
        result=client.get('/api/v1/career/context/assessment',headers={'Authorization':'Bearer owner'})
        assert result.status_code==200 and result.headers['cache-control']=='no-store'
        return result.json()

@pytest.mark.parametrize('rows,status,uploaded,evaluated',[
    ([], 'no_cv',False,False),
    ([row(owner=OTHER,skills=['private'])], 'no_cv',False,False),
    ([row(status='processing')], 'not_evaluated',True,False),
    ([row(status='failed')], 'not_evaluated',True,False),
    ([row()], 'not_evaluated',True,False),
    ([row(skills=['synthetic SQL'])], 'evaluated',True,True),
    ([row(),row(identifier='b',skills=['synthetic SQL'])], 'evaluated',True,True),
])
def test_saved_cv_and_nonempty_evaluated_skills_determine_next_step(rows,status,uploaded,evaluated,monkeypatch):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    cv=CV(rows)
    assert check(cv)=={'status':status,'cv_uploaded':uploaded,'skills_evaluated':evaluated}
    assert all(owner==OWNER for _,_,owner in cv.calls)


def test_service_failure_is_unknown_instead_of_an_empty_database(monkeypatch):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    assert check(CV([],failed=True))=={'status':'unavailable','cv_uploaded':None,'skills_evaluated':None}


def test_snapshot_failure_does_not_claim_skills_are_missing(monkeypatch):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    cv=CV([row()])
    async def fail(*args):raise GoalError('Unavailable',503)
    cv.get=fail
    assert check(cv)=={'status':'unavailable','cv_uploaded':True,'skills_evaluated':None}


@pytest.mark.parametrize('detail_owner,status',[(OWNER,'evaluated'),(OTHER,'not_evaluated')])
def test_owner_scoped_sparse_summary_still_requires_owned_detail(monkeypatch,detail_owner,status):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    cv=CV([row(owner=None)])
    async def detail(identifier,token,owner):
        assert (identifier,token,owner)==('a','Bearer owner',OWNER)
        return row(owner=detail_owner,skills=['synthetic SQL'])
    cv.get=detail
    assert check(cv)=={'status':status,'cv_uploaded':True,'skills_evaluated':status=='evaluated'}


@pytest.mark.parametrize('summary_owner,visible', [(None, True), (OWNER, True), (OTHER, False)])
def test_career_context_lists_owner_scoped_cv_metadata_without_requiring_duplicate_owner(monkeypatch, summary_owner, visible):
    monkeypatch.delenv('MONGODB_URI', raising=False)
    monkeypatch.setenv('AI_ENABLED', 'false')
    summary = SimpleNamespace(id='22222222-2222-4222-8222-222222222222', user_id=summary_owner,
        file_name='synthetic.docx', extraction_status='succeeded', extraction_version='1', version=4)
    def profile(request):
        return httpx.Response(200, json={'id': OWNER, 'email_verified': True}
            if request.url.path.endswith('/session') else {'onboarding_complete': True})
    with TestClient(create_app(cv_client=CV([summary]), profile_client=httpx.AsyncClient(
            base_url='http://profile.test', transport=httpx.MockTransport(profile)))) as client:
        assert client.get('/api/v1/career/context').status_code == 401
        result = client.get('/api/v1/career/context', headers={'Authorization': 'Bearer owner'})
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert result.json()['cv_service_available'] is True
        assert result.json()['cvs'] == ([{'id': summary.id, 'filename': summary.file_name,
            'status': summary.extraction_status, 'version': 4, 'extraction_version': '1'}] if visible else [])
