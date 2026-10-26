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
At most six deduplicated sources reach synthesis across the workflow. Gemini-enabled
Search plans up to four focused queries initially and refines them after evidence assessment.
It requests five results per query and permits at most six distinct searches, stopping at
three useful distinct URLs. The legacy connector/Answers paths retain one extra round.
Public APIs have bounded timeouts/responses; no page scraping or user-entered research
URLs are used. LLM Context is the default and consumes extracted grounding snippets; explicit Search consumes description plus interview-focused extra snippets,
with duplicate URLs/snippets removed and at most 600 characters per source.
Explicit Answers mode asks a natural-language interview question and
retains a summary separately from original citation snippets. Search does not support SG as a country value. Singapore roles use ALL with Singapore
retained in the query, avoiding an implicit US search default. Outgoing Search country
values are checked against its supported enum; unsupported hints fall back to ALL. Bounded citation offsets
link up to four answer claims to their real sources; missing/invalid offsets are not
guessed. Unattributed answer prose is context only, not evidence for a hiring stage.
Groq extracts source_excerpt findings from source snippets or brave_summary findings
from exact attributed claim text. The model receives a compact evidence list (ref,
origin and text) and returns semantic topic fields plus one evidence_ref. The backend
resolves that reference to verified source IDs, exact evidence and summary attribution;
the model does not copy citation arrays or quotes. Duplicate evidence text is removed
and complete evidence entries are selected within a 1,000-token budget; interview-process
entries have priority when the budget is exceeded. Only this selected evidence can be
referenced by model output. Instructions/schema are additional to that budget. Unknown references fail validation.
The persisted contract still stores evidence_origin and summary_id. No AI answer
wording is passed off as a website quotation or verified employer fact. The UI exposes
the summary and original links with explicit labels. The UI uses provider-neutral labels while retaining evidence links and AI attribution.
Answers uses a 35-second HTTP timeout, bounded output and a 40-second node timeout;
the 180-second Gemini-planned/60-second legacy workflow execution budget excludes quota waits and corrective model turns. A supported summary avoids
an unnecessary second broad query. No silent fallback occurs after denied access. Brave is the sole acquisition API; source pages may include public forum reports.
Historical source/coverage labels remain readable, but the new cache policy does not
reuse mixed-provider or old snippet-only results for Answers. The cache policy includes acquisition mode. No Reddit credentials or direct Reddit API calls are used.
API permission, access and storage rights must cover the deployed use case.

## Focused JD questions

`app/workflows/chat.py` routes JD questions through fixed topic names, projected
MongoDB reads and a small answer contract. Clear questions are routed without AI;
ambiguous questions use `question_route` (256 output tokens) with goal metadata and at
most two short recent messages. Explicit requests to change any saved goal field use the guided goal_edit contract. Short answers to a pending edit bypass question routing and use its structured intent/question.
`focused_answer` (768 output tokens) receives bounded matching facts, not whole goals,
Brave summaries or edit instructions. Questions asking for explanations/evidence may
include up to four matching skills and their supporting excerpts/attributed claims;
other skill questions omit that evidence. Follow-ups include at most
two recent messages truncated to 300 characters each; independent questions include none.
Clear unrelated inputs (including bare `weather`/`weather today`) and missing facts
return fixed messages; location and known round count
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
pending work. A 60-second execution budget excludes quota waits and structured-output correction turns. Failure preserves
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
Compatibility APIs retain bounded corrections. App workspace model nodes automatically
repair invalid structured output as described below. Focused Q&A uses a compact router
only when needed, followed by a bounded answer call when saved facts need explanation.
Goal changes use one guided decision call per turn, plus any validation corrections. Legacy JD chat may still use one
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
| `GEMINI_ENABLED` | false; opt into semantic saved-goal chat |
| `GEMINI_MODEL` | gemini-3.5-flash-lite |
| `GEMINI_API_KEY` | Separate, backend-only Gemini API credential; required when enabled |
| `BRAVE_API_KEY` | Required for Brave research |
| `BRAVE_SEARCH_MODE` | llm_context (default); search and answers require compatible API access |

