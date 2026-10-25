"""Authenticated temporary previews, adaptive exploration and explicit goal saving."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from app.core.auth import bearer, current_account
from app.ai.adapter import AIAdapter
from app.ai.config import AISettings
from app.ai.adapter import AIError
from app.clients.cvs import CvClient
from app.repositories.goals import GoalStore, GoalError
from app.api.v1.goals import router as goals_router
from app.api.v1.jd import router as jd_router
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.domain.preview import run_preview
from app.schemas.preview import MAX_BODY, MAX_FILE, Preview, UrlInput, ImportErrorView


class BodyLimit:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        maximum = MAX_BODY if scope['path'].endswith('/document') else 256 * 1024 if '/career/jd/' in scope['path'] else 96 * 1024 if '/explorations/' in scope['path'] else 16 * 1024
        headers = dict(scope.get('headers', []))
        try: declared = int(headers.get(b'content-length', b'0'))
        except ValueError: declared = maximum + 1
        if declared < 0 or declared > maximum:
            return await JSONResponse({'detail':'The request exceeds the upload limit. Choose a file up to 10 MiB.'},413,
                headers={'Cache-Control':'no-store'})(scope, receive, send)
        size = 0
        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > maximum:
                raise HTTPException(413, 'The request exceeds the upload limit. Choose a file up to 10 MiB.')
            return message
        await self.app(scope, limited_receive, send)


def create_app(profile_client=None, processor=run_preview, database=None, ai=None, cv_client=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.slots = asyncio.Semaphore(2)
        mongo = None
        db = database
        if db is None and os.getenv('MONGODB_URI'):
            mongo = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
            db = mongo[os.getenv('MONGODB_DATABASE','coachify_career')]
        app.state.goal_store = GoalStore(db) if db is not None else None
        if app.state.goal_store is not None:
            try: await run_in_threadpool(app.state.goal_store.ensure_indexes)
            except PyMongoError:
                if mongo is not None: mongo.close()
                raise RuntimeError('Career storage could not connect. Check database setup.') from None
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as ai_client:
            app.state.ai = ai or AIAdapter(AISettings.from_env(), ai_client)
            async with httpx.AsyncClient(base_url=os.getenv('CV_SERVICE_URL','http://cv-service:8000'),
                    timeout=5, trust_env=False, follow_redirects=False) as cv_http:
                app.state.cv = cv_client or CvClient(cv_http)
                try:
                    async with profile_lifespan(app): yield
                finally:
                    if mongo is not None: mongo.close()

    @asynccontextmanager
    async def profile_lifespan(app):
        if profile_client is not None:
            app.state.profile_client = profile_client
            yield
        else:
            async with httpx.AsyncClient(base_url=os.getenv('PROFILE_SERVICE_URL', 'http://profile-service:8000'),
                                         timeout=5, follow_redirects=False, trust_env=False) as client:
                app.state.profile_client = client
                yield

    app = FastAPI(title='Coachify Career API', version='0.2.0', lifespan=lifespan,
        description='Transient JD previews, optional-CV conversational exploration and explicit structured goal persistence. Temporary JD skill extraction and review do not publish goals.')
    app.add_middleware(BodyLimit)
    app.include_router(goals_router)
    app.include_router(jd_router)

    @app.exception_handler(ValidationError)
    async def model_error(request, error):
        return JSONResponse({'detail':'The assistant or stored record returned invalid data. Reload or retry; saved progress was not replaced.'},503)

    @app.exception_handler(GoalError)
    async def goal_error(request, error):
        return JSONResponse({'detail':error.message},error.status)

    @app.exception_handler(PyMongoError)
    async def storage_error(request, error):
        return JSONResponse({'detail':'Career storage is unavailable. Your last saved goal is unchanged.'},503)

    @app.exception_handler(AIError)
    async def ai_error(request, error):
        status=429 if error.code in ('busy','capacity','rate_limited') else 409 if error.code=='stale_input' else 503
        messages={'not_configured':'AI is disabled. Configure the Career service model and API key.',
                  'provider_auth':'The AI provider credentials need to be checked.',
                  'provider_configuration':'Check the configured AI model and response mode.',
                  'model_unavailable':'The configured AI model is not available to this provider account. Choose an accessible AI_MODEL and recreate the Career service.',
                  'invalid_output':'The AI returned an invalid structured response. Your saved progress is unchanged; retry your message.',
                  'context_limit':'This context is too long. Start without the temporary CV or use a shorter document.'}
        detail=messages.get(error.code,'The assistant could not complete this turn. Your saved progress is unchanged; retry shortly.')
        payload={'detail':detail,'code':error.code}
        if error.reason:
            descriptions={
                'schema_validation':'The AI response had missing or invalid fields.',
                'source_quote':'A supporting skill quote did not match the job description.',
                'duplicate_skill':'The model returned duplicate skills.',
                'unexpected_origin':'The model mixed JD requirements with unsupported suggestions.',
                'provider_json':'The AI provider rejected the generated JSON.',
                'json_syntax':'The model returned malformed JSON.',
                'response_envelope':'The model returned an unexpected response format.',
                'provenance':'The model returned unsupported source claims.',
            }
            action='retry extraction' if request.url.path.endswith('/jd/extract') else 'retry your message'
            payload['detail']=descriptions[error.reason]+' Your previous inputs and saved progress are unchanged; '+action+'.'
            payload['diagnostic']={'reason':error.reason,'fields':list(error.fields)}
        return JSONResponse(payload,status)


    @app.middleware('http')
    async def no_storage(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'detail':'Enter one valid URL of at most 2,048 characters.' if request.url.path.endswith('/url') else 'Check the required fields, lengths and version values.'},422)

    async def authenticated(request: Request, credentials=Depends(bearer)):
        return await current_account(request, credentials)

    @asynccontextmanager
    async def slot(request):
        try:
            await asyncio.wait_for(request.app.state.slots.acquire(), timeout=0.05)
        except TimeoutError:
            raise HTTPException(429, 'Other previews are processing. Please retry shortly.')
        try:
            yield
        finally:
            request.app.state.slots.release()

    @app.get('/health', include_in_schema=False)
    async def health(): return {'status':'ok'}

    errors = {status: {'model': ImportErrorView} for status in (400,401,403,413,415,422,429,503)}

    @app.post('/api/v1/career/imports/url', response_model=Preview, responses=errors, tags=['J06 URL preview'])
    async def url(data: UrlInput, request: Request, account=Depends(authenticated)):
        async with slot(request):
            return await run_in_threadpool(processor, 'url', data.url.encode('utf-8'), '')

    @app.post('/api/v1/career/explorations/cv/document', response_model=Preview, tags=['J08 temporary CV context'])
    @app.post('/api/v1/career/imports/document', response_model=Preview, responses=errors, tags=['J07 document preview'],
        openapi_extra={'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {
            'type': 'object', 'required': ['file'], 'properties': {'file': {'type': 'string', 'format': 'binary'}},
            'additionalProperties': False}}}}})
    async def document(request: Request, account=Depends(authenticated)):
        if not request.headers.get('content-type','').lower().startswith('multipart/form-data;'):
            raise HTTPException(415, 'Upload one PDF, DOCX or TXT file as multipart form data.')
        async with slot(request), request.form(max_files=1, max_fields=0) as form:
            file = form.get('file')
            if len(form.multi_items()) != 1 or not isinstance(file, UploadFile):
                raise HTTPException(422, 'Choose one file in the file field.')
            name = PurePosixPath((file.filename or 'document').replace('\\','/')).name[:160]
            extension = PurePosixPath(name).suffix.lower()
            types = {'.pdf':{'application/pdf'}, '.docx':{'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}, '.txt':{'text/plain'}}
            if extension not in types or file.content_type not in types[extension] | {'application/octet-stream'}:
                raise HTTPException(422, 'Choose a PDF, DOCX or UTF-8 TXT file whose format matches its extension.')
            data = await file.read(MAX_FILE + 1)
            if not data or len(data) > MAX_FILE:
                raise HTTPException(413 if data else 422, 'Choose a non-empty file up to 10 MiB.')
            result = await run_in_threadpool(processor, 'document', data, extension)
            return {'kind':'document','source_name':name, **result}

    return app


app = create_app()
