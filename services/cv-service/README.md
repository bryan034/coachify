# CV service

Owns structured CV records and exposes private reads for career exploration.
Dedicated upload, extraction and clarification remain planned.

## Saved CV context — J08 dependency

- `GET /api/v1/cv` — List the signed-in user's saved CV metadata (up to 50); excludes skill evidence and private file references.
- `GET /api/v1/cv/{id}` — Read one owned CV and its extraction/effective skill version.

Both routes verify the session and onboarding through Profile, enforce ownership
and return no-store responses. Career uses these APIs instead of reading this database.

## Upload and review — C01–C09

Upload, extraction, clarification and global analysis-CV selection endpoints are
not implemented. The Resume & Tracker page explains this and links to Career Goal,
which accepts an optional **temporary** attachment with an accuracy warning.
Career attachments do not create CV records here.

## Data contracts — SCRUM-310

Schemas and owner-scoped repositories use the Profile account UUID for `user_id`
and ObjectIds for CV IDs. Unknown proficiency stays null; a user's contribution
declaration needs no proof. Original-file references are optional and private.
See the [CV schema](../../contracts/api/models/cv.schema.json),
[read API contract](../../contracts/api/cv.yaml) and
[integration rules](../career-service/ANALYSIS_CONTRACTS.md).

For Python code reload in Docker, use the [development Compose override](../../infrastructure/docker/README.md#hot-reload-during-development). Dependency changes need a rebuild; JSON snapshot changes need an API restart.
