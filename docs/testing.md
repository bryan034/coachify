# Tests and CI

## Current state

The profile slice has component, browser and API tests plus real MongoDB integration.
CV has parser, saved-operation, ownership, mutation and handoff tests; Career has
preview and reviewed-target tests. Only the unimplemented roadmap/dashboard/review services may
pass with empty suites. Implemented service suites must collect tests.
See [application setup](setup.md) and the affected service README for setup and service details.

## Local commands

Use Node.js 24 and Python 3.12. From the root:

```sh
npm ci
npm run typecheck --workspace apps/frontend
npm run test --workspace apps/frontend
npx playwright install chromium
npm run test:e2e --workspace apps/frontend
```

The browser runner first discovers tests. If none exist it passes without starting
Next.js. When tests exist, Playwright builds and starts the frontend. The frontend builds the first workspace UI; unavailable services use empty states. Only Chromium is configured.
Browser tests cover public entry, nonce-bound Google access, session reload/logout, workspace editing and mobile layout using boundary fixtures. A separate full-stack browser job exercises the actual gateway, profile service and disposable MongoDB.

For each service, create an isolated Python environment, then run from its directory:

```sh
python -m pip install -e '.[test]'
python -m pytest
```

Each service's `tests/` directory is the pytest discovery root. Raw pytest exits 5
when no tests are collected; CI permits that only for the three remaining
scaffold services. All other nonzero exit codes fail. Profile, CV and Career integration jobs start MongoDB; ordinary
backend unit jobs do not.

## Automation

`.github/workflows/ci.yml` runs on PRs targeting `main`, every push to `main`
(including merges), merge-queue checks, and manual dispatch. All six backend suites
run independently. Frontend jobs run TypeScript/unit checks and Playwright browser
tests against a production Next.js build. Unit and browser test discovery are separate.
There are no path filters that could skip required jobs. The final `Test gate` fails
if any test job fails, is cancelled, or is skipped. Browser reports and failure
traces are uploaded for seven days; use synthetic data because artifacts may contain
page content. Linting is not configured yet.

## GitHub enforcement (repository administrator)

After this workflow has run on a PR:

1. Open repository Settings → Branches and add protection for `main`.
2. Require a pull request before merging.
3. Require status checks to pass; select `Test gate` from this workflow.
4. Require branches to be up to date before merging.
5. Disallow bypasses, force pushes, and deletion as appropriate for the team.

Availability depends on GitHub plan/repository visibility. Workflow files alone do
not enable branch protection. Push events verify merged code after the merge;
required PR checks are what prevent failing code from merging in the first place.
Local CI configuration does not publish a branch or modify GitHub settings.

## Real MongoDB and full-stack checks

Set `MONGODB_TEST_URI` to a disposable MongoDB instance when running the Profile
CV or Career suite to include database tests. Each creates/drops its own randomly named
test databases. Never use a production connection for tests.

The `local-ui-integration` job provisions a disposable Docker stack and tests
browser → gateway → API → MongoDB, including SMTP-to-Mailpit OTP verification, email/password A/B isolation, canonical onboarding, history restoration, logout/replay, cross-tab cleanup and profile/planning saves. For a manually provisioned **disposable** local-test stack on port 8081:

```sh
cd apps/frontend
PROFILE_E2E_BASE_URL=http://localhost:8081 MAILPIT_BASE_URL=http://localhost:8026 npx playwright test --config playwright.integration.config.ts
```

Use a separate Compose project and database volume, and set
`GATEWAY_PORT=8081`, `MAILPIT_PORT=8026` and `COMPOSE_PROFILES=development`, with
SMTP pointed at the disposable Mailpit container as in `.env.example`. This suite writes synthetic data; do not target your personal
profile. Boundary-fixture browser tests use
`NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com`, a test-only
public identifier, when running `npm run test:e2e --workspace apps/frontend`.

## Saved CV checks

CV tests cover parsing restrictions, extraction/evidence validation, ownership,
durable worker processing and lease fencing, idempotency, correction overlays,
clarification answer/skip behavior, explicit selection and versioned capability
input. Profile capability tests cover account-field preservation, normalized
matching, explicit attachment/distinct declarations and concurrent retries.

The full-stack CV browser test additionally exercises the real HTTP model adapter
against a deterministic synthetic server. Start the disposable stack with both
`-f infrastructure/docker/compose.yaml` and
`-f infrastructure/docker/compose.test.yaml`, and provide all four test database
passwords including `CV_DB_PASSWORD` and `CAREER_DB_PASSWORD`. The override uses a development-only HTTP
fixture and must not be used for personal CVs or production. It rejects sources
without the explicit synthetic marker. Generate the committed synthetic DOCX
fixtures with `python infrastructure/testing/make-cv-fixtures.py`.

