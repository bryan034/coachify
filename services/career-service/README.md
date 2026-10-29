# Career service

Career owns transient job inputs, the account's canonical goal and guided chat, conversational discovery and cited public research. JD intake and discovery share the same structured goal persistence path. Configured Gemini/Brave access is required for live interpretation and research; previews make no model calls. Synthetic tests do not establish live quality or provider cost.

## JD inputs — J01 / J06 / J07

Pasted text stays in browser memory until explicitly submitted for extraction. `POST /api/v1/career/imports/url` and `/imports/document` return bounded temporary previews; `/explorations/cv/document` supplies optional temporary CV context. Inputs and originals are not retained as raw JD/CV text. URL/document safeguards are detailed in [SPECIFICATION.md](SPECIFICATION.md).

## Canonical goal and chat — J02–J05 / J09

- `GET /api/v1/career/workspace` returns one owner-scoped saved workspace; `/workspace/progress` supports lightweight polling.
- `POST /api/v1/career/workspace/jd` starts or reconnects to versioned JD intake. A validated identity overlaps full extraction with public-only retrieval. Successful extraction saves the goal; combined chat output waits for extraction and research to complete.
- `POST /api/v1/career/workspace/messages` asks scoped questions or refines the current goal. Ambiguous edits retain a private pending question; valid edits save with owner/version checks and retry receipts.
- `/api/v1/career/goals` and `/goals/current` expose canonical structured history/current state. Goals edit in place with versions. A replacement becomes current only after validated saving.

Observed progress describes completed/running stages, never hidden model reasoning. Temporary chat/workflow context and 24-hour checkpoints are distinct from persistent goals and immutable research. Older compatibility review/guidance endpoints remain available as described in [ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md).

Goal summaries use bounded corrections for invalid model output, with at most six
repairs. Verified citation formatting is normalized locally; unknown sources and
forged destinations still fail. Each finding requires a supporting citation.
Rejected model text is not retained. Failed AI operation responses include
`operation_id` and fixed issue codes under `diagnostic.violations`; the ID also
appears in the initial 202 response, polling URL and content-free failure logs.
Operations are owner-scoped, remain in worker memory for at most 24 hours and are
lost on restart; they are not stored in MongoDB. Retention is capped at 128 jobs
per worker, 16 per owner and 32 reconnect aliases per job. Capacity evicts the
oldest terminal jobs; active work is preserved and excess admission returns 429.
Failed polling reconstructs a fresh error from safe data, without retained tracebacks. See
[analysis contracts](ANALYSIS_CONTRACTS.md) for recovery and diagnostic details.

## Explicit CV clarification context — C-series integration

- `GET /api/v1/career/goals/current/cv-confirmation` reports the exact current goal, goal version and selection version, whether that revision is confirmed, its context and an actionable reason when unavailable.
- `POST /api/v1/career/goals/current/cv-confirmation` acknowledges those exact versions with a UUID mutation key. It does not create another goal, advance selection or imply assessment.
- `GET /api/v1/career/goals/current/confirmed-context` returns the current valid confirmed projection or null. `/goals/{goal_id}/confirmed-context?expected_version=...` validates a pinned current revision for CV consumers.

Career automatic saving does not silently confirm a goal for CV review. `career_state.cv_confirmation` records goal ID/version, selection version, projection hash and confirmation time; edits/replacements invalidate it. Bounded receipts make lost-response retries exact. Up to 200 skills and 100 complete requirements retain source/category/origin and alternative-group metadata. Generic eligibility/location requirements remain unresolved context, without invented CV facts. Older UUID target snapshots remain historical data; production does not expose a second active `/targets` workflow.

## Saved CV context — J08 / J09

`GET /api/v1/career/context` lists available CV context; `/context/assessment` checks whether owned saved CV skill input is available. This does not compute mastery, skill gaps or readiness. Reads forward the owner's revocable session to CV and verify detail identity/owner. The adapter accepts the saved `{cvs, selection}` API and legacy read responses, preserving UUID/ObjectId references, unknown proficiency, attribution, guidance and evidence. Continuation cursors retain older CV choices within one bounded 512 KiB list budget.

Career's CV transport/projection intake is bounded at **512 KiB**, separately from CV's larger storage limit. Oversized input returns an actionable error and is never truncated. Internal projection schema is [career-cv-snapshot.schema.json](../../contracts/api/models/career-cv-snapshot.schema.json); the public CV response remains [cv.schema.json](../../contracts/api/models/cv.schema.json). Original `skill:*` source identities are not automatically equivalent to Career's dotted registry: future analysis must resolve mapping explicitly.

## Discovery and public research — J08 / J10 / J12 / J13

`/api/v1/career/discoveries` provides conversational direction setting, explicit area approval and researched requirement review without requiring a CV. It publishes through the same canonical goal store. See [CAREER_DISCOVERY.md](CAREER_DISCOVERY.md) for exact session/message/research routes and models.

`GET` / `POST /api/v1/career/goals/{id}/opportunity-research` read/start/reuse/refresh owner-linked public research, with independently saved category outcomes. Interviews, internship experience, career progression/conversion salary, historical conversion rates and culture retain citations, uncertainty and missing fields. Progress is compact and evidence loads on demand. See [OPPORTUNITY_INTELLIGENCE.md](OPPORTUNITY_INTELLIGENCE.md) and [ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md) for graph, models, bounded Gemini/Brave retrieval and version/quota recovery.

Private research links and retry receipts bind the goal revision and public context. Default reads exclude older links after an edit; explicit historical IDs remain readable. Legacy unversioned links need refresh after the first goal revision. Chat and summary quota waits recheck the current workspace at least every five seconds before any further model call.

Saved-goal Q&A uses backend topic routing and allowlisted projected facts. Explicit further-research requests may start scoped public retrieval. Private CV evidence and personal chat are excluded from shared research. Unknown information stays unknown; no assessment computation or roadmap is generated.

## Access and setup

Every endpoint requires a verified account and completed canonical onboarding. Owner checks and no-store responses apply to private data. Services use authenticated APIs rather than foreign MongoDB collections. Environment files remain private and must be configured by the user; agents use synthetic settings. See [application setup](../../docs/setup.md), [OpenAPI](../../contracts/api/career.yaml) and [tests](tests/README.md).

Canonical writes retain namespaced `create_key` metadata to coexist with the legacy unique index. History filters record shape explicitly. No index drop, destructive data migration or automatic conversion of older target snapshots occurs. Gap analysis and roadmap generation remain planned.
