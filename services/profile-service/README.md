# Student profile service

Planned framework: Python FastAPI. Public route reservation: `/api/v1/profile`.

User stories: P01-P03 and post-ingestion profile corrections.

## Responsibility

Canonical education, work experience, personal contributions, capabilities and profile versions.

Planned MongoDB database: `coachify_profile`; service-scoped credentials only.

## Current status

Structure only. `app/main.py` is a comment-only placeholder, not an ASGI application. There are no endpoints, schemas, database connections, LLM requests, jobs, authentication checks or application logic. No dependencies have been installed or selected in `pyproject.toml`.

## Package responsibilities

- `api/v1`: future HTTP route definitions.
- `schemas`: future request and response definitions.
- `domain`: future business operations.
- `clients`: future calls to other services or external providers.
- `core`: future environment, logging, identity and local configuration utilities.
- `repositories`: future access to this service's MongoDB database only.

`tests/` reserves future verification work. `Dockerfile.example` and `.env.example` are inactive templates. No `/internal/v1` endpoint is implemented.
