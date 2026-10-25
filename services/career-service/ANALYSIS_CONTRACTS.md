# AI and MongoDB contracts — SCRUM-282 / SCRUM-310

J08 exploration and J09 confirmation now use these foundations. Career connects
to its scoped MongoDB database; external AI is called only for explicit exploration
turns after consent and explicit JD extraction/review requests. Temporary import
previews make no AI calls. The adapter remains
available as `app.state.ai`.

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
- Confirmed goals and analysis/research records are immutable revisions. Exploration
  drafts and requirement reviews in the same `career_goals` collection are explicitly mutable and versioned. Allocate a new ObjectId for a new
  revision and pin its exact ID and version; a retry uses the same ID and payload.
  The `_id` unique index rejects conflicting retries. Owner/time indexes support
  private reads; research has context/time and unique context/version indexes.
  `GoalStore` installs owner/time/draft indexes at startup; other workers call their own `ensure_indexes()` when connected.
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
  name requires review/mapping. The small application-owned `app/data/skill-registry.json`
  supplies explicit name/category aliases under `skills-v1`; it is not a global dataset.
  Review and pending-goal skills may have null skill IDs, with stable per-item IDs.
  Ready goals require mapped IDs; `validate_inputs` rejects pending goals.
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
provider and schema provenance are stored with validated results. There is no destructive migration, existing-data rename or collection deletion.
J08 stores its bounded answers/turns directly inside `career_goals` draft records;
the older optional exploration repository is not used by these routes. `career_state`
is operational per-owner selection metadata, including expected version, bounded
idempotency receipts and a dependent-results review flag.

## Groq adapter

The HTTP client speaks OpenAI-compatible Chat Completions and returns application
models, never provider response objects. Default base URL:
`https://api.groq.com/openai/v1`. Supported internal stages: `extraction`, `chat`,
`guidance`, `research`, `gap_analysis`. `AIInput` contains transient inputs;
`Operation` carries owner/revision/stage and optional pinned versions.

Handlers verify session/onboarding/ownership and explain that selected
content will be sent to the configured external AI provider before a user
operation calls `generate`. Future integrations must supply `current_revision` and, for
analysis, `current_versions` callbacks, discard cancelled/stale completions, then
validate again at the persistence boundary. No source content is logged. Import previews send nothing to Groq. Extraction is an explicit action with a
provider disclosure; exploration has explicit consent.

| Settings | Default / purpose |
|---|---|
| `AI_ENABLED` | `false`; previews work with no key |
| `AI_PROVIDER`, `AI_BASE_URL` | `groq`, Groq HTTPS API URL; provider identity and endpoint |
| `AI_MODEL`, `AI_API_KEY` | Empty; required when enabled, backend only |
| `AI_RESPONSE_MODE` | `json_object`; alternatives `json_schema`, `json_schema_strict` when supported by the selected model |
| `AI_TOKEN_PARAMETER` | `max_completion_tokens`; compatible providers may require `max_tokens` |
| `AI_TIMEOUT_SECONDS`, `AI_RETRIES` | 45-second overall provider budget; one retry for 5xx, at most two configurable; no automatic 429 retry |
| `AI_MAX_OUTPUT_TOKENS`, `AI_CONTEXT_TOKENS` | 4096 and 65536; choose limits supported by your model |
| `AI_REQUESTS_PER_MINUTE`, `AI_CONCURRENCY` | Ten per user/minute; two concurrent requests per process and one per user |

Input budgeting conservatively counts UTF-8 prompt/schema bytes plus reserved
output tokens and a safety margin of at least 1,024 units or 10% of the configured
context window. This byte-based estimate is a guardrail, not an exact tokenizer.
When a request is too large, the adapter removes the oldest conversation messages
first, preserving the current user message. It then shortens eligible free-text
values in structured context and marks that context as truncated. It never clips
the source JD or current user message; requests that still exceed the budget fail
with `context_limit`. Provider responses are bounded to 128 KiB. Strict JSON,
application schemas, stop reason, known skill IDs and source provenance are checked
locally in every response mode.
Timeouts, auth/configuration faults, busy/rate limits, malformed output, stale
inputs and cancellation have safe error codes and never replace a prior result.
Provider `model_not_found`/`model_decommissioned` errors become `model_unavailable`;
`json_validate_failed` becomes `invalid_output`, rather than a model-setting error.
Only known error codes are mapped from bounded response bodies. Provider messages
and generated error text are never exposed. Model availability must be checked
against the configured account, not assumed from a public model catalogue.
JD extraction, explanation and skill-edit steps on Groq GPT-OSS 20B/120B upgrade
`json_object` to native strict schema output. Other models/stages and explicit
schema modes keep their configured mode. Pydantic and stage-specific validation still apply.
A failed JD extraction gets at most one correction request within the same overall
timeout, operation and concurrency slot. It receives only safe validation categories
and known field names, never the previous raw response or error values. HTTP retry
limits still apply per request. No provider/model fallback is used.
Transient JD interpretation accepts bounded supporting summaries instead of requiring
verbatim quotes. Stated requirements retain required/preferred priority; reasonable
inferences are labelled suggested guidance with their rationale, never employer facts.
Canonical publication/research contracts retain their separate provenance rules. Error responses expose only a fixed reason and schema field names;
no source, provider body, credentials or validation input is logged or returned. Retry failed
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

