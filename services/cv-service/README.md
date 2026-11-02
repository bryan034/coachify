# CV service

Saves owner-scoped CV extractions and effective evidence for review and Career inputs. Uses the existing Profile session and account declarations; it never imports CV claims into another profile authority.

## API by Jira story

| Stories | Available endpoints under `/api/v1/cv` |
|---|---|
| C01–C02 | `GET /policy`, `POST /uploads`, `GET /operations/{id}`, `POST /operations/{id}/retry`, `GET /{id}` save uploads, recover processing, and review bounded structured evidence. `DELETE /{id}` deletes an owner/version-checked saved source, its original and CV conversation history. |
| C03–C05 / C08 | `GET /{id}/clarifications`, `POST /{id}/clarifications/prepare`, `PUT /{id}/clarifications/{question_id}` use confirmed skill/condition context and source-bound answer/skip state. `POST /{id}/clarifications/{question_id}/interpretation/retry` recovers saved interpretations. |
| C06 / C01 reconciliation | `PATCH /{id}/items/{item_id}` corrects/removes claims and optional partial dates. `GET`/`POST /{id}/reconciliation` reviews/resolves a retained candidate; `POST /{id}/reconciliation/compare` explicitly compares a replacement with an earlier CV. |
| C07 | Account declarations remain in [Profile](../profile-service/README.md). `GET /declaration-links` assesses source relationships without changing the saved declarations. |
| C09 | `PUT /selection` explicitly selects a ready source. `GET /{id}/capability-input` retains source-only compatibility; `GET /{id}/analysis-input` returns a target-bound versioned snapshot without starting an assessment. |
| C01–C09 conversation | `POST /conversations` opens/resumes saved text chat for a CV or manual-only context. `GET /conversations` lists retained segments; `GET /conversations/{id}` pages history. `POST /conversations/{id}/messages` saves messages and starts bounded processing; `POST /conversations/{id}/actions/{action_id}` confirms, cancels or retries a saved action. |

