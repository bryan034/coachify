# API overview

The browser sends API requests through the gateway. Each prefix belongs to the
service below; its README lists individual endpoints grouped by Jira story.

| Main prefix | What it leads to | Service folder | Status |
|---|---|---|---|
| `/api/v1/profile` | Background, education, planning preferences and saved profile versions | [profile-service](../../services/profile-service/README.md) | Available |
| `/api/v1/cv` | CV upload, extraction and clarification of personal contributions | [cv-service](../../services/cv-service/README.md) | Planned |
| `/api/v1/career` | Target job requirements, capability assessment and skill gaps | [career-service](../../services/career-service/README.md) | Planned |
| `/api/v1/roadmaps` | Roadmap generation, milestones, task progress and revisions | [roadmap-service](../../services/roadmap-service/README.md) | Planned |
| `/api/v1/dashboard` | Daily, weekly, monthly and whole-roadmap progress | [dashboard-service](../../services/dashboard-service/README.md) | Planned |
| `/api/v1/reviews`, `/api/v1/review-schedules` | Manual or scheduled pace reviews and adaptation preferences | [review-service](../../services/review-service/README.md) | Planned |

Page URLs such as `/profile` and `/roadmap` belong to the frontend. They are not API
endpoints. Private `/internal/v1` routes are not exposed through the gateway.
