# API overview

The browser sends API requests through the gateway. Each prefix belongs to the
service below; its README lists individual endpoints grouped by Jira story.

| Main prefix | What it leads to | Service folder | Status |
|---|---|---|---|
| `/api/v1/profile` | Email/password access, verification, password recovery, onboarding, background, education, planning preferences, guided manual skills profiles and profile versions | [profile-service](../../services/profile-service/README.md) | Available |
| `/api/v1/cv` | Saved CV upload/deletion, extraction, clarification, correction, capability input, guided baseline skill review and private conversation history | [cv-service](../../services/cv-service/README.md) | Saved upload, selection, interpretation and resumable review available; live models require configuration |
| `/api/v1/career` | Career exploration, temporary JD/CV previews, saved role/skill/condition review, one autosaved goal/chat with explicit version-bound CV confirmation, LangGraph JD interpretation, advisory skills and Brave interview evidence; read-only versioned Assessment handoff | [career-service](../../services/career-service/README.md) | Available; external AI/research requires configured provider access |
| `/api/v1/assessments` | Private version-pinned CV/goal/interview comparison, saved evaluation freshness and durable operations | [assessment-service](../../services/assessment-service/README.md) | Available; configured database and model required |
| `/api/v1/roadmaps` | Study settings, chat helper and runway, validated LLM roadmaps with reviewed previews, timed or anytime tasks, backlog scheduling, checkpoints, self-ratings, progress and per-skill learning steps | [roadmap-service](../../services/roadmap-service/README.md) | Available; configured database and model required |
| `/api/v1/jobs` | Singapore job and internship search with filters, search links to other job sites, and private tracking of self-reported applications, including jobs saved from a pasted link | [jobs-service](../../services/jobs-service/README.md) | Available; listings fetched live from configured employer boards |
| `/api/v1/dashboard` | Daily, weekly, monthly and whole-roadmap progress | [dashboard-service](../../services/dashboard-service/README.md) | Backend available; frontend integration planned |
| `/api/v1/reviews`, `/api/v1/review-schedules` | Manual or scheduled pace reviews and adaptation preferences | [review-service](../../services/review-service/README.md) | Planned |

Page URLs such as `/profile` and `/roadmap` belong to the frontend. They are not API
endpoints. Private `/internal/v1` routes are not exposed through the gateway.

Career discovery session/message/research routes are implemented under `/api/v1/career/discoveries`; see [Career service](../../services/career-service/README.md).
