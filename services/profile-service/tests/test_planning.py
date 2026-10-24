from copy import deepcopy
from datetime import date, datetime, timezone
from threading import RLock
from uuid import uuid4
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.core.auth import current_owner
from app.main import create_app
from app.repositories.profile import ProfileRepository, VersionConflict, MutationConflict
from app.domain import planning


class PlanningMemoryRepository:
    """API fixture; real MongoDB tests separately exercise production persistence."""
    update = ProfileRepository.update
    change_period = ProfileRepository.change_period
    fingerprint = staticmethod(ProfileRepository.fingerprint)

    def __init__(self):
        self.records, self.receipts, self.lock = {}, {}, RLock()

    def current(self, owner):
        return deepcopy(self.records.get(owner, [None])[-1])

    def version(self, owner, version):
        return next((deepcopy(p) for p in self.records.get(owner, []) if p['version'] == version), None)

    def mutate(self, owner, expected_version, transform, mutation_id=None, fingerprint=None):
        with self.lock:
            if (owner, mutation_id) in self.receipts:
                if self.receipts[(owner, mutation_id)] != fingerprint:
                    raise MutationConflict
                return self.current(owner)
            old = self.current(owner)
            if (old or {}).get('version', 0) != expected_version:
                raise VersionConflict
            new = transform(old)
            if new != old:
                new['version'] = expected_version + 1
                self.records.setdefault(owner, []).append(deepcopy(new))
            if mutation_id:
                self.receipts[(owner, mutation_id)] = fingerprint
            return new


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2030, 1, 1, 16, 30, tzinfo=timezone.utc).astimezone(tz)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(planning, 'datetime', Clock)
    app = create_app(PlanningMemoryRepository())
    app.dependency_overrides[current_owner] = lambda: 'alice'
    with TestClient(app) as c:
        assert c.patch('/api/v1/profile', json={'expected_version':0,'occupational_status':'employed'}).status_code == 200
        yield c


def write(client, **fields):
    return client.patch('/api/v1/profile', headers={'Idempotency-Key':uuid4().hex}, json={
        'expected_version': client.get('/api/v1/profile').json()['version'], **fields})


def add(client, start='2030-01-03', end='2030-01-04', hours=7, **overrides):
    return client.post('/api/v1/profile/availability-periods', headers={'Idempotency-Key':uuid4().hex}, json={
        'expected_version': client.get('/api/v1/profile').json()['version'], 'start_date':start,'end_date':end,'weekly_hours':hours, **overrides})


def inputs(client, **query):
    return client.get('/api/v1/profile/planning-inputs', params={'time_zone':'Asia/Singapore', **query})


@pytest.mark.parametrize('value', ['2030-01-01','2030-01-02','2029-12-31','2030-02-30','20300103','bad',None,True,20300103])
def test_reject_invalid_deadlines_without_overwriting(client, value):
    assert write(client, application_date='2030-01-03',time_zone='Asia/Singapore').status_code == 200
    old=client.get('/api/v1/profile').json()
    assert write(client, application_date=value,time_zone='Asia/Singapore').status_code == 422
    assert client.get('/api/v1/profile').json() == old


def test_device_zone_midnight_and_exact_date(client):
    assert write(client,application_date='2030-01-02',time_zone='Asia/Singapore').status_code==422
    first=write(client,application_date='2030-01-02',time_zone='America/Los_Angeles').json()
    assert first['application_date']=='2030-01-02'
    assert inputs(client).json()['issues'][0]['field']=='application_date'
    assert inputs(client,time_zone='America/Los_Angeles').json()['application_date']=='2030-01-02'
    # Changing an unrelated field keeps an elapsed deadline.
    assert client.patch('/api/v1/profile',json={'expected_version':first['version'],'occupational_status':'unemployed'}).status_code==200
    assert client.get('/api/v1/profile').json()['application_date']=='2030-01-02'
    assert write(client,application_date='2032-02-29',time_zone='America/New_York').status_code==200


@pytest.mark.parametrize('zone',[None,'Mars/Base','',True])
def test_device_zone_must_be_explicit_valid_and_recoverable(client,zone):
    data={'application_date':'2030-01-03'}
    if zone is not None:data['time_zone']=zone
    assert write(client,**data).status_code==422
    assert client.get('/api/v1/profile/planning-inputs').status_code==422


