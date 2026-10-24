# Tests and CI

## Current state

The profile slice has component, browser and API tests plus real MongoDB integration.
Other services still have empty suites. Empty suites pass; real failures do not.
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
Browser tests cover the workspace, profile save/retry, Google navigation and mobile layout using boundary fixtures. A separate full-stack browser job exercises the actual gateway, profile service and disposable MongoDB.

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
databases. Never use a production connection for tests.

The `local-ui-integration` job provisions a disposable Docker stack and tests
browser → gateway → API → MongoDB, including save/reload and planning-conflict
recovery. For a manually provisioned **disposable** local-test stack on port 8081:

```sh
cd apps/frontend
PROFILE_E2E_BASE_URL=http://localhost:8081 npx playwright test --config playwright.integration.config.ts
```

Use a separate Compose project, database volume and local identity, and set
`GATEWAY_PORT=8081`. This suite writes synthetic data; do not target your personal
profile. Boundary-fixture browser tests use
`NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com`, a test-only
public identifier, when running `npm run test:e2e --workspace apps/frontend`.
