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
credentials are required by this configuration. Add isolated backend fixtures and
API/database lifecycle management before introducing full-stack journeys.

P07/P08 component tests and a browser journey are implemented; empty suites still pass. The browser runner uses Playwright
discovery first and avoids building/starting Next.js when no browser tests exist.
Actual test failures and discovery/configuration errors still fail. Add meaningful
tests with features; an empty passing suite does not establish test coverage.

For the browser suite, set NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com (a test-only public identifier). See docs/development/profile-setup.md from the root for fixtures and real sign-in setup.
