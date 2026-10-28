# API overview

The browser sends API requests through the gateway. Each prefix belongs to the
service below; its README lists individual endpoints grouped by Jira story.

| Main prefix | What it leads to | Service folder | Status |
|---|---|---|---|
| `/api/v1/profile` | Email/password access, verification, onboarding, background, planning and account-owned capability declarations | [profile-service](../../services/profile-service/README.md) | Available |
| `/api/v1/cv` | Saved CV review, resumable text conversations, interpreted clarifications, dates, source reconciliation, attachment assessment and versioned target-bound inputs | [cv-service](../../services/cv-service/README.md) | Available; extraction, free-text routing and interpretation need a configured provider; assessment execution remains planned |
| `/api/v1/career` | Temporary JD previews, reviewed target drafts, explicit confirmation/selection and versioned confirmed context | [career-service](../../services/career-service/README.md) | Reviewed targets available; AI interpretation, exploration chat and skill-gap analysis remain planned |
| `/api/v1/roadmaps` | Roadmap generation, milestones, task progress and revisions | [roadmap-service](../../services/roadmap-service/README.md) | Planned |
| `/api/v1/dashboard` | Daily, weekly, monthly and whole-roadmap progress | [dashboard-service](../../services/dashboard-service/README.md) | Planned |
| `/api/v1/reviews`, `/api/v1/review-schedules` | Manual or scheduled pace reviews and adaptation preferences | [review-service](../../services/review-service/README.md) | Planned |

Page URLs such as `/profile` and `/roadmap` belong to the frontend. They are not API
endpoints. Private `/internal/v1` routes are not exposed through the gateway.
