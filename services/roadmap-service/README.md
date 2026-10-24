# Roadmap and tasks service

Turns career gaps and saved planning preferences into actionable tasks and milestones.

## API by Jira story

**No API endpoints are implemented yet.** The `/api/v1/roadmaps` prefix is reserved.

| Jira stories | Planned purpose |
|---|---|
| R01–R09 | Generate a roadmap that fits the target role, deadline and capacity. |
| E01–E07 | Add, edit, move or remove roadmap tasks. |
| T01–T06 | View the plan and track task progress. |
| A02–A04 | Review, apply or dismiss proposed roadmap changes. |

P04–P06 deadline and availability inputs belong to the [Profile service](../profile-service/README.md). This service will use those saved inputs for scheduling.

See the [application API overview](../../docs/api/README.md) and [service boundaries](../../docs/architecture/service-boundaries.md).
