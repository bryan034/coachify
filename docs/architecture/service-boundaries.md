# Service ownership and user-story mapping

| Service | Story groups | Owned data |
|---|---|---|
| Profile | P01-P16; profile corrections following ingestion | Accounts/email verification/revocable sessions, canonical onboarding and education, experiences, personal contributions, capabilities, declared deadline/capacity/temporary availability, profile versions |
| CV | C01-C09; SCRUM-310 | cvs, ingestion state, provisional extraction, clarification questions/answers, processing operations |
| Career | J01-J13; G01-G07; SCRUM-282/310 | career_goals, interview_research, skill_gap_analyses, one career_state workspace, LangGraph checkpoints and per-user ai_user_usage; raw JD text stays transient |
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

Records are read through APIs, never another service's collections. Public endpoints verify ownership. Internal calls require authenticated service identities and owner context. P07/P08 profile ownership and MongoDB access are implemented; CV/Career data contracts and the internal AI adapter are implemented; the other service API integrations remain planned.

## P04–P06 ownership decision

The latest Jira stories and subtasks place declared planning preferences in the
existing versioned Profile aggregate. Profile owns the date-only application date,
normal weekly capacity and temporary availability periods; all edits use the same
owner/version boundary. This supersedes the original roadmap-owned P04–P06 mapping.
Roadmap will consume a snapshot through an API and own scheduling/results. It must
retain the source profile version, planning revision and explicit calendar context.
No roadmap generation or cross-service stale-plan notification is implemented yet.

LangGraph runs within the existing Career container. JD extraction is transient;
resumable research uses MongoDB checkpoints containing only structured references
and public evidence. Brave API adapters belong to Career. No new microservice
or cross-service database access is introduced.
