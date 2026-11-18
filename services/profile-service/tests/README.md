# Profile tests

API and snapshot tests use pytest. MongoDB integration requires MONGODB_TEST_URI pointing at a disposable instance. See the [application testing guide](../../../docs/testing.md) for commands and fixture boundaries.

`test_capabilities.py` exercises the account declaration repository with isolated
in-memory collections. The `storage_backends` cases also run against MongoDB for
declaration persistence, version conflicts, concurrent saves and lost-response replay.
`test_capability_cv_match.py` checks the authenticated service boundary, stale or
removed CV matches, redirect rejection and safe errors. These synthetic tests do
not claim live model quality or J/G analysis integration.

Attachment reconciliation adds project/work/education-derived matching, rejection
of team/observed/denied source links despite independent support elsewhere,
fingerprint validation, explicit detach/refresh history, unknown old fingerprints,
semantic no-op revisions, ownership, stale source/version failures and concurrent
or lost-response retries. The same account repository and synthetic Mongo fixtures
verify that unrelated Profile fields and manual statements are preserved.
