import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.api.v1.profile import router
from app.core.auth import auth_settings
from app.repositories.profile import ProfileRepository


def create_app(repository=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.auth_settings = auth_settings()
        client = None
        if repository is None:
            uri = os.getenv("MONGODB_URI")
            if not uri:
                raise RuntimeError("Set MONGODB_URI before starting the profile service.")
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            app.state.repository = ProfileRepository(client[os.getenv("MONGODB_DATABASE", "coachify_profile")])
        else:
            app.state.repository = repository
        try:
            yield
        finally:
            if client is not None:
                client.close()

    app = FastAPI(title="Coachify profile API", version="0.1.0", description="Google bearer authentication by default. Explicit local_test mode uses a fixed server identity only in development; see docs/development/profile-setup.md.", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo supplied values (including non-finite numbers) into JSON errors.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]})

    @app.exception_handler(PyMongoError)
    async def database_error(request: Request, exc: PyMongoError):
        return JSONResponse(status_code=503, content={"detail": "Profile storage unavailable; keep your inputs and retry."})

    return app


app = create_app()