## J08/J09 lifecycle

Exploration drafts use `record_type=exploration_draft`, structured topic answers
(answered/partial/skipped), structured interests/preferences, bounded conversational turns,
role suggestions with rationale/uncertainty, generation provenance and optional CV
reference. They use no separate domain collection. The latest 30 turns are stored,
with a total-turn counter; conversations can continue beyond that window. Each AI
request includes the latest 12 turn pairs plus structured context.
A temporary attachment's text stays in request/browser memory; only filename/hash
and resulting bounded structured progress survive. Reattach the same text on resume.
Saved-CV context is fetched through authenticated CV APIs and its exact versions are
checked before/after generation. It is optional and never selected implicitly.

Message writes use a per-draft 75-second processing lease and version compare-and-swap.
Lost-success retries return stored progress; expired leases recover after a worker
crash. Failure leaves the previous successful draft intact. No AI call changes a
selected goal. Confirmation copies reviewed metadata into a distinct immutable goal
revision, then changes per-owner selection using compare-and-swap. A competing
confirmation may leave an unselected record, but cannot replace the winning target.
Idempotency receipts are bounded to 100 turns/100 confirmations; clients use fresh UUIDs.

Backend-required topics are aspirations, education, personal experience/contribution,
skills, interests and preferences. These are coverage requirements, not a fixed
question sequence. The model chooses a follow-up for an unresolved topic and can
update several topics from one reply. Each update cites an exact quote from the
current user message; vague/partial answers remain unresolved. Unknown/skip counts
as explicitly addressed, not as a fact about capability. Role/field are required at confirmation; company/context may
remain null. New goals are `readiness=pending` until J03/J10 supplies validated skill
requirements. No-CV exploration does not create a fictional `cvs` document or enable
CV-based gap analysis. Existing raw-JD non-persistence constraints still apply.

## J02–J04 saved requirement reviews

The frontend uses one `/career-goal/chat` route, with `review={id}` for reload and
resuming. Explicit extraction sends transient JD text to the AI and stores only
its bounded structured interpretation in a `record_type=requirement_review`
document in `career_goals`. It records content, original structured baseline,
metadata origins, generation provenance, source kind/hash and item identities.
Raw sources, uploads and JD chat transcripts are never persisted.

`PATCH /goals/{id}/review` atomically updates metadata, skills and non-skill
conditions using owner/version checks and bounded idempotency receipts. Unchanged
saves do not advance the version. Reset can restore metadata or all extracted
fields without reusing raw text. The frontend also offers local reset and Cancel.
User corrections are tracked separately from extraction; metadata changes set a
requirements-review flag until explicitly acknowledged. URL edits do not silently
rewrite an existing item's supporting source URL. AND/OR groups span skills and
conditions; reclassification preserves item identity. Conditions retain description,
units/ranges and completion/eligibility wording. They do not infer user satisfaction.

Chat uses `review_id` and `expected_version`. The backend loads the owner-checked
context; client-authored context/raw JD is rejected. Before returning, it checks
that the review version is still current. Explanations use the structured role,
responsibilities, skills and conditions with bounded recent browser-held turns.
Employer facts/IDs/provenance stay authoritative when a proposal paraphrases an
unchanged explanation. New facts cannot be promoted to employer requirements;
user additions and guidance remain labelled. Applying a proposal saves a review
version and requires explicit user action. Replies/history are bounded to 4,000
characters per turn, the current user message to 600, and the prompt budget applies.

