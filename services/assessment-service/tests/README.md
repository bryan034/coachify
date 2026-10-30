# Assessment tests

Run this service separately with the shared package installed or on `PYTHONPATH`. Synthetic cases cover canonical aliases, captured revisions, AND/OR outcomes, declared limitations versus unknowns, complete requirement/component coverage, evidence references, partial research, owner isolation, stale input rejection, idempotency, restart recovery and checkpointed batch retry.

`fixtures/labelled-comparisons.json` is a small synthetic semantic diagnostic set for the separately opt-in `../evaluate.py`. The normal test suite does not call a live model or measure semantic accuracy. See [testing guidance](../../../docs/testing.md#assessment-and-roadmap-adviser).
