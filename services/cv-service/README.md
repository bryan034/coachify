# CV ingestion service

Turns a CV into a profile that reflects what the user actually contributed.

## API by Jira story

**No API endpoints are implemented yet.** The `/api/v1/cv` prefix is reserved.

| Jira stories | Planned purpose |
|---|---|
| C01–C02 | Upload a CV and review the extracted information. |
| C03–C05 | Clarify project roles, work responsibilities and ambiguous claims. |
| C06–C08 | Correct details, add missing capabilities or skip a clarification. |

See the [application API overview](../../docs/api/README.md) and [service boundaries](../../docs/architecture/service-boundaries.md).

## Data contracts — SCRUM-310

The CV document/embedded skill schemas and an owner-scoped MongoDB repository are
implemented. Upload, extraction and clarification endpoints remain planned.
`user_id` uses the existing Profile account UUID; CV IDs use ObjectIds. Original
files are optional private references, and a user's contribution declaration is
sufficient without proof. No raw file content is persisted by these contracts.

See the [CV JSON Schema](../../contracts/api/models/cv.schema.json) and
[shared integration rules](../career-service/ANALYSIS_CONTRACTS.md). The repository
is not connected to a running ingestion service yet; no database credentials are
needed for schema-only tests. `MONGODB_TEST_URI` enables disposable database tests.
