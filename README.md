# Coachify

Career-readiness planner for users in Singapore, including students, National Service personnel, employed and unemployed users.

**Status:** P01–P16 background, planning, account access and onboarding are implemented. CV supports saved PDF/DOCX extraction, claim-scoped clarification interpretation, partial-date corrections, explicit source reconciliation, manual-capability links and saved-CV selection. Extraction and interpretation need a configured provider. Career saves reviewed target skills and qualification/date conditions with explicit confirmation/selection. CV supplies a target-bound input contract; actual assessment admission, stale-result tracking, AI target generation, exploration chat and gap/roadmap generation remain planned. Tests use synthetic model responses. The local setup uses email/password and OTP. See [setup instructions](docs/setup.md).

## Stack

- Frontend: Next.js App Router, React, and TypeScript; Node.js server runtime.
- Backend: six independently deployed Python FastAPI services.
- Gateway: NGINX reverse proxy and request routing.
- Database: MongoDB, with separate databases and credentials for data-owning services.
- Development infrastructure: Docker Compose; optional local MongoDB container.
- Proposed production database: MongoDB Atlas, external to the application containers.
- Account access: email/password accounts with OTP email verification, and revocable 24-hour sessions. Development supports either Mailpit capture or real delivery with Gmail SMTP; production uses authenticated encrypted SMTP.
- AI: server-side Groq-compatible CV extraction adapter; optional provider configuration is required. Automated checks use synthetic fixtures, not live inference. Application hosting is not selected.

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

Use the active `infrastructure/docker/compose.yaml` for Profile, CV and Career. Files ending in `.example` remain inactive planning templates. Career keeps URL/document previews transient and saves reviewed structured targets in its own database; it makes no AI calls. Roadmap, dashboard and review services retain source placeholders. CV handoff includes versioned sources and declarations; it does not generate gap analysis or silently regenerate existing results. Keep real environment files, credentials, CV uploads and database data out of source control.
