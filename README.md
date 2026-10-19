# Coachify

Structure-only scaffold for a personalised career-readiness planner for university students in Singapore.

**Status:** directories, source placeholders, configuration templates, and architecture documentation only. There are no implemented UI components, HTTP endpoints, authentication flows, database connections, LLM integrations, schedulers, or application workers. Dependencies have not been installed. This is not yet a runnable application.

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Google sign-in: planned; provider, session integration, and backend token validation are not implemented.
- AI provider and application hosting: not selected.

## Repository layout

```text
apps/frontend/               Next.js frontend structure
services/profile-service/    Canonical student profile
services/cv-service/         CV extraction and clarification
services/career-service/     Job interpretation and capability assessment
services/roadmap-service/    Plans, tasks, progress history, and revisions
services/dashboard-service/ Stateless progress aggregation
services/review-service/    Pace reviews and scheduling
infrastructure/gateway/     NGINX configuration template
infrastructure/mongodb/     Local database and Atlas guidance
infrastructure/docker/      Compose deployment template
contracts/api/              Empty OpenAPI contracts for future endpoints
docs/                       Current design and development guidance
outputs/                    Earlier architecture deliverables
work/                       Ignored working files, not application source
```

## Read first

- [Current architecture](docs/architecture/README.md)
- [Service ownership and story mapping](docs/architecture/service-boundaries.md)
- [API route plan](docs/api/README.md)
- [Development and implementation status](docs/development/README.md)
- [Frontend structure](apps/frontend/README.md)
- [Docker template](infrastructure/docker/README.md)

The current documentation under `docs/` reflects the Next.js and MongoDB decisions. Earlier files under `outputs/` may show the previously proposed PostgreSQL architecture and are retained as historical deliverables.

## Scaffold conventions

- `.py`, `.tsx`, and `.css` source placeholders contain comments only. Empty Python package markers establish future import boundaries.
- `package.json` and `pyproject.toml` files contain project metadata only. Runtime dependencies and lockfiles will be added when the runnable skeleton is implemented.
- Files ending in `.example`, including Dockerfiles, are illustrative configuration templates. They do not start Coachify.
- The OpenAPI contracts intentionally have empty `paths` objects; their existence does not imply endpoints have been implemented.
- Real environment files, credentials, CV uploads, and database data must stay out of source control.
- No Git repository has been initialised or remote configured by this scaffold.
