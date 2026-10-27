# Career service

Prepares temporary job-description previews and saves owner-scoped, reviewed
career targets. Profile supplies authentication and onboarding state; Career owns
structured targets in MongoDB. No AI interpretation or automatic guidance is used.

## Input previews — J01 / J06 / J07

Pasted descriptions stay in browser memory. `POST /api/v1/career/imports/url`
prepares an editable public-page preview; `POST /api/v1/career/imports/document`
accepts PDF, DOCX or UTF-8 TXT up to 10 MiB. Descriptions have a 20,000-character
limit. Previews and originals are temporary; no full source is saved. See
[SPECIFICATION.md](SPECIFICATION.md) for parser and network safeguards.

## Reviewed target context — J09 foundation / SCRUM-310

`GET` and `POST /api/v1/career/targets` list and save structured target drafts.
Lists return 20 targets per page with an opaque `next_cursor`; pass that cursor
to read older targets. `selected_target` always includes the current selection,
even when it is outside the page. Pagination preserves all saved history.
Specific-job skills require a bounded verbatim excerpt from the transient reviewed
JD. Exploration skills are the user's personal guidance, explicitly labelled as
such; they are not generated recommendations or employer requirements.
Optional qualification/date conditions use the same source distinction. Each
names the relevant CV sections and specific subject phrases so clarification can
defer unrelated records. Job subject phrases must occur in the cited JD excerpt.

`GET /api/v1/career/targets/{id}` restores a saved target. `POST
/api/v1/career/targets/{id}/confirm` confirms its reviewed, non-empty set of skills
or qualification/date conditions.
`PUT /api/v1/career/targets/selection` explicitly selects a confirmed version.
Confirmation does not select it automatically. Content is immutable; save a new
target to change requirements, preserving previous snapshots.

`GET /api/v1/career/targets/selected-context` and `GET
/api/v1/career/targets/{id}/confirmed-context?expected_version=N` supply CV with
the authenticated, selected target identity, type, skill IDs, conditions and selection fence.
Stale or unselected context is rejected. Saving/selecting a target never starts or
regenerates an assessment.

## Access, setup and remaining scope

All product endpoints require a verified session and completed initial setup.
Responses are `no-store`; request/source contents are not logged. `MONGODB_URI`
and optional `MONGODB_DATABASE` (default `coachify_career`) enable saved targets.
Missing/unavailable storage returns a recoverable 503 for targets; previews still
work. Run the tests using [tests/README.md](tests/README.md).

AI extraction, AI-generated career exploration, J02–J05 semantic interpretation,
automatic non-skill interpretation, interview research and gap analysis remain
unimplemented. This implements a manual reviewed-context foundation for J09,
not all J09 acceptance criteria. No Groq key is required. See
[setup](../../docs/setup.md) and [API contracts](../../contracts/api/career.yaml).
