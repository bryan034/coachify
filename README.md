# Coachify

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** Profile, onboarding, email/password and OTP are implemented. Career Goal now has one automatically saved goal/chat per account. A validated job identity starts public research alongside full JD extraction. The chat shows temporary observed progress and waits for JD extraction plus completed research before Gemini writes one combined, cited overview; follow-up questions can start scoped Brave research; saved goal cards update as extraction finishes. Five-category Opportunity Intelligence adds cited interviews, internship experience, career progression/conversion salary, historical conversion rates and company/team culture through Gemini/Brave; guided chat supports refinements, and a CV assessment link uses owner-scoped saved-data checks. New JDs replace the live conversation. Conversational Career Discovery collects all research context (accepting explicit unsure/skip answers) before automatically researching a direction, retains bounded conversation context, and keeps chat open during research; its reviewed target still requires explicit confirmation through the shared goal persistence path. The current goal is returned once and edited in place with version checks; lightweight progress polling and lazy evidence reads avoid repeated source payloads. Structured goals and research persist in MongoDB, with temporary 24-hour workflow checkpoints. Dedicated CV extraction, gap analysis and roadmaps remain planned. See [setup](docs/setup.md) and [Career service](services/career-service/README.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Account access: email/password accounts with OTP email verification, and revocable 24-hour sessions. Development supports either Mailpit capture or real delivery with Gmail SMTP; production uses authenticated encrypted SMTP.
- AI provider: Gemini 3.5 Flash Lite powers all reasoning, extraction and chat; preview endpoints do not call AI. Application hosting is not selected.

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

Use the active `infrastructure/docker/compose.yaml` for the implemented profile slice. Files ending in `.example` remain inactive planning templates. Career supports optional-CV exploration, importance review, advisory skill generation and confirmed goals with scoped MongoDB persistence. Brave API adapters and versioned interview research are implemented; live calls require your configured credentials/access. CV exposes owner-scoped reads; dedicated upload/extraction remains planned. Temporary URL/document previews have no database writes or AI calls; explicit JD extraction and approved review saves persist structured data only. Other services retain source placeholders. Profile and preview API contracts are implemented; remaining endpoint contracts are shells. Keep real environment files, credentials, CV uploads and database data out of source control.

For Docker source-code hot reload, see the [development setup](infrastructure/docker/README.md#hot-reload-during-development).
