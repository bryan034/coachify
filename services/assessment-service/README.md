# Assessment service

Compares the owner's effective CV/declarations and Career goal with relevant interview evidence. Owns private immutable `skill_gap_analyses` in its own database; other services are read through authenticated APIs.

## API by Jira story

| Stories | Available endpoints under `/api/v1/assessments` |
|---|---|
| G01 / SCRUM-169–171 | `GET /context` checks selected extracted inputs without model calls. `POST` at the exact prefix (no trailing slash) accepts an idempotent analysis operation. `GET /operation` restores/retries interrupted work on a subsequent authenticated read. |
| G01–G04, G06–G07 | `GET /current` returns the complete saved comparison, progress and freshness; `GET /{id}` reads an owner-scoped immutable historical result. |

The UI lives beside the adviser on **Roadmap**. `job_skill_gaps` and `interview_prep_gaps` contain supported/partial/uncertain outcomes as well as explicit shortfalls. Non-learning conditions and priorities remain separate. This is not a readiness guarantee.

See [SPEC.md](SPEC.md), [contract](../../contracts/api/assessment.yaml) and [service setup](../../docs/setup.md#assessment-and-roadmap-adviser). All tests use synthetic data/provider outputs; live semantic accuracy remains to be evaluated.

Local testing can use the shared 1.5B Ollama alias through this service's own
`*_LLM_BASE_URL`, `*_LLM_MODEL` and explicit development `*_LLM_ALLOW_HTTP` flag.
Local requests omit stored cloud credentials; cloud requests retain authentication.
JSON/domain validation stays mandatory. See [all-service local setup](../../docs/setup.md#career-model-and-search-configuration).
