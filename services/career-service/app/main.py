"""Temporary source previews and owner-scoped reviewed career targets."""
import asyncio
import os
from contextlib import asynccontextmanager
from anyio import CapacityLimiter
from pymongo import MongoClient
from pathlib import PurePosixPath
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from app.core.auth import bearer, current_account
from app.api.v1.targets import router as targets_router
from app.domain.preview import run_preview
from app.schemas.preview import MAX_BODY, MAX_FILE, Preview, UrlInput, ImportErrorView


class BodyLimit:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        target_request = scope['path'] == '/api/v1/career/targets' or scope['path'].startswith('/api/v1/career/targets/')
        maximum = 256 * 1024 if target_request else MAX_BODY if scope['path'].endswith('/document') else 16 * 1024
        limit_message = 'Career target requests must be at most 256 KiB.' if target_request else 'The request exceeds the upload limit. Choose a file up to 10 MiB.'
        headers = dict(scope.get('headers', []))
        try: declared = int(headers.get(b'content-length', b'0'))
        except ValueError: declared = maximum + 1
        if declared < 0 or declared > maximum:
            return await JSONResponse({'detail':limit_message},413,
                headers={'Cache-Control':'no-store'})(scope, receive, send)
        size = 0
        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > maximum:
                raise HTTPException(413, limit_message)
            return message
        await self.app(scope, limited_receive, send)


def create_app(profile_client=None, processor=run_preview, target_repository=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.slots = asyncio.Semaphore(2)
        app.state.target_limiter = CapacityLimiter(8)
        app.state.target_repository = target_repository
        app.state.target_database = None
        mongo = None
        if target_repository is None and os.getenv('MONGODB_URI'):
            mongo = MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=3000,
                                connectTimeoutMS=3000, socketTimeoutMS=5000)
            app.state.target_database = mongo[os.getenv('MONGODB_DATABASE', 'coachify_career')]
        try:
            if profile_client is not None:
                app.state.profile_client = profile_client
                yield
            else:
                async with httpx.AsyncClient(base_url=os.getenv('PROFILE_SERVICE_URL', 'http://profile-service:8000'),
                                             timeout=5, follow_redirects=False, trust_env=False) as client:
                    app.state.profile_client = client
                    yield
        finally:
            if mongo is not None: mongo.close()

    app = FastAPI(title='Coachify Career API', version='0.1.0', lifespan=lifespan,
        description='Temporary source previews and immutable user-reviewed targets with explicit confirmation and selection. No AI interpretation.')
    app.add_middleware(BodyLimit)
    app.include_router(targets_router)

    @app.middleware('http')
    async def no_storage(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        if request.url.path == '/api/v1/career/targets' or request.url.path.startswith('/api/v1/career/targets/'):
            return JSONResponse({'detail': 'Review the target fields and limits. Job skills and conditions need exact source excerpts. Conditions need specific subject phrases supported by their excerpt; duplicate skills or conditions are not allowed.'}, 422)
        return JSONResponse({'detail':'Enter one valid URL of at most 2,048 characters.'},422)

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
