# Roadmap adviser and tasks service

Works with the user on a personalised preparation plan through saved chat, proposed activities and daily workload. Owns active/proposed plans, immutable plan revisions and task history in a separate MongoDB database.

## API by Jira story

| Stories | Available endpoints under `/api/v1/roadmaps` |
|---|---|
| R01 / SCRUM-185–187 | `GET /progress` polls compact operation state. `GET /workspace` restores chat, proposals, active plan, progress and source freshness. `POST /messages` saves a message and starts/resumes durable adviser work. `POST /activate` applies the reviewed proposal; `POST /draft/discard` discards it. |
| R05–R09 | `POST /preferences` previews a date-based workload using selected weekdays/session budgets. `GET /history/{id}` reads an owner-scoped immutable plan revision. |
| E01–E04/E06–E07 | `POST /tasks` adds/edits task definitions, estimates, links and prerequisites; `POST /tasks/remove` retains removal intent/history. |
| T03–T06 | `POST /tasks/status` starts, completes or explicitly reopens work without altering capability evidence or fabricating actual time. |

The frontend opens chat with the plan beside it on `/roadmap`; daily/weekly/monthly workload views use the same saved allocations. Plan changes are proposals until explicitly applied. Direct task edits preserve timing and show review issues.

[Specification](SPEC.md) · [API contract](../../contracts/api/roadmap.yaml) · [Setup](../../docs/setup.md#assessment-and-roadmap-adviser). Exact clock-time scheduling, external calendars, automatic adaptation and direct allocation editing (E05) remain unimplemented.
