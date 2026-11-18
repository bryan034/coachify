import os
import uuid

import mongomock
import pytest
from pymongo import MongoClient


storage_backends = pytest.mark.parametrize('database', ['mongomock', 'mongodb'], indirect=True)


@pytest.fixture
def database(request):
    if getattr(request, 'param', 'mongomock') == 'mongomock':
        yield mongomock.MongoClient(tz_aware=True).jobs_test
        return
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri:
        pytest.skip('MONGODB_TEST_URI is not set')
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    name = 'elo_jobs_test_' + uuid.uuid4().hex
    try:
        yield client[name]
    finally:
        client.drop_database(name)
        client.close()
