# Coachify

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** Profile, onboarding and account access are implemented. CV supports saved PDF/DOCX extraction, resumable text conversations, source-linked clarification interpretation, corrections, explicit source reconciliation and saved-CV selection. Profile owns manual capability declarations. Career has one automatically saved canonical goal/chat per account, JD extraction and cited five-category Opportunity Intelligence. Public research starts alongside JD extraction; once both finish, chat automatically presents a combined overview with inline fact citations. Follow-up questions can start scoped research. Conversational Career Discovery automatically researches a clear direction, retains bounded private conversation context and keeps chat open during research; its reviewed target still requires explicit final confirmation through the shared goal persistence path. Saved goals use version-checked edits, compact progress polling and lazy evidence reads. See the [Career service](services/career-service/README.md).

Before CV clarification uses the current goal, the user explicitly confirms its exact goal and selection revision. Subsequent changes require confirmation again. Structured goals, research and CV evidence persist in separate MongoDB service databases; temporary Career workflow checkpoints expire after 24 hours independently of durable discovery messages and CV history. Assessment computation, gap analysis and roadmap generation remain planned. Tests use synthetic provider responses; configured provider access is required for live extraction, chat interpretation and research. See [setup](docs/setup.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Account access: email/password accounts with OTP email verification, and revocable 24-hour sessions. Development supports either Mailpit capture or real delivery with Gmail SMTP; production uses authenticated encrypted SMTP.
- AI: Career uses configured Gemini reasoning and Brave public research. CV uses a separately configured OpenAI-compatible API for extraction, conversation routing and clarification interpretation. Preview endpoints make no model calls. Application hosting is not selected.

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
contracts/api/              Profile, CV and Career OpenAPI contracts
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

Use the active `infrastructure/docker/compose.yaml` for Profile, CV and Career. CV owns uploads, provisional extraction, factual clarifications and private conversation history. Career owns the canonical goal, research and the version-bound CV confirmation stamp. An automatically saved goal is not automatically confirmed for clarification. Older reviewed target snapshots remain historical data; the application does not maintain a second active target-selection flow.

Career accesses saved CVs through the authenticated CV API. CV accesses confirmed goal context through Career's API. There is no cross-service database access. Finishing a CV review, extracting skills or confirming a goal does not establish mastery or generate a gap analysis. Keep environment files, credentials, originals and database data out of source control.

For Docker source-code hot reload, see the [development setup](infrastructure/docker/README.md#hot-reload-during-development).
