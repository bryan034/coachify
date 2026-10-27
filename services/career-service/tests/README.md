# Career service tests

Run `python -m pytest` from this service after installing `.[test]` in its own
virtual environment. Both Profile and Career use an `app` package, so run each
service's tests independently rather than importing both into one Python process.

Tests use synthetic text/files, fake Profile responses and mocked website
transport/DNS. They cover PDF/DOCX/TXT parsing in real child processes,
authentication, no-store responses, file cleanup, limits, invalid files, safe XML,
public-address checks, TLS host verification, robots, redirects and fallbacks.
The preview cases need no MongoDB. No Groq key, real credentials or external
website calls are required.

Frontend component/browser coverage lives under `apps/frontend`. The full-stack
Career test uses real Profile authentication and TXT parsing, with synthetic
accounts and Mailpit. It also verifies internal URLs are rejected and previews
are absent from browser storage and lost after reload.


## Saved reviewed targets

`MONGODB_TEST_URI=mongodb://127.0.0.1:27028 .venv/bin/python -m pytest`
runs the target contracts against explicit in-memory and isolated real MongoDB
adapters. Test databases use unique names and are removed after each case. Without
`MONGODB_TEST_URI`, real MongoDB cases are skipped and must not be reported as
verified. Coverage includes owner isolation, transient source non-persistence,
strict/Unicode limits, exact excerpt membership, immutable confirmation, explicit
selection, no-op/replay safety, concurrent creates/confirms/selections, context
switch fences and recoverable storage failure. Target-history coverage includes
large structured records across multiple pages, stable traversal during concurrent
insertion, an older selected target outside the page, malformed/foreign-owner
cursors and the database read bound. All data is synthetic; no provider
calls are made. The complete suite also retains existing parser/URL preview tests.

Non-skill condition tests cover condition-only job/exploration confirmation,
source-backed subject phrases, bounded arrays/text, immutable server identities,
read-only context, stale/foreign context, and old targets/retry fingerprints
without the new field. Frontend cases retain failed condition drafts and safely
retry the same request; malformed condition responses are rejected.
