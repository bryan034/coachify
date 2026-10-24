# API route plan

The profile routes for P07/P08 are implemented; remaining routes below are reservations. Public APIs use `/api/v1`; private service-to-service APIs will use `/internal/v1` and must not be routed from the public gateway.

| Prefix | Owning service | Planned resource groups |
|---|---|---|
| `/api/v1/profile` | Profile | Profile, profile items, versions |
| `/api/v1/cv` | CV | Ingestions, provisional items, clarifications, completion, operations |
| `/api/v1/career` | Career | Targets, requirements, assessments, corrections, operations |
| `/api/v1/roadmaps` | Roadmap | Constraints, availability exceptions, generations, tasks, task status, revisions, operations |
| `/api/v1/dashboard` | Dashboard | Current progress with day/week/month/all period selection |
| `/api/v1/reviews` | Review | Manual reviews, results, review operations |
| `/api/v1/review-schedules` | Review | Frequency, pause/resume, timezone, approval preferences |

Page routes such as `/profile`, `/cv`, and `/roadmap` belong to Next.js and are distinct from these API paths. Profile authentication uses Google ID bearer tokens, with no app-session endpoint.

`contracts/api/profile.yaml` is generated from the implemented API. The other five contracts remain shells with empty `paths`. Fill in schemas and operations as endpoints are designed and implemented. The earlier endpoint catalogue under `outputs/coachify-architecture.md` is a planning reference only; its PostgreSQL deployment description is superseded by the current MongoDB design.

Future contracts must address resource ownership, input validation, version conflicts, idempotent writes, operation/retry state, and preservation of saved inputs. There is no dashboard-generation endpoint: task changes cause the frontend to refetch current dashboard data.
