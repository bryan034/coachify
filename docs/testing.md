# Tests and CI

## Current state

The profile slice has component, browser and API tests plus real MongoDB integration.
Career has preview/AI/contract tests and CV has contract tests; Roadmap, Dashboard
and Review still have empty suites. Empty suites pass; real failures do not.
See [application setup](setup.md) and the affected service README for setup and service details.

## Suite maintenance

Keep tests for distinct behaviours and boundaries, including cross-service contracts.
When consolidating overlapping tests, move unique assertions into the retained case.
Remove obsolete UI journeys when the current journey covers their useful checks;
do not remove valid failing tests to make CI pass.

The 26 October 2026 cleanup removed nine cases: three overlapping/default-only
Career backend checks, three superseded form-based onboarding cases, two duplicate
chat retry/formatting cases and one obsolete manual goal editor browser journey.
Retry preservation, Markdown formatting, provider scope, saved-goal reload and mobile
research-source assertions remain in the current tests. That cleanup left 772 discovered
cases: 648 backend, 95 frontend component/unit, 17 mocked browser and 12 full-stack
browser cases. Parameterised cases are counted separately.

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
when no tests are collected; CI treats only that code as success. All other
nonzero exit codes fail. The profile integration job starts MongoDB; ordinary
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

Set `MONGODB_TEST_URI` to a disposable MongoDB instance when running the profile
suite to include database tests. They create/drop randomly named `coachify_test_*`
and `coachify_accounts_test_*` databases. Never use a production connection for tests.

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

## Career input/previews

Run Career pytest from `services/career-service` in a separate virtual environment
(`python -m pip install -e ".[test]"`, then `python -m pytest`). The existing CI
career matrix job now runs these tests. Do not collect Profile and Career together
in one Python process because both use an `app` package. Frontend tests cover
three methods, Unicode, failure recovery, method-switch races and temporary state.
The full-stack Career browser test uses the usual disposable Compose stack and
Mailpit variables; no Groq key or live website is used. Career imports are rate
limited at the gateway; use synthetic sources and discard only test-stack data.

## AI and analysis contracts

The Career suite tests the Groq-compatible adapter through fake HTTP responses;
no live key, external provider calls or billing are needed. Career and CV each
validate the exported MongoDB schemas. Their `MONGODB_TEST_URI` tests create/drop
random `coachify_analysis_test_*` / `coachify_cv_test_*` databases, checking real
BSON, indexes, private ownership and idempotent/versioned writes. Use only a
disposable MongoDB. The required `analysis-integration` CI matrix runs both suites
against MongoDB; ordinary backend jobs skip only their database-dependent tests.

J08/J09 add fake-provider + real MongoDB flow tests, CV API ownership checks,
component/browser adaptive chat and JD handoff checks, and a full-stack confirmed-goal reload
check. The disposable Compose test stack also needs `CAREER_DB_PASSWORD` and
`CV_DB_PASSWORD`; CI supplies synthetic values. Real Groq credentials are never
used by automated tests. Goal-flow tests create/drop `coachify_goals_test_*` DBs.

JD review tests use synthetic AI outputs for semantic supporting summaries,
labelled inferences, structured job fields and URL metadata, context-only chat,
proposal approval, invalid history, empty results and recoverable failures. They
verify raw JD text is excluded from chat requests and unknown requirements are not
promoted to employer facts; they do not establish live-model extraction accuracy. Browser coverage checks
automatic document reading, the shared chat and explicit proposal approval. Activity
tests verify drafts survive tab switches, interaction renews the five-minute deadline,
and expiry blocks the mounted workspace until explicit refresh.

Docker hot-reload verification uses an isolated Compose project with `/dev/null`
as its environment-file source and explicit synthetic settings. A disposable client
component verifies an edited label updates through the gateway HMR socket while
preserving a counter and avoiding page navigation. Temporary API probes verify
Python edits reload in Profile, Career and CV. Probes are restored/removed afterward;
no private environment files or live account data are used. The production frontend
Docker target is built separately to check that the dev target remains opt-in.

J02–J04 add saved review editing, reset/cancel, atomic skill/condition reclassification,
source/metadata provenance, mapping-pending states, guarded confirmation, version
conflicts and immutable history. Career MongoDB tests use random
`coachify_reviews_test_*` databases. Browser fixtures cover extract → chat proposal →
automatic save → reload → latest goal, including mobile layout. External AI
remains mocked; these checks do not establish live-model semantic accuracy.

The Local UI and MongoDB job uploads `local-ui-integration-results` for seven days,
including retained failure traces and error context. Its Career preview journey
keeps AI disabled: it asserts the real `/workspace/jd` API returns `503/not_configured`,
the UI preserves retry controls and disables chat, and no review was saved. It does
not depend on introductory wording or use live Groq credentials.


Career J05/J10/J12/J13 checks cover importance/reset identities, advisory generation,
exact selection versions, owner isolation, shared public research reuse, leases,
immutable history and failed refresh recovery. API source connectors and AI are
synthetic fixtures; no live source API or model accuracy is claimed. An unconnected
source API is tested as unavailable. Frontend checks cover the shared skills review,
read-only historical evidence, retry preservation and mobile layout. Run Career
with a disposable `MONGODB_TEST_URI` to include these database-backed tests.


LangGraph single-workspace checks use real disposable MongoDB with synthetic models
and Brave HTTP responses. They cover automatic current-goal saves, session
replacement, stale-session/owner rejection, research-before-chat gating, persisted
checkpoints, quota pause/resume without repeating searches, no-findings and expiry.
User-usage tests verify 4,000-input boundaries, 7,000-token rolling admission,
actual usage without output reservations, owner isolation, atomic MongoDB appends,
individual expiry, retry delays, provider distinction and output caps. Browser checks cover the
new single-chat flow and mobile evidence. No live model/search credentials are used.

Brave Answers checks cover fragmented SSE, cited AI summaries versus source excerpts,
invalid/missing references, uncited-answer rejection, output limits, public-scope queries,
mode-specific cache policies, MongoDB summary persistence/reuse and the 4,000-token cap.
All external responses are synthetic; live Answers access must be configured separately.

Career overview coverage checks category membership, research-in-progress display,
CV assessment absence versus service failure, guided refinement, safe goal replacement
and reload restoration. `career-overview.spec.ts` exercises the desktop/mobile flow
through CV-page navigation using synthetic providers. Backend assessment-status tests
verify authentication/no-store, owner filtering, empty/pending/failed/succeeded CVs
and unavailable upstream snapshots without database or model writes.

Opportunity Intelligence tests use a real disposable MongoDB with synthetic Gemini,
Groq and Brave boundaries. They cover independent parallel categories, partial
failure, no company/no results, conflicting employee/intern salary context, forged
refs/quotes, bounded schema repair, category cache/expiry, refresh/idempotency,
owner access, quota recovery and restart without repeating acquired searches.
Foreground extraction regressions cover reconnecting an identical JD under a new
key during a 600-second simulated quota wait, replay/ownership checks, safe
different-input conflicts and chat navigation retaining its request key. A Chromium
journey leaves/reopens pending extraction and reaches the saved goal without 409s.
The optional `OPPORTUNITY_LIVE_TEST=1` smoke consumes actual configured public
provider requests; it is skipped by default. Frontend unit/browser checks cover
source/confidence/date transparency, partial status and category-only refresh.
