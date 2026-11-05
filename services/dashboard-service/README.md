# Progress dashboard service

Provides an authenticated, stateless dashboard read using passive Roadmap and Assessment APIs. It does not own a database or launch model work.

## API by Jira story

| Story | Available endpoint under `/api/v1/dashboard` |
|---|---|
| D01 / SCRUM-63 | `GET` checks the owner's saved sources and reports missing, unavailable or changed data. Detailed progress projections are introduced in later stories. |

See the [API contract](../../contracts/api/dashboard.yaml) and [tests](tests/README.md). Dashboard frontend integration is not implemented.
