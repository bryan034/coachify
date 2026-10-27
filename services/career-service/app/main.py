"""Authenticated previews, LangGraph research and one autosaved career workspace."""
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
from app.ai.config import GeminiSettings
from app.ai.routing import ModelRouter,opportunity_models
from app.ai.adapter import AIError
from app.ai.jd_scope import CareerScopeError
from app.clients.cvs import CvClient
from app.repositories.goals import GoalStore, GoalError
from app.api.v1.goals import router as goals_router
from app.api.v1.jd import router as jd_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.guidance import router as guidance_router
from app.api.v1.research import router as research_router
from app.repositories.research import ResearchStore
from app.clients.search_sources import SourceAPIs
from app.repositories.workspace import WorkspaceStore
from app.workflows.career import CareerWorkflow
from app.workflows.opportunity.engine import OpportunityEngine
from app.ai.opportunity_config import OpportunitySettings
from app.api.v1.opportunity import router as opportunity_router
from app.workflows.operations import Operations,OperationConflict
from app.api.v1.workspace import router as workspace_router
from app.repositories.reviews import ReviewStore
from app.workflows.discovery import DiscoveryEngine
from app.api.v1.discovery import router as discovery_router
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.domain.preview import run_preview
from app.schemas.preview import MAX_BODY, MAX_FILE, MAX_JD_TEXT, Preview, JDPreview, UrlInput, ImportErrorView


class BodyLimit:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        maximum = MAX_BODY if scope['path'].endswith('/document') else 256 * 1024 if '/career/jd/' in scope['path'] or '/career/workspace/' in scope['path'] or scope['path'].endswith('/review') else 96 * 1024 if '/explorations/' in scope['path'] else 16 * 1024
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