`GET /goals/{id}` also presents confirmed goals for editing. A changed save forks a
review; it never mutates the immutable goal. The original interests, preferences and
CV/exploration references survive confirmation. `POST /goals/confirm` claims the exact
review version briefly, prepares an immutable structured goal, then uses the existing
selection compare-and-swap/idempotency boundary. Concurrent review writes are rejected
while confirming; failure releases the claim. Selected goals include source-review ID
and version; actual selection changes flag dependent results for review. Current
requirements and conditions are exposed under that same goal revision for G01/G07.
Those analysis endpoints, J10 generation and interview research are not implemented.

Required/optional fields remain Pydantic-validated. Supporting summaries need not be
verbatim quotes. The registry never guesses unknown canonical identities. Empty or
unmapped skills can be saved/confirmed as pending; they cannot enter gap analysis.
Existing records read with additive defaults; no destructive data migration is used.


JD inputs are capped at 8,000 Unicode characters across paste, URL and document
imports; temporary CV previews retain their 20,000-character limit. Native schema
responses carry the schema only in `response_format`; JSON-object mode includes
it in the instructions. Unused AI input defaults are omitted.

Quota failures retain `code=rate_limited` and add `limit_scope` (`user` or
`provider`). Valid cooldowns are returned as `retry_after` seconds and the
`Retry-After` header. Provider 429 responses are not automatically retried.
No provider bodies are exposed. The per-user operation limit is per process;
Groq's organisation/model quotas remain separate. An explicitly configured
`AI_REQUESTS_PER_MINUTE` overrides the default, including in Compose.


### Compact JD model contracts

The provider-facing contracts in `app/ai/jd_contracts.py` are smaller than the
public API and MongoDB models. Extraction returns facts and AND/OR group labels;
Python supplies item identities, source URLs, correction defaults and document
metadata. Nullable/unknown fields and all domain validation still apply. Schema
titles, descriptions and defaults are removed from the provider schema; types,
lengths, enum constraints and strict-object rules remain. No database migration,
HTTP contract change or LangGraph dependency is needed.

Each operation receives a separate prompt: extraction, explanation or editing.
Ordinary JD chat returns only a reply and an edit-intent flag. If it requests a
proposal, a second model call returns retained skill references plus additions;
Python reconstructs unchanged authoritative records. This is one Coachify operation
but two provider requests, within the same timeout/concurrency slot. Failed edit
steps publish nothing. Existing provenance/current-message quote checks apply;
proposals still require explicit user approval. Explanation and editing requests
receive compact structured context, with JSON objects rather than escaped JSON
strings. Only editing receives transient skill references. No raw JD is resent.

The Uvicorn `uvicorn.error.ai_usage` logger emits `ai_usage` events for completed
provider responses that supply numeric usage counters. Events contain the fixed
stage, correction-attempt number, HTTP-attempt number, `prompt_tokens`,
`completion_tokens` and `total_tokens`; they include invalid-output responses too.
No prompts, outputs, model credentials, owner IDs or provider error text are logged.
Missing or malformed counters are ignored; a rejected request without usage has no
measured token count. Sum events to account for additional correction/edit calls.
These are provider-reported tokens, unlike the conservative local byte guardrail.
Output ceilings remain unchanged; actual live savings must be measured with the
configured provider rather than inferred from schema character counts.


### JD output/deadline safeguards

Groq GPT-OSS 20B/120B JD extraction, explanation and editing explicitly use
`reasoning_effort=low` so reasoning is less likely to exhaust the completion budget
before JSON finishes. This setting is not sent to unknown models or compatible
providers. It does not disable reasoning or guarantee a particular token count.
The output ceiling stays at 4,096 by default; no blind increase in quota usage.
Extraction requests compact JSON and short evidence/context while retaining distinct
requirements and alternatives.

The overall default deadline is 45 seconds in Python and Compose (still bounded to
60 seconds by validation and below the gateway's 70-second read timeout). Correction
and edit follow-ups share that deadline. They start only when at least the smaller
of 20 seconds or 75% of the configured deadline remains. Otherwise a specific
`timeout` response preserves inputs/progress without launching a doomed follow-up.
Timeouts, incomplete output and oversized responses have separate readable messages.
Usage logs include allowlisted `finish_reason`, `reasoning_tokens` and `cached_tokens`
when supplied, in addition to existing numeric counters; private content stays out.
If an existing deployment explicitly sets `AI_TIMEOUT_SECONDS=20`, the default change
does not override it: set it to 45 yourself and recreate the Career container.
