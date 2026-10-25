import asyncio
import httpx
import pytest
from app.clients.cvs import CvClient
from app.repositories.goals import GoalError


def test_cv_api_boundary_uses_metadata_then_owner_scoped_effective_snapshot(documents):
    row=documents['cv'];seen=[]
    summary={key:row[key] for key in ('_id','user_id','file_name','extraction_status','extraction_version','version')}
    def handler(request):
        seen.append(request.url.path)
        assert request.headers['Authorization']=='Bearer synthetic'
        return httpx.Response(200,json={'items':[summary]} if request.url.path=='/api/v1/cv' else row)
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test',transport=httpx.MockTransport(handler)) as http:
            client=CvClient(http)
            assert (await client.list('Bearer synthetic'))[0].id==row['_id']
            assert (await client.get(row['_id'],'Bearer synthetic',row['user_id'])).skills[0].proficiency is None
            with pytest.raises(GoalError): await client.get(row['_id'],'Bearer synthetic','foreign-owner')
    asyncio.run(check())
    assert seen==['/api/v1/cv','/api/v1/cv/'+row['_id'],'/api/v1/cv/'+row['_id']]