Coachify applies exactly two model-usage limits:

- Each outgoing Groq HTTP attempt has at most **4,000 estimated input tokens**,
  including system/task instructions, user data, recent turns and response schema.
  `o200k_harmony` tokenizes the serialized messages/schema/tools, with no extra output
  reservation or arbitrary 512-token allowance. This is a local estimate; Groq's
  framing/schema accounting can differ. Older turns and eligible explanatory context
  may be trimmed, but the full JD and current user message are preserved. If the
  request still exceeds the cap, return HTTP 422 `input_limit`: shorten it, rather
  than waiting for a minute refresh.
- Each authenticated user has **7,000 completed input + output tokens per rolling
  60 seconds** for Groq only, shared across their extraction, research, exploration, chat, corrections
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
rejections are not charged. Gemini neither checks nor writes this ledger and has no local 4,000-input or 7,000/minute cap; provider quotas, configured context windows, output limits and timeouts still apply. No prompts, response text or credentials enter this ledger.

A blocked user receives HTTP 429 `rate_limited`, `limit_scope=user`, and Retry-After /
retry_after giving the seconds until sufficient older usage expires for usage to fall
below 7,000. Each entry expires individually; there is no calendar-minute reset.
The app automatically waits for both local rolling usage and provider HTTP 429 resets.
`Prefer: respond-async` on workspace JD/message POSTs returns HTTP 202 with an
owner-scoped operation ID. Both require a UUID Idempotency-Key in this mode. Poll
`GET /workspace/operations/{operation_id}` for running/repairing/waiting_quota/succeeded state,
a retry_after countdown, a repairing status with safe validation_feedback diagnostics,
or the validated result. Polling makes no model calls. Failed
jobs return the original HTTP status/code through the normal exception handlers; they
never return unvalidated provider bodies. Without the header, compatibility APIs still
return immediate 429 errors and their retry delay.

The frontend retains the JD request key in its transient career session across
chat remounts. Reposting the identical JD with another key while it is pending
reattaches to the existing owner/kind/digest operation; accepted key aliases replay
that operation's result, without extra extraction calls. A different pending input
returns `409` / `operation_in_progress`; a reused key with changed details returns
`409` / `operation_key_reused`. Only these fixed conflict explanations are displayed;
raw provider diagnostics stay out of the interface. No raw JD is added to storage.

`ai/waiting.py` provides a task-local progress callback. The adapter suspends its active
execution deadline while sleeping, rechecks cancellation/revision, then retries only the
unfinished payload. A quota rejection is not an invalid-output correction attempt and
is not charged to the token ledger. It does not repeat completed routing/retrieval steps.
Foreground jobs run outside gateway HTTP timeouts; the UI waits without another POST or
approval. Research continues to use its MongoDB checkpoint/lease pause path, isolated
from foreground callbacks. Non-resetting input/context/output caps, bad credentials,
invalid JSON and graph recursion failures are not quota waits. JSON failures use the
separate structured-output correction flow below.

Transient extraction/chat jobs and idempotency receipts are worker-local memory only,
expire after 24 hours and are cancelled on shutdown. Raw JD/chat inputs never enter
MongoDB checkpoints. A restart interrupts these jobs; the browser retains its submitted
input while mounted and can retry. This mode uses the current single Career worker;
replicated deployment needs affinity or a shared job registry before distributing polls.
Previously validated current goals/research stay durable throughout waits/failures.

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


## Automatic structured-output correction