def create_app(profile_client=None, processor=run_preview, database=None, ai=None, cv_client=None, review_store=None, research_client=None, context_ai=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.slots = asyncio.Semaphore(2)
        app.state.operations = Operations()
        mongo = None
        db = database
        if db is None and os.getenv('MONGODB_URI'):
            mongo = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
            db = mongo[os.getenv('MONGODB_DATABASE','coachify_career')]
        app.state.goal_store = GoalStore(db) if db is not None else None
        app.state.review_store = review_store if review_store is not None else ReviewStore(db) if db is not None else None
        app.state.research_store = ResearchStore(db) if db is not None else None
        if app.state.research_store is not None:
            await run_in_threadpool(app.state.research_store.ensure_indexes)
        if app.state.goal_store is not None:
            try: await run_in_threadpool(app.state.goal_store.ensure_indexes)
            except PyMongoError:
                if mongo is not None: mongo.close()
                raise RuntimeError('Career storage could not connect. Check database setup.') from None
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as ai_client:
            # One Gemini client serves every reasoning/extraction/chat stage.
            gemini=GeminiSettings.reasoning_from_env() if ai is None else None
            primary=ai or AIAdapter(gemini,ai_client)
            context=primary if ai is None else context_ai
            app.state.ai=ModelRouter(primary,context) if context is not None else primary
            app.state.research_client = research_client or SourceAPIs.from_environment(ai_client)
            if app.state.research_store is not None:
                app.state.research_store.policy=getattr(app.state.research_client,'cache_policy',app.state.research_store.policy)
            app.state.workspace_store = WorkspaceStore(app.state.goal_store,app.state.review_store) if db is not None else None
            app.state.workflow = await run_in_threadpool(CareerWorkflow,app,db) if db is not None else None
            opportunity_settings=OpportunitySettings.from_env()
            opportunity_ai=opportunity_models(primary,context,gemini,opportunity_settings,ai_client)
            app.state.opportunities=OpportunityEngine(app,db,opportunity_settings,opportunity_ai) if db is not None else None
            app.state.discovery=DiscoveryEngine(app,db,opportunity_ai,app.state.opportunities.source) if db is not None else None
            # Chat and research share Gemini; provider retry delays remain resumable.
            app.state.chat_ai=opportunity_ai if getattr(opportunity_ai,'context_enabled',False) else app.state.ai
            async with httpx.AsyncClient(base_url=os.getenv('CV_SERVICE_URL','http://cv-service:8000'),
                    timeout=5, trust_env=False, follow_redirects=False) as cv_http:
                app.state.cv = cv_client or CvClient(cv_http)
                try:
                    async with profile_lifespan(app): yield
                finally:
                    if app.state.discovery is not None:await app.state.discovery.close()
                    if app.state.opportunities is not None:await app.state.opportunities.close()
                    await app.state.operations.close()
                    if app.state.workflow is not None: await app.state.workflow.close()
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
        description='One automatically saved career workspace per account. Validated job identity enables concurrent JD extraction and public research, with observed progress and scoped chat. Exploration follows a separate graph.')
    app.add_middleware(BodyLimit)
    app.include_router(discovery_router)
    app.include_router(opportunity_router)
    app.include_router(workspace_router)
    app.include_router(goals_router)
    app.include_router(jd_router)
    app.include_router(research_router)
    app.include_router(guidance_router)
    app.include_router(reviews_router)

    @app.exception_handler(ValidationError)
    async def model_error(request, error):
        return JSONResponse({'detail':'The assistant or stored record returned invalid data. Reload or retry; saved progress was not replaced.'},503)

    @app.exception_handler(GoalError)
    async def goal_error(request, error):
        return JSONResponse({'detail':error.message,**({'code':error.code} if isinstance(error,(OperationConflict,CareerScopeError)) else {})},error.status)

    @app.exception_handler(PyMongoError)
    async def storage_error(request, error):
        return JSONResponse({'detail':'Career storage is unavailable. Your last saved goal is unchanged.'},503)

    @app.exception_handler(AIError)
    async def ai_error(request, error):
        status=429 if error.code=='rate_limited' else 422 if error.code=='input_limit' else 409 if error.code=='stale_input' else 503
        messages={'not_configured':'AI is disabled. Configure AI_ENABLED and GEMINI_API_KEY on the Career service.',
                  'provider_auth':'Check GEMINI_API_KEY and its API/application restrictions on the Google project.',
                  'provider_configuration':'The AI provider rejected the request configuration. Check provider_error for the safe status and rejected field names.',
                  'provider_schema':'Gemini rejected the structured-output schema. Check provider_error.fields; your saved goal is unchanged.',
                  'provider_parameter':'Gemini rejected a model request parameter. Check provider_error.fields; your saved goal is unchanged.',
                  'provider_access':'Google project access, API enablement, billing or regional availability needs checking. Your saved goal is unchanged.',
                  'model_unavailable':'The configured AI model is not available to this provider account. Check GEMINI_REASONING_MODEL access for GEMINI_API_KEY and recreate the Career service.',
                  'invalid_output':'The AI returned an invalid structured response. Your saved progress is unchanged; retry your message.',
                  'timeout':'The AI did not finish within the time limit. Your inputs and saved progress are unchanged; retry the request.',
                  'incomplete_output':'The AI response ended before it was complete, possibly at its output limit. No incomplete result was saved; retry the request.',
                  'output_limit':'The AI response exceeded the allowed response size. Your inputs and saved progress are unchanged.',
                  'unavailable':'The AI provider is temporarily unavailable. Your inputs and saved progress are unchanged; retry shortly.',
                  'input_limit':f'This request contains {error.input_count} estimated input tokens; this request leaves insufficient output space within the configured model context. Shorten the description or conversation and retry. Your saved progress is unchanged.',
                  'context_limit':'This request exceeds the configured model or token allowance. Shorten the description/chat context or check the configured model context window. Saved progress is unchanged.'}
        detail=messages.get(error.code,'The assistant could not complete this turn. Your saved progress is unchanged; retry shortly.')
        payload={'detail':detail,'code':error.code}
        if error.provider_error:payload['provider_error']=error.provider_error
        if error.code == 'rate_limited':
            payload['limit_scope'] = error.limit_scope
            payload['detail'] = 'The AI provider request or token quota was reached.' + ' Your inputs and saved progress are unchanged.'
            if error.retry_after is not None:
                payload['retry_after'] = error.retry_after
                payload['detail'] += f' Retry after {error.retry_after} seconds.'
            else:
                payload['detail'] += ' Wait for the provider quota to reset before retrying.'
        if error.reason:
            descriptions={
                'schema_validation':'The AI response had missing or invalid fields.',
                'source_quote':'A user-added skill was not supported by the current message.',
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
            if error.violations:payload['diagnostic']['violations']=list(error.violations)
        headers = {'Retry-After': str(error.retry_after)} if error.retry_after is not None else None
        return JSONResponse(payload,status,headers=headers)


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

    @app.post('/api/v1/career/imports/url', response_model=JDPreview, responses=errors, tags=['J06 URL preview'])
    async def url(data: UrlInput, request: Request, account=Depends(authenticated)):
        async with slot(request):
            result = await run_in_threadpool(processor, 'url', data.url.encode('utf-8'), '')
            if len(result['text']) > MAX_JD_TEXT:
                raise HTTPException(422, 'The job description exceeds 8,000 characters. Paste a shorter description; nothing was truncated.')
            return result

    @app.post('/api/v1/career/explorations/cv/document', response_model=Preview, tags=['J08 temporary CV context'])
    @app.post('/api/v1/career/imports/document', response_model=JDPreview, responses=errors, tags=['J07 document preview'],
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
            if request.url.path == '/api/v1/career/imports/document' and len(result['text']) > MAX_JD_TEXT:
                raise HTTPException(422, 'The job description exceeds 8,000 characters. Paste a shorter description; nothing was truncated.')
            return {'kind':'document','source_name':name, **result}

    return app


app = create_app()
