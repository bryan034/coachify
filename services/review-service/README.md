# Review and scheduling service

Planned framework: Python FastAPI. Public route reservation: `/api/v1/reviews and /api/v1/review-schedules`.

User stories: A01 orchestration and S01-S06.

## Responsibility

Manual/scheduled reviews, pace analysis, next execution times and revision approval preferences.

Planned MongoDB database: `coachify_review`; service-scoped credentials only.

## Current status

Structure only. `app/main.py` is a comment-only placeholder, not an ASGI application. There are no endpoints, schemas, database connections, LLM requests, jobs, authentication checks or application logic. No dependencies have been installed or selected in `pyproject.toml`.

## Package responsibilities

- `api/v1`: future HTTP route definitions.
- `schemas`: future request and response definitions.
- `domain`: future business operations.
- `clients`: future calls to other services or external providers.
- `core`: future environment, logging, identity and local configuration utilities.
- `repositories`: future access to this service's MongoDB database only.
- `scheduling`: reserved for scheduling responsibilities; no implementation.
- `workers`: future durable background operation execution; no queue technology is selected.

`tests/` reserves future verification work. `Dockerfile.example` and `.env.example` are inactive templates. No `/internal/v1` endpoint is implemented.
