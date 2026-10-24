# Frontend tests

Vitest and React Testing Library cover functions and synchronous/client components.
Put tests in `src/**/*.test.ts(x)` or `tests/unit/**/*.test.ts(x)`.
Playwright covers browser journeys and async Server Components through the running app.
Put browser tests in `tests/e2e/*.spec.ts`.

From the repository root:

```sh
npm ci
npm run test --workspace apps/frontend
npx playwright install chromium
npm run test:e2e --workspace apps/frontend
```

When browser tests exist, Playwright builds and starts Next.js automatically on port 3000. Stop any existing
server on that port first. Chromium is the initial browser target. No production
credentials are required by this configuration.

The separate `playwright.integration.config.ts` runs `tests/integration/` against
`PROFILE_E2E_BASE_URL`. It requires a disposable Docker local-test stack and writes
profile data through the real API into MongoDB. CI provisions and removes that stack
in the `local-ui-integration` job. See `docs/development/profile-setup.md`.

P07/P08 component tests and a browser journey are implemented; empty suites still pass. The browser runner uses Playwright
discovery first and avoids building/starting Next.js when no browser tests exist.
Actual test failures and discovery/configuration errors still fail. Add meaningful
tests with features; an empty passing suite does not establish test coverage.

For the browser suite, set NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com (a test-only public identifier). See docs/development/profile-setup.md from the root for fixtures and real sign-in setup.

Workspace browser checks cover navigation, shared Google identity, saved background on Home, unavailable service controls, connection failure/retry, and mobile overflow. The week/month and roadmap filters are presentation-only and do not call unfinished services.
