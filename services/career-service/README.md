# Career service

Interprets job descriptions, explores career directions and researches interviews.
Each account has one live career goal and conversation. Validated changes become
the latest goal automatically; a new extracted JD replaces the conversation.

## JD inputs — J01/J06/J07

- `POST /api/v1/career/imports/url` — Prepare an editable public job-page preview.
- `POST /api/v1/career/imports/document` — Read a PDF/DOCX/TXT file up to 10 MiB.

Previews call no AI and write no database records. JD input is capped at 8,000
characters; original documents and full extracted text are transient.

## Single career goal and chat — J02–J05/J09

- `GET /api/v1/career/workspace` — Open the account's latest goal and processing state.
- `POST /api/v1/career/workspace/jd` — Extract a new JD, save it as current and start interview research. Requires a UUID idempotency key.
- `PATCH /api/v1/career/workspace/review` — Save/reset structured details, skills and conditions, immediately updating the current goal. Requires session ID, expected review version and UUID idempotency key.
- `POST /api/v1/career/workspace/messages` — Ask scoped questions about the saved role, requirements and interviews. Clear questions use focused retrieval; ambiguous ones use a small router. Explicit skill edits use a separate model contract.
- `POST /api/v1/career/workspace/retry` — Resume expired work or retry failed research.

LangGraph validates extraction, reuses or acquires interview evidence, then enables
chat. The initial explanation is built from saved fields without another model call. It
covers role scope, high-level skills, supported interview stages and an explicitly
sourced round count (unknown otherwise). Unknown stages remain unknown. No confirmation button or
conversation selector is used. Each AI request is capped at 4,000 estimated input tokens, and each user has a rolling
7,000-token input/output allowance. Calls may proceed while usage is below 7,000;
output is not reserved. Limit errors explain shortening versus timed retry. Workspace responses include
`error_code` for background failures; the UI shows token-limit messages while keeping
other diagnostic details in Network responses. Provider
quotas remain separate; task output caps and timeouts still apply. Goal versions remain immutable internally; late
results and requests for replaced sessions cannot overwrite the current goal.

Importance distinguishes required, preferred, unspecified, conflicting and advisory;
legacy essential means required. Evidence/origin, stable identities and AND/OR
alternatives survive edits/reset. The small [skill registry](app/data/skill-registry.json)
maps known aliases; unknown skills remain pending for future gap analysis.

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

## Interview evidence — J12/J13

Brave is the sole API used to acquire public interview evidence. Research uses a
60-second execution budget and at most one extra search round. Quota waiting
pauses the workflow and may extend elapsed time. The UI shows partial coverage,
failures and unknown findings; anecdotes never become employer requirements.

- `GET /api/v1/career/goals/{id}/interview-research` — Read linked research; `research_id` pins an exact version.
- `POST /api/v1/career/goals/{id}/interview-research` — Compatibility API for explicit research/reuse on the current goal.

Normalized role/company/location/seniority matches reuse seven-day research across
users. Only public evidence is shared; account/CV/chat context is excluded.
Brave `answers` is the default and requires an Answers-plan API key. It asks a targeted
role/company/location question, keeps a bounded AI summary with linked citations, and
extracts structured interview findings. Groq receives compact evidence entries and
returns skill/stage fields with an evidence reference; Career restores source IDs and
summary attribution itself and validates claims before saving. Unattributed summary
prose cannot establish interview requirements. The UI labels summary-derived findings as
Brave AI synthesis; source excerpts remain separate. Up to six cited sources are kept.
`search` remains an explicit snippet-only alternative. Cache policies separate modes;
older research stays readable. Failures distinguish missing runtime configuration, denied
access, quota/billing, rejected parameters, network errors and invalid responses without
showing credentials or provider response bodies. Recognised Brave error codes
(such as `RESOURCE_NOT_ALLOWED`) and validated field names are included in failures;
HTTP 400 alone does not establish that a request parameter is wrong. Environment changes require recreating
the career-service container; hot reload alone does not reload its environment.

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
