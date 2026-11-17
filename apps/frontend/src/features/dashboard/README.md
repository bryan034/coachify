# dashboard

Home reads saved data from other services through their APIs and only presents it. A failed service shows its own retry and is never counted as done.

- **Hero**: until Background (Profile), Career goal (Career), Skills profile (Profile and CV) and Roadmap (Roadmap) all hold data it shows the open step; then the roadmap timeline and the next unfinished session. **Mark as done** uses Roadmap's `POST /planner/tasks/status` with the workspace version and a mutation id.
- **Cards**: Goal match (saved comparison, read only), Roadmap (days to target, week, this week, next checkpoint), Your progress, Coming up (Jobs deadlines and follow-ups plus the goal's application deadline) and a daily tip or practice question from saved Career research (`GET /goals/{id}/opportunity-research`; reading never starts research).
- **Derived figures** (`home-data.ts`): weeks on track counts consecutive weeks in which every planned session was finished; recent wins are the latest finished sessions and reached checkpoints. Both come from the roadmap's sessions; nothing is stored separately.
- Not implemented: reminders when applications open. Daily, weekly and monthly progress views (`/api/v1/dashboard`) are not used by the frontend.

`lib/api/workspace-summary.ts` holds the read-only loaders, shared with Search Jobs, Chats & Socials and Calendar & Events. Daily, weekly and monthly progress views are not implemented.
