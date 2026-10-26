# Career service

Interprets job descriptions, explores career directions and researches opportunities.
Each account has one saved goal overview with category cards and one live conversation. Manual changes open guided refinement chat; there is no edit form or Apply button. Validated changes become
the latest goal automatically; a new extracted JD replaces the conversation.

## JD inputs — J01/J06/J07

- `POST /api/v1/career/imports/url` — Prepare an editable public job-page preview.
- `POST /api/v1/career/imports/document` — Read a PDF/DOCX/TXT file up to 10 MiB.

Previews call no AI and write no database records. JD input is capped at 8,000
characters; original documents and full extracted text are transient.

## Single career goal and chat — J02–J05/J09

- `GET /api/v1/career/workspace` — Open the account's latest goal and processing state.
- `POST /api/v1/career/workspace/jd` — Extract a new JD, save it as current and start interview research. Requires a UUID idempotency key.
- `PATCH /api/v1/career/workspace/review` — Compatibility API for saving/resetting structured details, skills and conditions. The app uses chat for edits. Requires session ID, expected review version and UUID idempotency key.
- `POST /api/v1/career/workspace/messages` — Ask scoped questions about the saved role, requirements and interviews. Clear questions use focused retrieval; ambiguous ones use a small router. Ask for changes to any supported goal field here. The agent asks guided questions until the change is specific, then validates and saves it automatically.
- `GET /api/v1/career/workspace/operations/{operation_id}` — Read an account-owned extraction/chat job and its automatic quota countdown.
- `POST /api/v1/career/workspace/retry` — Resume expired work or retry failed research.

Successful extraction opens the saved goal overview immediately, with separate skill/condition categories and live research status. A new JD replaces the entire goal only after successful extraction. LangGraph researches public opportunity evidence. General research questions open after interview completion; guided goal refinement remains available while research is pending or unavailable. The initial explanation is built from saved fields without another model call. It
covers role scope, high-level skills, supported interview stages and an explicitly
sourced round count (unknown otherwise). Unknown stages remain unknown. No confirmation button or
conversation selector is used. Groq has a 7,000-token per-user rolling-minute input/output allowance. Atomic
in-flight reservations prevent parallel calls from overshooting; unused output capacity
is released on completion. There is no separate 4,000-input cap. Gemini is outside this ledger.
The app runs JD extraction and chat as background operations:
when a timed quota is reached, the unfinished model step waits and resumes automatically,
with a countdown and no approval or resubmission. Waiting does not consume the model's
execution timeout. Invalid JSON/schema responses trigger automatic corrections in the
failed LangGraph node, with at most six repairs.
The model receives only the latest field/type issues; the UI shows “Refining the response…”.
A complete JSON object wrapped only in a Markdown code fence is unwrapped locally,
then passes the same duplicate-key, schema and provenance checks without another call.
Interview synthesis has its own task prompt without unrelated JD/CV instructions.
Corrective calls count toward token usage and quota waits. Only valid output is saved/shown. Input/context-size and configuration failures still stop. API clients
opt in using `Prefer: respond-async` and a UUID `Idempotency-Key`, then poll the returned
operation ID; clients without this header retain synchronous responses.
The same pending JD reconnects to its owner-scoped operation even if navigation
issued a new request key; accepted keys replay the same result. A different active
input returns `409` with `operation_in_progress`; changing an accepted key's payload
returns `operation_key_reused`. These safe conflicts are explained in the UI.
Workspace responses include
`error_code` for background failures; the UI shows token-limit messages while keeping
other diagnostic details in Network responses. Provider
quotas remain separate; task output caps and timeouts still apply. Goal versions remain immutable internally; late
results and requests for replaced sessions cannot overwrite the current goal.

Importance distinguishes required, preferred, unspecified, conflicting and advisory;
legacy essential means required. Evidence/origin, stable identities and AND/OR
alternatives survive edits/reset. The small [skill registry](app/data/skill-registry.json)
maps known aliases; unknown skills remain pending for future gap analysis.

Unclear changes stay in a private structured edit draft; the current goal is unchanged.
The latest question survives reload. Users can cancel a pending edit in chat. Complete
changes update the same conversation, preserve untouched requirements and refresh
interview research as needed. Chat saves use idempotency keys and expected versions.
User corrections remain distinct from employer-provided evidence.

## CV assessment handoff — J09 / CV dependency

- `GET /api/v1/career/context/assessment` — Read whether the owner has a saved CV and nonempty successfully extracted skills, through CV APIs only.

Returns `no_cv`, `not_evaluated`, `evaluated` or `unavailable`, with nullable presence/evaluation flags for unknown upstream state. No private skill evidence is returned. The overview links missing/unevaluated data to `/cv`; an unavailable service offers retry. This does not perform a gap analysis. Dedicated CV upload and assessment remain planned in the CV service.

## Career exploration — J08/J10

- `GET /api/v1/career/context` — Saved CV options and AI availability.
- `POST /api/v1/career/explorations` — Start or resume the one exploration after consent.
- `GET /api/v1/career/explorations/{id}` — Read its structured progress.
- `POST /api/v1/career/explorations/{id}/messages` — Answer, skip or refine with the agent.
- `POST /api/v1/career/explorations/cv/document` — Prepare an optional temporary CV preview.
- `POST /api/v1/career/workspace/direction` — Choose a suggested direction; generate advisory skills and research before continuing the same chat.

