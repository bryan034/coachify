# Career service

Career owns transient job inputs, the account's canonical goal and guided chat, conversational discovery and cited public research. JD intake and discovery share the same structured goal persistence path. Configured Gemini/Brave access is required for live interpretation and research; previews make no model calls. Synthetic tests do not establish live quality or provider cost.

## JD inputs — J01 / J06 / J07

Pasted text stays in browser memory until explicitly submitted for extraction. `POST /api/v1/career/imports/url` and `/imports/document` return bounded temporary previews; `/explorations/cv/document` supplies optional temporary CV context. Inputs and originals are not retained as raw JD/CV text. URL/document safeguards are detailed in [SPECIFICATION.md](SPECIFICATION.md).

## Canonical goal and chat — J02–J05 / J09

- `GET /api/v1/career/workspace` returns one owner-scoped saved workspace; `/workspace/progress` supports lightweight polling.
- `POST /api/v1/career/workspace/jd` starts or reconnects to versioned JD intake. A validated identity overlaps full extraction with public-only retrieval. Successful extraction saves the goal; combined chat output waits for extraction and research to complete.
- `POST /api/v1/career/workspace/summary` generates a concise Gemini overview from the saved goal and finished revision-linked research, including partial reports with explicit limitations. It supports the same owner-scoped background operations and snapshot retries.
- `POST /api/v1/career/workspace/messages` asks scoped questions or refines the current goal. Ambiguous edits retain a private pending question; valid edits save with owner/version checks and retry receipts.
- `/api/v1/career/goals` and `/goals/current` expose canonical structured history/current state. Goals edit in place with versions. A replacement becomes current only after validated saving.

Observed progress describes completed/running stages, never hidden model reasoning. Temporary chat/workflow context and 24-hour checkpoints are distinct from persistent goals and immutable research. Older compatibility review/guidance endpoints remain available as described in [ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md).

After extraction and research finish, chat automatically loads the saved report and presents a concise overview as short, single-idea paragraphs with bold topic labels (for example, **Field:** and **Required skills:**), ending with “Ask me anything about this goal set!” Finished partial reports retain explicit limitations. Saved goal cards are available immediately after extraction, while the composer waits for the combined response.

Goal summaries use bounded corrections for invalid model output, with at most six
repairs. Gemini returns plain-text blocks with backend-assigned fact references; Python
escapes model text and attaches only saved source links beside each point. Unknown fact
references fail validation. Follow-up answers resolve inline fact references to saved
links beside their claims; unapproved URLs fail validation.
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

`/api/v1/career/discoveries` provides conversational direction setting without requiring a CV. A clear direction automatically starts research; ambiguous directions receive a focused question. Bounded conversation context supports follow-up chat during research. Reviewed requirements still need explicit confirmation before publication through the same canonical goal store. See [CAREER_DISCOVERY.md](CAREER_DISCOVERY.md) for exact session/message/research routes and models.

`GET` / `POST /api/v1/career/goals/{id}/opportunity-research` read/start/reuse/refresh owner-linked public research, with independently saved category outcomes. Interviews, internship experience, career progression/conversion salary, historical conversion rates and culture retain citations, uncertainty and missing fields. Progress is compact and evidence loads on demand. See [OPPORTUNITY_INTELLIGENCE.md](OPPORTUNITY_INTELLIGENCE.md) and [ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md) for graph, models, bounded Gemini/Brave retrieval and version/quota recovery.

Private research links and retry receipts bind the goal revision and public context. Default reads exclude older links after an edit; explicit historical IDs remain readable. Legacy unversioned links need refresh after the first goal revision. Chat and summary quota waits recheck the current workspace at least every five seconds before any further model call.

Saved-goal Q&A uses backend topic routing and allowlisted projected facts. Explicit further-research requests may start scoped public retrieval. Private CV evidence and personal chat are excluded from shared research. Unknown information stays unknown; no assessment computation or roadmap is generated.

## Access and setup

Every endpoint requires a verified account and completed canonical onboarding. Owner checks and no-store responses apply to private data. Services use authenticated APIs rather than foreign MongoDB collections. Environment files remain private and must be configured by the user; agents use synthetic settings. See [application setup](../../docs/setup.md), [OpenAPI](../../contracts/api/career.yaml) and [tests](tests/README.md).

Canonical writes retain namespaced `create_key` metadata to coexist with the legacy unique index. History filters record shape explicitly. No index drop, destructive data migration or automatic conversion of older target snapshots occurs. Gap analysis and roadmap generation remain planned.
URL previews allow five seconds per network operation and one timeout retry within
a 25-second import budget (30-second worker, 35-second gateway). Timeouts, certificate
failures and other connection errors have distinct messages. Robots checks, validated
public-IP pinning and hostname verification remain enforced; inaccessible sites offer
paste/document actions. Roblox and standard Greenhouse/Lever job links use public,
key-free APIs with validated identity and original-link/API provenance. Other sites
keep HTML/robots extraction; accessible JavaScript shells may use one bounded,
sandboxed Chromium render. Blocked/authentication/challenge pages keep paste/upload
fallback. No preview invokes an LLM. Browser dependencies and container sandbox
settings require a Career rebuild/recreate; see [deployment notes](../../infrastructure/docker/README.md#career-url-preview-browser)
and [preview safeguards](SPECIFICATION.md).

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
uses the existing `CAREER_LLM_API_KEY` and `CAREER_RESEARCH_API_KEY` when `OPPORTUNITY_ENABLED=true`
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
automatic Brave job-listing research after a backend readiness gate, bounded memory
and Gemini skill synthesis. The six clarification topics must be addressed; explicit
unsure/skip answers are accepted, and missing topics are bundled. Role scope can
stay broad without a separate broad-exploration or industry question.
Discovery opens fresh with a fixed Python introduction and no initial AI calls;
the introduction is returned only on fresh opening and excluded from model history; a new
private session starts with the first sent message. Chat remains open during research
and supports source-linked follow-up questions.
Discovery assesses and ranks candidates by relevance and available Brave employer metadata;
faithful paraphrases are accepted and rejected evidence gets one replacement search;
usable sources survive replacement shortfalls, with honest coverage warnings;
truncated extraction batches split without discarding completed source work.
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

## Assessment producer handoff — G01 integration

`GET /api/v1/career/assessment-input` is an authenticated read-only current goal/selection and owner-linked research snapshot. It includes additive canonical skill IDs/registry versions and source-grounded job dates; it never starts a comparison or acknowledges a goal for CV clarification. The separate [Assessment service](../assessment-service/README.md) owns new analyses. Original analysis-v1 schemas remain compatibility contracts.