@pytest.mark.parametrize('value',[None,True,False,'10','',0,-1,168.01])
def test_invalid_base_hours_preserve_old_budget(client,value):
    assert write(client,weekly_hours=14.125).status_code==200
    old=client.get('/api/v1/profile').json()
    assert write(client,weekly_hours=value).status_code==422
    assert client.get('/api/v1/profile').json()==old


@pytest.mark.parametrize('value',[.1,1.125,14.123456789,168])
def test_fractional_and_max_hours_roundtrip(client,value):
    saved=write(client,weekly_hours=value).json()
    assert saved['weekly_hours']==value
    assert inputs(client).json()['weekly_hours']==value
    assert client.get(f"/api/v1/profile/versions/{saved['version']}").json()['weekly_hours']==value


def test_nonfinite_and_bool_hours_rejected(client):
    for literal in ['NaN','Infinity','-Infinity','true']:
        r=client.patch('/api/v1/profile',headers={'Content-Type':'application/json','Idempotency-Key':uuid4().hex},content='{"expected_version":1,"weekly_hours":'+literal+'}')
        assert r.status_code==422


def test_idempotency_noop_stale_versions_and_history(client):
    key=uuid4().hex
    data={'expected_version':1,'weekly_hours':14}
    r=client.patch('/api/v1/profile',headers={'Idempotency-Key':key},json=data)
    assert r.status_code==200
    assert client.patch('/api/v1/profile',headers={'Idempotency-Key':key},json=data).json()==r.json()
    assert client.patch('/api/v1/profile',headers={'Idempotency-Key':key},json={**data,'weekly_hours':15}).status_code==409
    assert client.patch('/api/v1/profile',headers={'Idempotency-Key':uuid4().hex},json=data).status_code==409
    unchanged=write(client,weekly_hours=14).json()
    assert unchanged['version']==r.json()['version']
    assert unchanged['planning_revision']==1
    assert client.patch('/api/v1/profile',json={'expected_version':unchanged['version'],'weekly_hours':16}).status_code==422


def test_period_crud_overlap_boundaries_and_proration(client):
    assert add(client).status_code==422
    assert write(client,application_date='2030-02-01',time_zone='Asia/Singapore',weekly_hours=14).status_code==200
    first=add(client).json();row=first['availability_periods'][0]
    assert add(client,start='2030-01-04',end='2030-01-05').status_code==422
    adjacent=add(client,start='2030-01-05',end='2030-01-05',hours=0).json()
    assert len(adjacent['availability_periods'])==2
    # Exclude the period's own ID when checking an unchanged edit.
    same=client.patch('/api/v1/profile/availability-periods/'+row['id'],headers={'Idempotency-Key':uuid4().hex},json={'expected_version':adjacent['version'],'weekly_hours':7})
    assert same.json()['version']==adjacent['version']
    window=inputs(client,start_date='2030-01-02',end_date='2030-01-08').json()
    assert window['capacity_window']['available_hours']==10 # two days at half rate + one at zero
    assert window['week_start']=='Monday'
    assert window['capacity_time_zone']=='Asia/Singapore'
    old=client.get('/api/v1/profile').json()
    lowered=write(client,weekly_hours=6).json()
    assert lowered['availability_periods']==old['availability_periods']
    assert row['id'] in inputs(client).json()['issues'][0]['period_ids']
    r=client.delete('/api/v1/profile/availability-periods/'+row['id'],params={'expected_version':lowered['version']},headers={'Idempotency-Key':uuid4().hex})
    assert len(r.json()['availability_periods'])==1
    final=r.json()['availability_periods'][0]
    r=client.delete('/api/v1/profile/availability-periods/'+final['id'],params={'expected_version':r.json()['version']},headers={'Idempotency-Key':uuid4().hex})
    assert r.json()['availability_periods']==[]
    assert inputs(client,start_date='2030-01-02',end_date='2030-01-08').json()['capacity_window']['available_hours']==6


def test_reference_capacity_example_and_missing_values(client):
    assert not inputs(client).json()['ready']
    assert write(client,weekly_hours=14).status_code==200
    assert add(client).status_code==201
    result=inputs(client,start_date='2030-01-02',end_date='2030-01-08').json()
    assert result['capacity_window']['available_hours']==12
    assert result['hours_unit']=='hours_per_week'
    assert not result['ready'] # missing deadline is never guessed
    assert inputs(client,start_date='2030-01-02').status_code==422
    assert inputs(client,start_date='2030-01-08',end_date='2030-01-02').status_code==422