`app/workflows/structured.py` wraps the live workspace's JD interpretation, question
routing, grounded answer, skill-edit response and background guidance/synthesis nodes.
A sole enclosing Markdown JSON fence is removed locally before normal validation;
duplicate keys, trailing prose, non-finite values and invalid provenance remain rejected.
Interview synthesis uses its own prompt without unrelated JD/CV instructions.
An invalid JSON object, missing/wrong schema fields, unsupported response references or
truncated JSON keeps that node running. It requests a complete corrected result until
validation passes, the operation expires, input becomes stale, or the task is cancelled.
There is no fixed correction-attempt cap. Credential, input/context-size, storage and
network errors are not blindly retried as formatting errors. Compatibility synchronous
APIs keep their bounded behavior; live workspace POSTs opt in through background jobs.

Each corrective request includes the original node inputs and only its latest safe
feedback: a validation reason, known field names and bounded field paths/error types
(e.g. skills.0.category / missing). Pydantic input values, validator prose/ctx, unknown
extra-field names and failed provider responses are excluded. The response schema and
provenance checks remain authoritative. No failed response is displayed, saved as a goal
or written into checkpoints. Repair prompts replace previous feedback instead of growing
chat history. Retries repeat only the failed node, preserving completed retrieval/search.

Each new model call has its normal execution timeout and existing input/output caps.
Actual token usage is charged for corrective generations; quota errors use the existing
automatic wait/resume flow. Research's 60-second base budget pauses for corrective calls,
while its ownership and acquisition leases are renewed before each retry. Foreground jobs
retain their 24-hour lifetime. Cancellation and current-session/version checks stop
superseded work from publishing. Provider schema rejection without field diagnostics
receives a JSON/schema correction instruction without inventing a field-level cause.

Operation polls expose repairing plus validation_feedback for Network debugging. Chat
shows “Refining the response…” instead of a JSON error or Retry button, then replaces the
activity with the final validated reply. No model reasoning or raw diagnostics are shown.


## Guided career-goal edits

The app replaces the manual editor and proposed-skill Apply button with chat requests.
`POST /workspace/messages` routes edit requests to `workflows/chat.py:edit_goal`.
`ai/goal_edit_contracts.py` defines a decision (clarify/ready/cancel/off_topic), a concise
intent and narrow typed changes. Metadata, skills, non-skill conditions and
responsibilities are supported. Questions about the saved JD/research retain their
focused retrieval path. The edit prompt receives only the current structured goal,
its private pending edit (if any) and current message, never interview evidence or raw JD.

For an unclear request, the agent asks one guided question with useful examples and
stores a bounded intent, proposed changes, latest question and review version under
`career_state.workspace.edit_draft`. It saves no raw chat transcript. A partial edit
never changes career_goals or starts research. Subsequent answers continue the edit
until specific enough; explicit cancellation clears it. GET /workspace exposes only
edit_question for resuming the UI. New JDs and published goal revisions clear the draft.
The workspace's existing 24-hour expiry/ownership/version checks apply.

Ready decisions are validated inside the recoverable LangGraph node before saving.
`domain/goal_edits.py` applies only the requested fields to an owned snapshot. Python
resolves s0/c0/r0 references, allocates new item/group IDs and preserves all other
values, IDs, AND/OR groups and evidence. User changes cannot invent employer provenance:
new/modified content is user-declared, while priority-only corrections preserve original
evidence and record user priority provenance. Manual evidence uses the concise
structured edit intent, so a short final clarification is not mislabelled as the source
of every earlier requested change. Invalid commands or final Pydantic models
use structured-output recovery. Required role/field cannot be cleared. No approval
button is required after a complete request. Edited values/intents are never silently
shortened to fit a model request; existing input/context limits remain enforced.

Validated saves use ReviewStore.save and WorkspaceStore.activate, returning edit_status
and a fresh workspace alongside the chat reply. Goal changes preserve the session and
publish a new immutable current-goal revision. Changed career context retains the
existing requirements_need_review safeguard; acknowledgement is accepted only when
explicitly requested. Research can reuse its context cache, or rerun for a changed target.
The UI refreshes the saved summary and waits for research before accepting another turn.

