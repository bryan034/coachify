# Tests and CI

## Current state

The repository contains comment-only application placeholders and no product test
cases. Test tooling is configured, but CI is intentionally not green: empty suites
fail. Do not bypass the gate or add dummy tests to bootstrap a passing result.
Implement real pages/service entry points and meaningful tests before requiring
the gate for merges. No application business logic was added by this CI change.

## Local commands

Use Node.js 24 and Python 3.12. From the root:

```sh
npm ci
npm run typecheck --workspace apps/frontend
npm run test --workspace apps/frontend
npx playwright install chromium
npm run test:e2e --workspace apps/frontend
```

Playwright builds and starts the frontend itself. The scaffold currently cannot
build because pages and layouts lack implementations. Only Chromium is configured.
There are no live backend fixtures, credentials, or databases in browser tests yet.

For each service, create an isolated Python environment, then run from its directory:

```sh
python -m pip install -e '.[test]'
python -m pytest
```

Each service's `tests/` directory is the pytest discovery root. Empty suites return
a failure. Add MongoDB fixtures and CI service containers when database integration
tests are introduced; the current workflow does not start MongoDB or the API stack.

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

After meaningful tests exist and this workflow has run on a PR:

1. Open repository Settings → Branches and add protection for `main`.
2. Require a pull request before merging.
3. Require status checks to pass; select `Test gate` from this workflow.
4. Require branches to be up to date before merging.
5. Disallow bypasses, force pushes, and deletion as appropriate for the team.

Availability depends on GitHub plan/repository visibility. Workflow files alone do
not enable branch protection. Push events verify merged code after the merge;
required PR checks are what prevent failing code from merging in the first place.
Local CI configuration does not publish a branch or modify GitHub settings.
