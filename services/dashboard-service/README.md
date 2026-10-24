# Progress dashboard service

Brings together progress from the other services so users can see how they are doing.

## API by Jira story

**No API endpoints are implemented yet.** The `/api/v1/dashboard` prefix is reserved.

| Jira stories | Planned purpose |
|---|---|
| D01–D06 | Show progress and remaining work across daily, weekly, monthly and whole-roadmap goals. |

The dashboard will read other services through their APIs; it will not own a separate database.

See the [application API overview](../../docs/api/README.md) and [service boundaries](../../docs/architecture/service-boundaries.md).
