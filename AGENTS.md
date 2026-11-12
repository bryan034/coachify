# AGENTS.md — elo

elo is a career-readiness planner for users in Singapore. This file is the working map for agents: rules, architecture, where things live, and how to verify. Detail lives in linked docs; verify against code before relying on any doc.

## Working rules

- Use the current checkout. Check Git status and branch before editing; preserve unrelated contributors' changes. Never push directly to `main`; if on `main`, suggest a new branch and implement on a separate one.
- Follow the requested scope and existing conventions. Avoid unrelated refactoring or new dependencies. Discuss material architecture changes, breaking APIs and destructive migrations before proceeding unless already authorised.
- Do not invent requirements or present placeholders as implemented features. Label unimplemented work.
- Commit or push only when asked.

## Architecture at a glance

Browser → **NGINX gateway** (`127.0.0.1:${GATEWAY_PORT:-8080}`) → Next.js frontend or a FastAPI service by `/api/v1/<prefix>`. Each data-owning service has its own MongoDB database and credentials on a private `database` network; services call each other only over HTTP on the private `backend` network (`http://<name>-service:8000`). Compose project name: `elo-profile`.

| Service (folder under `services/`) | API prefix | Database | Status | Owns |
|---|---|---|---|---|
| `profile-service` | `/api/v1/profile` | `elo_profile` | Live | Accounts, email/OTP, sessions, onboarding, background, planning defaults, manual skill declarations |
| `cv-service` | `/api/v1/cv` | `elo_ingestion` | Live | Saved CVs/uploads (volume `cv_uploads`), extraction, clarification, private CV conversations, CV selection |
| `career-service` | `/api/v1/career` | `elo_career` | Live | Canonical goal + chat, JD extraction, public research, discovery, Opportunity Intelligence, CV confirmation stamp |
| `assessment-service` | `/api/v1/assessments` | `elo_assessment` | Live | Immutable versioned skill-gap comparisons |
| `roadmap-service` | `/api/v1/roadmaps` | `elo_roadmap` | Live | Study settings, adviser chat, LLM roadmaps, timed sessions, progress |
| `jobs-service` | `/api/v1/jobs` | `elo_jobs` | Live | Live Singapore employer-board search, self-reported application tracking |
| `dashboard-service` | `/api/v1/dashboard` | none (stateless) | Backend only | Progress aggregation from Roadmap/Assessment |
| `review-service` | `/api/v1/reviews`, `/api/v1/review-schedules` | — | Scaffold | Planned pace reviews; not routed by the gateway (404); the only service allowed an empty test suite |

