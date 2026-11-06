# dashboard

Home reads saved data from other services through their APIs and only presents it. A failed service shows its own retry and is never counted as done.

- **The path**: Background (Profile), Career goal (Career), Skills profile (Profile and CV), Roadmap (Roadmap) and Applications (Jobs). A stop is done when that service holds the data; applications count once a job moves past `saved`. The button leads to the first unfinished stop.
- **Cards**: saved background, career goal with skills per category, skills per category as a column chart, and roadmap days, sessions done, next session and study hours.
- **Learning & skills**: each skill the active roadmap works on, from Roadmap's `GET /learning`, with sessions done and missed and its next session. It appears once a roadmap has steps. Progress means sessions done, not a tested level.
- **Up next**: job applications, Learning & skills and Explore careers are live. Events and expert conversations are not implemented and are labelled Soon.

`lib/api/workspace-summary.ts` holds the read-only loaders, shared with Search Jobs, Chats & Socials and Calendar & Events. Daily, weekly and monthly progress views are not implemented.
