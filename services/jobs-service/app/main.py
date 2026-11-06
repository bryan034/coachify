"""Authenticated live job search and private application tracking."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from elo_shared.runtime import Problem, application, authenticated
from fastapi import Depends, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool as thread

from app.external import external_searches
from app.schemas import (Application, ApplicationList, CreateApplication, ExternalSearchList, FilterOptions, Industry, JobType,
                         Posting, SaveJobLink, SearchResult, UpdateApplication, Workplace)
from app.store import JobsStore, search_filter
from app.live import LiveJobs

SINGAPORE_TIME = ZoneInfo('Asia/Singapore')
Identifier = Annotated[str, Path(pattern=r'^[0-9a-f]{32}$')]


def start_of_day(value):
    return datetime.combine(value, time.min, SINGAPORE_TIME).astimezone(timezone.utc)


def create_app(store=None, upstream=None, clock=None, catalogue=None):
    # This service makes no model calls; the shared runtime's model slot stays unused.
    app = application('elo Jobs API', 'JOBS', store=store, upstream=upstream, model=object())
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))

    catalogue = catalogue if catalogue is not None else LiveJobs(clock=app.state.clock)

    def jobs():
        cached = getattr(app.state, 'jobs', None)
        if cached is not None:
            return cached
        if app.state.store.database is None:
            raise Problem('Service storage is not configured.', 503, 'storage')
        store = JobsStore(app.state.store.database, live=catalogue if isinstance(catalogue, LiveJobs) else None)
        store.ensure_indexes()
        app.state.jobs = store
        return store

    @app.get('/api/v1/jobs/search', response_model=SearchResult)
    async def search(request: Request,
                     q: Annotated[str | None, Query(max_length=120)] = None,
                     job_type: Annotated[list[JobType] | None, Query()] = None,
                     industry: Annotated[list[Industry] | None, Query()] = None,
                     workplace: Annotated[list[Workplace] | None, Query()] = None,
                     company: Annotated[list[str] | None, Query(max_length=20)] = None,
                     posted_within_days: Annotated[int | None, Query(ge=1, le=365)] = None,
                     posted_from: date | None = None,
                     posted_to: date | None = None,
                     cursor: Annotated[str | None, Query(max_length=200)] = None,
                     limit: Annotated[int, Query(ge=1, le=50)] = 20,
                     account=Depends(authenticated)):
        if posted_from and posted_to and posted_from > posted_to:
            raise Problem('Choose a start date on or before the end date.', 422, 'validation')
        earliest = start_of_day(posted_from) if posted_from else None
        if posted_within_days:
            recent = app.state.clock() - timedelta(days=posted_within_days)
            earliest = max(earliest, recent) if earliest else recent
        query = search_filter(q, job_type or (), industry or (), workplace or (), company or (), earliest,
                              start_of_day(posted_to + timedelta(days=1)) if posted_to else None)
        return await thread(lambda: catalogue.search(query, cursor, limit))

    @app.get('/api/v1/jobs/filters', response_model=FilterOptions)
    async def filters(request: Request, account=Depends(authenticated)):
        return await thread(lambda: catalogue.filter_options())

    @app.get('/api/v1/jobs/postings/{identifier}', response_model=Posting)
    async def posting(identifier: Identifier, request: Request, account=Depends(authenticated)):
        return await thread(lambda: catalogue.posting(identifier))

    @app.get('/api/v1/jobs/external-searches', response_model=ExternalSearchList)
    async def external(request: Request, q: Annotated[str, Query(min_length=1, max_length=120)], account=Depends(authenticated)):
        keywords = q.strip()
        if not keywords:
            raise Problem('Enter a job title or keywords.', 422, 'validation')
        return {'items': external_searches(keywords)}

    @app.get('/api/v1/jobs/applications', response_model=ApplicationList)
    async def applications(request: Request, account=Depends(authenticated)):
        return await thread(lambda: jobs().list_applications(account['id']))

    @app.post('/api/v1/jobs/applications', response_model=Application)
    async def create_application(body: CreateApplication, request: Request, account=Depends(authenticated)):
        return await thread(lambda: jobs().create_application(account['id'], body.posting_id, app.state.clock()))

    @app.post('/api/v1/jobs/applications/link', response_model=Application)
    async def save_link(body: SaveJobLink, request: Request, account=Depends(authenticated)):
        return await thread(lambda: jobs().save_link(account['id'], body, app.state.clock()))

    @app.patch('/api/v1/jobs/applications/{identifier}', response_model=Application)
    async def update_application(identifier: Identifier, body: UpdateApplication, request: Request, account=Depends(authenticated)):
        return await thread(lambda: jobs().update_application(account['id'], identifier, body.expected_version, body.status, app.state.clock()))

    @app.delete('/api/v1/jobs/applications/{identifier}', status_code=204)
    async def delete_application(identifier: Identifier, expected_version: Annotated[int, Query(ge=1)], request: Request, account=Depends(authenticated)):
        await thread(lambda: jobs().delete_application(account['id'], identifier, expected_version))
        return Response(status_code=204)

    return app


app = create_app()
