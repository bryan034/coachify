"""Owner-scoped transient jobs keep quota waits outside gateway request timeouts.

Inputs/results live in this worker's memory for at most 24 hours, never MongoDB.
A restart loses unfinished transient work; validated goals remain in MongoDB.
"""
import asyncio
import math
import time
from dataclasses import dataclass, field
from uuid import uuid4
from app.ai.waiting import quota_progress,quota_reason
from app.ai.recovery import recover_responses,validation_progress
from app.repositories.goals import GoalError
from app.workflows.activity import activity_observer,LABELS


class OperationConflict(GoalError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


@dataclass
class Pending:
    owner: str
    key: str
    digest: str
    kind: str
    id: str = field(default_factory=lambda: uuid4().hex)
    created: float = field(default_factory=time.monotonic)
    status: str = 'running'
    resume_at: float | None = None
    limit_scope: str | None = None
    provider: str | None = None
    validation_feedback: dict | None = None
    result: dict | None = None
    error: Exception | None = None
    task: asyncio.Task | None = None
    activities: list[str] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)

    def view(self):
        return {'operation_id': self.id, 'status': self.status,
                'retry_after': max(0, math.ceil(self.resume_at-time.monotonic())) if self.resume_at else None,
                'result': self.result if self.status == 'succeeded' else None,
                'activities':self.activities,'validation_feedback': self.validation_feedback,'limit_scope':self.limit_scope,'provider':self.provider}


class Operations:
    lifetime = 86400

    def __init__(self):
        self.jobs = {}

    def prune(self):
        for id, job in list(self.jobs.items()):
            if time.monotonic()-job.created >= self.lifetime:
                if job.task and not job.task.done(): job.task.cancel()
                del self.jobs[id]

    def submit(self, owner, key, digest, kind, execute):
        self.prune()
        for job in list(self.jobs.values()):
            if job.owner != owner: continue
            if job.key == key or key in job.aliases:
                if job.digest != digest or job.kind != kind:
                    raise OperationConflict('operation_key_reused','This request changed after it started. Return to Career Goal and submit the updated description again.')
                if job.error is not None:
                    del self.jobs[job.id]
                    break
                return job.view()
            if job.kind == kind and job.status in ('running', 'repairing', 'waiting_quota'):
                if kind in ('jd','summary') and job.digest==digest:
                    # A remount/new tab can issue a new key for the same retained JD.
                    # Reconnect to the owned operation instead of making another LLM call.
                    job.aliases.add(key)
                    return job.view()
                raise OperationConflict('operation_in_progress','Another request is still being processed. Wait for it to finish before submitting different input.')
        if kind == 'summary':
            for job in self.jobs.values():
                if job.owner == owner and job.kind == kind and job.digest == digest and job.error is None:
                    job.aliases.add(key)
                    return job.view()
        job = Pending(owner, key, digest, kind)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self.run(job, execute))
        return job.view()

    async def run(self, job, execute):
        def progress(seconds):
            reason=quota_reason.get() or {}
            job.limit_scope=reason.get('limit_scope');job.provider=reason.get('provider')
            job.status = 'waiting_quota' if seconds is not None else 'repairing' if job.validation_feedback else 'running'
            job.resume_at = time.monotonic()+seconds if seconds is not None else None
        def repairing(feedback):
            job.validation_feedback = feedback
            if job.status != 'waiting_quota': job.status = 'repairing' if feedback else 'running'
        def observed(stage):
            if stage in LABELS and stage not in job.activities:job.activities=(job.activities+[stage])[-12:]
        activity_context=activity_observer.set(observed)
        context = quota_progress.set(progress)
        recovery = recover_responses.set(True)
        observer = validation_progress.set(repairing)
        try:
            async with asyncio.timeout(self.lifetime):
                job.result = await execute()
            job.status = 'succeeded'
        except asyncio.CancelledError:
            job.status = 'failed'
            job.error = GoalError('This temporary operation was cancelled. Retry your retained input.', 409)
            raise
        except Exception as error:
            job.status, job.error = 'failed', error
        finally:
            job.resume_at = None
            activity_observer.reset(activity_context)
            quota_progress.reset(context)
            recover_responses.reset(recovery)
            validation_progress.reset(observer)

    def read(self, owner, id):
        self.prune()
        job = self.jobs.get(id)
        if job is None or job.owner != owner:
            raise GoalError('Temporary operation not found. Retry your retained input.', 404)
        if job.error is not None: raise job.error
        return job.view()

    async def close(self):
        tasks = [job.task for job in self.jobs.values() if job.task]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
