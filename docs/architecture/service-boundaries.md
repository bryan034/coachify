# Service ownership and user-story mapping

| Service | Story groups | Owned data |
|---|---|---|
| Profile | P01-P08; profile corrections following ingestion | Canonical education, experiences, personal contributions, capabilities, declared deadline/capacity/temporary availability, profile versions |
| CV | C01-C08 | Ingestion state, provisional extraction, clarification questions/answers, processing operations |
| Career | J01-J05; G01-G07 | Target job descriptions, requirements, assessment versions, capability gaps |
| Roadmap | R01-R09; E01-E07; T01-T06; A02-A04 | Consumed planning-input snapshots, milestones, tasks, progress history, proposed/applied revisions |
| Dashboard | D01-D06 | No persistent domain records; aggregate responses |
| Review | A01 orchestration; S01-S06 | Manual/scheduled review state, pace analysis, schedules, approval preferences |

## Planned internal dependencies

- CV -> Profile: idempotent import of the clarified profile.
- Career -> Profile: versioned input and student capability corrections.
- Roadmap -> Profile/Career: generation inputs and freshness checks.
- Roadmap -> Review: verify the current automatic-application policy.
- Dashboard -> Roadmap/Career/Review: current progress and dated pace analysis.
- Review -> Profile/Career/Roadmap: read inputs, request a revision, request authorised application.

Records are read through APIs, never another service's collections. Public endpoints verify ownership. Internal calls require authenticated service identities and owner context. P07/P08 profile ownership and MongoDB access are implemented; the other service integrations remain planned.

## P04–P06 ownership decision

The latest Jira stories and subtasks place declared planning preferences in the
existing versioned Profile aggregate. Profile owns the date-only application date,
normal weekly capacity and temporary availability periods; all edits use the same
owner/version boundary. This supersedes the original roadmap-owned P04–P06 mapping.
Roadmap will consume a snapshot through an API and own scheduling/results. It must
retain the source profile version, planning revision and explicit calendar context.
No roadmap generation or cross-service stale-plan notification is implemented yet.
