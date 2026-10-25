# AI and MongoDB contracts — SCRUM-282 / SCRUM-310

These are internal foundations. Existing HTTP endpoints still provide temporary
previews only. No chat, extraction, research or analysis endpoint is added here,
and no live AI call or database connection occurs at startup. The adapter is
available as `app.state.ai` for future authenticated handlers.

## Ownership and identities

| Logical collection | Authority | Contract |
|---|---|---|
| users | Existing Profile `accounts` and session API | Existing account UUID; no new users collection or auth migration |
| cvs | CV service | `app/schemas/cv.py` in CV; Career consumes a matching API snapshot |
| career_goals | Career | `CareerGoal` in `app/schemas/analysis.py` |
| interview_research | Career | `InterviewResearch`; reusable public context only |
| skill_gap_analyses | Career | `SkillGapAnalysis`; private, pinned source versions |

`user_id` is the **UUID string returned by Profile's authenticated session API**,
not Profile's private `owner` field or Mongo `_id`. Domain document `_id` values
are BSON ObjectIds, represented as lowercase 24-character strings in JSON. `users`
is a logical diagram name; do not rename Profile's collections. Pydantic contracts
reject extra fields, constrain arrays/text/counts and preserve null proficiency.
Published date uses `published_date`, matching the embedded-object UML.

[JSON Schema artifacts](../../contracts/api/models/) describe these records, not
new HTTP endpoints or automatically installed MongoDB validators. Contract tests
check that the CV-owned model, Career boundary snapshot and exported artifact
agree. Run service tests separately: their `app` packages are independent.

## Storage and publication rules

- `AnalysisRepository` writes Career-owned data; `CvRepository` writes CV-owned
  data. Neither queries a foreign database. Their constructors take a configured
  service-scoped PyMongo database; they do not read credentials or provision users.
- Domain records are immutable revisions. Allocate a new ObjectId for a new
  revision and pin its exact ID and version; a retry uses the same ID and payload.
  The `_id` unique index rejects conflicting retries. Owner/time indexes support
  private reads; research has context/time and unique context/version indexes.
  Call `ensure_indexes()` when wiring each future persistence worker.
- Before analysis publication, `validate_inputs` / `validate_analysis` require
  authenticated, owner-checked CV and Profile **API snapshots**, a Career-owned
  goal and research snapshots. They validate existence, successful extraction,
  exact versions, skill mapping, context and referenced skills. Re-read versions
  immediately before publication; cross-service changes cannot be made atomic by
  MongoDB foreign keys. Later reads must compare current versions to these pinned
  snapshots and expose stale status rather than reinterpret stored results.
- `supported`, `partial`, `uncertain` and `confirmed_shortfall` are per-skill
  outcomes. Unknown proficiency cannot establish confirmed shortfall. Separate
  arrays retain job and interview gaps. Missing/failed research requires an
  explicitly partial run; successful `no_findings` research remains distinct.
- Skill IDs use explicit namespaces (`language.python`, `tool.python`) and a
  versioned alias registry; identical display names do not imply the same skill.
  The adapter accepts only canonical IDs supplied by the caller. An unrecognized
  name requires review/mapping; this task does not invent a global skills dataset.
- Research reuse keys normalize company/field/role/location/seniority, including
  null company. Reuse requires a caller-selected freshness policy and current
  mapping version; these schemas do not fetch websites. Workers must assign
  source IDs and deduplicated report groups before synthesis. Model URLs are
  not retrieval evidence. Shared records reject private identity/chat/CV fields;
  the research AI request permits only public context and retrieved sources.
- Evidence is at most 600 characters per item; each document is at most 512 KiB.
  No `source_text`, raw JD, extracted document text or original file bytes are
  accepted in stored domain contracts. Bounded quotations are allowed; callers
  must not disguise full descriptions as evidence or split them across items.
- CV original storage is optional and private. `file_url=null` is normal after
  original cleanup; any retained reference must use `private://`, `s3://` or
  `gs://` with access enforced outside this schema. No public permanent CV URL or
  new retention period is introduced. Original extraction and user-declared
  contribution remain separate fields; the user's declaration needs no proof.

Private `exploration_sessions` and `ai_operations` are operational collections,
in addition to the five logical domain collections. They store bounded app-owned
chat/preferences, selected goal references and safe operation metadata. They have
owner-scoped reads and version compare-and-swap writes; terminal operations cannot
be overwritten by late completions. Never copy raw JD buffers into private chat
history. Sources/prompts are in request memory, while prompt **versions**, model,
provider and schema provenance are stored with validated results. There is no
migration, existing-data rename, collection deletion or new runtime DB connection.

## Groq adapter

The HTTP client speaks OpenAI-compatible Chat Completions and returns application
models, never provider response objects. Default base URL:
`https://api.groq.com/openai/v1`. Supported internal stages: `extraction`, `chat`,
`guidance`, `research`, `gap_analysis`. `AIInput` contains transient inputs;
`Operation` carries owner/revision/stage and optional pinned versions.

Future handlers must verify session/onboarding/ownership, explain that selected
content will be sent to the configured external AI provider, and require a user
operation before calling `generate`. They must supply `current_revision` and, for
analysis, `current_versions` callbacks, discard cancelled/stale completions, then
validate again at the persistence boundary. No source content is logged. Existing
preview UI sends nothing to Groq, so no consent UI is added to that inactive flow.

| Settings | Default / purpose |
|---|---|
| `AI_ENABLED` | `false`; previews work with no key |
| `AI_PROVIDER`, `AI_BASE_URL` | `groq`, Groq HTTPS API URL; provider identity and endpoint |
| `AI_MODEL`, `AI_API_KEY` | Empty; required when enabled, backend only |
| `AI_RESPONSE_MODE` | `json_object`; alternatives `json_schema`, `json_schema_strict` when supported by the selected model |
| `AI_TOKEN_PARAMETER` | `max_completion_tokens`; compatible providers may require `max_tokens` |
| `AI_TIMEOUT_SECONDS`, `AI_RETRIES` | 20-second overall provider budget; one retry for 429/5xx, at most two configurable |
| `AI_MAX_OUTPUT_TOKENS`, `AI_CONTEXT_TOKENS` | 4096 and 65536; choose limits supported by your model |
| `AI_REQUESTS_PER_MINUTE`, `AI_CONCURRENCY` | Six per user/minute; two concurrent requests per process and one per user |

Input budgeting conservatively counts UTF-8 prompt/schema bytes plus reserved
output tokens; oversized context is rejected rather than truncated. Provider
responses are bounded to 128 KiB. Strict JSON, application schemas, stop reason,
known skill IDs and source provenance are checked locally in every response mode.
Timeouts, auth/configuration faults, busy/rate limits, malformed output, stale
inputs and cancellation have safe error codes and never replace a prior result.
No provider fallback or unsupported options are silently enabled. Retry failed
operations with a new ID; preserve the last validated result.

Limits are **per API process**. Before adding workers/replicas, shared quotas,
concurrency and operation publication must be coordinated at the orchestration
boundary. Database reference checks do not authenticate a caller by themselves.

Groq's [compatibility guide](https://console.groq.com/docs/openai) and
[structured output guide](https://console.groq.com/docs/structured-outputs)
describe supported request fields and model-dependent capabilities. Provider
changes can require capability adjustments; compatibility is not a guarantee.
All automated tests use synthetic data and a fake HTTP provider, with no API key
or paid calls. `MONGODB_TEST_URI` enables disposable repository integration tests.
