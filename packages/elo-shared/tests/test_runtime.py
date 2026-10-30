"""Disposable MongoDB checks; never use an application database or inherited URI."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from pymongo import MongoClient
from elo_shared.runtime import Store,Problem,begin
from pydantic import BaseModel

@pytest.fixture
def store():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Set an explicit disposable MONGODB_TEST_URI.')
    client=MongoClient(uri,serverSelectionTimeoutMS=3000)
    name='elo_planning_test_'+uuid4().hex
    try:
        client.admin.command('ping')
        yield Store(client[name],'skill_gap_analyses')
    finally:client.drop_database(name);client.close()

def test_mongo_cas_has_one_winner_and_never_overwrites_unrelated_owner(store):
    def attempt(value):
        try:return store.cas('owner',0,{'messages':[value],'receipts':[]})
        except Problem:return None
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(attempt,['a','b']))
    assert sum(r is not None for r in results)==1
    assert store.load('owner')['version']==1
    assert store.load('another')['version']==0

def test_immutable_result_recovers_after_lost_pointer_commit_and_is_owner_scoped(store):
    original={'id':'result1','request_hash':'same-request','created_at':'2030-01-01','input_hash':'source'}
    store.save_result('owner',original)
    recovered=store.save_result('owner',{**original,'created_at':'2030-02-01'})
    assert recovered==original
    assert store.result('owner','result1')==original
    with pytest.raises(Problem):store.result('another','result1')
    with pytest.raises(Problem):store.save_result('owner',{**original,'request_hash':'different'})

def test_checkpoint_survives_repository_recreation_and_preserves_fencing(store):
    row=store.cas('owner',0,{'messages':[],'receipts':[],'pending':{'id':'operation','token':'lease1','checkpoint':{'outcomes':['done']}}})
    store.checkpoint('owner',row)
    reopened=Store(store.database,'skill_gap_analyses')
    assert reopened.load('owner')['pending']['checkpoint']['outcomes']==['done']
    with pytest.raises(Problem):reopened.cas('owner',1,{'messages':[]})

def test_oversized_history_is_rejected_before_publication(store):
    with pytest.raises(Problem) as error:store.cas('owner',0,{'messages':['x'*(4*1024*1024)]})
    assert error.value.status==413 and store.load('owner')['version']==0


def test_same_request_identity_cannot_rebind_an_immutable_result_to_different_inputs(store):
    store.save_result('owner',{'id':'result1','request_hash':'same','input_hash':'old'})
    with pytest.raises(Problem):store.save_result('owner',{'id':'result1','request_hash':'same','input_hash':'new'})
