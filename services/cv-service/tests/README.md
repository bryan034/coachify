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

Semantic-evidence cases use explicit synthetic verdicts to cover paraphrase/formatting acceptance, unsupported/malformed verdict rejection, source scoping and shared daily admission. They do not measure live semantic accuracy.

Extraction regressions cover lossless splitting of source-verified long quotations, invented-suffix rejection, retained explicit-skill/count checks, source-checked uncategorised content, persistence/API output and nonfatal unclear/invalid/unsupported dates. Frontend checks cover the Other information section.

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

Provider adapter tests exercise OpenAI SDK requests using explicit HTTP mocks,
including host-scoped Gemini reasoning and reduced-complexity decoding schemas while retaining backend limits, DeepSeek extensions and local credential
isolation. Shared transport tests cover bounded bodies, redirects and SDK retry
suppression. No live provider credentials are used.

Extraction-failure tests cover provider HTTP status, SDK connection/timeouts,
stream transfer failures, response limits, invalid envelope/content JSON and
incomplete output. Worker cases verify parsing, source, admission and validation
categories, persisted polling/list diagnostics, private log boundaries and error
clearing after a successful retry. All responses and documents are synthetic.
Provider-rejection cases additionally cover fixed HTTP 400 schema/format/parameter
reasons, quota/authentication recovery messages, malformed/oversized rejection
bodies and exclusion of provider prose/arbitrary parameter names from saved API
responses and logs. Requests are not automatically retried or downgraded.

The real LangGraph harness is exercised with synthetic HTTP responses: first-pass
success, overlong evidence/conflicting dates repaired once, schema/evidence failure
after repair, repair-provider rejection, budget denial, short/expired/replaced
leases and late publication fencing. Tests inspect strict schema requests and the
explicit JSON-mode opt-out, bounded private feedback, tracing suppression, saved
metadata and frontend compatibility. These validate runtime behavior, not a live
provider's constrained-decoding implementation or extraction accuracy.

Saved-source deletion tests exercise ready/queued/failed/expired CVs, ownership and
stale versions, selected/other sources, late workers/edits, conversation removal,
filesystem failure, lost tombstone acknowledgements, quota recovery, bootstrap and
old-upload replay prevention on both repositories. UI/API tests verify explicit
confirmation, review/selection reset, cancellation, interrupted-request identity,
stale-version refresh and strict deletion acknowledgements.
Deletion OpenAPI checks also simulate Python 3.12's older HTTP status phrases;
the published 413/422 descriptions remain stable across supported runtimes.

Skills Profile tests cover explicit review without Career, model-written questions,
manual field order/skips, semantically equivalent values, unsupported/foreign
answer rejection, persisted partial drafts and exact-write recovery after lost
cross-service acknowledgements. Semantic proficiency/independence acceptance uses
explicit synthetic verdicts; it does not establish live model quality.

Saved-title tests cover validation, owner isolation, persistence/list projections, stale/replayed writes, queued-source renaming and unchanged source/evidence/history. Mongo cases require the disposable test database described above.

Agent-led CV interview checks in `test_cv_interview.py` cover durable memory on both
repositories, rich/partial evidence, scoped skips, side questions, user stops,
known-field suppression, unproductive probing, coverage/estimate guards, semantic
rejection, old source-answer context, stale-provider fencing and retry without
duplicate evidence. Mongo cases reconstruct the coordinator over persisted records.
They use explicit synthetic outputs and do not measure live interview quality.
