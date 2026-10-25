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
external website calls are required. Set `MONGODB_TEST_URI` to disposable MongoDB
to include real repository/index/ownership/idempotency tests; these create and
drop only random `coachify_analysis_test_*` databases.

Frontend component/browser coverage lives under `apps/frontend`. The full-stack
Career test uses real Profile authentication and TXT parsing, with synthetic
accounts and Mailpit. It also verifies internal URLs are rejected and previews
are absent from browser storage and lost after reload.
