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

Playwright builds and starts Next.js automatically on port 3000. Stop any existing
server on that port first. Chromium is the initial browser target. No production
credentials are required by this configuration. Add isolated backend fixtures and
API/database lifecycle management before introducing full-stack journeys.

No product tests exist yet; both runners must fail when no tests are found.
Do not add dummy assertions just to make CI pass. Add meaningful tests with features.
