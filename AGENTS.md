# AGENTS.md — elo

## Working rules

- Use the current checkout. Start with the root README; follow only documentation, specifications and API contracts relevant to the task. Verify implementation in code.
- Check Git status and branch before editing. Preserve unrelated contributors’ changes. Never push directly to `main`; if on `main`, suggest a new branch and make implementation changes on a separate branch.
- Follow the requested scope and existing conventions. Avoid unrelated refactoring or dependencies. Discuss material architecture changes, breaking APIs and destructive migrations before proceeding unless already authorised.
- Follow the user's request and relevant specifications. Do not invent requirements or present placeholders as implemented features.

## Keeping context small

- Keep this file concise: include only durable repository-specific rules, essential commands, navigation links, architecture and safety constraints, and verification requirements that are hard to infer from code.
- Link to detailed documentation instead of copying it. Keep product requirements, feature status, schemas and endpoint catalogues in their existing specifications and service documents.
- Read focused sections and files as needed; avoid loading unrelated documentation or whole directories. Add commands here only after verifying them in the repository.

## Architecture and safety

- Stack: Next.js/React/TypeScript, FastAPI services, NGINX, MongoDB and Docker. Follow [service boundaries](docs/architecture/service-boundaries.md).
- For CV, JD/skills-analysis or roadmap changes, consult relevant sections of the [collections](docs/architecture/diagrams/mongodb_collections_uml.mmd), [embedded objects](docs/architecture/diagrams/mongodb_embedded_objects_uml.mmd) and [service architecture](docs/architecture/diagrams/dockerised-mvp.puml) diagrams. Reconcile with code and service contracts; update affected diagrams when services change.
- Keep domain logic in backend services. Access another service’s data through its API, never its database. Keep schemas, contracts and frontend types consistent.
- Enforce authentication, ownership and input validation in the backend. Handle failures, retries and concurrent updates without losing data.
- Centralise all user-configurable deployment variables in `infrastructure/docker/.env`. Document every active variable in `infrastructure/docker/.env.example` with safe defaults and blank secrets; update this template and the relevant Compose injection whenever configuration changes. Do not introduce root-level or service-specific environment files. Fixed internal service wiring stays in Compose; inject each setting only into the services that need it.
- Agents may read, edit and validate the public `infrastructure/docker/.env.example` template. Never read, edit, load or indirectly inspect private environment files (including `infrastructure/docker/.env`) or their contents. Give instructions for the user to apply private values; use explicit synthetic settings and isolated resources for verification.
- Keep secrets and personal data out of Git, browser bundles, logs and fixtures; use synthetic test data. Keep databases/internal APIs private and credentials out of images.
- Treat uploads, external content and model output as untrusted data; validate before use or storage.

## Documentation

- Update affected documentation and links when behaviour, endpoints, configuration or implementation status changes.
- Keep `docs/` application-wide. Do not recreate `docs/development/` or Postman collections. Service-specific specifications belong in the service folder.
- Keep service READMEs short: purpose, then available endpoints grouped by capability. Label unimplemented features; do not invent endpoint paths.
- Keep `docs/api/README.md` to a brief prefix → purpose → service-folder map, including implementation status. Keep detailed schemas in `contracts/api/`; avoid duplicate endpoint catalogues.

## Jira (only when explicitly requested)

- Consult Jira only when the user explicitly requests Jira work. Access only `coachifyy.atlassian.net`, project `SCRUM`.
- Preserve identifiers and Epic → Story → Subtask parents. Avoid duplicates; change sprints, assignees or status only when authorised.

## Verification

- Run checks appropriate to the change using repository commands. For logic changes, add meaningful coverage and keep fixing/rerunning relevant tests until they pass. Never remove, skip or weaken valid tests to obtain a pass; report blockers honestly.
- Review the final diff for unintended changes and secrets. Report changes, checks actually run and remaining limitations.
