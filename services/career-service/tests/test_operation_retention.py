"""Bounded transient jobs preserve retries without retaining raised exceptions."""
import asyncio
import traceback
import pytest
from app.ai.adapter import AIError
from app.ai.jd_scope import CareerScopeError
from app.repositories.goals import GoalError
from app.workflows.operations import Failure, Operations, OperationConflict


@pytest.mark.parametrize('error,kind,status', [
    (AIError('invalid_output', True, reason='provenance', fields=('reply',),
             violations=({'field':'reply','issue':'missing_finding_citation'},)), AIError, None),
    (GoalError('Your career goal changed. Reload its latest version.'), GoalError, 409),
    (OperationConflict('operation_key_reused', 'This request changed.'), OperationConflict, 409),
    (CareerScopeError(), CareerScopeError, 422),
    (RuntimeError('PRIVATE_PROVIDER_BODY'), GoalError, 503),
])
def test_failed_polling_raises_fresh_errors_with_bounded_tracebacks(error,kind,status):
    async def run():
        jobs = Operations()
        async def fail(): raise error
        accepted = jobs.submit('owner','key','digest','chat',fail)
        job = jobs.jobs[accepted['operation_id']]
        await job.task
        assert isinstance(job.error, Failure) and not isinstance(job.error, BaseException)
        caught = []
        for _ in range(200):
            with pytest.raises(kind) as outcome: jobs.read('owner',job.id)
            caught.append(outcome.value)
        assert len({id(item) for item in caught}) == 200
        assert len({len(traceback.extract_tb(item.__traceback__)) for item in caught}) == 1
        assert all(item is not error for item in caught)
        if status is not None: assert all(item.status == status for item in caught)
        if isinstance(error, AIError):
            assert caught[-1].violations == error.violations
            assert caught[-1].code == error.code and caught[-1].retryable
        if isinstance(error, OperationConflict): assert caught[-1].code == error.code
        assert 'PRIVATE_PROVIDER_BODY' not in str(job.error)
        with pytest.raises(GoalError) as hidden: jobs.read('stranger',job.id)
        assert hidden.value.status == 404
        await jobs.close()
    asyncio.run(run())


def test_owner_and_global_terminal_retention_remain_bounded():
    async def run():
        jobs = Operations(max_jobs=3,max_owner_jobs=2)
        async def done(): return {'saved': True}
        oldest = None
        for index in range(30):
            owner = 'owner-a' if index < 15 else 'owner-b'
            accepted = jobs.submit(owner,str(index),str(index),'chat',done)
            await jobs.jobs[accepted['operation_id']].task
            oldest = oldest or accepted['operation_id']
            assert len(jobs.jobs) <= 3
            assert sum(job.owner == owner for job in jobs.jobs.values()) <= 2
        assert oldest not in jobs.jobs
        assert jobs.read('owner-b',accepted['operation_id'])['result'] == {'saved': True}
        await jobs.close()
    asyncio.run(run())


def test_active_capacity_rejection_does_not_cancel_owned_work():
    async def run():
        jobs = Operations(max_jobs=2,max_owner_jobs=1)
        release = asyncio.Event()
        async def pending(): await release.wait(); return {}
        first = jobs.submit('owner-a','a','a','jd',pending)
        second = jobs.submit('owner-b','b','b','jd',pending)
        with pytest.raises(OperationConflict) as full:
            jobs.submit('owner-c','c','c','jd',pending)
        assert full.value.code == 'operation_capacity' and full.value.status == 429
        with pytest.raises(OperationConflict): jobs.submit('owner-a','other','other','chat',pending)
        assert jobs.submit('owner-a','a','a','jd',pending) == first
        assert set(jobs.jobs) == {first['operation_id'],second['operation_id']}
        assert all(not job.task.cancelled() for job in jobs.jobs.values())
        release.set()
        await asyncio.gather(*(job.task for job in jobs.jobs.values()))
        await jobs.close()
    asyncio.run(run())


@pytest.mark.parametrize('complete',[False,True])
def test_alias_capacity_preserves_every_accepted_retry(complete):
    async def run():
        jobs = Operations(max_aliases=2)
        release = asyncio.Event()
        async def pending(): await release.wait(); return {'saved': True}
        original = jobs.submit('owner','original','same','summary',pending)
        if complete:
            release.set(); await jobs.jobs[original['operation_id']].task
        for key in ('alias-one','alias-two'):
            assert jobs.submit('owner',key,'same','summary',pending)['operation_id'] == original['operation_id']
        with pytest.raises(OperationConflict) as full:
            jobs.submit('owner','too-many','same','summary',pending)
        assert full.value.code == 'operation_capacity'
        for key in ('original','alias-one','alias-two'):
            assert jobs.submit('owner',key,'same','summary',pending)['operation_id'] == original['operation_id']
            with pytest.raises(OperationConflict) as mismatch:
                jobs.submit('owner',key,'changed','summary',pending)
            assert mismatch.value.code == 'operation_key_reused'
        assert jobs.jobs[original['operation_id']].aliases == {'alias-one','alias-two'}
        release.set(); await jobs.jobs[original['operation_id']].task
        await jobs.close()
    asyncio.run(run())


def test_same_key_after_failed_work_can_start_a_fresh_attempt():
    async def run():
        jobs = Operations(max_jobs=1,max_owner_jobs=1)
        async def fail(): raise AIError('unavailable', True)
        first = jobs.submit('owner','same-key','same','chat',fail)
        await jobs.jobs[first['operation_id']].task
        async def done(): return {'saved':True}
        second = jobs.submit('owner','same-key','same','chat',done)
        assert second['operation_id'] != first['operation_id'] and len(jobs.jobs) == 1
        await jobs.jobs[second['operation_id']].task
        assert jobs.read('owner',second['operation_id'])['result'] == {'saved':True}
        await jobs.close()
    asyncio.run(run())