A message UUID Idempotency-Key is preserved across frontend retries. Published edits
atomically store bounded hash/key receipts in career_state.chat_receipts; replay returns
the current workspace without applying the change again. Receipts contain no transcript
or model reply. Stale session/version requests fail before mutation. The older PATCH
/workspace/review and legacy skill-proposal APIs remain compatibility interfaces.


## Gemini semantic chat

`ModelRouter` sends `context_route` and `context_answer` to Gemini's OpenAI-compatible
endpoint; extraction, interview synthesis, focused reasoning and goal edits retain the
primary provider. No Gemini SDK dependency or new frontend endpoint is required.
Gemini uses `max_tokens`, JSON Schema and `reasoning_effort=minimal`; Groq retains its
own model/key/payload configuration. Only Groq checks and records the per-user usage ledger.
Gemini requests do not consume or wait for the Groq allowance; provider quotas remain independent.

When enabled, `context_chat.py` replaces deterministic keyword routing for saved-goal
chat. Its LangGraph interprets a compact index, retrieves selected facts, then answers.
The index contains metadata plus labels/references for skills, conditions and interview
items, never full evidence, raw JD/CV, account credentials or database IDs. It is capped
at 1,800 estimated tokens; a partial index is labelled. At most six recent messages,
400 characters each, accompany the current question. References are validated against
this exact owner-linked snapshot. A plan cannot supply MongoDB queries, projections,
URLs or arbitrary tools. Ref prefixes determine additional fixed retrieval sections.
Complementary projections are merged without losing source evidence or skill names.
Selected AND/OR groups stay together, facts are deduplicated and capped at 1,600 tokens.
Gemini resolves the current question into a standalone question; the answer receives
only goal metadata and selected facts. Straightforward answers use Gemini; comparisons
and trade-offs use GPT. Both must cite existing fact refs; Python restores source URLs.
Missing/ambiguous context produces a missing-information response or guided question.
Goal-edit intent enters the existing GPT validation/save workflow, including pending
edit questions. No confirmation form, extra research call or provider-side memory is
introduced. Only the current failing node is corrected/retried; quota waiting and
stale/session/ownership checks still apply. Disabled Gemini preserves the legacy route.


## Expanded Gemini-planned interview search

When Gemini and LLM Context (or explicit Search) are enabled, cache → research_plan → retrieval →
research_assess repeats until three useful distinct source URLs or six searches, then
synthesis/publish. Planning/assessment use Gemini Flash-Lite; final evidence extraction
uses the primary model. These model stages accept only public role/company/location/
seniority/field, up to eight public skill-name hints, bounded query history and snippets;
no raw JD, CV, account or conversation context is accepted. The model supplies query
text, never an endpoint/key/HTTP options. Search responses remain bounded to five
results and 600 characters/source. Interview-bearing windows are selected before truncation, including later passages in LLM Context chunks. Assessment sees the complete stored excerpt so supporting quotes are not hidden by a second 180-token cut.

Usefulness requires concrete role/company-related interview stages, rounds, assessments,
tested skills or question patterns. Bare career pages/job adverts do not count. Source
refs must resolve to supplied candidates and include an exact supporting quote from the excerpt. Empty results, missing-key/configuration notices and metadata-only entries never count. Canonical URL/excerpt duplicates are removed;
different URLs do not establish independent authorship. Up to 30 candidates can be
checkpointed, but only assessed useful sources (up to six) reach synthesis/persistence.
Rejected/unchanged sources are not repeatedly assessed. Search/history/assessments are
separate graph nodes so correction or quota waits never repeat a completed search.
The public coverage array supports six rounds and records useful_sources, target_sources
and limit_reached. Fewer than three is explicitly limited coverage, not a fabricated
success. Useful evidence can still be explained; zero useful sources gives no_findings.
Valid limited-coverage/no-findings records are reused for seven days under the current mode/version policy; having fewer than three sources does not force the same searches on every visit. Older extraction policies are refreshed once, while historical records remain readable.
Each active node renews owner/research leases; the graph permits enough steps for all
six searches, stopping sooner after two rounds without new useful sources or when the remaining active budget cannot accommodate another retrieval, assessment and synthesis. Coverage marks a limited result. A later acquisition failure preserves already assessed evidence and its unavailable coverage; a failure without useful evidence remains retryable. API failures still surface safely instead of hammering invalid credentials.
No new environment keys or Google Search grounding charges are introduced; normal
Gemini tokens and Brave Search requests apply. Only Groq synthesis uses the local Coachify token limits.

