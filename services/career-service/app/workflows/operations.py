"""Owner-scoped transient jobs keep quota waits outside gateway request timeouts.

Inputs/results live in this worker's memory for at most 24 hours, never MongoDB.
A restart loses unfinished transient work; validated goals remain in MongoDB.
"""
import asyncio
import math
import time
import logging
import re
from dataclasses import dataclass, field
from uuid import uuid4
from app.ai.waiting import quota_progress,quota_reason
from app.ai.recovery import recover_responses,validation_progress
from app.repositories.goals import GoalError
from app.workflows.activity import activity_observer,LABELS
from app.ai.adapter import AIError
from app.ai.jd_scope import CareerScopeError


class OperationConflict(GoalError):
    def __init__(self,code,message,status=409):
        self.code=code
        super().__init__(message,status)


@dataclass(frozen=True)
class Failure:
    """Retain bounded public diagnostics, never an exception or request frames."""
    kind: str
    values: dict

    @classmethod
    def capture(cls, error):
        if isinstance(error, AIError):
            # AIError revalidates all diagnostic fields and does not accept raw
            # provider text. Reconstruct once to detach mutable caller values.
            code=error.code if isinstance(error.code,str) and re.fullmatch(r'[a-z_]{1,80}',error.code) else 'unavailable'
            safe = AIError(code, bool(error.retryable), reason=error.reason,
                fields=error.fields, violations=error.violations, provider=error.provider,
                provider_error=error.provider_error, limit_scope=error.limit_scope,
                retry_after=error.retry_after, input_count=error.input_count)
            return cls('ai', {name: getattr(safe, name) for name in
                ('code','retryable','reason','fields','violations','provider','provider_error',
                 'limit_scope','retry_after','input_count')})
        if isinstance(error, CareerScopeError): return cls('scope', {})
        if isinstance(error, GoalError):
            if not isinstance(error.message,str) or len(error.message)>1024:
                return cls('goal', {'message':'This temporary operation failed. Retry your retained input.','status':503})
            values = {'message': error.message, 'status': error.status if type(error.status) is int and 400<=error.status<=599 else 503}
            if isinstance(error, OperationConflict):
                code=error.code if isinstance(error.code,str) and re.fullmatch(r'[a-z_]{1,80}',error.code) else 'operation_failed'
                return cls('operation', {**values, 'code': code})
            return cls('goal', values)
        return cls('goal', {'message': 'This temporary operation failed. Retry your retained input.', 'status': 503})

    def exception(self):
        if self.kind == 'ai': return AIError(**self.values)
        if self.kind == 'scope': return CareerScopeError()
        if self.kind == 'operation': return OperationConflict(**self.values)
        return GoalError(**self.values)


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
    error: Failure | None = None
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

    def __init__(self, *, max_jobs=128, max_owner_jobs=16, max_aliases=32):
        if any(type(value) is not int or value < 1 for value in (max_jobs,max_owner_jobs,max_aliases)):
            raise ValueError('Operation capacities must be positive integers.')
        self.max_jobs, self.max_owner_jobs, self.max_aliases = max_jobs,max_owner_jobs,max_aliases
        self.jobs = {}

    def alias(self, job, key):
        if key != job.key and key not in job.aliases:
            if len(job.aliases) >= self.max_aliases:
                raise OperationConflict('operation_capacity', 'Too many reconnect attempts. Use the existing operation link or retry after it finishes.', 429)
            job.aliases.add(key)

    def make_room(self, owner):
        # Evict only terminal cache entries. Never cancel another owner's active
        # request to admit a new one, or forget aliases within a retained job.
        for same_owner, limit in ((True,self.max_owner_jobs),(False,self.max_jobs)):
            candidates = [job for job in self.jobs.values() if not same_owner or job.owner == owner]
            if len(candidates) < limit: continue
            terminal = sorted((job for job in candidates if job.status in ('succeeded','failed')), key=lambda job: job.created)
            if not terminal:
                raise OperationConflict('operation_capacity', 'Career is processing the current requests. Retry shortly; your saved goal is unchanged.', 429)
            del self.jobs[terminal[0].id]

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
                    self.alias(job,key)
                    return job.view()
                raise OperationConflict('operation_in_progress','Another request is still being processed. Wait for it to finish before submitting different input.')
        if kind == 'summary':
            for job in self.jobs.values():
                if job.owner == owner and job.kind == kind and job.digest == digest and job.error is None:
                    self.alias(job,key)
                    return job.view()
        self.make_room(owner)
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
            job.error = Failure.capture(GoalError('This temporary operation was cancelled. Retry your retained input.', 409))
            raise
        except Exception as error:
            job.status, job.error = 'failed', Failure.capture(error)
            if isinstance(error,AIError):
                job.validation_feedback={'reason':error.reason,'fields':list(error.fields),'violations':list(error.violations)}
            logging.getLogger('uvicorn.error.ai_usage').warning(
                'operation_failed operation_id=%s kind=%s error_code=%s reason=%s',
                job.id,job.kind,error.code if isinstance(error,AIError) else 'operation_failed',
                error.reason if isinstance(error,AIError) else None)
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
        if job.error is not None: raise job.error.exception()
        return job.view()

    async def close(self):
        tasks = [job.task for job in self.jobs.values() if job.task]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