@pytest.mark.parametrize('changes',[
 {'start':'2030-01-05','end':'2030-01-03'}, {'end':'2030-01-01','start':'2030-01-01'},
 {'hours':14},{'hours':15},{'hours':-1},{'hours':True},{'hours':None},{'hours':'7'},
 {'start':'2030-02-30'},
])
def test_invalid_periods_do_not_persist(client,changes):
    write(client,weekly_hours=14)
    assert add(client,**changes).status_code==422
    assert client.get('/api/v1/profile').json()['availability_periods']==[]


def test_historical_periods_remain_visible_deletable_and_nonblocking(client,monkeypatch):
    write(client,weekly_hours=14)
    saved=add(client).json();row=saved['availability_periods'][0]
    monkeypatch.setattr(planning,'today_in',lambda zone:date(2030,2,1))
    latest=write(client,weekly_hours=3).json()
    assert not any(i['field']=='availability_periods' for i in inputs(client).json()['issues'])
    assert inputs(client,start_date='2030-02-01',end_date='2030-02-07').json()['capacity_window']['available_hours']==3
    assert client.patch('/api/v1/profile/availability-periods/'+row['id'],headers={'Idempotency-Key':uuid4().hex},json={'expected_version':latest['version'],'weekly_hours':1}).status_code==422
    result=client.delete('/api/v1/profile/availability-periods/'+row['id'],params={'expected_version':latest['version']},headers={'Idempotency-Key':uuid4().hex})
    assert result.status_code==200
    assert result.json()['availability_periods']==[]


def test_period_lost_success_retry_and_ownership(client):
    write(client,weekly_hours=14)
    data={'expected_version':2,'start_date':'2030-01-03','end_date':'2030-01-04','weekly_hours':0}
    key=uuid4().hex
    first=client.post('/api/v1/profile/availability-periods',headers={'Idempotency-Key':key},json=data).json()
    again=client.post('/api/v1/profile/availability-periods',headers={'Idempotency-Key':key},json=data).json()
    assert again==first
    row=first['availability_periods'][0]
    client.app.dependency_overrides[current_owner]=lambda:'bob'
    assert client.get('/api/v1/profile').json()['availability_periods']==[]
    assert client.get(f"/api/v1/profile/versions/{first['version']}").status_code==404
    assert client.delete('/api/v1/profile/availability-periods/'+row['id'],params={'expected_version':first['version']},headers={'Idempotency-Key':uuid4().hex}).status_code==409
    client.app.dependency_overrides[current_owner]=lambda:'alice'
    assert client.get('/api/v1/profile').json()==first


def test_storage_error_does_not_claim_success_or_change_profile(client):
    from pymongo.errors import AutoReconnect
    old=client.get('/api/v1/profile').json()
    with patch.object(client.app.state.repository,'change_period',side_effect=AutoReconnect('private password')):
        assert add(client).status_code==503
    assert client.get('/api/v1/profile').json()==old


def test_planning_endpoints_require_authentication(monkeypatch):
    monkeypatch.setenv('AUTH_MODE','google')
    with TestClient(create_app(PlanningMemoryRepository())) as client:
        assert client.get('/api/v1/profile/planning-inputs?time_zone=Asia/Singapore').status_code==401
        assert client.post('/api/v1/profile/availability-periods',json={}).status_code==401


def test_lost_deadline_success_can_replay_after_midnight_without_a_second_version(client,monkeypatch):
    key=uuid4().hex
    body={'expected_version':1,'application_date':'2030-01-03','time_zone':'Asia/Singapore'}
    first=client.patch('/api/v1/profile',headers={'Idempotency-Key':key},json=body)
    assert first.status_code==200
    monkeypatch.setattr(planning,'today_in',lambda zone:date(2030,1,3))
    replay=client.patch('/api/v1/profile',headers={'Idempotency-Key':key},json=body)
    assert replay.json()==first.json()
    assert write(client,application_date='2030-01-03',time_zone='Asia/Singapore').status_code==422
    assert client.get('/api/v1/profile').json()['application_date']=='2030-01-03'
    assert not inputs(client).json()['ready']


def test_same_valid_deadline_does_not_rewrite_saved_zone_or_revision(client):
    first=write(client,application_date='2030-01-10',time_zone='Asia/Singapore').json()
    again=write(client,application_date='2030-01-10',time_zone='America/Los_Angeles').json()
    assert again==first
    assert again['application_time_zone']=='Asia/Singapore'