The saved CV journey checks manual entry before upload, extraction, no automatic
selection, saved correction after reload and exact-source reprocessing, versioned
handoff, provider failure isolation and cross-account access. The clarification integration journey uses real Career saved targets and CV
HTTP context requests: draft, confirmation, explicit selection, project/work
answers, skill skips, reload, unrelated exploration selection, target revisit and
voluntary answers. It verifies preserved effective versions and owner isolation. These checks establish application behavior and contract
handling, not real-provider extraction quality; evaluate the configured model on
reviewed synthetic CVs before relying on its interpretation.

Profile compatibility adds unit and browser coverage for C-series drafts through session
revalidation, transient or malformed validation responses, explicit retry and
expiry/account changes. Healthy periodic checks remain silent; there is no new
inactivity lock. The real-service branch matrix covers students, National Service,
employment and both unemployment paths, including edits after a saved CV upload.
Its uploads are paced to the unchanged gateway limit of six per minute because
the synthetic accounts share one IP. Native browser cache eligibility and actual
model interpretation quality are not established by these checks.

## Career input/previews

Run Career pytest from `services/career-service` in a separate virtual environment
(`python -m pip install -e ".[test]"`, then `python -m pytest`). The existing CI
career matrix job now runs these tests. Do not collect Profile and Career together
in one Python process because both use an `app` package. Frontend tests cover
three methods, Unicode, failure recovery, method-switch races and temporary state.
The full-stack Career browser test uses the usual disposable Compose stack and
Mailpit variables; no Groq key or live website is used. Career imports are rate
limited at the gateway; use synthetic sources and discard only test-stack data.

## Confirmed target context

Career tests exercise immutable structured snapshots and bounded JD evidence,
normalization parity, separate confirmation/selection, empty drafts, owner isolation,
Mongo CAS, idempotent lost-response retries, stale revisions and database outages.
CV adapter tests cover bearer forwarding, strict bounded responses, dependency
failures and target switches during preparation. Frontend tests verify exact target
and selection versions, synchronized CV snapshots, safe drafts and delayed responses.

The gateway exposes only the Career target prefix plus existing import routes.
Career stores no full JD and requires its own database user; existing volumes use
the idempotent setup instructions without deleting stored data. AI target extraction,
exploration chat, research and gap generation are outside these checks.

## C-series interpretation completion

Clarification tests separate answer receipt, interpretation status and factual
resolution. Synthetic cases cover personal/team/observed/denied contribution,
explicit new personal skills, unknown values, independent supporting sources,
attribute preservation, partial dates, distinct follow-ups and effective no-ops.
Execution tests cover concurrent identical requests, live/expired interpretation
leases, bounded capacity and late-result rejection. Model output is tested for
wrong identities, unsupported excerpts, unrelated field changes and manufactured
date precision. These checks do not establish live-model semantic accuracy.

Source reconciliation tests retain both results, require explicit same-kind mapping,
preserve origin/history, and allow dismissal after the previous CV changes. Manual
attachment tests check project-derived skills, fingerprints, explicit detach/reattach
and semantic no-op refresh. Target-bound input checks exercise both target types and
version races without invoking an assessment or roadmap service.

## Saved CV conversation

The CV suite exercises the account-owned conversation store against both the
in-memory repository and disposable MongoDB. Coverage includes resumable and
manual-only conversations, ordered pagination, segment rollover, revision
conflicts, exact retries after a lost response, partial multi-action outcomes,
interrupted processing and recovery after a fact was saved but its chat receipt
was not. Listing history uses projected metadata rather than loading old message
bodies. Transcript activity is checked separately from evidence versions.

Routing and interpretation tests reject foreign source IDs, unsupported excerpts,
invalid actions and malformed or oversized provider responses. They preserve the
full user answer, including negation and team attribution, while appending bounded
source-linked clarification events. Session revocation during processing, stale
target/source context, provider capacity and storage limits are checked before
publishing facts. Corrections and manual additions still require explicit approval.

Frontend tests cover saved history, source choices, confirmation cards, async save
receipts, retries with the original mutation body, stale responses and account/CV
switches. The full-stack `cv-chat.spec.ts` uses the real local gateway, services and
MongoDB with the deterministic model fixture. Its journeys include rich answers,
questions without evidence changes, additional context, correction cancel/save,
reload/resume, skips, manual-only capabilities, ambiguous references, stale cards
and partial failures. Existing saved-upload, Profile and Career journeys remain in
the suite. Boundary browser checks also cover unsent chat drafts through temporary
session failures and the absence of private CV content in browser storage.

Use synthetic accounts and documents for recordings. A recording of this fixture
workflow demonstrates interaction and persistence, not live-model interpretation
quality. Conversational quality and comparative usability still need evaluation
with the configured model and representative users.
