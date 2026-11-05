# Roadmap service

Prepares a personal study roadmap towards the user's career goal. A fixed planner form collects the schedule, with an optional chat helper to guide the user through it. The service calculates the runway, the LLM writes the plan, and the service validates it before the user reviews it. Owns settings, plan revisions, session progress and adviser chat in a separate MongoDB database.

## API by Jira story

| Stories | Available endpoints under `/api/v1/roadmaps` |
|---|---|
| R01 / SCRUM-185–187 | `GET /workspace` restores chat, settings, runway, previews, the active roadmap and change signals. `GET /progress` polls compact operation state. `POST /messages` saves a chat helper message; it updates settings or prepares a preview. |
| E / T Roadmap task backend | `POST /planner/tasks/add` saves a personal or linked task. `POST /planner/tasks/edit` changes task instructions or title; `/reconcile` resolves possible repeated work in previews. `POST /planner/tasks/remove` retains a removal record and leaves dependent work intact. |
| E / T Roadmap task backend | `POST /planner/tasks/add` saves a personal or linked task. `/planner/tasks/reconcile` resolves potentially repeated work in previews. `POST /planner/tasks/edit` changes task instructions or title. `POST /planner/tasks/remove` retains a removal record and leaves dependent work intact. `GET /planner/tasks` reads tasks and optional date ranges, including unscheduled remainder. `POST /planner/tasks/status` starts work. |
| R05–R09 | `POST /planner/runway` calculates runway without a model call. `POST /planner/config` saves settings, including recurring blackout rules. `POST /planner/generate` runs Assessment if needed, then writes and validates a plan or revision. `POST /planner/accept` applies a preview; `POST /planner/discard` removes it. `POST /planner/confirmations` saves self-reported experience answers. `GET /history/{id}` reads an owner-scoped immutable plan, including earlier untimed plans. |
| T03–T06 | `POST /planner/assignments/status` completes or reopens a session with an optional evidence note. `POST /planner/milestones/outcome` records a self-reported outcome. Neither changes assessed skills. |

[Specification](SPEC.md) · [API contract](../../contracts/api/roadmap.yaml) · [Setup](../../docs/setup.md#assessment-and-roadmap-adviser). External calendars, automatic revision are not implemented. Live-model plan quality has not been evaluated.

Model calls use the shared OpenAI Python SDK transport with Gemini as the cloud
default. No Gemini SDK is required. SDK retries are disabled; existing response
limits, provider quota handling and schema repair attempts remain enforced.

Local testing can use the shared 1.5B Ollama alias through this service's own
`*_LLM_BASE_URL`, `*_LLM_MODEL` and explicit development `*_LLM_ALLOW_HTTP` flag.
Local requests omit stored cloud credentials; cloud requests retain authentication.
JSON/domain validation stays mandatory. See [all-service local setup](../../docs/setup.md#career-model-and-search-configuration).
