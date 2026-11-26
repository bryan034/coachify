# Roadmap service

Prepares a personal study roadmap towards the user's career goal. A fixed planner form collects the schedule, with an optional chat helper to guide the user through it. The service calculates the runway, the LLM writes the plan, and the service validates it before the user reviews it. Owns settings, plan revisions, session progress and adviser chat in a separate MongoDB database.

Free plan: task details are generated only for the first two weeks of the active outline. `POST /planner/weeks/generate` for a later week returns 402 with code `premium_required`, and a queued later week fails with the same code. Weekly objectives stay visible and manual task changes are allowed in every week. A free account generates one roadmap outline, counted across discards and replacements (`planner.first_outline_operation`; rows saved before it count an existing outline or plan). Another `POST /planner/outlines/generate` returns 402 `premium_required`, and an adviser chat turn that would revise the outline fails with the same code. Replaying or retrying the operation that generated the first outline, editing and accepting or discarding it still work.

## API by capability

| Stories | Available endpoints under `/api/v1/roadmaps` |
|---|---|
| R01 / SCRUM-185–187 | `GET /workspace` restores chat, settings, runway, previews, the active roadmap and change signals. `GET /progress` polls compact operation state. `POST /messages` saves a chat helper message; it updates settings or prepares a preview. |
| D01–D06 / SCRUM-63–68 | `GET /dashboard-source` passively returns the owner’s active roadmap, milestone review, task readiness and workspace version without resuming pending adviser work. The active plan points to its most recently accepted immutable pace baseline, when known. |
| R05–R09 | `POST /planner/runway` calculates runway without a model call. `POST /planner/config` saves settings, including recurring blackout rules. `POST /planner/confirmations` saves self-reported experience answers. `GET /history/{id}` reads an owner-scoped immutable plan, including earlier untimed plans. |
| R01 / SCRUM-185–187 | `POST /planner/outlines/generate` previews the full weekly journey and first week together. `PATCH /planner/outlines/{id}` edits the outline; `POST /planner/outlines/{id}/accept` publishes it with the valid first-week preview; `/discard` discards it. `POST /planner/weeks/generate` prepares one subsequent week; `POST /planner/weeks/{id}/carryover` reviews unfinished-work choices; `/accept` publishes the reviewed week and `/discard` removes its preview. Generation uses the operation poll. Legacy and month generation routes are retired; existing accepted work remains readable. |
| No Jira story yet | `GET /learning` lists each skill the active roadmap works on, most important first, with sessions done, missed and remaining and its next session. It reads saved data only and makes no model call. |
| E01–E07 / SCRUM-50–56 | `GET /planner/tasks` reads active tasks, optional date range, readiness and scheduling warnings. `POST /planner/tasks/add`, `/edit` and `/remove` change tasks; `/reconcile` resolves possible repeated work in a revision preview. |
| Task notes | `POST /planner/tasks/notes` saves a task's notes document: paragraphs, headings, lists, checkboxes and single-choice questions with bold, italic and underline, validated as data (never HTML) and capped at 300 blocks and 20,000 characters. Notes never change status, evidence or the schedule; a task with notes is protected when the plan is regenerated. Each projected session carries `task_id`. File attachments are not implemented. |
| T01–T06 / SCRUM-57–62 | `POST /planner/tasks/status` starts, completes or reopens a task. `POST /planner/assignments/status` remains available for compatible single-session tasks; `POST /planner/milestones/outcome` records a self-reported outcome. `GET /workspace` restores the active roadmap. None of these actions verifies a capability. |
| Session planning | `POST /planner/sessions/free-times` and `/backlog-plan` calculate available times and proposed backlog moves without saving. `/move` applies reviewed moves atomically; `/save` edits a session’s name, completion criterion, skills, schedule, notes and self-ratings; `/add` creates a timed or anytime task; `/skip` removes a missed task. Writes use workspace version checks and mutation receipts. |
| Checkpoints | `POST /planner/milestones/checkpoint` records or clears a self-reported checkpoint. Generated milestones include dated checkpoints and sessions include short task names and skill links. |
| Evidence suggestions | `GET /planner/evidence-proposals` lists completed-session notes that could become Skills Profile evidence. `POST /planner/evidence-proposals/{proposal_id}/confirm` writes one to Profile only after explicit confirmation. |

New and edited task titles accept 1–19 whitespace-separated words and at most 160 characters. Existing titles remain readable; scripts without word-separating spaces are limited by characters.

[Specification](SPEC.md) · [API contract](../../contracts/api/roadmap.yaml) · [Setup](../../docs/setup.md#assessment-and-roadmap-adviser). Removed settings are cleaned from saved records at service start. The roadmap UI provides Today, Week, Month, Milestones and Progress views, an editable task panel, backlog proposals and automatic activation after creation. Legacy preview APIs remain available. After two invalid outline attempts, invalid requirement-reference rows can be removed to produce an explicitly labelled partial preview; other validation remains strict. External calendars and automatic revision are not implemented. Live-model plan quality has not been evaluated.

Model calls use the shared OpenAI Python SDK transport with OpenRouter as the cloud
default. No provider-specific SDK is required. SDK retries are disabled; existing response
limits, provider quota handling and schema repair attempts remain enforced.

Each service has its own `*_LLM_BASE_URL`, `*_LLM_MODEL` and `*_LLM_API_KEY`;
`*_LLM_ALLOW_HTTP` permits plain HTTP only for synthetic fixture providers in
development. JSON/domain validation stays mandatory. See [model setup](../../docs/setup.md#career-model-and-search-configuration).

Roadmap reuses the saved current Assessment and Skills Profile judgements. Missing or outdated evaluations need an explicit update; an already-running evaluation can be reconnected. Freshness is rechecked before publication and preview acceptance, and an evaluation without an explicit `current` status is treated as outdated. `allow_partial_assessment` is deprecated and ignored.

Generated tasks have actionable titles under 12 words and a `description` containing numbered steps and practical completion guidance. Descriptions are saved and returned with task and session views; older tasks may have a null description. Existing task edits accept descriptions and enforce the title limit for new or changed titles.

The roadmap UI creates and activates plans in one operation with `auto_accept: true` on outline generation. The first week must validate before activation; failures keep saved tasks and any existing preview intact and can be retried. Clients omitting this option retain the preview lifecycle.

Static analysis: `python -m ruff check app` (unused arguments, nested imports, swallowed exceptions) and `python -m vulture` (unused code) run in CI with `.[lint]` installed. `tests/test_code_rules.py` adds checks they do not cover.
