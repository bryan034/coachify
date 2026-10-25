"""Read-only CV dependency for J08. Upload/extraction remain separate stories."""
import os
from contextlib import asynccontextmanager
import httpx
from bson import ObjectId
from bson.codec_options import CodecOptions
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool
from app.core.auth import bearer, current_account
from app.schemas.cv import CvSnapshot, CvSummary, CvList, object_id


def create_app(database=None, profile_client=None):
    @asynccontextmanager
    async def lifespan(app):
        mongo = None
        app.state.db = database
        if app.state.db is None and os.getenv('MONGODB_URI'):
            mongo = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
            app.state.db = mongo[os.getenv('MONGODB_DATABASE', 'coachify_ingestion')]
        async with httpx.AsyncClient(base_url=os.getenv('PROFILE_SERVICE_URL','http://profile-service:8000'),
                timeout=5, trust_env=False, follow_redirects=False) as client:
            app.state.profile_client = profile_client or client
            yield
        if mongo is not None: mongo.close()

    app = FastAPI(title='Coachify CV read API', version='0.1.0', lifespan=lifespan)

    @app.middleware('http')
    async def private(request, call_next):
        result = await call_next(request)
        result.headers['Cache-Control'] = 'no-store'
        return result

    @app.exception_handler(ValidationError)
    async def invalid_record(request, error):
        return JSONResponse({'detail':'The saved CV needs review before it can be used.'},503)

    @app.exception_handler(PyMongoError)
    async def unavailable(request, error):
        return JSONResponse({'detail':'Saved CVs are unavailable. Please retry.'},503)

    async def owner(request: Request, credentials=Depends(bearer)):
        return await current_account(request, credentials)

    def collection(request):
        if request.app.state.db is None: raise HTTPException(503,'CV storage is not configured.')
        return request.app.state.db.get_collection('cvs', codec_options=CodecOptions(tz_aware=True))

    @app.get('/health', include_in_schema=False)
    async def health(): return {'status':'ok'}

    @app.get('/api/v1/cv', response_model=CvList, tags=['J08 saved CV context'])
    async def list_cvs(request: Request, account=Depends(owner)):
        rows = await run_in_threadpool(lambda:list(collection(request).find({'user_id':account},{'_id':1,'user_id':1,'file_name':1,'extraction_status':1,'extraction_version':1,'version':1}).sort('created_at',-1).limit(50)))
        return {'items':[CvSummary.model_validate(row).model_dump(mode='json',by_alias=True) for row in rows]}

    @app.get('/api/v1/cv/{identifier}', response_model=CvSnapshot, tags=['J08 saved CV context'])
    async def get_cv(identifier: str, request: Request, account=Depends(owner)):
        try: object_id(identifier)
        except ValueError: raise HTTPException(404,'CV was not found.') from None
        row = await run_in_threadpool(collection(request).find_one, {'_id':ObjectId(identifier),'user_id':account})
        if row is None: raise HTTPException(404,'CV was not found.')
        return CvSnapshot.model_validate(row)
    return app


app=create_app()
