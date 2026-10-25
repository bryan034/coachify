# Career tests

Run `python -m pytest` from this service after installing `.[test]` in its own
virtual environment. Both Profile and Career use an `app` package, so run each
service's tests independently rather than importing both into one Python process.

Tests use synthetic text/files, fake Profile responses and mocked website
transport/DNS. They cover PDF/DOCX/TXT parsing in real child processes,
authentication, no-store responses, file cleanup, limits, invalid files, safe XML,
public-address checks, TLS host verification, robots, redirects and fallbacks.
Schema and fake-provider tests also cover structured outputs, provenance, limits,
provider failures, cancellation and stale input. No Groq key, real credentials or
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
use synthetic HTTP transport; these checks do not measure live Groq token savings.


`test_jd_generation_failures.py` covers the provider JSON-failure/deadline sequence,
model-specific low reasoning, insufficient follow-up time, specific API errors and
safe reasoning/cache/finish-reason metrics. No live Groq credentials are used.
