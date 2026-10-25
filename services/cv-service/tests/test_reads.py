import json
import os
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.repositories.cvs import CvRepository


def test_read_endpoints_require_auth_even_without_storage():
    with TestClient(create_app()) as client:
        assert client.get('/api/v1/cv').status_code==401
        assert client.get('/api/v1/cv/000000000000000000000001').status_code==401


def test_saved_cv_read_is_owner_scoped_and_read_only():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI for CV API integration.')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000); name='coachify_cv_test_'+uuid4().hex
    data=json.loads((Path(__file__).parent/'cv.json').read_text())
    def profile(req):
        owner=data['user_id'] if req.headers.get('Authorization')=='Bearer owner' else '22222222-2222-4222-8222-222222222222'
        return httpx.Response(200,json={'id':owner,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        CvRepository(mongo[name]).save(data,data['user_id'])
        upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
        with TestClient(create_app(mongo[name],upstream)) as client:
            summary=client.get('/api/v1/cv',headers={'Authorization':'Bearer owner'}).json()['items'][0]
            assert summary['_id']==data['_id']
            assert 'skills' not in summary and 'file_url' not in summary
            assert client.get('/api/v1/cv',headers={'Authorization':'Bearer other'}).json()=={'items':[]}
            assert client.get('/api/v1/cv/'+data['_id'],headers={'Authorization':'Bearer other'}).status_code==404
            assert client.get('/api/v1/cv/'+data['_id'],headers={'Authorization':'Bearer owner'}).json()['skills'][0]['proficiency'] is None
            assert client.post('/api/v1/cv',headers={'Authorization':'Bearer owner'},json={}).status_code==405
    finally: mongo.drop_database(name);mongo.close()
