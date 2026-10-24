# Profile service

FastAPI service for P07/P08 occupational status and school category. Owns canonical
profile versions in MongoDB `coachify_profile`; other services remain scaffolded.
P01–P03 institution/course/year entry is implemented; see the education-profile guide. Snapshot-based Singapore/international school
lookup is implemented here without a school directory collection in MongoDB.

Implemented routes:

- `GET /api/v1/profile/auth-config` — public read-only authentication mode, with no identity or secrets.
- `GET /api/v1/profile` — own latest profile; Google bearer token by default, or the explicit local test identity.
- `PATCH /api/v1/profile` — status/category save with expected version.
- `GET /api/v1/profile/versions/{version}` — own immutable historical profile.
- `GET /api/v1/profile/school-categories` — public category constants.
- `GET /api/v1/profile/school-countries` — public university country options.
- `GET /api/v1/profile/institutions` — public filtered/paginated snapshot search.

See `../../docs/development/profile-setup.md` for credentials, runtime and tests.
Contracts are generated from `app.main.app.openapi()` in `../../contracts/api/profile.yaml`.
Original `.example` Docker files are inactive; use the new `Dockerfile` and active
`infrastructure/docker/compose.yaml`. No internal service endpoints are implemented.

For browser or Postman testing without Google, set APP_ENV=development and AUTH_MODE=local_test. See the local-testing section of the setup guide.
