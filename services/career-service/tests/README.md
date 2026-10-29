# Career tests

Run `python -m pytest` from this service after installing `.[test]` in its own
virtual environment. Both Profile and Career use an `app` package, so run each
service's tests independently rather than importing both into one Python process.

The shared test harness clears inherited application database, provider and tracing
settings before collection and before each test. `MONGODB_TEST_URI` remains an
explicit disposable-database opt-in; tests can inject mocks and synthetic settings
after setup. Default HTTPX/Requests transports and the preview socket connector
are blocked. Supply an already populated `TIKTOKEN_CACHE_DIR` when using a cached
runtime; tests do not download tokenizer assets or opt into live provider calls.
The public Docker-template test must use the user-approved clean tracked template
in an isolated copy when environment-file access is otherwise prohibited.

Tests use synthetic text/files, fake Profile responses and mocked website
transport/DNS. They cover PDF/DOCX/TXT parsing in real child processes,
authentication, no-store responses, file cleanup, limits, invalid files, safe XML,
public-address checks, TLS host verification, robots, redirects and fallbacks.
Schema and fake-provider tests also cover structured outputs, provenance, limits,
provider failures, cancellation and stale input. No real credentials or
external website calls are required. JD checks cover paraphrased support, structured
job metadata, labelled inferred skills, conversation context without raw sources,
and approval boundaries for proposed changes. Set `MONGODB_TEST_URI` to disposable MongoDB
to include real repository/index/ownership/idempotency tests; these create and
drop only random `coachify_analysis_test_*` databases.

Frontend component/browser coverage lives under `apps/frontend`. The full-stack
Career test uses real Profile authentication and TXT parsing, with synthetic
accounts and Mailpit. It also verifies internal URLs are rejected and previews
are absent from browser storage and lost after reload.

J02–J04 integration tests create/drop `coachify_reviews_test_*` databases. They cover
structured-only storage, owner isolation, source hashes, no-op/reset/correction
behaviour, mixed AND/OR groups, duration ranges, mapping, reclassification,
confirmation claims, lost-response retries and immutable goal edits. Unit tests
inject an in-memory repository boundary; MongoDB tests exercise the real repository.


`test_jd_token_budget.py` verifies small model schemas, operation-specific prompts,
backend-owned metadata, explanation-only requests, reference-based edit proposals,
provenance checks, stale/quota failures and content-free token-usage logs. All calls
use synthetic HTTP transport; these checks do not measure live token savings.


`test_jd_generation_failures.py` covers the provider JSON-failure/deadline sequence,
Gemini minimal reasoning, insufficient follow-up time, specific API errors and
safe reasoning/cache/finish-reason metrics. No live credentials are used.

Brave-only research checks verify that acquisition contacts only the Brave API,
public forum citations remain labelled as anecdotes, the old mixed-provider cache
is refreshed without deleting historical evidence, and quota/restart recovery
does not repeat completed searches. No Reddit credentials or live calls are used.

`test_user_usage.py` verifies prompt/schema size estimates, repeated concurrent
Gemini requests beyond 8,000 input tokens without local admission or output reduction,
provider HTTP 429 handling and distinct context-versus-provider-limit messages.
Frontend checks cover countdowns, retained drafts and retry readiness.

`test_brave_summaries.py` covers attributed AI claims, forged references, original
excerpt separation and summary-rich input budgets. Connector tests cover fragmented
streaming and plan-access failures; workspace tests cover MongoDB persistence/reuse.

Research regressions cover Gemini requests beyond 8,000 input tokens, concurrent requests
without a local minute quota and independent provider 429s, late interview passages, full assessment
excerpts, deadline-aware early stopping, no-progress limits, partial cache reuse and
preserving assessed evidence after later retrieval timeouts. Workflow/cache checks
require disposable MongoDB; all provider responses use synthetic fixtures.

`test_five_category_queries.py` verifies Gemini-written initial queries for finance
and engineering roles, all five required intents, no template fallback, preserved
legacy reports/jobs, and historical conversion-rate evidence. Opportunity tests
exercise five parallel branches, partial failures, bounded follow-ups and paid-evidence
reuse. HTTP-mocked field mapping covers every schema-v2 category including conversion
salary/currency and historical percentages; live providers remain opt-in only.

## Saved CV and canonical confirmation compatibility

CV client/contract checks cover the public saved-CV API plus legacy read shapes, UUID/ObjectId reference roundtrips, sparse owner metadata, exact detail identity, provenance, fractional duration and unknown proficiency. Arrays above 200 entries remain valid within the existing 512 KiB admission bound. Declared and chunked oversized HTTP responses fail before unbounded JSON decoding, with no truncation. Public CV and internal Career projection schemas are tested separately.

Canonical-confirmation checks exercise explicit acknowledgement, version/selection/projection races, owner isolation, receipt-key reuse and lost-response replay. Editing or replacing the goal invalidates its CV context without deleting saved CV facts. Mixed legacy UUID target/canonical ObjectId history and the legacy unique index require compatibility checks without destructive migration. Legacy target domain tests use an explicit injected test adapter; they do not establish that production has a parallel active target flow.

One upstream test reads the public Docker environment template. The user's narrow exception permits that exact test against a clean tracked public template in an isolated copy. It does not permit agents or other tests to inspect local environment files or modified examples. Use only synthetic settings and disposable databases. Local functional checks against MongoDB 7 do not establish MongoDB 8 compatibility; intended-version checks require a compatible runner. Final counts and evidence belong in the integration handoff, not a historical test-discovery total.

Security regressions cover bounded operation/alias retention, fresh polling errors,
current-context quota retries, real review edits during research acquisition and
link-publication races. CV-list regressions follow cursors while preserving a
single 512 KiB intake budget and reject malformed/repeated continuation pages.
