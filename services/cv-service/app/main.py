"""Saved, owner-scoped CV workflow; synthetic extraction exists only in tests."""
import asyncio
from contextlib import asynccontextmanager, AsyncExitStack, suppress
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.api.v1.cv import router
from app.api.v1.conversations import router as conversation_router
from app.clients.conversation import ConversationRouter
from app.conversation.service import ConversationService
from app.clients.extractor import Extractor
from app.clients.interpretation import Interpreter
from app.clients.career import CareerTargetProvider, service_url
from app.core.config import Settings
from app.domain.errors import CvError
from app.domain.service import CvService
from app.repositories.cv import CvRepository
from app.repositories.files import FileStore
from app.workers.ingestion import IngestionWorker


class BodyLimit:
    def __init__(self, app, maximum): self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        maximum = self.maximum + 64 * 1024 if scope['path'].endswith('/uploads') else 32 * 1024
        headers = dict(scope.get('headers', []))
        try: length = int(headers.get(b'content-length', b'0'))
        except ValueError: length = maximum + 1
        if length < 0 or length > maximum:
            return await JSONResponse({'detail': 'This request exceeds the configured upload/text limit.'}, 413,
                                      headers={'Cache-Control': 'no-store'})(scope, receive, send)
        size = 0
        async def limited():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > maximum: raise HTTPException(413, 'This request exceeds the configured upload/text limit.')
            return message
        await self.app(scope, limited, send)


def create_app(repository=None, profile_client=None, extractor=None, settings=None, target_provider=None,
               parser=None, start_worker=True, interpreter=None, chat_provider=None):
    settings = settings or Settings.environment()
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            client = None
            if repository is None:
                uri = os.getenv('MONGODB_URI')
                if not uri: raise RuntimeError('Set MONGODB_URI before starting the CV service.')
                client = MongoClient(uri, serverSelectionTimeoutMS=5000)
                stack.callback(client.close)
                app.state.repository = CvRepository(client[os.getenv('MONGODB_DATABASE', 'elo_cv')])
            else: app.state.repository = repository
            app.state.profile_client = profile_client or await stack.enter_async_context(httpx.AsyncClient(
                base_url=os.getenv('PROFILE_SERVICE_URL', 'http://profile-service:8000'), timeout=5,
                follow_redirects=False, trust_env=False))
            app.state.settings = settings
            app.state.extractor = extractor or Extractor()
            app.state.interpreter = interpreter or Interpreter()
            app.state.files = FileStore(settings.storage_path)
            app.state.service = CvService(app.state.repository, app.state.files, settings)
            app.state.conversations = ConversationService(app.state.service, chat_provider or ConversationRouter())
            if target_provider is not None: app.state.target_provider = target_provider
            else:
                career_client = await stack.enter_async_context(httpx.AsyncClient(
                    base_url=service_url(os.getenv('CAREER_SERVICE_URL', 'http://career-service:8000')),
                    timeout=5, follow_redirects=False, trust_env=False))
                app.state.target_provider = CareerTargetProvider(career_client)
            options = {'parser': parser} if parser else {}
            app.state.worker = IngestionWorker(app.state.repository, app.state.files, settings, app.state.extractor,
                capacity=app.state.service.capacity, model_usage=app.state.service.model_usage, **options)
            task = asyncio.create_task(app.state.worker.run()) if start_worker else None
            try: yield
            finally:
                await app.state.conversations.close()
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError): await task

    app = FastAPI(title='elo CV API', version='0.1.0', lifespan=lifespan,
                  description='C01–C09 saved CV upload, review, source corrections, clarification and explicit versioned selection.')
    app.add_middleware(BodyLimit, maximum=settings.max_file_bytes)
    app.include_router(conversation_router)
    app.include_router(router)

    @app.get('/health', include_in_schema=False)
    async def health(): return {'status': 'ok'}

    @app.middleware('http')
    async def private(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': 'Enter valid fields within the documented limits; keep your draft and correct the input.'}, 422)

    @app.exception_handler(CvError)
    async def domain_error(request, exc):
        content = {'detail': exc.detail}
        if getattr(exc, 'code', None): content['code'] = exc.code
        return JSONResponse(content, exc.status)

    @app.exception_handler(PyMongoError)
    async def storage_error(request, exc):
        return JSONResponse({'detail': 'CV storage is unavailable. Keep your inputs and retry.'}, 503)

    return app


app = create_app()
