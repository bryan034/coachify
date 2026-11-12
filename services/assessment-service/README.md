# Assessment service

Compares the owner's effective CV/declarations and Career goal with relevant interview evidence. Owns private immutable `skill_gap_analyses` in its own database; other services are read through authenticated APIs.

## API by Jira story

| Stories | Available endpoints under `/api/v1/assessments` |
|---|---|
| G01 / SCRUM-169–171 | `GET /context` checks selected extracted inputs without model calls and reports the setup state (`cv_reviewed`, `research_pending`) behind the evaluate banner. `POST` at the exact prefix (no trailing slash) accepts an idempotent analysis operation. `GET /operation` restores/retries interrupted work on a subsequent authenticated read. |
| G01–G04, G06–G07 | `GET /current` returns the complete saved comparison, progress and freshness, and resumes a pending operation. It never starts a comparison: only the explicit `POST` does ([rules](SPEC.md#explicit-evaluation-and-goal-skill-competence)); `GET /{id}` reads an owner-scoped immutable historical result. |
| Skills Profile | `GET /skill-ratings` lists the levels (1–10) the person set for skills elo could not rate; `POST /skill-ratings` sets or clears one (`expected_version`, `name`, optional `canonical_skill_id`, `score` or null). Self-ratings are shown as such and never change a model score or the evaluation inputs. Refused while an evaluation is running. |
| D01–D06 / SCRUM-63–68 | `GET /dashboard-source` passively reads the saved comparison and source freshness without resuming a pending operation. |

The UI lives beside the adviser on **Roadmap**. `job_skill_gaps` and `interview_prep_gaps` contain supported/partial/uncertain outcomes as well as explicit shortfalls. Non-learning conditions and priorities remain separate. This is not a readiness guarantee.

See [SPEC.md](SPEC.md), [contract](../../contracts/api/assessment.yaml) and [service setup](../../docs/setup.md#assessment-and-roadmap-adviser). All tests use synthetic data/provider outputs; live semantic accuracy remains to be evaluated.

Model calls use the shared OpenAI Python SDK transport with OpenRouter as the cloud
default. No provider-specific SDK is required. SDK retries are disabled; existing response
limits, provider quota handling and schema repair attempts remain enforced.

Local testing can use the shared 1.5B Ollama alias through this service's own
`*_LLM_BASE_URL`, `*_LLM_MODEL` and explicit development `*_LLM_ALLOW_HTTP` flag.
Local requests omit stored cloud credentials; cloud requests retain authentication.
JSON/domain validation stays mandatory. See [all-service local setup](../../docs/setup.md#career-model-and-search-configuration).

Standalone comparison is available before a roadmap exists. Without a selected CV, saved Profile declarations can supply the evidence. Selected incomplete CVs still block comparison. Each completed comparison also includes `skill_profile`. Context/current/dashboard reads expose evaluation freshness, processing state, completeness, evaluation time and change reasons. Reviewed CV levels are reused with existing evidence checks. For every profile skill, the model judges a display category, a sub-category, relevance to the goal, and a 0–10 competence score next to the goal's level, using the reviewed CV evidence. Skills Profile shows these judgements. See [SPEC](SPEC.md#per-skill-profile-evaluation).
