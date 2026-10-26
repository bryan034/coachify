# Career workflows, AI and MongoDB contracts

## Current workflow

The single-workspace flow supersedes the earlier user-confirmation/session-picker
behavior. One account owns one current conversation and goal. A new JD is interpreted
and validated before replacing that workspace. Every saved valid edit/advisory skill
update immediately becomes the latest goal; immutable internal versions preserve
analysis references. Existing legacy API routes remain compatible.

`app/workflows/career.py` uses LangGraph for transient JD interpretation/validation,
optional exploration skill generation, research reuse, Brave searches,
evidence assessment, synthesis and publication. `app/workflows/exploration.py` handles
exploratory model turns separately. The shared chat opens its initial explanation
only after structured role skills and successful/no-findings interview research exist.
Technical failure offers retry; no-findings explicitly means insufficient evidence.

A query plan uses public role/field/company/location/seniority. Missing company means
general role research. Answers retains up to six citations; Search returns up to three results per round.
At most six deduplicated sources reach synthesis across the workflow. One additional query round is permitted when coverage is sparse.
Public APIs have bounded timeouts/responses; no page scraping or user-entered research
URLs are used. Answers (the default) asks a natural-language interview question and
retains a summary separately from original citation snippets. Explicit Singapore
location uses SG search scope; other/free-form locations use ALL with the location
retained in the question, avoiding an implicit US search default. Bounded citation offsets
link up to four answer claims to their real sources; missing/invalid offsets are not
guessed. Unattributed answer prose is context only, not evidence for a hiring stage.
Groq extracts source_excerpt findings from source snippets or brave_summary findings
from exact attributed claim text. The model receives a compact evidence list (ref,
origin and text) and returns semantic topic fields plus one evidence_ref. The backend
resolves that reference to verified source IDs, exact evidence and summary attribution;
the model does not copy citation arrays or quotes. Unknown references fail validation.
The persisted contract still stores evidence_origin and summary_id. No AI answer
wording is passed off as a website quotation or verified employer fact. The UI exposes
the summary and original links with explicit labels. Search is a snippet-only option.
Answers uses a 35-second HTTP timeout, bounded output and a 40-second node timeout;
the existing 60-second workflow execution budget remains. A supported summary avoids
an unnecessary second broad query. No silent fallback occurs after denied access. Brave is the sole acquisition API; source pages may include public forum reports.
Historical source/coverage labels remain readable, but the new cache policy does not
reuse mixed-provider or old snippet-only results for Answers. The cache policy includes acquisition mode. No Reddit credentials or direct Reddit API calls are used.
API permission, access and storage rights must cover the deployed use case.

## Focused JD questions

`app/workflows/chat.py` routes JD questions through fixed topic names, projected
MongoDB reads and a small answer contract. Clear questions are routed without AI;
ambiguous questions use `question_route` (256 output tokens) with goal metadata and at
most two short recent messages. Only explicit saved-skill edits use the edit contract.
`focused_answer` (768 output tokens) receives bounded matching facts, not whole goals,
Brave summaries or edit instructions. Questions asking for explanations/evidence may
include up to four matching skills and their supporting excerpts/attributed claims;
other skill questions omit that evidence. Follow-ups include at most
two recent messages truncated to 300 characters each; independent questions include none.
Unrelated tasks and missing facts return fixed messages; location and known round count
can be answered without generation. Model citation refs must resolve to supplied facts;
backend code appends saved source URLs. Answers cannot write goal changes. All model
attempts still share the per-user rolling allowance and per-request input cap.

Interview research includes optional `process`: explicit `round_count`, count evidence
and up to eight sourced stages/assessment types. Round count is never inferred from
stage mentions. Each stage/count resolves to excerpts or attributed Brave claims;
unknown counts remain null. Older records default to an empty process. A new cache
policy refreshes pre-process research on new runs; existing linked records stay readable.
The initial UI overview uses saved fields and needs no additional model call.

## Storage and recovery

Five logical domain collections retain their existing ownership:

