# Profile service

FastAPI service for P07/P08 occupational status and school category. Owns canonical
profile versions in MongoDB `coachify_profile`; other services remain scaffolded.
P01–P03 institution/course/year entry is implemented; see the education-profile guide. Snapshot-based Singapore/international school
lookup is implemented here without a school directory collection in MongoDB.

Implemented routes:

- `GET /api/v1/profile/auth-config` — public read-only authentication mode, with no identity or secrets.
- `GET /api/v1/profile` — own latest profile; Google bearer token by default, or the explicit local test identity.
- `PATCH /api/v1/profile` — partial background or planning save with expected version. Planning writes require `Idempotency-Key`.
- `GET /api/v1/profile/versions/{version}` — own immutable historical profile.
- `GET /api/v1/profile/school-categories` — public category constants.
- `GET /api/v1/profile/school-countries` — public university country options.
- `GET /api/v1/profile/institutions` — public filtered/paginated snapshot search.

See `../../docs/development/profile-setup.md` for credentials, runtime and tests.
Contracts are generated from `app.main.app.openapi()` in `../../contracts/api/profile.yaml`.
Original `.example` Docker files are inactive; use the new `Dockerfile` and active
`infrastructure/docker/compose.yaml`. No internal service endpoints are implemented.

For browser or Postman testing without Google, set APP_ENV=development and AUTH_MODE=local_test. See the local-testing section of the setup guide.

P04–P06 add application dates, normal weekly hours and reduced periods:

- `POST /api/v1/profile/availability-periods` — add a period.
- `PATCH /api/v1/profile/availability-periods/{period_id}` — edit supplied period fields.
- `DELETE /api/v1/profile/availability-periods/{period_id}?expected_version=N` — remove a period.
- `GET /api/v1/profile/planning-inputs?time_zone=Asia%2FSingapore` — validated, versioned planning inputs; optional inclusive `start_date`/`end_date` capacity window.

See `../../docs/development/planning-preferences.md` for payloads, calendar rules,
retry semantics, persistence, handoff boundaries and verification.
