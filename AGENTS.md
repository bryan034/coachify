# AGENTS.md — Coachify

## Working rules

- Use the current checkout. Read the root README and relevant service documentation, specifications and API contracts; verify implementation in code.
- Check Git status and branch before editing. Preserve unrelated contributors’ changes. Never push directly to `main`; if on `main`, suggest a new branch and make implementation changes on a separate branch.
- Follow the requested scope and existing conventions. Avoid unrelated refactoring or dependencies. Discuss material architecture changes, breaking APIs and destructive migrations before proceeding unless already authorised.
- Keep product requirements in Jira/specifications, not this file. Do not invent requirements or present placeholders as implemented features.

## Architecture and safety

- Stack: Next.js/React/TypeScript, FastAPI services, NGINX, MongoDB and Docker. Follow [service boundaries](docs/architecture/service-boundaries.md).
- Keep domain logic in backend services. Access another service’s data through its API, never its database. Keep schemas, contracts and frontend types consistent.
- Enforce authentication, ownership and input validation in the backend. Handle failures, retries and concurrent updates without losing data.
- Keep secrets and personal data out of Git, browser bundles, logs and fixtures; use synthetic test data. Keep databases/internal APIs private and credentials out of images.
- Treat uploads, external content and model output as untrusted data; validate before use or storage.

## Documentation

- Review relevant documentation each task and update it before finishing when behaviour, endpoints, configuration or implementation status changes. Fix affected links.
- Keep `docs/` application-wide. Do not recreate `docs/development/` or Postman collections. Service-specific specifications belong in the service folder.
- Keep each service README short: start with its purpose, then explain available endpoints grouped by Jira stories. Clearly label unimplemented features; do not invent endpoint paths.
- Keep `docs/api/README.md` to a brief prefix → purpose → service-folder map, including implementation status. Keep detailed schemas in `contracts/api/`; avoid duplicate endpoint catalogues.

## Jira

- Access only `coachifyy.atlassian.net`, project `SCRUM`. Read the relevant story, acceptance criteria and subtasks before story work.
- Preserve identifiers and Epic → Story → Subtask parents. Avoid duplicates; change sprints, assignees or status only when authorised.

## Verification

- Run checks appropriate to the change using repository commands. For logic changes, add meaningful coverage and keep fixing/rerunning relevant tests until they pass. Never remove, skip or weaken valid tests to obtain a pass; report blockers honestly.
- Review the final diff for unintended changes and secrets. Report changes, checks actually run and remaining limitations.