| Collection | Authority |
|---|---|
| users | Existing Profile accounts/session API; no new auth collection |
| cvs | CV service, consumed through authenticated API snapshots |
| career_goals | Career structured reviews and immutable current-goal revisions |
| interview_research | Career immutable reusable public-context evidence |
| skill_gap_analyses | Career version-pinned private results; analysis endpoints planned |

Profile account IDs are authenticated UUID strings. Domain record IDs are BSON
ObjectIds, represented as 24-character strings in JSON. Services never query another
service's database. `career_state` atomically holds the one workspace/current-goal
pointer, review version, replacement identity, bounded receipts and stale-dependent flag.
Goal revisions are inserted before pointer compare-and-swap; losing writers cannot
replace the winner. Old revisions remain internal history, not selectable chat sessions.

Operational `career_checkpoints` and `career_checkpoint_writes` hold LangGraph's
resumable state with MongoDB TTL indexes. The application checks a 24-hour inactivity
expiry explicitly; MongoDB physical deletion is asynchronous. Chat activity refreshes
the current thread's checkpoint retention. Expiry discards temporary execution state,
not the saved current goal or research; retry rebuilds from structured records.

Raw JD extraction has no durable checkpointer. Durable graphs contain references,
public scope/evidence and processing status, never raw documents, provider credentials
or JD chat transcripts. JD recent turns stay in browser memory. Existing exploration
stores bounded structured answers and its latest 30 turns; temporary CV text is not saved.
Tracing is disabled for these graph invocations. No LangSmith account or API key is needed.

Background research uses a MongoDB lease across API replicas. A live process resumes
quota pauses from its checkpoint; after restart, reading the workspace can resume
pending work. A 60-second execution budget excludes quota waits. Failure preserves
the latest saved goal. There is no managed queue/worker deployment dependency.

`research_contexts` coordinates seven-day public-context reuse and acquisition leases.
Research results keep exact source references and versions; private per-goal links
constrain reads. Source URLs/excerpts and reposts are deduplicated. Unknown report
independence stays unknown, with no invented counts. `coverage` preserves platform
availability, including on cache reuse. Stage/type/difficulty require support in cited
material; unmapped topics stay readable but cannot enter future gap analysis.

## Structured requirements and comparison

Pydantic rejects extra fields and bounds text, arrays and documents (512 KiB).
Evidence is at most 600 characters per item; do not disguise a full JD as split evidence.
Employer interpretations, generated suggestions and user declarations stay distinct.
`priority_evidence` and `priority_origin` retain importance wording and provenance.
Required/preferred/unspecified/conflicting/suggested are supported; essential normalizes
to required. AND/OR scope, negation, ranges and conditions remain explicit. Conflicting
importance, unknown mappings or unfinished context keep analysis readiness pending.
Valid pending-context edits still become the current goal; a review acknowledgement
is about requirement readiness, not a separate goal-confirmation step. Invalid empty
role/field saves are rejected before changing the draft.
Readiness describes usable requirements, not whether a person is job-ready.

The versioned `skills-v1` registry maps explicit name/category aliases. It is not a
global catalogue. Unknown skill IDs remain null; no skill identity is guessed.
`validate_inputs`/`validate_analysis` enforce owner, exact input versions, context,
matching skill versions and source references. Unknown CV proficiency cannot establish
confirmed shortfall. Job requirements and interview expectations remain separate arrays.
Original CV storage remains private/optional; the Career service consumes effective CV
skills through its API and never reads the CV database.

## AI configuration and provider limits

`app/ai/adapter.py` retains the OpenAI-compatible Groq HTTP interface and compact,
stage-specific schemas. Python owns IDs, source URLs, unchanged items and provenance.
The model interprets/explains; it cannot invent employer requirements or retrieved sources.
JD extraction gets at most one correction. The workspace chat uses one compact
model call for an explanation plus optional referenced skill edits, avoiding an
unfinishable second call under the shared quota. Legacy JD chat may still use one
extra proposal call within its original operation deadline. Prompt/schema output is not logged.

