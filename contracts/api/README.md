# API contracts

`profile.yaml` describes the implemented Profile API and is generated from the
FastAPI application. `career.yaml` describes temporary previews, adaptive exploration, temporary JD skill review
and explicit goal confirmation; `cv.yaml` describes owner-scoped CV reads. Other
endpoint contracts remain empty shells. [models/](models/) contains SCRUM-310 JSON Schemas for CVs, career
goals, interview research and gap analyses; these do not add endpoint routes.

Individual endpoint explanations live in each service README; the
[API overview](../../docs/api/README.md) maps prefixes to services. Keep schemas
aligned with implementation. Private internal routes stay behind the gateway.
