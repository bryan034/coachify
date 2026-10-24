# Coachify

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** P01–P03 education entry and P07/P08 occupational status/category are implemented with profile persistence and local/international school snapshots. Other product features remain scaffolded. Google sign-in requires your Web Client ID. See [setup instructions](docs/development/profile-setup.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Google sign-in: JavaScript button and FastAPI ID-token verification implemented for the profile slice; real credentials must be configured. Tokens are kept in memory, not a persistent app session.
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

## Implementation scope

Use the active `infrastructure/docker/compose.yaml` for the P07/P08 slice. Files ending in `.example` remain inactive planning templates. Other services retain source placeholders. The profile API contract is implemented; remaining contracts are shells. Keep real environment files, credentials, CV uploads and database data out of source control.