| Process variable | Default / purpose |
|---|---|
| `AI_ENABLED` | false; enable model operations explicitly |
| `AI_PROVIDER`, `AI_BASE_URL` | groq, `https://api.groq.com/openai/v1` |
| `AI_MODEL`, `AI_API_KEY` | Required when AI is enabled; backend only |
| `AI_MAX_OUTPUT_TOKENS` | 4096; overall completion ceiling; chat uses at most 1024 and interview synthesis 2048 |
| `AI_CONTEXT_TOKENS` | 65536; separate model context-window guard |
| `AI_TIMEOUT_SECONDS`, `AI_RETRIES` | 45-second total operation; one bounded 5xx retry |
| `AI_RESPONSE_MODE`, `AI_TOKEN_PARAMETER` | json_object, max_completion_tokens; compatible alternatives supported |
| `BRAVE_API_KEY` | Required for Brave research |
| `BRAVE_SEARCH_MODE` | answers (default), requires an Answers-plan key; search is an explicit snippet-only alternative |

Coachify applies exactly two model-usage limits:

- Each outgoing model HTTP attempt has at most **4,000 estimated input tokens**,
  including system/task instructions, user data, recent turns and response schema.
  `o200k_harmony` tokenizes the serialized messages/schema/tools, with no extra output
  reservation or arbitrary 512-token allowance. This is a local estimate; Groq's
  framing/schema accounting can differ. Older turns and eligible explanatory context
  may be trimmed, but the full JD and current user message are preserved. If the
  request still exceeds the cap, return HTTP 422 `input_limit`: shorten it, rather
  than waiting for a minute refresh.
- Each authenticated user has **7,000 completed input + output tokens per rolling
  60 seconds**, shared across their extraction, research, exploration, chat, corrections
  and retries and across service replicas. Admission checks only whether accumulated
  usage is already >=7,000; it does not reserve the next input or maximum output.
  At 6,999 used, a <=4,000-input call may proceed and take usage over 7,000. Concurrent
  in-flight calls may also cross the threshold; this policy is not a strict spending cap.

`ai_user_usage` stores hashed owner IDs and timestamped numeric usage entries only.
Atomic pipeline appends prevent lost usage across replicas, and a TTL index removes
inactive records; the application explicitly excludes entries older than 60 seconds.
Completed usage is anchored at response time. Valid Groq prompt/completion/total
counters take precedence, including reasoning once. If counters are unavailable,
use tokenized input plus observable answer/reasoning; failed/unknown network outcomes
charge estimated input only, never a possible maximum response. Connection failures before processing and provider 401/403/429
rejections are not charged. No prompts, response text or credentials enter this ledger.

A blocked user receives HTTP 429 `rate_limited`, `limit_scope=user`, and Retry-After /
retry_after giving the seconds until sufficient older usage expires for usage to fall
below 7,000. Each entry expires individually; there is no calendar-minute reset.
The UI shows the wait, preserves the draft and counts down in the JD chat. Background
research pauses and resumes its failed node after this delay. Provider HTTP 429 stays
separate (`limit_scope=provider`) and honors its supplied delay without immediate retry.

There is no fixed requests/minute limit, global 8,000-token gate, maximum-output
reservation or model-call concurrency gate. Legacy AI_TOKENS_PER_MINUTE,
AI_REQUESTS_PER_MINUTE and AI_CONCURRENCY variables remain ignored. Old ai_token_budgets
records remain untouched and unused. The two new limits are constants, not new .env
settings. The Docker image bundles its tokenizer cache to avoid runtime downloads.

Task output caps remain bounded by AI_MAX_OUTPUT_TOKENS: chat 1024, interview synthesis
2048 and JD extraction defaults to 4096. Timeouts, context/input validation, bounded
5xx/correction retries, ownership, authentication, stale-result protection and parser
resource bounds remain. Numeric provider usage logs contain no private text. Graph
memory does not create provider-side memory; nodes send relevant bounded context.
