# CV verification

From this service folder:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
MONGODB_TEST_URI=mongodb://127.0.0.1:27028 .venv/bin/python -m pytest -q
```

Use a disposable MongoDB instance. Each Mongo test creates a unique `elo_cv_test_*` database and drops only that database. Without `MONGODB_TEST_URI`, Mongo cases are explicitly skipped; memory-only results do not prove Mongo behavior.

Synthetic fixtures cover text PDF/DOCX sources, sparse CVs, exact/over size limits, corrupt/encrypted/image-only/unsafe archives, provider JSON structure, unsupported evidence and strict unknown numeric values. Both repositories exercise persisted status, owner isolation/revoked sessions, replay/conflicts, explicit selection, independent capability evidence, answer/skip/deferred context, same-source overrides, cleanup interruption, expired worker fencing, concurrent writers and changing declarations during input assembly.

Career adapter tests verify authenticated versioned requests, strict bounded context fields, canonical skill IDs, absent versus failed context, timeout/redirect handling and safe service configuration. Memory and real Mongo cases exercise empty-but-prepared results, old saved history, current-context relevance filtering, selection revisions including switch-away/back, target changes during preparation, removed sources and preparation invalidation after re-extraction.

Interpretation cases cover personal/team/guided/observed/denied contribution, explicitly named new skills, independent evidence, attribute-specific updates, cross-source conflicts, partial/unknown answers, distinct follow-ups, semantic no-ops, exact excerpts, invalid output, invented date precision in extraction and answers, correction/interpretation ordering, interrupted leases, same-key concurrent calls and late-result fencing. Reconciliation cases cover retained candidates, explicit mapping/archival, replacement ownership, stale choices and safe dismissal after the previous source changes, and date conflicts after reapplication without losing the comparison. Handoff tests cover both target types and source/target/declaration races; they do not claim atomic admission.

No live provider or real CV is used. These tests validate contracts and storage/failure behavior; they do not validate model quality against human labels or J/G gap analysis implementation.

The public `contracts/api/models/cv.schema.json` is generated from `CvDetail`, the saved-CV API response. Career may project that response into its own context contract; that projection does not replace the CV schema or create another CV store. Read-contract checks exercise authenticated sparse listings, owner isolation, private-field exclusion, read-only GET behavior, and strict rejection of injected write controls. Repository checks retain idempotency and conflicting-upload protection for both adapters.

Storage regressions run against both adapters: concurrent owner/global admission,
same-key uploads, original-byte expiry versus persistent record limits, every
reservation/file/record publication interruption, ambiguous Mongo acknowledgements,
live-writer exclusion, stale-generation release, preserved over-limit legacy data,
untracked/partial-file accounting, bounded projected list pages and selected CVs
outside the first page. Worker regressions fill the real 12 MiB history boundary,
retain prior evidence after oversized extraction, recover deletion interruptions,
and advance past full pages of poison cleanup/ingestion records. Mongo7 local
functional results do not establish Mongo8 compatibility or live-provider quality.

Model-admission regressions exercise shared owner/global daily budgets across
instances/restarts, real Mongo CAS contention, committed acknowledgement loss,
UTC rollover and backwards clocks, bounded owner maps, disabled providers and
receipt replays. Actual OS-lock tests cover owner fairness across routing,
interpretation and extraction, malformed busy tags, cancellation of an async
waiter while its provider thread remains active, and process-death recovery.
All callbacks are synthetic; these checks do not measure provider billing.

Clarification lifecycle regressions retain historical answers while excluding their
facts after source correction, prepare fresh questions after pending/failed/unknown
answers, preserve unrelated sources and keep repeated preparation stable. Both
direct API and chat paths accept new explanations for corrected sources. Distinct
same-uncertainty chat events retain unique identities and follow-up links after
explicit source reconciliation, and each can be retried independently.

Capacity cases fill the real 12 MiB boundary, reject answers/retries before an
unfinishable pending write, stop concurrent edits spending reserved result space,
and recover an interrupted answer at the reserved limit without duplicating its
content snapshot. A schema-bound UTF-8/BSON case checks the result allowance covers
maximum interpretation fields plus worker bookkeeping. Private reservation data
is excluded from public CV responses.
