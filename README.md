# elo

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** Profile, onboarding and account access are implemented. CV supports saved PDF/DOCX extraction, resumable text conversations, source-linked clarification interpretation, corrections, explicit source reconciliation, saved-CV selection and deletion. Skills Profile opens on a summary with upload-to-review navigation and manual-chat entry. CV review derives source-specific skill baselines with independent three-question budgets per project/experience and backend-only insufficient-evidence tracking. Profile owns structured manual skills intake and reviewed capability declarations. Career has one automatically saved canonical goal/chat per account, JD extraction and cited five-category Opportunity Intelligence. Cloud public research starts alongside JD extraction; local R1 starts it after full extraction supplies the role metadata. Once both finish, chat automatically presents a combined overview with inline fact citations. Follow-up questions can start scoped research. Jobs fetches Singapore listings live from configured employer boards for search with filters and self-reported application tracking; users apply on employers' sites. Conversational Career Discovery collects all research context (accepting explicit unsure/skip answers) before automatically researching a direction, retains bounded private conversation context and keeps chat open during research; its validated results and refinements automatically update the current Career Goal through the shared persistence path, without a chat save action. Saved goals use version-checked edits, compact progress polling and lazy evidence reads. See the [Career service](services/career-service/README.md).

Before CV clarification uses the current goal, the user explicitly confirms its exact goal and selection revision. Subsequent changes require confirmation again. Structured goals, research and CV evidence persist in separate MongoDB service databases; temporary Career workflow checkpoints expire after 24 hours independently of durable discovery messages and CV history. A separate Assessment service now compares versioned evidence independently of Roadmap, including saved manual Profile evidence when no CV is selected, while Roadmap hosts saved adviser chat, user-reviewed proposals, daily workload and task progress. Both require their own database and model configuration; live-provider quality is not established by synthetic tests. Tests use synthetic provider responses; configured provider access is required for live extraction, chat interpretation and research. See [setup](docs/setup.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: eight independently deployed Python FastAPI service boundaries.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Account access: email/password accounts with OTP email verification, emailed-code password recovery, and revocable 24-hour sessions. Development supports either Mailpit capture or real delivery with Gmail SMTP; production uses authenticated encrypted SMTP.
- AI: Model calls use the OpenAI Python SDK. The public deployment template configures OpenRouter for Career, CV, Assessment and Roadmap using one server-side key and a shared model setting; other compatible providers remain configurable. Career public research uses a separate Brave or DeepSeek Search integration. CV extraction uses schema-constrained output and validated repair. Preview endpoints make no model calls. See [model setup](docs/setup.md#career-model-and-search-configuration).

## Repository layout

```text
apps/frontend/               Next.js frontend structure
services/profile-service/    Canonical student profile
services/cv-service/         CV extraction and clarification
services/career-service/     Career goals, JD interpretation and public research
services/assessment-service/ Private versioned skill comparisons
services/jobs-service/       Singapore job search and application tracking
services/roadmap-service/    Study settings, validated LLM roadmaps, timed sessions, adviser chat and progress
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

The adviser implementation and remaining limits are described in [Roadmap](services/roadmap-service/SPEC.md). [Set up the new services](docs/setup.md#assessment-and-roadmap-adviser) before starting the updated Compose stack.

For Docker source-code hot reload, see the [development setup](infrastructure/docker/README.md#hot-reload-during-development).

Existing installations: read the [rename and data migration notes](docs/setup.md#renamed-installations) before rebuilding; the renamed defaults do not migrate existing volumes.