### LLM Context retrieval

`GET /res/v1/llm/context` considers 20 candidates and requests at most five URLs,
2,048 context tokens total and 512 tokens per URL, with balanced relevance and local
results disabled. Only `grounding.generic[].snippets` supplies evidence; `sources`
provides title metadata. Empty grounding yields no findings; malformed/error envelopes
remain provider errors. Explicit Search and Answers options are not sent in this mode.


## Saved goal overview and assessment handoff

After a validated JD becomes current, `/career-goal` shows its role, summary,
metadata and all skills/conditions grouped by their saved categories. Responsibilities
and sourced interview preparation have separate cards. Unknown findings and research
progress/failure remain explicit; the overview does not wait for interview completion.
`/career-goal/chat?refine=1` opens the existing guided-edit workflow. Replacement
JD inputs use `/career-goal?new=1`; opening/cancelling this view makes no goal write.
The old goal is replaced only by successful extraction.

Authenticated `GET /api/v1/career/context/assessment` uses CV's metadata and
owner-scoped snapshot APIs, never its collection. At most four snapshots are read
concurrently, from the bounded list of 50 CVs. Only a succeeded CV with nonempty
embedded skills establishes `evaluated`. Missing records give `no_cv`; pending,
failed or succeeded-but-empty CVs give `not_evaluated`. Upstream failure gives
`unavailable` and null evaluation, not an empty successful result. Responses expose
only status and presence/evaluation flags, with no-store and the same authentication/
onboarding checks as other Career reads. No selection, gap record, private evidence
copy or new collection is created. Missing/unevaluated inputs offer the `/cv` link;
dedicated CV upload/extraction remains unimplemented, as documented by its owner.


## Opportunity Intelligence extension — current J12/J13 path

The optional typed `InterviewResearch.intelligence` extension, detailed in
[OPPORTUNITY_INTELLIGENCE.md](OPPORTUNITY_INTELLIGENCE.md), supersedes the
interview-only search loop when both configured models and Brave LLM Context are
available. Existing consumers and disabled-provider flows remain compatible.
The graph fans out three independent categories, uses Groq for quoted evidence
extraction and Gemini for planning/validated reference selection, then validates
and persists in its final node. Durable jobs/cache/command receipts reuse
research_contexts; no duplicate domain collection or destructive migration is used.
Employment type is additive structured JD/goal metadata with `unknown` default.
Explicit chat `mode=refine` uses the validated edit workflow without requiring
completed interview research; ordinary questions retain their evidence gate.
Opportunity-specific schema repair/search/retry/deadline budgets are bounded,
while the existing Groq 4k/7k and independent Gemini provider policies remain.
Research uses the configured Gemini key independently of `GEMINI_ENABLED` (chat),
and a dedicated Brave LLM Context client independently of the legacy Brave mode.
`OPPORTUNITY_ENABLED=false` explicitly disables research. Availability diagnostics
use fixed capability codes; they never include environment values or API keys.
Opportunity evaluation cursors and invalid-response repair counts persist across
quota pauses. The workspace propagates category quota/error codes and actual retry
delays. Global timeout, validation and state errors have distinct safe codes and end
the loading state without discarding saved findings.
