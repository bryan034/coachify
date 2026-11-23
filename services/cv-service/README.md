# CV service

Saves owner-scoped CV extractions and effective evidence for review and Career inputs. Uses the existing Profile session and account declarations; it never imports CV claims into another profile authority.

## API by Jira story

| Stories | Available endpoints under `/api/v1/cv` |
|---|---|
| C01–C02 | `GET /policy`, `POST /uploads`, `GET /operations/{id}`, `POST /operations/{id}/retry`, `GET /{id}` save uploads, recover processing, and review bounded structured evidence. `DELETE /{id}` deletes an owner/version-checked saved source, its original and CV conversation history. |
| C03–C05 / C08 | `GET /{id}/clarifications`, `POST /{id}/clarifications/prepare`, `PUT /{id}/clarifications/{question_id}` use confirmed skill/condition context and source-bound answer/skip state. `POST /{id}/clarifications/{question_id}/interpretation/retry` recovers saved interpretations. |
| C06 / C01 reconciliation | `PATCH /{id}/items/{item_id}` corrects/removes claims and optional partial dates. `GET`/`POST /{id}/reconciliation` reviews/resolves a retained candidate; `POST /{id}/reconciliation/compare` explicitly compares a replacement with an earlier CV. |
| C07 | Account declarations remain in [Profile](../profile-service/README.md). `GET /declaration-links` assesses source relationships without changing the saved declarations. |
| Skills Profile | `GET /skills` returns the active or requested CV, chat and declaration skills as one owner-scoped list. |
| C09 | `PUT /selection` explicitly selects a ready source. `GET /{id}/capability-input` retains source-only compatibility; `GET /{id}/analysis-input` returns a target-bound versioned snapshot without starting an assessment. |
| C01–C09 conversation | `POST /conversations` opens/resumes saved text chat for a CV or manual-only context. `GET /conversations` lists retained segments; `GET /conversations/{id}` pages history. `POST /conversations/{id}/messages` saves messages and starts bounded processing; in a CV review its `command` can also skip a question, skip one topic, skip all remaining topics or reopen a skipped topic ([topic skips](INTERVIEW.md#topic-skips-question-format-and-early-topic-completion)); `POST /conversations/{id}/actions/{action_id}` confirms, cancels or retries a saved action. |

Deletion supports ready, queued, processing and failed CVs. It clears that source if selected, releases storage quota after recoverable cleanup and preserves manual capabilities and existing analysis/roadmap snapshots. Content-free markers prevent stale uploads and extraction checkpoints from restoring deleted data. See [deletion semantics](SPEC.md#delete-a-saved-cv).

A new CV can become active on its first successful extraction. Reprocessing and reopening the page preserve the saved selection. Each listed ready CV carries `review_progress` (`reviewed_topics` of `total_topics`) from its latest saved review conversation, or null before a review starts. Finishing the guided review marks the CV reviewed (`profile_reviewed_effective_version`); `CvDetail.review_summary` reports what the review changed.

The saved-CV list uses the exact path `GET /api/v1/cv` with no trailing slash. It returns projected metadata in pages of 25 by default (`limit` 1–100 and opaque `cursor`), with `next_cursor` and the explicit selection retained on every page. Upload storage and saved-record quotas preserve existing records and report clear capacity errors; see the specification for defaults and recovery.

Extraction runs a LangGraph with at most one model repair. Each state change is saved in `cv_extraction_states`, so an interrupted or retried run continues from its first unfinished step. The state stays until replaced by a later run or erased with the CV. Transient failures retry automatically up to twice. Output rejected after repair and malformed or incomplete responses stop with an explicit retry option; they do not restart extraction automatically. Extraction, repair and semantic checks share a durable six-call limit across automatic retries and worker recovery; an explicit retry starts a new allowance. See [SPEC.md](SPEC.md#automatic-retries). Evidence accepts equivalent meaning: formatting differences pass locally, while paraphrases/summaries are checked against their cited source blocks by the configured model. Missing sources, unsupported facts, changed negation/attribution and malformed verification results are rejected. Each semantic check shares the existing model budget, concurrency slots and worker lease. Exact/formatting-equivalent evidence needs no extra call; a candidate can require one semantic check (up to four model calls including repair). This is model judgment, not independently verified evidence.

`CV_LLM_RESPONSE_MODE=json_schema` requests strict decoding; full backend limits remain enforced. Evidence has no character limit. `other_information` retains uncategorised source-linked content through retries/reconciliation and review. Dates are best effort: unclear, invalid, conflicting or unsupported dates become null without failing other facts. Manual corrections and clarification interpretation retain their existing validation. See [harness details](SPEC.md#extraction-runtime-harness).

Failures include `error.failure_stage`, `error.failure_category`, `error.repair_attempted` and, for provider HTTP rejections, `error.provider_status_code`, `error.provider_reason` and `error.provider_parameter` in saved-CV, operation and list responses. HTTP rejection messages distinguish invalid requests, credentials, quota and temporary outages. Object and single-element list-wrapped provider rejections are classified. Reasons/parameter names are allowlisted; provider prose is never returned or logged. Successful extraction metadata includes `response_mode`, `workflow_version` and `repair_attempts`. Older records have null diagnostics until retried; see [failure diagnostics](SPEC.md#extraction-failure-diagnostics).

See [SPEC.md](SPEC.md) for semantics, [OpenAPI](../../contracts/api/cv.yaml) for fields, and [setup](../../docs/setup.md) for Compose. `GET /health` is process health. All CV routes require an authenticated owner with completed onboarding and return `Cache-Control: no-store`.

In development only, `POST /api/v1/cv/dev/reset` removes the caller's CV data and files, then releases their upload quota, including stale reservations left by earlier resets. Failed file cleanup can be retried. This route is excluded from OpenAPI and is absent outside development; see [Start afresh](../../docs/setup.md#start-afresh-development-only).

The running service uses MongoDB and private originals. Model calls use the OpenAI Python SDK; the public deployment template selects OpenRouter for all four model-backed services. SDK retries are disabled and response/time limits remain enforced. Configure `CV_LLM_BASE_URL` and `CV_LLM_MODEL` for extraction, clarification interpretation and conversational routing. The Compose template uses `OPENROUTER_API_KEY` for OpenRouter, with an optional `CV_LLM_API_KEY` override; direct processes may supply either key. Missing configuration preserves the upload/answer/message and offers retry; runtime never substitutes synthetic output. Chat responses distinguish durable messages, pending work, proposed changes and saved facts. History is owner-scoped, bounded and retained for resume. `CAREER_SERVICE_URL` supplies confirmed skill and qualification/date context. Assessment admission, stale-result tracking and gap/roadmap generation remain outside this service. Tests use synthetic responses and do not establish live-model accuracy.

Cloud model calls honour the process's HTTP(S) proxy and CA settings, including
`HTTPS_PROXY`, `NO_PROXY` and `SSL_CERT_FILE`; TLS verification and redirect
blocking remain enabled. Internal service requests remain direct. See [configuration troubleshooting](../../docs/setup.md#cv-extraction-configuration-troubleshooting).

CV model requests share configurable per-account daily attempt budgets and concurrency across service instances. Admission failures preserve saved inputs and explain when to retry. Original storage quotas and model budgets are separate; the specification documents their limits, private-volume assumptions and recovery.

For providers that document JSON-object output only, set `CV_LLM_RESPONSE_MODE=json_object`. This explicitly opts out of schema-constrained decoding; the harness still validates and can repair once. Requests carry no provider-specific extensions.

Extraction and repair timeouts are capped by the remaining 180-second worker lease, reserving ten seconds for validation/publication. Existing output/domain checks remain enforced. Rebuild the CV image to install LangGraph before retrying saved uploads.

## Skills Profile guided entry

Saved-CV detail responses include `skill_groups`, mapping each skill name to its display category. It is derived on read and never stored.

Skills Profile opens on a summary. Uploading opens progress immediately;
successful extraction displays classified results before any optional guided questions.
Distinct responsibilities and contributions retain their own source quotes and
attribution even when they share a category. Review CV explicitly starts guided review.
Manual guided entry uses Profile-owned structured
background and per-experience skill evidence. Basic CV review works without a
Career target; target-specific questions retain their existing confirmation rules.
`POST /api/v1/cv/{cv_id}/profile-review` saves a version-bound review stamp from
the summary. Unknowns remain uncertain. Uploaded-CV review is agent-led, with persistent interview memory, grounded role/skill
evidence, targeted partial-answer follow-ups and topic-based progress. Relevant
review answers take precedence over CV statements; review checks schema and topic
relevance, without an evidence-alignment verifier. The chat advances automatically
and announces completion before offering Review profile. Model calls
use a compact discussion summary, four recent messages and on-demand exact-answer
recall, retaining the complete saved transcript without a separate summary model call. See the
[interview harness](INTERVIEW.md) and
[guided intake specification](SPEC.md#skills-profile-entry-and-guided-intake).

## Saved CV titles (C01/C09)

`PATCH /api/v1/cv/{cv_id}/title` accepts `display_name`, `expected_version` and
`mutation_id`. Titles are owner-scoped, trimmed, limited to 200 characters and
reject control characters. Listing/detail responses expose nullable `display_name`;
older records fall back to `file_name` in the UI without migration. Renaming is
available during processing and after failure, uses the existing CAS/replay controls,
and leaves source bytes, extraction/effective versions and review history intact.

Upload status responses include persisted `processing_progress` with a stage-based
percentage and fixed activity message. Successful publication alone reaches 100%;
no model reasoning or simulated time progress is exposed. See [progress semantics](SPEC.md#upload-processing-progress).

Interview planning supplies exact open targets and retains bounded, content-free
rejection codes for debugging; exhausted plans explain the last rejection category.
See [planner diagnostics](INTERVIEW.md#planner-rejection-diagnostics).

Uploaded-CV review allows free and paid users at most two questions per individual
project or job; other review sections retain a shared section allowance. Opening and skipped questions count, and
saved clarification receipts rebuild the allowance across reloads. Clear sources
need no questions. Misclassified answers are not met with the same question again;
a bounded recovery can defer the question with uncertainty. Source-linked evidence
and supported baseline estimates remain specific to each item. See the
[interview budget](INTERVIEW.md#review-question-budget).

Users may skip review questions, leaving targeted ownership/details uncertain.
Skipped ownership can close with gaps and does not block moving to another project.
A failed planner step offers Skip and continue without resubmitting saved answers.
See [skip recovery](INTERVIEW.md#skips-uncertain-ownership-and-recovery).

Guided review also invites a quoted 1–10 skill self-rating as a rough baseline within its existing question budget; evidence-based assessment takes precedence. See [the interview policy](INTERVIEW.md#skill-self-ratings-during-review).