Exploration uses a separate LangGraph path. CV context is optional and explicitly
chosen; the UI recommends dedicated CV extraction and explains the temporary
attachment's limitations. Choosing a direction automatically makes it current.

## Opportunity Intelligence — J12/J13

- `GET /api/v1/career/goals/{id}/opportunity-research` — Owner-scoped category status/results; optional `research_id` pins an immutable linked version.
- `POST /api/v1/career/goals/{id}/opportunity-research` — Start/reuse/refresh with expected goal/selection versions and UUID idempotency; optional category refresh.

The configured path starts after goal validation. Gemini plans queries, three LangGraph
branches retrieve Brave LLM Context and use the primary reasoner for cited evidence,
then Gemini selects validated summary findings. Each category saves progress independently;
failed categories retain other results. The overview has expandable Interview Intelligence,
Internship Insights and Company Intelligence with sources/confidence/context, dates,
missing information and targeted refresh. No-company targets skip employer categories.

Durable jobs and category cache use existing `research_contexts`; typed immutable reports
extend `interview_research`. Worker leases, checkpoint/restart recovery and receipt/version
checks prevent duplicate paid retrieval and stale publication. Groq-only local token limits
remain unchanged. See [feature specification, graph, API models, limits and setup](OPPORTUNITY_INTELLIGENCE.md).

Legacy interview endpoints remain readable/compatible:

- `GET /api/v1/career/goals/{id}/interview-research` — Linked exact interview/public research version.
- `POST /api/v1/career/goals/{id}/interview-research` — Explicit legacy research/reuse.

Legacy Search/Answers settings remain supported on that path. New Opportunity Intelligence
uses the existing `GEMINI_API_KEY` and `BRAVE_API_KEY` when `OPPORTUNITY_ENABLED=true`
(default), independently of the Gemini chat switch and legacy Brave mode. It always
calls LLM Context; no silent provider substitution occurs. Availability responses
name the specific disabled/missing capability without exposing configuration values.
Quota pauses retain successful evaluations and resume only unfinished calls; response
repair budgets survive pauses. Workspace errors preserve the actual category/quota
code and retry delay instead of reporting a generic research failure.
Existing saved results remain available if providers fail. No raw JD/CV/chat is added to
shared research, and no personal capability gaps or roadmap are generated.

## Saved-goal questions — J13

With `GEMINI_ENABLED=true`, Gemini `gemini-3.5-flash-lite` interprets every saved-goal
chat turn using a compact catalogue (up to 1,800 estimated tokens) and the last six
messages (400 characters each). It selects application-owned item references by
meaning, resolves follow-ups and asks guided questions for ambiguity. Python retrieves
allowlisted sections and selected records, preserving AND/OR alternatives. Answers
receive up to 1,600 fact tokens, not the full JD, catalogue or chat history.
Gemini answers straightforward questions; the primary GPT model handles comparisons,
trade-offs and validated goal edits. JD extraction and interview synthesis remain on
the primary model. Citation and ownership checks apply to both. No new searches run
for ordinary chat; missing information stays unknown. Gemini failure does not silently
fall back to another provider. Enable with a separate server-only `GEMINI_API_KEY`;
`GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. The
7,000-total/user/rolling-minute admission limits apply only to Groq, including corrections. Gemini neither consumes nor waits for that allowance; its provider quota, context/output limits and timeouts still apply.
Gemini uses minimal thinking and bounded outputs. The compact catalogue is rebuilt
from the latest saved goal; provider memory is not relied upon. Existing goal/edit
state and recent client-supplied messages provide continuity without a new collection.

When Gemini is disabled, the existing Groq-only path remains available.
Ordinary Q&A sends only relevant projected fields and matching facts, without full
research summaries or the edit schema. Location/round-count lookups, missing facts and
clear unrelated requests need no answering call. Ambiguous scope uses a 256-output-token
router; grounded answers use at most 768 output tokens, subject to the existing caps.
Independent questions omit chat history; follow-ups include only two short recent
messages. Unrelated tasks are refused. Q&A never performs another Brave search or
silently edits the goal. JD chat history remains temporary browser memory.

## Compatibility and setup

Older `/jd/extract`, `/jd/messages`, `/goals`, `/goals/current`, `/goals/{id}`,
`/goals/{id}/review`, `/goals/confirm` and `/goals/{id}/guidance` remain available
for existing API consumers. The application uses `/workspace` for automatic saves;
legacy confirmation is not part of the new user flow. There is no destructive migration.

All endpoints require a verified account and completed onboarding. Private reads
are owner-scoped and responses are no-store. See [workflow/storage and API settings](ANALYSIS_CONTRACTS.md),
[preview safeguards](SPECIFICATION.md), [OpenAPI](../../contracts/api/career.yaml)
and [application setup](../../docs/setup.md). Gap analysis and roadmaps remain planned.

## Career discovery — conversational targets

`POST /api/v1/career/discoveries`, `GET /api/v1/career/discoveries/current`, and owned
`/discoveries/{id}` message/research routes implement a Gemini goal-setting conversation,
explicit scope approval, Brave job-listing research and Groq requirement extraction.
The final review uses the existing review/confirmation APIs and target persistence.
No CV is needed. See [Career Discovery](CAREER_DISCOVERY.md) for exact routes, models,
configuration, evidence rules, recovery and verification. Saved-goal questions remain
available while research is waiting; configured research Gemini can handle lightweight
context chat independently of Groq capacity.
