import os
import uuid

import mongomock
import pytest
from pymongo import MongoClient


@pytest.fixture(params=['mongomock', 'mongodb'])
def database(request):
    """Every store test runs in CI's unit job on mongomock, and against real MongoDB when one is supplied."""
    if request.param == 'mongomock':
        yield mongomock.MongoClient(tz_aware=True).jobs_test
        return
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri:
        pytest.skip('MONGODB_TEST_URI is not set')
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    name = 'elo_jobs_test_' + uuid.uuid4().hex
    yield client[name]
    client.drop_database(name)
    client.close()
