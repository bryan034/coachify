# CV verification

From this service folder:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
MONGODB_TEST_URI=mongodb://127.0.0.1:27028 .venv/bin/python -m pytest -q
```

Use a disposable MongoDB instance. Each Mongo test creates a unique `coachify_cv_test_*` database and drops only that database. Without `MONGODB_TEST_URI`, Mongo cases are explicitly skipped; memory-only results do not prove Mongo behavior.

Synthetic fixtures cover text PDF/DOCX sources, sparse CVs, exact/over size limits, corrupt/encrypted/image-only/unsafe archives, provider JSON structure, unsupported evidence and strict unknown numeric values. Both repositories exercise persisted status, owner isolation/revoked sessions, replay/conflicts, explicit selection, independent capability evidence, answer/skip/deferred context, same-source overrides, cleanup interruption, expired worker fencing, concurrent writers and changing declarations during input assembly.

Career adapter tests verify authenticated versioned requests, strict bounded context fields, canonical skill IDs, absent versus failed context, timeout/redirect handling and safe service configuration. Memory and real Mongo cases exercise empty-but-prepared results, old saved history, current-context relevance filtering, selection revisions including switch-away/back, target changes during preparation, removed sources and preparation invalidation after re-extraction.

Interpretation cases cover personal/team/guided/observed/denied contribution, explicitly named new skills, independent evidence, attribute-specific updates, cross-source conflicts, partial/unknown answers, distinct follow-ups, semantic no-ops, exact excerpts, invalid output, invented date precision in extraction and answers, correction/interpretation ordering, interrupted leases, same-key concurrent calls and late-result fencing. Reconciliation cases cover retained candidates, explicit mapping/archival, replacement ownership, stale choices and safe dismissal after the previous source changes, and date conflicts after reapplication without losing the comparison. Handoff tests cover both target types and source/target/declaration races; they do not claim atomic admission.

No live provider or real CV is used. These tests validate contracts and storage/failure behavior; they do not validate model quality against human labels or J/G gap analysis implementation.
