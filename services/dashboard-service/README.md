# Progress dashboard service

Provides an authenticated, stateless progress view using passive Roadmap and Assessment APIs. It has no dashboard database and does not start model work.

## API by Jira story

| Stories | Available endpoint under `/api/v1/dashboard` |
|---|---|
| D01–D06 / SCRUM-63–68 | `GET` returns task, milestone, requirement and pace data. `period` accepts `daily`, `weekly`, `monthly` or `whole`; `focus_date` selects a calendar date. Periods use the active roadmap's time zone. |

The response separates current assessment results from task progress, reports source freshness and a bounded version recheck, and labels estimates. No active plan and an empty plan are distinct. Pace uses the latest accepted baseline when recorded; earlier plans without one report it unavailable. Period selection is request-only; cross-session preference and the dashboard interface remain frontend work. Completing a task does not establish capability.

[Specification](SPEC.md) · [API contract](../../contracts/api/dashboard.yaml) · [Tests](tests/README.md).
