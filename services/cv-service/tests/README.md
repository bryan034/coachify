# CV contract tests

Install `.[test]` and run `python -m pytest` from this service's own environment.
Tests validate structured CV records and check the CV JSON Schema against the
Career snapshot contract. No upload/extraction endpoints are implemented.

Set `MONGODB_TEST_URI` to disposable MongoDB to include the real BSON, idempotency
and owner-isolation test. It creates/drops a random `coachify_cv_test_*` database.
No real CV, account credentials or AI key is needed.
