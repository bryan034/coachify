# Career service

Interprets job descriptions, explores career directions and researches opportunities.
Each account has one saved goal overview with category cards and one live conversation. Manual changes open guided refinement chat; there is no edit form or Apply button. Validated changes become
the latest goal automatically; a new extracted JD replaces the conversation.

Brave research exclusively calls `/res/v1/llm/context`, including discovery,
interview research and Opportunity Intelligence. Legacy search/answers mode settings
are ignored. Opportunity research retains the best three useful URLs per category
after bounded follow-ups; reaching three initial URLs does not stop a weak search.
Other research uses up to six URLs. Retrieval considers 30 candidates, 8,192 context
tokens, 2,048 per URL and six snippets per URL. Saved evidence allows 8,000 characters
per source for Opportunity and 2,400 for other research, within model budgets.
Gemini 3.5 Flash Lite runs every reasoning/extraction/chat stage. See
[retrieval and evidence parameters](ANALYSIS_CONTRACTS.md).

## JD inputs — J01/J06/J07

- `POST /api/v1/career/imports/url` — Prepare an editable public job-page preview.
- `POST /api/v1/career/imports/document` — Read a PDF/DOCX/TXT file up to 10 MiB.

Previews call no AI and write no database records. JD input is capped at 8,000
characters; original documents and full extracted text are transient.

## Single career goal and chat — J02–J05/J09

- `GET /api/v1/career/workspace` — Open the account's latest goal and processing state.
- `POST /api/v1/career/workspace/jd` — Extract a new JD, save it as current and start interview research. Requires a UUID idempotency key.
- `PATCH /api/v1/career/workspace/review` — Compatibility API for saving structured details, skills and conditions. The app uses chat for edits. Requires session ID, expected review version and UUID idempotency key.
- `POST /api/v1/career/workspace/summary` — Generate a concise Gemini Markdown overview from the saved goal and finished linked research, including partial reports with explicit limitations. Requires session/goal version, research ID and UUID idempotency key; supports background operations.
- `POST /api/v1/career/workspace/messages` — Ask scoped questions about the saved role, requirements and interviews. Clear questions use focused retrieval; ambiguous ones use a small router. Ask for changes to any supported goal field here. The agent asks guided questions until the change is specific, then validates and saves it automatically.
- `GET /api/v1/career/workspace/operations/{operation_id}` — Read an account-owned extraction/chat job and its automatic quota countdown.
- `POST /api/v1/career/workspace/retry` — Resume expired work or retry failed research.

Successful extraction fills the saved goal overview immediately while keeping the user in the chat. Public retrieval overlaps full JD extraction after the identity check. After extraction and research finish, the chat automatically loads the saved report and types a concise Gemini overview as short, single-idea bullets, including the role overview. Finished partial results include their limitations. The overview ends with “Ask me anything about this goal set!” A new JD replaces the entire goal only after successful extraction. LangGraph researches public opportunity evidence. The chat composer opens after the combined response is ready; the underlying saved-goal APIs remain available while research is pending or unavailable; interview claims require saved evidence. The initial explanation is written by Gemini from saved goal fields and completed research; Python validates and restores citations. Temporary observed activity disappears when the answer is ready. Missing details and explicit further-research requests can trigger a focused Brave search selected by Gemini. Public searches use only saved employer/role/location and an allowlisted focus; answers cite retrieved evidence without automatically changing the goal. It
covers role scope, high-level skills, supported interview stages and an explicitly
sourced round count (unknown otherwise). Unknown stages remain unknown. No confirmation button or
conversation selector is used. Every stage uses the server-only `GEMINI_API_KEY`
and `GEMINI_REASONING_MODEL` (default `gemini-3.5-flash-lite`) for every stage. Provider quotas, context/output limits and timeouts still apply.
The app runs JD extraction and chat as background operations:
when a timed quota is reached, the unfinished model step waits and resumes automatically,
with a countdown and no approval or resubmission. Waiting does not consume the model's
execution timeout. Invalid JSON/schema responses trigger automatic corrections in the
failed LangGraph node, with at most six repairs.
The model receives only the latest field/type issues; the UI shows “Refining the response…”. Summary generation uses the same bounded corrections. Gemini returns plain-text points and saved-fact references; Python builds source links beside each point, including saved JD/requirement sources. Unknown references still fail. Model-written links cannot become summary citations. Selected research takeaways require supporting references; the concise overview need not repeat every saved finding. Loading a saved report or retrying summary generation does not restart research.
Failed AI operation responses include `operation_id` and fixed issue codes under
`diagnostic.violations`. Find the ID in the initial 202 response or Network polling URL;
it also appears in content-free failure logs. Operations are held in worker memory
for at most 24 hours, lost on restart, and never stored in MongoDB. Rejected model text
is not retained.
A complete JSON object wrapped only in a Markdown code fence is unwrapped locally,
then passes the same duplicate-key, schema and provenance checks without another call.
Gemini receives an inlined, fixed-shape decoding schema without length/count/range
bounds; the complete original bounds are enforced by backend validation. This avoids
the reproduced nested-schema `400 INVALID_ARGUMENT` rejection without changing saved
goal/research models or retrying without structured output.
Interview synthesis has its own task prompt without unrelated JD/CV instructions.
Corrective calls count toward token usage and quota waits. Only valid output is saved/shown. Input/context-size and configuration failures still stop. API clients
opt in using `Prefer: respond-async` and a UUID `Idempotency-Key`, then poll the returned
operation ID; clients without this header retain synchronous responses.
The same pending JD reconnects to its owner-scoped operation even if navigation
issued a new request key; accepted keys replay the same result. A different active
input returns `409` with `operation_in_progress`; changing an accepted key's payload
returns `operation_key_reused`. These safe conflicts are explained in the UI.
Workspace responses include
`error_code` for background failures; the UI shows token-limit messages and a fixed
`not_configured` explanation while keeping private diagnostics in Network responses. Provider
quotas remain separate; task output caps and timeouts still apply. Current-goal edits use owner/version checks; late
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

