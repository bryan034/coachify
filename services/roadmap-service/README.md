# Roadmap service

Prepares a personal roadmap towards the user's career goal, then runs it as a weekly task planner and coach. A fixed planner form collects the schedule, with an optional chat helper. The service owns dates, capacity, progress and projections. The LLM writes gaps, milestones and tasks, and the service validates them before the user reviews them. Owns settings, plans, task history, check-ins and adviser chat in a separate MongoDB database.

## API by Jira story

| Stories | Available endpoints under `/api/v1/roadmaps` |
|---|---|
| R01 / SCRUM-185–187 | `GET /workspace` restores chat, settings, runway, previews and the active roadmap. It also reconciles missed tasks and check-ins, and starts rolling detail when needed. `GET /progress` polls compact operation state. `POST /messages` saves a chat helper message, which can update settings or prepare a preview. |
| R05–R09 | `POST /planner/runway` calculates capacity without a model call. `POST /planner/config` saves settings. `POST /planner/generate` writes and validates a new roadmap in two stages. `POST /planner/accept` applies it and archives the previous roadmap; `POST /planner/discard` removes the preview. `POST /planner/rolling` retries rolling detail. `POST /planner/confirmations` saves self-reported experience answers. `GET /history/{id}` reads an owner-scoped saved or archived plan. |
| T03–T06, E05 | `POST /planner/assignments/status` completes or reopens a task. `POST /planner/tasks/skip`, `/restore`, `/move`, `/update` and `/custom` provide the other task actions. `POST /planner/events/undo` undoes an automatic move. `POST /planner/milestones/complete` and `/outcome` record self-reported milestones. None of these changes the Skills Profile. |
| E01–E07 | `POST /planner/checkins/answer` and `/checkins/propose` run the weekly check-in. `POST /planner/proposals/pause`, `/unpause`, `/pace`, `/edit` and `/scope` prepare previews. `POST /planner/proposals/accept` and `/discard` decide them. |
| Dashboard input | `GET /summary` returns reusable progress, pace and projection data without changing anything. No dashboard widget uses it yet. |

[Specification](SPEC.md) · [API contract](../../contracts/api/roadmap.yaml) · [Setup](../../docs/setup.md#assessment-and-roadmap-adviser). External calendars, reminders and actual-time logging are not implemented. Live-model plan quality has not been evaluated. Jira wording for these stories could not be checked when this was written, so reconcile it with the specification.

Model calls use the shared OpenAI Python SDK transport with Gemini as the cloud
default. No Gemini SDK is required. SDK retries are disabled; existing response
limits, provider quota handling and schema repair attempts remain enforced.

Local testing can use the shared 1.5B Ollama alias through this service's own
`*_LLM_BASE_URL`, `*_LLM_MODEL` and explicit development `*_LLM_ALLOW_HTTP` flag.
Local requests omit stored cloud credentials; cloud requests retain authentication.
JSON/domain validation stays mandatory. See [all-service local setup](../../docs/setup.md#career-model-and-search-configuration).
