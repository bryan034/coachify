# Career service

Interprets job descriptions, helps users explore roles, and saves reviewed career
goals. Profile verifies accounts/onboarding; CV supplies owner-scoped saved skills.

## JD input — J01/J06/J07

- `POST /api/v1/career/imports/url` — Prepare an editable public job-page preview, including available company/location metadata.
- `POST /api/v1/career/imports/document` — Read a PDF/DOCX/TXT file up to 10 MiB.

Previews make no AI calls or database writes. Pasted text and original uploads are
transient; only later structured interpretation is saved. JDs are capped at 8,000
characters; oversized content is rejected without truncation. Temporary CV
previews retain their separate 20,000-character limit.

## Role, skills and conditions — J02/J03/J04

- `POST /api/v1/career/jd/extract` — Interpret a reviewed JD and save a private structured review. Returns `review_id`, version, extracted values and reset baseline.
- `GET /api/v1/career/goals` — List confirmed goals, saved reviews and exploration drafts.
- `GET /api/v1/career/goals/{id}` — Open a saved review or an editable view of a confirmed goal.
- `PATCH /api/v1/career/goals/{id}/review` — Save role details, skills and conditions together, or reset metadata/all fields to the baseline.
- `POST /api/v1/career/jd/messages` — Explain the saved review identified by `review_id` and `expected_version`, or propose skill changes for approval. No raw JD or client-authored context is accepted here.

The shared chat page supports Save, Cancel, Reset, adding/removing items and moving
items between skills and conditions. Item identities and AND/OR groups survive
reclassification. Conditions retain qualification wording, duration ranges and
completion requirements; they never establish the user's legal eligibility.

Supporting evidence can be a faithful summary. Stated requirements, inferred
suggestions and user changes remain labelled. Changing role/context marks its
requirements for review; acknowledgement is required before confirmation. Edits
stay local until saved, and failures preserve them. No-op saves retain the version.

MongoDB stores structured fields, bounded evidence, reset baseline and provenance;
full JD text, originals and JD chat transcripts are not saved. Chat reload starts
from saved context. Editing a confirmed goal creates a review revision and keeps
its history. Only explicit confirmation changes the selected goal.

The backend's small [versioned registry](app/data/skill-registry.json) maps explicit
name/category aliases. Unfamiliar skills remain saved with `skill_id=null`; they
block analysis readiness, not extraction or review. This is not a global skill
catalogue. Employer facts are never generated from the user's CV or role stereotypes.

## Career exploration — J08

- `GET /api/v1/career/context` — Saved CV options and AI availability.
- `POST /api/v1/career/explorations` — Start a private draft after AI-processing consent.
- `GET /api/v1/career/explorations/{id}` — Resume structured progress.
- `POST /api/v1/career/explorations/{id}/messages` — Answer, skip or refine with the agent.
- `POST /api/v1/career/explorations/cv/document` — Read an optional temporary CV attachment.

CV use is optional and explicit. The UI recommends dedicated CV extraction and
warns that this goal-focused model may interpret current skills less accurately.
Vague answers stay unresolved; unknown/skip is allowed. Suggestions require
confirmation; J10 role-skill generation is still planned.

## Confirm a goal — J09

- `GET /api/v1/career/goals/current` — Selected goal and selection version.
- `POST /api/v1/career/goals/confirm` — Select reviewed metadata/requirements using the saved review ID/version, or confirm an exploration direction.

Replacing a selection requires explicit approval. Saved goals keep reviewed skills,
conditions, provenance and exact source-review version. Unknown mappings, empty
skills or unfinished requirements keep readiness pending. Requirements readiness
is not a claim of job readiness. Research, gap analysis and roadmaps remain planned.

All routes require a verified bearer session and completed onboarding. Extraction,
review saves and confirmation require a UUID `Idempotency-Key`; edits check expected
versions. Responses are no-store. See [API contract](../../contracts/api/career.yaml),
[implementation rules](ANALYSIS_CONTRACTS.md), [input safeguards](SPECIFICATION.md),
[setup](../../docs/setup.md) and [Docker hot reload](../../infrastructure/docker/README.md#hot-reload-during-development).


AI defaults to 10 operations per user per minute. Provider quotas are separate;
quota responses identify their origin and return a retry delay when available.
Provider quota errors are not automatically retried. Explicit configuration
overrides the default. Extraction, explanation and editing use separate compact
prompts/schemas. Ordinary chat uses one call; requested skill proposals use a second
call and still need approval. Numeric `ai_usage` events in Career service logs show
actual input/output/total tokens per response and attempt, without logging content.
Groq GPT-OSS JD calls use low reasoning effort to leave room for structured output.
The default overall deadline is 45 seconds; corrections/edits are skipped when too
little time remains. Explicit settings override defaults. See [AI settings and
usage](ANALYSIS_CONTRACTS.md).