## Concurrent JD intake and career-only scope

Gemini first checks job-description scope and evidence-backed public identity, then
full JD extraction overlaps initial public retrieval. The same target persistence
saves validated goals; matching early searches seed the durable research job without
being repeated. Changed identity discards early results, and provider waits are preserved.

Operation/workspace `activities` expose fixed observed steps. Chat shows typed summaries
and stays open; the Career Goal button opens already populated cards. The initial response
and composer wait for both results. Follow-up answers replace internal fact markers with the actual saved links beside each claim. Follow-up questions can use cited company/internship
findings as well as the JD.
Both JD extraction APIs reject unrelated documents with HTTP 422 `career_scope`.
Question/refine paths refuse unrelated tasks and instruction overrides. See the
[concurrency, progress and scope contract](ANALYSIS_CONTRACTS.md#concurrent-jd-intake-progress-and-career-only-guardrails).

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

The configured path starts after goal validation. Gemini plans role-tailored queries, five LangGraph
branches retrieve Brave LLM Context and use Gemini to structure cited findings,
then Python builds overview references from saved findings. Each category saves progress independently;
failed categories retain other results. The overview has expandable Interview Intelligence,
Internship Insights, Career Progression, Historical Conversion Rates and Company and Team Culture with sources/confidence/context, dates,
missing information and targeted refresh. No-company targets research all five categories as explicitly general role context.

Durable jobs and category cache use existing `research_contexts`; typed immutable reports
extend `interview_research`. Worker leases, checkpoint/restart recovery and receipt/version
checks prevent duplicate paid retrieval and stale publication. Gemini structures all categories
against the existing JSON fields and exact citations. See [feature specification, graph, API models, limits and setup](OPPORTUNITY_INTELLIGENCE.md).

Legacy interview endpoints remain readable/compatible:

- `GET /api/v1/career/goals/{id}/interview-research` — Linked exact interview/public research version.
- `POST /api/v1/career/goals/{id}/interview-research` — Explicit legacy research/reuse.

Legacy Search/Answers mode values are ignored. Opportunity Intelligence
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

Gemini 3.5 Flash Lite interprets every saved-goal chat turn using a compact catalogue
(up to 1,800 estimated tokens) and six recent messages (400 characters each).
Python retrieves allowlisted owner-linked records, preserving AND/OR alternatives;
answers receive up to 1,600 fact tokens. The same Gemini model handles comparisons,
goal edits, JD extraction and interview synthesis. Citation and ownership checks
remain mandatory. Ordinary chat performs no new searches; unknown details stay unknown.
`AI_ENABLED` is the master switch; unused provider/model/chat settings are ignored.
No provider fallback exists. All stages default to the explicit Flash Lite model ID
as described in [setup](../../docs/setup.md#gemini-reasoning-configuration).

Ordinary Q&A sends only relevant projected fields and matching facts, without full
research summaries or the edit schema. Location/round-count lookups, missing facts and
clear unrelated requests need no answering call. Ambiguous scope uses a 256-output-token
router; grounded answers use at most 768 output tokens, subject to the existing caps.
Independent questions omit chat history; follow-ups include only two short recent
messages. Unrelated tasks are refused. Q&A never performs another Brave search or
silently edits the goal. JD chat history remains temporary browser memory.

Provider rejections include safe `provider_error` metadata: HTTP status, known
Google code and rejected field names. This distinguishes invalid keys, unavailable
models, project access, schema and parameter failures without revealing provider prose.
See [configuration and rejection diagnostics](ANALYSIS_CONTRACTS.md#safe-gemini-rejection-diagnostics).

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
explicit scope approval, Brave job-listing research and Gemini requirement extraction.
The final review uses the existing review/confirmation APIs and target persistence.
No CV is needed. See [Career Discovery](CAREER_DISCOVERY.md) for exact routes, models,
configuration, evidence rules, recovery and verification. Saved-goal question APIs remain
available while research is waiting; the chat UI waits for combined completion before
opening its composer.


### Compact goal/research responses

The saved content appears once in `current.goal`; edits update the same goal ID/version.
There is no original-content restore action; startup clears its retired stored copies. Poll `/workspace/progress` and
`/goals/{id}/opportunity-research/progress` for lightweight state; load full goal/findings
only when their versions change. Finding evidence is fetched on expansion through
`/goals/{id}/opportunity-research/findings/{finding_id}/evidence?research_id={id}`.
Standard responses omit source excerpts, quotes and duplicate interview structures.
Exact quotes allow whitespace-only normalization. Values may paraphrase cited excerpts
from a single Gemini structuring pass. Source IDs match the cited records exactly, and every
number must occur verbatim in a cited excerpt. Quotes stay separate from displayed text. The final finding wording is shown directly
in chat; no second Gemini grading, rewrite or overview-selection call is made. Generation and storage share label/text rules,
and rejected findings retain precise field-level repair feedback. Missing information
is a successful “not found” result, not a category failure. See [the contract](ANALYSIS_CONTRACTS.md#canonical-goal-and-compact-reads--28-october-2026).

Category outcomes distinguish irrelevant results, absent facts, validation failures
and provider failures. Category refresh preserves cached findings and retained source
links. See [coverage outcomes](OPPORTUNITY_INTELLIGENCE.md#coverage-outcomes-and-follow-ups).
