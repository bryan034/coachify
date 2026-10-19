# Progress dashboard service

Planned framework: Python FastAPI. Public route reservation: `/api/v1/dashboard`.

User stories: D01-D06.

## Responsibility

Stateless aggregation of live roadmap progress, assessed requirements and dated review analysis.

Stateless: no database, repository layer or MongoDB credentials.

## Current status

Structure only. `app/main.py` is a comment-only placeholder, not an ASGI application. There are no endpoints, schemas, database connections, LLM requests, jobs, authentication checks or application logic. No dependencies have been installed or selected in `pyproject.toml`.

## Package responsibilities

- `api/v1`: future HTTP route definitions.
- `schemas`: future request and response definitions.
- `domain`: future business operations.
- `clients`: future calls to other services or external providers.
- `core`: future environment, logging, identity and local configuration utilities.

`tests/` reserves future verification work. `Dockerfile.example` and `.env.example` are inactive templates. No `/internal/v1` endpoint is implemented.
