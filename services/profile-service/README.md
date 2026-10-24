# Profile service

Stores each user's background, education and planning preferences so future
assessments and roadmaps can use their saved information. P01–P08 are available.

## Shared profile — P01–P08

| Endpoint | What it does |
|---|---|
| `GET /api/v1/profile` | Load your latest saved details. |
| `PATCH /api/v1/profile` | Save changes to background, education, application date or weekly hours. |
| `GET /api/v1/profile/versions/{version}` | Read an earlier saved profile. |

## Education choices — P01–P03, P07/P08

| Endpoint | What it does |
|---|---|
| `GET /api/v1/profile/school-categories` | List the five school categories. |
| `GET /api/v1/profile/school-countries` | List countries for university searches. |
| `GET /api/v1/profile/institutions` | Search school suggestions by category, name and country. |

Users can also enter an unlisted institution. Students provide current education;
other occupational statuses use their last education.

## Planning preferences — P04–P06

The shared profile endpoints above save the application date (P04) and normal
weekly hours (P05). P06 adds temporary periods of lower availability:

| Endpoint | What it does |
|---|---|
| `POST /api/v1/profile/availability-periods` | Add a reduced-availability period. |
| `PATCH /api/v1/profile/availability-periods/{period_id}` | Change a period. |
| `DELETE /api/v1/profile/availability-periods/{period_id}` | Remove a period. |
| `GET /api/v1/profile/planning-inputs` | Read planning preferences and any issues that need attention. |

Periods use inclusive Singapore dates and cannot overlap. Planning preferences
supply inputs; they do not generate a roadmap.

## Account configuration — shared support for P01–P08

`GET /api/v1/profile/auth-config` tells the frontend whether Google or local-test
access is enabled. Account creation and onboarding stories P09–P15 are still planned.

## Using the service

Only the signed-in owner can read or change private details. Writes include the
latest `expected_version`; planning writes also need an `Idempotency-Key` so retries
are safe. Deletion takes `expected_version` as a query parameter. Planning-input
reads require the device `time_zone`; optional `start_date` and `end_date` give a capacity window.

- [Run the application](../../docs/setup.md) · [Run tests](../../docs/testing.md)
- [Detailed service rules](SPECIFICATION.md) · [School data](app/data/README.md)
- [Request/response schemas](../../contracts/api/profile.yaml)