Service-to-service dependencies (read through APIs only, forwarding the owner's revocable bearer):

- CV → Profile (session, declarations), CV → Career (confirmed goal for clarification)
- Career → Profile (session/onboarding), Career → CV (saved CV evidence)
- Assessment → Profile/CV/Career; Roadmap → Assessment/Profile/CV/Career; Dashboard → Roadmap/Assessment; Jobs → Profile only
- Full table and rationale: [service boundaries](docs/architecture/service-boundaries.md). Private `/internal/v1` routes are never exposed by the gateway.

Other moving parts: `mongodb` (local container, Mongo 8.2) with one-shot `mongodb-*-init` containers running `infrastructure/mongodb/init-*.js`; `mailpit` (development profile) for captured email. Production DB proposal is MongoDB Atlas, external to containers.

AI: all model calls use the OpenAI Python SDK, routed to OpenRouter by default (shared `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`, per-service overrides `CAREER_/CV_/ASSESSMENT_/ROADMAP_LLM_*`). Career public research uses Brave (test) or DeepSeek Search (production). Tests use synthetic providers; live-model quality is unverified.

## Where things are

```text
apps/frontend/               Next.js 16 App Router, React 19, TS. Routes: src/app/{(auth),(setup),(workspace)}
  src/features/<domain>/     Feature UI/logic (assessment, auth, calendar, career, career-assessment,
                             cv-ingestion, dashboard, jobs, profile, reviews, roadmap)
  src/lib/api/               Typed API clients per service (keep in sync with contracts/)
  src/styles/ + public/      elo theme tokens (elo-theme.css), bundled fonts, brand assets
  tests/                     Playwright e2e; unit tests (Vitest) sit beside source as *.test.ts(x)
services/<name>-service/     FastAPI app in app/ (api, core, domain, repositories, schemas, clients,
                             workflows/workers where relevant); tests in tests/; pyproject.toml
  README.md                  Short: purpose + endpoints by capability.  SPEC(IFICATION).md: detailed spec
packages/elo-shared/         Shared Python lib `elo_shared` (skill identities/groups, model SDK/errors,
                             dates, runtime, API-contract helpers). Installed editable by every service
contracts/api/               OpenAPI per service (*.yaml) + JSON Schemas in models/. Source of truth for schemas
infrastructure/
  docker/                    compose.yaml (active stack), compose.dev.yaml (hot reload), compose.test.yaml,
                             compose.career-test.yaml, dev-shell.sh (`dc` helper), .env.example, README.md
  gateway/nginx.conf         Route table and per-route body-size limits
  mongodb/                   init-*.js database/user bootstrap, Atlas guidance
  testing/                   Synthetic fixtures/smoke scripts (career, CV, planner)
docs/                        App-wide docs only: setup.md, testing.md, api/README.md, architecture/ (+ diagrams/),
                             design/ (visual system, canvas)
outputs/                     Historical deliverables (may describe old PostgreSQL design) — not current
work/                        Git-ignored scratch/reports — not source
.github/workflows/ci.yml     CI definition
```

Key documents (read only what the task needs): [README](README.md) · [architecture](docs/architecture/README.md) · [service boundaries](docs/architecture/service-boundaries.md) · [API route map](docs/api/README.md) · [setup](docs/setup.md) · [testing](docs/testing.md) · [frontend](apps/frontend/README.md) · [design](docs/design/README.md) · [Docker](infrastructure/docker/README.md) · [gateway](infrastructure/gateway/README.md) · per-service `README.md`/`SPEC.md`.

Stale items to ignore: `*.egg-info` dirs (including `coachify_*` names from before the rename), `elo-mongo-8.0-backup.tgz`, `.claude/worktrees`. Do not treat them as current.

## Architecture and safety rules

- Follow [service boundaries](docs/architecture/service-boundaries.md). Keep domain logic in backend services; the frontend only displays and calls APIs. Access another service's data through its API, never its database.
- For CV, JD/skills-analysis or roadmap changes, consult the [collections](docs/architecture/diagrams/mongodb_collections_uml.mmd), [embedded objects](docs/architecture/diagrams/mongodb_embedded_objects_uml.mmd) and [service architecture](docs/architecture/diagrams/dockerised-mvp.puml) diagrams. Reconcile with code and contracts; update affected diagrams when services change.
- Skill identity is `canonical_skill_id`; display categories come from `elo_shared.skill_groups`, are derived on read, and are never stored or compared.
- Keep schemas, OpenAPI contracts (`contracts/api/`), backend schemas and frontend types in step. Contract tests compare full generated OpenAPI documents.
- Enforce authentication, ownership and input validation in the backend. Handle failures, retries and concurrent updates (version/CAS checks) without losing data.
- Adding or changing a route: update the service, `infrastructure/gateway/nginx.conf` (route and body limit), `contracts/api/`, the service README, `docs/api/README.md`, and the frontend client in `src/lib/api/`.
- Treat uploads, external content and model output as untrusted; validate before use or storage. Keep secrets and personal data out of Git, bundles, logs and fixtures; use synthetic test data. Keep databases and internal APIs private and credentials out of images.

## Configuration

- Centralise all user-configurable deployment variables in `infrastructure/docker/.env`. Document every active variable in `infrastructure/docker/.env.example` with safe defaults and blank secrets; update the template and the relevant Compose injection whenever configuration changes. No root-level or service-specific env files. Fixed internal wiring (service URLs, Mongo URIs/databases, upload paths) stays in Compose; inject each setting only into services that need it.
- Agents may read, edit and validate the public `.env.example`. Never read, edit, load or indirectly inspect private env files (including `infrastructure/docker/.env`) or their contents. Give the user instructions for private values; use explicit synthetic settings and isolated resources for verification.

## Run and verify

Tooling: Node.js 24, Python 3.12 (pinned in `.python-version` and CI; the system `python3` may be newer, so create venvs with 3.12), Docker Compose. No linter or formatter is configured; follow `.editorconfig` (LF, 2-space indent, 4 for Python) and match surrounding code.

```sh
# Stack (from repo root; the user supplies the private .env)
source infrastructure/docker/dev-shell.sh      # defines `dc` = compose + dev hot-reload override
dc up -d --build                               # gateway at http://127.0.0.1:8080

# Frontend (from repo root)
npm ci
npm run typecheck --workspace apps/frontend
npm run test --workspace apps/frontend         # Vitest
npx playwright install chromium && npm run test:e2e --workspace apps/frontend

# Backend (per service, from services/<name>-service)
python -m pip install -e ../../packages/elo-shared -e '.[test]'
python -m pytest
```

- Profile, CV and Career integration tests need a disposable MongoDB (`MONGODB_TEST_URI`); ordinary unit tests do not. Career needs its tiktoken tokenizer cache (see CI). Full-stack browser journeys and fixtures: [testing](docs/testing.md), `compose.test.yaml`, `infrastructure/testing/`.
- CI (`.github/workflows/ci.yml`) runs frontend typecheck/unit, Playwright, a backend matrix over all eight services, shared-package tests (via the assessment job), and Mongo integration jobs. Run the equivalent for what you touched. Changes to `elo-shared` affect every service: run more than one service's tests.
- For logic changes, add meaningful coverage and keep fixing/rerunning relevant tests until they pass. Never remove, skip or weaken valid tests to get a pass; report blockers honestly. Report exact current results, not historical totals.
- Review the final diff for unintended changes and secrets. Report changes, checks actually run and remaining limitations.

## Conventions

- Backend: FastAPI + Pydantic schemas; repositories wrap Mongo access; clients wrap calls to other services; long work runs in workers/workflows (LangGraph in CV and Career). Follow the layout of the neighbouring service.
- Frontend: feature-folder structure; use the elo theme tokens (no ad-hoc colours); no runtime font requests; unimplemented actions show empty states and make no API calls.
- Frontend env: `GOOGLE_CLIENT_ID` is public and used in the build; no secret may reach a browser bundle.
- Product decisions already made (see memory/design docs): commercial product, Singapore first, users apply on employers' sites (Jobs never submits applications), no Adzuna.

## Git workflow

- Branch from `main` as `feat/<topic>`, `fix/<topic>` or `chore/<topic>`; open PRs into `main` (CI runs on PRs, pushes to `main` and merge queue).
- Commit subjects are short imperative sentences in sentence case, no type prefix (e.g. "Keep partly verified CV extractions and flag unverified sections"). Keep commits focused.

## Gotchas

- Python 3.12 and newer print different HTTP status phrases for 413/422; Assessment/Roadmap contract tests fix them explicitly. Do not regenerate OpenAPI snapshots on another interpreter without checking.
- CI Mongo jobs pin `ubuntu-22.04` and `mongo:8.2` because `mongo:8.0` refuses to start on Linux kernels 6.19+ (see `docs/testing.md`).
- Career needs the `o200k_harmony` tiktoken encoding cached before network-isolated tests (`TIKTOKEN_CACHE_DIR`).
- Uploads: gateway limit is 11 MB on CV/JD document routes while `CV_MAX_FILE_BYTES` is 10 MiB; change both together.
- Existing installs keep old private env values and volumes; changing `.env.example` does not change a private `.env`, and renamed defaults do not migrate volumes (see `docs/setup.md#renamed-installations`).
- Frontend tests run against synthetic fixtures; unavailable services render empty states rather than errors.

## Debugging

- Logs: `dc logs -f <service>` (after `source infrastructure/docker/dev-shell.sh`). Captured email: Mailpit UI on `MAILPIT_PORT` (default 8025) with the `development` profile.
- Inspect data only through service APIs or a disposable Mongo started for tests; never point tests or scripts at a personal database or inspect the private `.env`.
- Reset local data: `dc down` keeps volumes; removing volumes deletes accounts, CVs and goals, so ask the user first.

## Glossary

- **Career goal**: the one autosaved canonical goal and chat per account (Career). **Confirmation stamp**: the user's explicit confirmation of an exact goal and selection revision, required before CV clarification uses the goal.
- **Skills Profile** (`/cv`): summary of CV and manual skill evidence. **Manual declarations**: Profile-owned skills the user states without a CV.
- **Opportunity Intelligence**: Career's cited five-category research on a role. **Discovery**: conversational flow that researches a career direction and updates the goal.
- **Assessment**: immutable, versioned comparison of CV/profile evidence against goal and interview research. **Roadmap**: user-reviewed, LLM-generated study plan with timed sessions and an adviser chat.
- **CAS**: compare-and-swap version checks used to reject stale writes.

## Documentation

- Update affected docs and links when behaviour, endpoints, configuration or implementation status changes.
- Keep `docs/` application-wide. Do not recreate `docs/development/` or Postman collections. Service-specific specs belong in the service folder.
- Keep service READMEs short: purpose, then endpoints grouped by capability; label unimplemented features; do not invent endpoint paths.
- Keep `docs/api/README.md` to a prefix → purpose → service-folder map with status. Keep detailed schemas in `contracts/api/`; avoid duplicate endpoint catalogues.
- Keep this file concise: durable rules, navigation, architecture and verification only. Link rather than copy; feature status belongs in specs and READMEs. Add commands only after verifying them.

## Jira (only when explicitly requested)

- Consult Jira only when the user explicitly requests it. Access only `coachifyy.atlassian.net`, project `SCRUM`.
- Preserve identifiers and Epic → Story → Subtask parents. Avoid duplicates; change sprints, assignees or status only when authorised.
