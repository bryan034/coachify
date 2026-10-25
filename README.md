# Coachify

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** P01–P16 education, planning preferences, email/password access, email verification and initial onboarding are implemented with profile persistence and local/international school snapshots. Career Goal includes one chat page with J08 adaptive optional-CV exploration and J09 goal confirmation/persistence. J01/J06/J07 previews remain transient; selecting a JD starts structured AI extraction and saved review on that same page. J02–J04 now save editable role/skill/condition reviews in MongoDB, restore them after reload and explicitly confirm structured goals. A small versioned registry maps known skills; unfamiliar skills keep analysis pending. The first workspace UI is integrated; unimplemented features use empty states and disabled actions. The current local setup uses email/password and OTP; no Google OAuth credentials are needed. See [setup instructions](docs/setup.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Account access: email/password accounts with OTP email verification, and revocable 24-hour sessions. Development supports either Mailpit capture or real delivery with Gmail SMTP; production uses authenticated encrypted SMTP.
- AI provider: Groq powers explicit exploration turns; preview endpoints do not call AI. Application hosting is not selected.

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
contracts/api/              Profile OpenAPI contract and future service shells
docs/                       Current design and development guidance
outputs/                    Earlier architecture deliverables
work/                       Ignored working files, not application source
```

## Read first

- [Current architecture](docs/architecture/README.md)
- [Service ownership and story mapping](docs/architecture/service-boundaries.md)
- [API route plan](docs/api/README.md)
- [Run the application](docs/setup.md)
- [Tests and CI](docs/testing.md)
- [Frontend structure](apps/frontend/README.md)
- [Docker template](infrastructure/docker/README.md)

The current documentation under `docs/` reflects the Next.js and MongoDB decisions. Earlier files under `outputs/` may show the previously proposed PostgreSQL architecture and are retained as historical deliverables.

## Implementation scope

Use the active `infrastructure/docker/compose.yaml` for the implemented profile slice. Files ending in `.example` remain inactive planning templates. Career supports optional-CV exploration and confirmed goals with scoped MongoDB persistence. CV exposes owner-scoped reads; dedicated upload/extraction remains planned. Temporary URL/document previews have no database writes or AI calls; explicit JD extraction and approved review saves persist structured data only. Other services retain source placeholders. Profile and preview API contracts are implemented; remaining endpoint contracts are shells. Keep real environment files, credentials, CV uploads and database data out of source control.

For Docker source-code hot reload, see the [development setup](infrastructure/docker/README.md#hot-reload-during-development).
