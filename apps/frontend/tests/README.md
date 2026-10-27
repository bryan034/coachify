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
in the `local-ui-integration` job. These tests create explicit synthetic local accounts and cover switching, revocation and cross-tab logout. See [application testing guide](../../../docs/testing.md).

P01–P16 component tests and a browser journey are implemented; empty suites still pass. The browser runner uses Playwright
discovery first and avoids building/starting Next.js when no browser tests exist.
Actual test failures and discovery/configuration errors still fail. Add meaningful
tests with features; an empty passing suite does not establish test coverage.

For the browser suite, set NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com (a test-only public identifier). See the [setup guide](../../../docs/setup.md) for real sign-in and the [testing guide](../../../docs/testing.md) for fixtures.

Workspace browser checks cover navigation, validated account sessions, public access pages, session reload/logout, saved background on Home, unavailable service controls, connection failure/retry, and mobile overflow. The week/month and roadmap filters are presentation-only and do not call unfinished services.

Full-stack account tests additionally require `MAILPIT_BASE_URL` for the disposable captured-email inbox. They verify actual SMTP OTP delivery, password sign-in, guarded setup and cross-tab completion.

Initial-setup checks cover one-question screens, optional course, unlisted school,
extended study years, partial saves, lost completion responses, version conflicts,
exit/sign-out and canonical routing. Directory tests cover country headings,
name-only school buttons and editable country defaults. Full-stack tests verify
the wizard against actual MongoDB saves.

Profile-summary tests cover conditional student/work fields, legacy missing work
details and separate editing. Development-preview tests verify a full replay
without profile writes, while production rejects direct preview URLs. Real MongoDB
journeys cover employer/role persistence, later editing and unchanged profile
version/data after preview.

Inline profile-editing checks verify opening existing values, discarding edits on
Cancel, retaining drafts after a failed save, and refreshing the saved summary.
The full-stack summary journey verifies employment edits survive reload.

Onboarding presentation checks verify full-screen desktop/mobile layouts, a bottom
progress bar that stays visible while questions scroll, forward/back transitions,
heading focus and reduced-motion support.

The ordinary editor uses stacked dropdowns and fields. Checks cover searching only
when changing a school, retaining the saved school, clearing an optional course,
and the All countries label.

Employment checks cover searchable suggestions and manual fallback, industry
validation, explicit unemployed yes/no branching, historical work retention,
last-job profile display/editing, and the 75% desktop onboarding width. Full-stack
journeys verify both unemployed branches against MongoDB and captured-email setup.

Graduation checks cover question order, resuming a missing year, invalid/future years, profile display/editing and a real MongoDB save/reload journey. Company-data checks require at least 5,000 unique named employers with positive counts, employee-ranked search and Singapore coverage.


C-series tests cover authenticated response validation, exact upload limits,
interrupted-upload idempotency, identical filenames, explicit selection, private
state clearing on account changes, effective provenance, unknown values, retained
correction drafts, stale-version reconciliation, skip behavior and explicit manual
capability matches. Browser fixtures cover upload → selection → correction →
manual declaration → reload/removal, failed replacements and mobile overflow.
The workspace baseline now expects CV API reads while still checking other
unimplemented services remain disconnected. These fixtures use synthetic data and
mocked API responses; real service/database coverage lives under `tests/integration`.


Confirmed-target checks cover structured draft review, explicit confirmation and
selection, reloaded targets, source excerpt validation, request identity and stale
responses. CV tests distinguish absent context from dependency failure and an empty
prepared question set, preserve drafts, and keep target-irrelevant pending prompts
hidden while retaining answers/skips. `integration/clarification-flow.spec.ts` uses
real Career/CV/Profile/Mongo/gateway services plus the labelled synthetic CV model
fixture. It exercises project/work explanations, unknown skill answers, skips,
voluntary return, reload, target switching and owner isolation.

Profile compatibility checks exercise delayed editor initialization and shared
session recovery. The C-series browser fixture keeps an unsaved correction,
clarification answer, manual capability and selected file through hide/show,
temporary validation failure/retry and simulated back/forward-cache restoration.
It verifies masking, keyboard focus, expiry/account-change cleanup and more than
five minutes without an inactivity lock. These fixtures simulate lifecycle events;
they do not establish browser-specific native cache eligibility.

The full-stack compatibility journey covers Student, National Service, Employed
and both Unemployed branches. It creates verified synthetic accounts, uploads a CV,
adds a manual capability, then edits Profile and reloads to check saved selection
and declarations. Backend checks use the existing Profile completion and version
contracts with real disposable MongoDB; model responses remain synthetic.

Interpretation-completion checks distinguish raw answer saves, validated claims,
partial/unanswerable resolution and recoverable provider failure. They cover
explicit new personal skills, partial dates, qualification conditions, manual-link
repair and replacement reconciliation. The shared
`integration/completion-workflow.ts` journey is used by
`integration/c-series-completion.spec.ts` and the local workflow recording. It
asserts the target-bound input contract through the real services without creating
an assessment or claiming live model accuracy. The synthetic fixture accepts only
its labelled test model and fixed fixture answers.
