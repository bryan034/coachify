# CV service

Saves owner-scoped CV extractions and effective evidence for review and Career inputs. Uses the existing Profile session and account declarations; it never imports CV claims into another profile authority.

## API by Jira story

| Stories | Available endpoints under `/api/v1/cv` |
|---|---|
| C01–C02 | `GET /policy`, `POST /uploads`, `GET /operations/{id}`, `POST /operations/{id}/retry`, `GET /{id}` save uploads, recover processing, and review bounded structured evidence. |
| C03–C05 / C08 | `GET /{id}/clarifications`, `POST /{id}/clarifications/prepare`, `PUT /{id}/clarifications/{question_id}` use confirmed skill/condition context and source-bound answer/skip state. `POST /{id}/clarifications/{question_id}/interpretation/retry` recovers saved interpretations. |
| C06 / C01 reconciliation | `PATCH /{id}/items/{item_id}` corrects/removes claims and optional partial dates. `GET`/`POST /{id}/reconciliation` reviews/resolves a retained candidate; `POST /{id}/reconciliation/compare` explicitly compares a replacement with an earlier CV. |
| C07 | Account declarations remain in [Profile](../profile-service/README.md). `GET /declaration-links` assesses source relationships without changing the saved declarations. |
| C09 | `PUT /selection` explicitly selects a ready source. `GET /{id}/capability-input` retains source-only compatibility; `GET /{id}/analysis-input` returns a target-bound versioned snapshot without starting an assessment. |
| C01–C09 conversation | `POST /conversations` opens/resumes saved text chat for a CV or manual-only context. `GET /conversations` lists retained segments; `GET /conversations/{id}` pages history. `POST /conversations/{id}/messages` saves messages and starts bounded processing; `POST /conversations/{id}/actions/{action_id}` confirms, cancels or retries a saved action. |

The saved-CV list uses the exact path `GET /api/v1/cv` with no trailing slash. It returns projected metadata in pages of 25 by default (`limit` 1–100 and opaque `cursor`), with `next_cursor` and the explicit selection retained on every page. Upload storage and saved-record quotas preserve existing records and report clear capacity errors; see the specification for defaults and recovery.

See [SPEC.md](SPEC.md) for semantics, [OpenAPI](../../contracts/api/cv.yaml) for fields, and [setup](../../docs/setup.md) for Compose. `GET /health` is process health. All CV routes require an authenticated owner with completed onboarding and return `Cache-Control: no-store`.

The running service uses MongoDB and private originals. Configure `CV_LLM_BASE_URL`, `CV_LLM_MODEL` and `CV_LLM_API_KEY` for extraction, clarification interpretation and conversational routing. Missing configuration preserves the upload/answer/message and offers retry; runtime never substitutes synthetic output. Chat responses distinguish durable messages, pending work, proposed changes and saved facts. History is owner-scoped, bounded and retained for resume. `CAREER_SERVICE_URL` supplies confirmed skill and qualification/date context. Assessment admission, stale-result tracking and gap/roadmap generation remain outside this service. Tests use synthetic responses and do not establish live-model accuracy.

CV model requests share configurable daily attempt budgets and per-account/global concurrency across service instances. Admission failures preserve saved inputs and explain when to retry. Original storage quotas and model budgets are separate; the specification documents their limits, private-volume assumptions and recovery.
