# Roadmap service

Prepares a personal study roadmap towards the user's career goal. A fixed planner form collects the schedule, with an optional chat helper to guide the user through it. The service calculates the runway, the LLM writes the plan, and the service validates it before the user reviews it. Owns settings, plan revisions, session progress and adviser chat in a separate MongoDB database.

## API by Jira story

| Stories | Available endpoints under `/api/v1/roadmaps` |
|---|---|
| R01 / SCRUM-185–187 | `GET /workspace` restores chat, settings, runway, previews, the active roadmap and change signals. `GET /progress` polls compact operation state. `POST /messages` saves a chat helper message; it updates settings or prepares a preview. |
| D01–D06 / SCRUM-63–68 | `GET /dashboard-source` passively returns the owner’s active roadmap, milestone review, task readiness and workspace version without resuming pending adviser work. The active plan points to its most recently accepted immutable pace baseline, when known. |
| R05–R09 | `POST /planner/runway` calculates runway without a model call. `POST /planner/config` saves settings, including recurring blackout rules. `POST /planner/generate` runs Assessment if needed, then writes and validates a plan or revision. `POST /planner/accept` applies a preview; `POST /planner/discard` removes it. `POST /planner/confirmations` saves self-reported experience answers. `GET /history/{id}` reads an owner-scoped immutable plan, including earlier untimed plans. |
| No Jira story yet | `GET /learning` lists each skill the active roadmap works on, most important first, with sessions done, missed and remaining and its next session. It reads saved data only and makes no model call. |
| E01–E07 / SCRUM-50–56 | `GET /planner/tasks` reads active tasks, optional date range, readiness and scheduling warnings. `POST /planner/tasks/add`, `/edit` and `/remove` change tasks; `/reconcile` resolves possible repeated work in a revision preview. |
| No Jira story yet | `POST /planner/tasks/notes` saves a task's notes document: paragraphs, headings, lists, checkboxes and single-choice questions with bold, italic and underline, validated as data (never HTML) and capped at 300 blocks and 20,000 characters. Notes never change status, evidence or the schedule; a task with notes is protected when the plan is regenerated. Each projected session carries `task_id`. File attachments are not implemented. |
| T01–T06 / SCRUM-57–62 | `POST /planner/tasks/status` starts, completes or reopens a task. `POST /planner/assignments/status` remains available for compatible single-session tasks; `POST /planner/milestones/outcome` records a self-reported outcome. `GET /workspace` restores the active roadmap. None of these actions verifies a capability. |

[Specification](SPEC.md) · [API contract](../../contracts/api/roadmap.yaml) · [Setup](../../docs/setup.md#assessment-and-roadmap-adviser). Removed settings are cleaned from saved records at service start. The frontend task editor, period views, revision-review controls and dashboard are not implemented by this backend work. External calendars, automatic revision and direct session editing (E05) are not implemented. Live-model plan quality has not been evaluated.

Model calls use the shared OpenAI Python SDK transport with Gemini as the cloud
default. No Gemini SDK is required. SDK retries are disabled; existing response
limits, provider quota handling and schema repair attempts remain enforced.

Local testing can use the shared 1.5B Ollama alias through this service's own
`*_LLM_BASE_URL`, `*_LLM_MODEL` and explicit development `*_LLM_ALLOW_HTTP` flag.
Local requests omit stored cloud credentials; cloud requests retain authentication.
JSON/domain validation stays mandatory. See [all-service local setup](../../docs/setup.md#career-model-and-search-configuration).
