import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from pymongo import MongoClient
from app.repositories.profile import ProfileRepository, VersionConflict
from app.schemas.profile import ProfilePatch

pytestmark = pytest.mark.skipif(not os.getenv("MONGODB_TEST_URI"), reason="Set MONGODB_TEST_URI for real MongoDB integration tests")


def test_real_mongodb_roundtrip_concurrency_and_restart():
    client = MongoClient(os.environ["MONGODB_TEST_URI"], serverSelectionTimeoutMS=5000)
    name = "elo_test_" + uuid4().hex
    try:
        repo = ProfileRepository(client[name])
        patch = ProfilePatch(expected_version=0, occupational_status="student", school_category="university")
        def save(_):
            try:
                return repo.update("alice", patch)["version"]
            except VersionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        assert sorted(map(str, results)) == ["1", "conflict"]
        restored = ProfileRepository(client[name])
        assert restored.current("alice")["school_category"] == "university"
        assert restored.current("bob") is None
        restored.update("alice", ProfilePatch(expected_version=1, occupational_status="employed", school_category=None))
        assert restored.version("alice", 1)["education_context"] == "current"
        assert restored.current("alice")["education_context"] == "last"
        assert restored.current("alice")["education_review_required"]
        restored.update("alice", ProfilePatch(expected_version=2, school_category="university", education={
            "institution": {"kind": "custom", "name": "International Test University"},
            "course": "Design & Computing",
        }))
        separate_client = MongoClient(os.environ["MONGODB_TEST_URI"], serverSelectionTimeoutMS=5000)
        try:
            reconnected = ProfileRepository(separate_client[name])
            latest = reconnected.current("alice")
            assert latest["education"]["institution"]["name"] == "International Test University"
            assert latest["education"]["course"] == "Design & Computing"
            assert latest["education"]["context"] == "last"
            assert reconnected.version("alice", 1)["education"]["institution"] is None
        finally:
            separate_client.close()
    finally:
        client.drop_database(name)
        client.close()


def test_real_planning_atomicity_replay_and_reconnect():
    from app.repositories.profile import MutationConflict
    from datetime import timedelta
    from app.domain.planning import today_in
    client=MongoClient(os.environ['MONGODB_TEST_URI'],serverSelectionTimeoutMS=5000)
    name='elo_test_'+uuid4().hex
    try:
        repo=ProfileRepository(client[name])
        repo.update('alice',ProfilePatch(expected_version=0,occupational_status='employed'))
        repo.update('alice',ProfilePatch(expected_version=1,weekly_hours=14),'base')
        day=(today_in('Asia/Singapore')+timedelta(days=2)).isoformat()
        changes={'start_date':day,'end_date':day,'weekly_hours':7}
        def add(index):
            try:
                return repo.change_period('alice','add',None,2,changes,'add-'+str(index))['version']
            except VersionConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(add,range(2)))
        assert sorted(map(str,results))==['3','conflict']
        latest=repo.current('alice');row=latest['availability_periods'][0]
        # Exact replay succeeds despite an old expected version; it never adds a second row.
        winner=results.index(3)
        assert repo.change_period('alice','add',None,2,changes,'add-'+str(winner))==latest
        with pytest.raises(MutationConflict):
            repo.change_period('alice','add',None,2,{**changes,'weekly_hours':0},'add-'+str(winner))
        unchanged=repo.update('alice',ProfilePatch(expected_version=3,weekly_hours=14),'noop')
        assert unchanged['version']==3
        assert client[name].profile_versions.count_documents({'owner':'alice'})==3
        # Replay a recorded no-op after a different edit without reverting that edit.
        newer=repo.update('alice',ProfilePatch(expected_version=3,weekly_hours=15),'newbase')
        assert repo.update('alice',ProfilePatch(expected_version=3,weekly_hours=14),'noop')==newer
        deleted=repo.change_period('alice','delete',row['id'],4,{},'delete')
        assert deleted['availability_periods']==[]
        assert repo.change_period('alice','delete',row['id'],4,{},'delete')==deleted
        assert repo.change_period('alice','delete',row['id'],5,{},'delete-again')['version']==5
        separate=MongoClient(os.environ['MONGODB_TEST_URI'])
        try:
            restored=ProfileRepository(separate[name])
            assert restored.current('alice')==deleted
            assert restored.version('alice',3)['availability_periods']==[row]
            assert restored.current('bob') is None
            assert restored.version('bob',3) is None
        finally:
            separate.close()
    finally:
        client.drop_database(name);client.close()


def test_real_planning_duplicate_submission_and_base_period_race():
    from datetime import timedelta
    from app.domain.planning import today_in, planning_inputs
    client=MongoClient(os.environ['MONGODB_TEST_URI'],serverSelectionTimeoutMS=5000)
    name='elo_test_'+uuid4().hex
    try:
        repo=ProfileRepository(client[name])
        repo.update('alice',ProfilePatch(expected_version=0,occupational_status='employed'))
        repo.update('alice',ProfilePatch(expected_version=1,weekly_hours=14),'base')
        day=(today_in('Asia/Singapore')+timedelta(days=1)).isoformat()
        changes={'start_date':day,'end_date':day,'weekly_hours':7}
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:repo.change_period('alice','add',None,2,changes,'same-key'),range(2)))
        assert [r['version'] for r in result]==[3,3]
        assert len(repo.current('alice')['availability_periods'])==1
        def competing(kind):
            try:
                if kind=='base':return repo.update('alice',ProfilePatch(expected_version=3,weekly_hours=6),'lower')['version']
                return repo.change_period('alice','edit',result[0]['availability_periods'][0]['id'],3,{'weekly_hours':5},'edit')['version']
            except VersionConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(competing,['base','period']))
        assert sorted(map(str,result))==['4','conflict']
        latest=repo.current('alice')
        issues=planning_inputs(latest,'Asia/Singapore')['issues']
        conflicts=[i for i in issues if i['field']=='availability_periods']
        assert bool(conflicts)==(latest['weekly_hours']==6)
    finally:
        client.drop_database(name);client.close()


def test_real_reused_key_cannot_race_a_noop_and_changed_save():
    from app.repositories.profile import MutationConflict
    client=MongoClient(os.environ['MONGODB_TEST_URI'],serverSelectionTimeoutMS=5000)
    name='elo_test_'+uuid4().hex
    try:
        repo=ProfileRepository(client[name])
        repo.update('alice',ProfilePatch(expected_version=0,occupational_status='employed'))
        repo.update('alice',ProfilePatch(expected_version=1,weekly_hours=14),'base')
        def competing(hours):
            try:
                repo.update('alice',ProfilePatch(expected_version=2,weekly_hours=hours),'reused-key')
                return 'success'
            except MutationConflict:return 'key conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(competing,[14,15]))
        assert sorted(result)==['key conflict','success']
        assert repo.current('alice')['version'] in (2,3)
    finally:
        client.drop_database(name);client.close()
