import os
from anyio import CapacityLimiter
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.api.v1.profile import router
from app.core.auth import auth_settings
from app.api.v1.accounts import router as account_router
from app.repositories.accounts import AccountRepository
from app.repositories.profile import ProfileRepository
from app.core.mail import SmtpMailer, mail_settings
from app.api.v1.capabilities import router as capability_router
from app.repositories.capabilities import CapabilityRepository


def create_app(repository=None, accounts=None, mailer=None, capabilities=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.auth_settings = auth_settings()
        # Attachments call CV, which authenticates back through Profile. Reserve
        # separate capacity so these waits cannot exhaust the auth/DB thread pool.
        app.state.capability_limiter = CapacityLimiter(8)
        client = None
        if repository is None:
            uri = os.getenv("MONGODB_URI")
            if not uri:
                raise RuntimeError("Set MONGODB_URI before starting the profile service.")
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            database = client[os.getenv("MONGODB_DATABASE", "coachify_profile")]
            app.state.repository = ProfileRepository(database)
            app.state.accounts = AccountRepository(database, mailer or SmtpMailer(mail_settings(app.state.auth_settings.environment)))
            app.state.capabilities = CapabilityRepository(database)
        else:
            app.state.repository = repository
            app.state.accounts = accounts
            app.state.capabilities = capabilities or (CapabilityRepository(accounts.accounts.database) if accounts is not None else None)
        try:
            yield
        finally:
            if client is not None:
                client.close()

    app = FastAPI(title="Coachify profile API", version="0.1.0", description="Verified email/password accounts, optional Google, and revocable owner-scoped sessions.", lifespan=lifespan)
    app.include_router(router)
    app.include_router(account_router)
    app.include_router(capability_router)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

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