Deletion supports ready, queued, processing and failed CVs. It clears that source if selected, releases storage quota after recoverable cleanup and preserves manual capabilities and existing analysis/roadmap snapshots. Only a content-free deletion receipt remains to prevent stale upload replay. See [deletion semantics](SPEC.md#delete-a-saved-cv).

The saved-CV list uses the exact path `GET /api/v1/cv` with no trailing slash. It returns projected metadata in pages of 25 by default (`limit` 1–100 and opaque `cursor`), with `next_cursor` and the explicit selection retained on every page. Upload storage and saved-record quotas preserve existing records and report clear capacity errors; see the specification for defaults and recovery.

Extraction runs a transient LangGraph with at most one model repair. Evidence accepts equivalent meaning: formatting differences pass locally, while paraphrases/summaries are checked against their cited source blocks by the configured model. Missing sources, unsupported facts, changed negation/attribution and malformed verification results are rejected. Each semantic check shares the existing model budget, concurrency slots and worker lease. Exact/formatting-equivalent evidence needs no extra call; a candidate can require one semantic check (up to four model calls including repair). This is model judgment, not independently verified evidence.

`CV_LLM_RESPONSE_MODE=json_schema` requests strict decoding; Gemini receives a simplified decoding grammar while full backend limits remain enforced. Evidence targets fewer than 400 characters with a hard limit of 500. Source-supported long text is split losslessly within existing citation-count limits. `other_information` retains uncategorised source-linked content through retries/reconciliation and review. Dates are best effort: unclear, invalid, conflicting or unsupported dates become null without failing other facts. Manual corrections and clarification interpretation retain their existing validation. See [harness details](SPEC.md#extraction-runtime-harness).

Failures include `error.failure_stage`, `error.failure_category`, `error.repair_attempted` and, for provider HTTP rejections, `error.provider_status_code`, `error.provider_reason` and `error.provider_parameter` in saved-CV, operation and list responses. HTTP rejection messages distinguish invalid requests, credentials, quota and temporary outages. Object and single-element list-wrapped provider rejections are classified. Reasons/parameter names are allowlisted; provider prose is never returned or logged. Successful extraction metadata includes `response_mode`, `workflow_version` and `repair_attempts`. Older records have null diagnostics until retried; see [failure diagnostics](SPEC.md#extraction-failure-diagnostics).

See [SPEC.md](SPEC.md) for semantics, [OpenAPI](../../contracts/api/cv.yaml) for fields, and [setup](../../docs/setup.md) for Compose. `GET /health` is process health. All CV routes require an authenticated owner with completed onboarding and return `Cache-Control: no-store`.

The running service uses MongoDB and private originals. Model calls use the OpenAI Python SDK; the public deployment template selects Gemini through its OpenAI-compatible endpoint. SDK retries are disabled and response/time limits remain enforced. Configure `CV_LLM_BASE_URL`, `CV_LLM_MODEL` and `CV_LLM_API_KEY` for extraction, clarification interpretation and conversational routing. Missing configuration preserves the upload/answer/message and offers retry; runtime never substitutes synthetic output. Chat responses distinguish durable messages, pending work, proposed changes and saved facts. History is owner-scoped, bounded and retained for resume. `CAREER_SERVICE_URL` supplies confirmed skill and qualification/date context. Assessment admission, stale-result tracking and gap/roadmap generation remain outside this service. Tests use synthetic responses and do not establish live-model accuracy.

CV model requests share configurable daily attempt budgets and per-account/global concurrency across service instances. Admission failures preserve saved inputs and explain when to retry. Original storage quotas and model budgets are separate; the specification documents their limits, private-volume assumptions and recovery.

For DeepSeek Chat Completions, set `CV_LLM_BASE_URL=https://api.deepseek.com`, `CV_LLM_MODEL=deepseek-flash`, `CV_LLM_RESPONSE_MODE=json_object` and your private `CV_LLM_API_KEY`. This explicitly opts out of schema-constrained decoding because that endpoint documents JSON-object output only. The harness still validates and can repair once. Requests to the exact `api.deepseek.com` host automatically disable thinking for extraction, chat routing and clarification interpretation; other provider hosts keep their existing options. See [DeepSeek's request format](https://api-docs.deepseek.com/api/create-chat-completion/).

For optional local testing, select `elo-deepseek-r1:1.5b` at
`http://host.docker.internal:11434/v1`. `APP_ENV=development` and
`CV_LLM_ALLOW_HTTP=true` are required. This known local endpoint supports keyless
requests and never receives stored cloud API keys. Local extraction gets a 120-second
HTTP timeout; chat/interpretation get 60 seconds, retaining their existing leases.
Extraction and repair timeouts are capped by the remaining 180-second worker lease, reserving ten seconds for validation/publication. Existing output/domain checks remain enforced. Rebuild the CV image to install LangGraph before retrying saved uploads.

## Skills Profile guided entry

Skills Profile opens on a summary. Uploading opens the full-page review immediately;
the review screen opens immediately after upload, waits for extraction and then starts guided questions automatically. Manual guided entry uses Profile-owned structured
background and per-experience skill evidence. Basic CV review works without a
Career target; target-specific questions retain their existing confirmation rules.
`POST /api/v1/cv/{cv_id}/profile-review` saves a version-bound review stamp from
the summary. Unknowns remain uncertain. Uploaded-CV review is agent-led, with persistent interview memory, grounded role/skill
evidence, targeted partial-answer follow-ups and validated completion. See the
[interview harness](INTERVIEW.md) and
[guided intake specification](SPEC.md#skills-profile-entry-and-guided-intake).

## Saved CV titles (C01/C09)

`PATCH /api/v1/cv/{cv_id}/title` accepts `display_name`, `expected_version` and
`mutation_id`. Titles are owner-scoped, trimmed, limited to 200 characters and
reject control characters. Listing/detail responses expose nullable `display_name`;
older records fall back to `file_name` in the UI without migration. Renaming is
available during processing and after failure, uses the existing CAS/replay controls,
and leaves source bytes, extraction/effective versions and review history intact.
