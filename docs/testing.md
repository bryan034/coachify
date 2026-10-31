# Tests and CI

## Current state

The profile slice has component, browser and API tests plus real MongoDB integration.
Career has preview/AI/contract/workflow tests; CV has parser, saved-operation, interpretation, owner/mutation, conversation and handoff tests. Only the unimplemented Roadmap, Dashboard and Review services may pass with empty suites. Implemented services must collect tests.
See [application setup](setup.md) and the affected service README for setup and service details.

## Suite maintenance

Assessment and Roadmap contracts compare the complete generated OpenAPI document.
Their shared API factory fixes error descriptions explicitly because Python 3.12
and newer interpreters use different HTTP status phrases for 413 and 422.
The planning integration journey checks Profile defaults through the Roadmap
workspace response and adviser opening, then returns through Profile to edit them.

Preserve checks for distinct behavior and boundaries, including cross-service contracts. If a UI journey is replaced, retain its useful ownership, draft, retry and validation assertions against the new flow. Do not weaken or remove valid failures to obtain a pass. Historical discovery totals and earlier passing logs are not evidence for the current merged tree; report exact current results separately.

## Local commands

Use Node.js 24 and Python 3.12. From the root:

```sh
npm ci
npm run typecheck --workspace apps/frontend
npm run test --workspace apps/frontend
npx playwright install chromium
npm run test:e2e --workspace apps/frontend
```

The browser runner first discovers tests. If none exist it passes without starting
Next.js. When tests exist, Playwright builds and starts the frontend. The frontend builds the first workspace UI; unavailable services use empty states. Only Chromium is configured.
Browser tests cover public entry, nonce-bound Google access, session reload/logout, workspace editing and mobile layout using boundary fixtures. A separate full-stack browser job exercises the actual gateway, profile service and disposable MongoDB.

For each service, create an isolated Python environment, then run from its directory:

```sh
python -m pip install -e '.[test]'
python -m pytest
```

Each service's `tests/` directory is the pytest discovery root. Raw pytest exits 5
when no tests are collected; CI permits it only for the three unimplemented scaffolds. Other nonzero exits fail. Profile, CV and Career integration jobs start MongoDB; ordinary backend unit jobs do not.

## Automation

`.github/workflows/ci.yml` runs on PRs targeting `main`, every push to `main`
(including merges), merge-queue checks, and manual dispatch. All six backend suites
run independently. Frontend jobs run TypeScript/unit checks and Playwright browser
tests against a production Next.js build. Unit and browser test discovery are separate.
There are no path filters that could skip required jobs. The final `Test gate` fails
if any test job fails, is cancelled, or is skipped. Browser reports and failure
traces are uploaded for seven days; use synthetic data because artifacts may contain
page content. Linting is not configured yet.

MongoDB-backed jobs (`profile-integration`, `analysis-integration` and
`local-ui-integration`) explicitly use `ubuntu-22.04`, whose hosted image uses
the Linux 6.8 Azure kernel. MongoDB 8.0 refuses to start on affected kernels 6.19
and newer, before test steps run; `ubuntu-latest` can introduce that incompatibility
as hosted images change. Other jobs retain `ubuntu-latest`. This is a temporary
compatibility pin: review it before Ubuntu 22.04 runner retirement, and move to a
newer runner only after verifying its kernel with the MongoDB image. See the
[runner image inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2204-Readme.md).

## GitHub enforcement (repository administrator)

After this workflow has run on a PR:

1. Open repository Settings → Branches and add protection for `main`.
2. Require a pull request before merging.
3. Require status checks to pass; select `Test gate` from this workflow.
4. Require branches to be up to date before merging.
5. Disallow bypasses, force pushes, and deletion as appropriate for the team.

Availability depends on GitHub plan/repository visibility. Workflow files alone do
not enable branch protection. Push events verify merged code after the merge;
required PR checks are what prevent failing code from merging in the first place.
Local CI configuration does not publish a branch or modify GitHub settings.

## Real MongoDB and full-stack checks

Set `MONGODB_TEST_URI` to a disposable MongoDB instance when running the profile
suite to include database tests. They create/drop randomly named `elo_test_*`
and `elo_accounts_test_*` databases. Never use a production connection for tests.
`tests/test_password_reset.py` covers recovery delivery/retry, unknown emails,
duplicate signup, code expiry and guess limits, concurrent resets, authentication
mode isolation, and session/old-password invalidation without losing profile data.
Frontend recovery coverage is in `password-recovery.test.tsx`.

The `local-ui-integration` job provisions a disposable Docker stack and tests
browser → gateway → API → MongoDB, including SMTP-to-Mailpit OTP verification, email/password A/B isolation, canonical onboarding, history restoration, logout/replay, cross-tab cleanup and profile/planning saves. For a manually provisioned **disposable** local-test stack on port 8081:

```sh
cd apps/frontend
PROFILE_E2E_BASE_URL=http://localhost:8081 MAILPIT_BASE_URL=http://localhost:8026 npx playwright test --config playwright.integration.config.ts
```

Use a separate Compose project and database volume, and set
`GATEWAY_PORT=8081`, `MAILPIT_PORT=8026` and `COMPOSE_PROFILES=development`, with
SMTP pointed at the disposable Mailpit container as in `.env.example`. This suite writes synthetic data; do not target your personal
profile. Boundary-fixture browser tests use
`NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com`, a test-only
public identifier, when running `npm run test:e2e --workspace apps/frontend`.

## Career input/previews

Run Career pytest from `services/career-service` in a separate virtual environment.
Provision its tokenizer cache before the suite enables network isolation:

```sh
python -m pip install -e ".[test]"
export TIKTOKEN_CACHE_DIR="$(mktemp -d)"
python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')"
python -m pytest
```

The provisioning command downloads the vocabulary used by the pinned tokenizer;
reuse an already populated `TIKTOKEN_CACHE_DIR` when running offline. Both Career
CI paths provision it into a disposable runner cache after dependency installation
and before pytest. Do not collect Profile and Career together
in one Python process because both use an `app` package. The shared Career harness
clears inherited application database, provider and tracing settings before collection
and each test; only `MONGODB_TEST_URI` remains an explicit disposable-database opt-in.
Default HTTPX/Requests transports and the preview socket connector are blocked.
Tests inject synthetic settings and mock transports after setup; use an already
populated `TIKTOKEN_CACHE_DIR` because tokenizer downloads are blocked too.
Frontend tests cover
three methods, Unicode, failure recovery, method-switch races and temporary state.
The full-stack Career browser test uses the usual disposable Compose stack and
Mailpit variables; no live Gemini key or live website is used. Career imports are rate
limited at the gateway; use synthetic sources and discard only test-stack data.

## AI and analysis contracts

The Career suite tests the OpenAI-compatible adapter through fake HTTP responses;
no live key, external provider calls or billing are needed. Career and CV each
validate the exported MongoDB schemas. Their `MONGODB_TEST_URI` tests create/drop
random `elo_analysis_test_*` / `elo_cv_test_*` databases, checking real
BSON, indexes, private ownership and idempotent/versioned writes. Use only a
disposable MongoDB. The required `analysis-integration` CI matrix runs both suites
against MongoDB; ordinary backend jobs skip only their database-dependent tests.

J08/J09 add fake-provider + real MongoDB flow tests, CV API ownership checks,
component/browser adaptive chat and JD handoff checks, and a full-stack confirmed-goal reload
check. The disposable Compose test stack also needs `CAREER_DB_PASSWORD` and
`CV_DB_PASSWORD`; CI supplies synthetic values. Real provider credentials are never
used by automated tests. Goal-flow tests create/drop `elo_goals_test_*` DBs.

JD review tests use synthetic AI outputs for semantic supporting summaries,
labelled inferences, structured job fields and URL metadata, context-only chat,
proposal approval, invalid history, empty results and recoverable failures. They
verify raw JD text is excluded from chat requests and unknown requirements are not
promoted to employer facts; they do not establish live-model extraction accuracy. Browser coverage checks
automatic document reading, the shared chat and explicit proposal approval. Session compatibility checks verify draft-preserving revalidation, explicit retry and actual authentication expiry. The upstream idle-activity component is not mounted by the merged workspace; its standalone tests do not establish an active inactivity policy.

Docker hot-reload verification uses an isolated Compose project with `/dev/null`
as its environment-file source and explicit synthetic settings. A disposable client
component verifies an edited label updates through the gateway HMR socket while
preserving a counter and avoiding page navigation. Temporary API probes verify
Python edits reload in Profile, Career and CV. Probes are restored/removed afterward;
no private environment files or live account data are used. The production frontend
Docker target is built separately to check that the dev target remains opt-in.

J02–J04 add saved review editing, reset/cancel, atomic skill/condition reclassification,
source/metadata provenance, mapping-pending states, guarded confirmation, version
conflicts and immutable history. Career MongoDB tests use random
`elo_reviews_test_*` databases. Browser fixtures cover extract → chat proposal →
automatic save → reload → latest goal, including mobile layout. External AI
remains mocked; these checks do not establish live-model semantic accuracy.

The Local UI and MongoDB job uploads `local-ui-integration-results` for seven days,
including retained failure traces and error context. Its Career preview journey
keeps AI disabled: it asserts `/workspace/jd` returns a running 202 operation, then
the owner-scoped operation poll returns `503/not_configured`. The UI shows a fixed
disabled-AI alert, preserves retry controls and disables chat; no review is saved. It does
not depend on introductory wording or use live provider credentials.


Career J05/J10/J12/J13 checks cover importance/reset identities, advisory generation,
exact selection versions, owner isolation, shared public research reuse, leases,
immutable history and failed refresh recovery. API source connectors and AI are
synthetic fixtures; no live source API or model accuracy is claimed. An unconnected
source API is tested as unavailable. Frontend checks cover the shared skills review,
read-only historical evidence, retry preservation and mobile layout. Run Career
with a disposable `MONGODB_TEST_URI` to include these database-backed tests.


LangGraph single-workspace checks use real disposable MongoDB with synthetic models
and Brave HTTP responses. They cover automatic current-goal saves, session
replacement, stale-session/owner rejection, saved-goal chat during research failures, persisted
checkpoints, quota pause/resume without repeating searches, no-findings and expiry.
Token-limit tests verify large and concurrent Gemini requests without a local
minute quota, provider retry delays and bounded output. Browser checks cover the
new single-chat flow and mobile evidence. No live model/search credentials are used.

Brave Answers checks cover fragmented SSE, cited AI summaries versus source excerpts,
invalid/missing references, uncited-answer rejection, output limits, public-scope queries,
versioned context cache policies, MongoDB summary persistence/reuse and bounded model requests.
All external responses are synthetic; live Answers access must be configured separately.

Career overview coverage checks category membership, research-in-progress display,
CV assessment absence versus service failure, guided refinement, safe goal replacement
and reload restoration. `career-overview.spec.ts` exercises the desktop/mobile flow
through CV-page navigation using synthetic providers. Backend assessment-status tests
verify authentication/no-store, owner filtering, empty/pending/failed/succeeded CVs
and unavailable upstream snapshots without database or model writes.

Opportunity Intelligence tests use a real disposable MongoDB with synthetic Gemini,
Gemini and Brave boundaries. They cover independent parallel categories, partial
failure, no company/no results, conflicting employee/intern salary context, forged
refs/quotes, bounded schema repair, category cache/expiry, refresh/idempotency,
owner access, quota recovery and restart without repeating acquired searches.
Foreground extraction regressions cover reconnecting an identical JD under a new
key during a 600-second simulated quota wait, replay/ownership checks, safe
different-input conflicts and chat navigation retaining its request key. A Chromium
journey leaves/reopens pending extraction and reaches the saved goal without 409s.
The live Opportunity smoke remains skipped by the shared synthetic harness, which
clears inherited `OPPORTUNITY_LIVE_TEST` and blocks provider transports. Live-provider
evaluation needs a separately authorized isolated setup. Frontend unit/browser checks cover
source/confidence/date transparency, partial status and category-only refresh.

Career Discovery tests cover broad/specific directions, automatic research for a
clear direction, owner/version/idempotency boundaries, source quotations, stage mismatch,
deduplicated listing frequencies, limited/no evidence, provider errors, quota recovery,
immutable refresh evidence, interrupted conversation-commit recovery with payload-bound
checkpoint replay, and shared goal persistence without a CV. Frontend tests
cover category review and explicit final confirmation using the existing goal endpoint;
`career-discovery.spec.ts` checks the same journey and mobile width in Chromium.
Transcript/context regressions cover reload, duplicate-message replay, bounded memory
and recent context, messages during research, optional questions, scope changes and
re-synthesis before stale results can publish. Context-list checks retain the newest
distinct entries while validating every supplied entry before trimming. Provider
requests are mocked.


Gemini reasoning migration regressions use synthetic settings and HTTP responses:
all Career production stages share Gemini 3.5 Flash Lite and ignore unused provider/model/key
switches. Brave grounding snippets
pass through the real JSON-schema adapter into every existing research field in all
five categories; model round-trips, exact citations, invalid aliases and forged
quotes are checked. These tests preserve existing domain schemas and do not establish
live-provider access or extraction accuracy. The opt-in live smoke uses the same
Gemini reasoning configuration as production.

Schema compatibility regressions also check all stage projections and reject oversized
skills, condition arrays, names, evidence and experience ranges despite provider HTTP
success. Gemini's decoding projection leaves the domain models unchanged.


Concurrent JD regressions hold full extraction open to prove public retrieval starts
first, then verify matching searches are not repeated, changed scopes discard seeds,
empty initial results still get a follow-up, and provider cooldowns survive adoption.
Combined-response regressions also hold the research summary open, verify no manual
resume is needed on success, and resume summary quota/transient failures without
repeating paid retrieval. A failed category cannot mark the workspace ready. Failed
cached categories and older missing summaries can recover while reusing valid work.
Frontend/component and browser checks hold back both initial summaries until both
results are ready, then verify that one assistant message contains the JD and research.
They verify owner-isolated progress, no raw-JD persistence, non-job document refusal,
unchanged goals on failure and refusal of unrelated tasks in question/refine modes.
Chat tests cover remaining on the chat route, fixed activity labels without provider
prose, typed summaries and continued questions; browser journeys open saved cards by
an explicit button after checking the chat summary. API artifacts include the additive
operation/workspace activity arrays; domain schema artifacts are unchanged.


Gemini rejection regressions cover native invalid-key/model/project/schema/parameter
errors, malformed bodies, safe API/log diagnostics, no schema-free fallback, and a
single explicit model override across every Career role. The Docker-template check
uses only the user-approved clean tracked public template in an isolated copy,
verifies that every declared key is consumed by the active Compose file, and requires
example secrets to remain blank. This exact-test exception does not permit inspecting
modified local examples or other environment files. Live provider credentials are not used.

`services/career-service/tests/test_compact_workspace.py` covers canonical goal promotion,
in-place edits/version conflicts, activation recovery, compact progress/results, lazy
owner/version-scoped evidence, whitespace-only quotes, salary/cohort safeguards, grounded
presentation checks, precise repair metadata and successful no-information results.

Research-validation regressions cover differently worded corroborating sources, shared
generation/storage text bounds and label enums, and preservation of storage failure
paths/reasons. Exact quote and exact-number
checks remain active; synthetic provider fixtures make no live Gemini/Brave calls.

Duplicate-finding regressions cover different summaries sharing one extract ID, stable
identity while merging corroborating citations, and quality-stage cleanup of persisted
duplicates before final report validation.

Opportunity-source limit checks verify that Brave receives a three-URL limit, the
adapter retains no more than three results even if the provider returns extras, and
weak coverage can replace initial sources through bounded follow-ups while the
final report retains at most three useful sources per category.

Direct-structuring regressions accept faithful paraphrasing without a second model
pass, preserve the model's exact final wording in storage/chat, and still reject
forged quotes/source references and unsupported numeric tokens. Numbers outside the
selected quote may be supported by the full cited excerpt; uncited numbers cannot.
Semantic faithfulness is instructed during structuring, not independently graded.

`test_research_coverage.py` exercises replacement of three irrelevant results, relevant
sources without facts, provider versus validation outcomes, retained citation integrity
and richer excerpts. UI regressions check the distinct category explanations.

Coverage refresh checks also preserve existing findings on provider failure and
normalize prefetched source IDs before evaluation without repeating early searches.

Structuring replaces the former model evaluation/support/overview-selection stages.
Quota/retry/ownership coverage remains; overviews are built locally from finding IDs.
Chat fixtures verify retained findings are displayed through the Gemini overview response, with temporary progress removed on completion.

Goal-chat presentation checks in `services/career-service/tests/test_goal_chat_presentation.py`
use synthetic adapters without MongoDB: summary citation validation, stale-goal rejection,
public-only follow-up queries, ambiguous/off-topic/edit search exclusion and summary-operation
reuse. Frontend chat tests mock the summary endpoint and verify completion and follow-ups.

`test_chat_citation_recovery.py` checks grouped markers, approved URL normalization,
rejection of forged destinations, per-finding citation coverage, summary-only bounded
repairs, discarded-response privacy, owner-scoped failed-operation diagnostics and
operation IDs. Frontend API coverage checks that error objects retain operation IDs.
These checks use synthetic responses; they do not establish live-provider quality.

Chat completion regressions cover delayed saved-report reads, automatic summary startup,
finished partial coverage, report-read retry without paid research, concise selection of
saved key points, and the exact final invitation appearing once. Backend tests also
verify pending categories remain blocked and summary context omits repeated quotations.

Structured summary coverage checks per-point fact references, unknown-reference rejection,
job-description/requirement citation registration, inline placement and deduplication,
plain-prose escaping, and the real adapter's JSON/schema boundary. Follow-up regressions
include balanced-parenthesis URLs, angle destinations and forged destinations. Frontend
Markdown tests verify that links sit in the paragraph/list item they support and that
escaped model links do not become active citations.

`test_followup_citations.py` verifies grouped fact markers become inline verified links,
unknown/undeclared references are rejected, source URLs deduplicate within a claim,
fresh-search references resolve, and expanded answers respect the reply limit. The
frontend interview-list regression checks the links are inside their supported stage.

## Saved CV checks

CV tests cover parsing restrictions, extraction/evidence validation, ownership,
durable worker processing and lease fencing, idempotency, correction overlays,
clarification answer/skip behavior, explicit selection and versioned capability
input. Profile capability tests cover account-field preservation, normalized
matching, explicit attachment/distinct declarations and concurrent retries.

The full-stack CV browser test additionally exercises the real HTTP model adapter
against a deterministic synthetic server. Start the disposable stack with both
`-f infrastructure/docker/compose.yaml` and
`-f infrastructure/docker/compose.test.yaml`, and provide all four test database
passwords including `CV_DB_PASSWORD` and `CAREER_DB_PASSWORD`. The override uses a development-only HTTP
fixture and must not be used for personal CVs or production. It rejects sources
without the explicit synthetic marker. Generate the committed synthetic DOCX
fixtures with `python infrastructure/testing/make-cv-fixtures.py`.

The saved CV journey checks manual entry before upload, extraction, no automatic
selection, saved correction after reload and exact-source reprocessing, versioned
handoff, provider failure isolation and cross-account access. The clarification integration journey uses the canonical Career goal with explicit version-bound confirmation and real CV HTTP context requests: project/work answers, skill skips, reload, goal changes, reconfirmation and voluntary answers. It verifies preserved effective versions and owner isolation. These checks establish application behavior and contract
handling, not real-provider extraction quality; evaluate the configured model on
reviewed synthetic CVs before relying on its interpretation.

Profile compatibility adds unit and browser coverage for C-series drafts through session
revalidation, transient or malformed validation responses, explicit retry and
expiry/account changes. Healthy periodic checks remain silent; there is no new
inactivity lock. The real-service branch matrix covers students, National Service,
employment and both unemployment paths, including edits after a saved CV upload.
Its uploads are paced to the unchanged gateway limit of six per minute because
the synthetic accounts share one IP. Native browser cache eligibility and actual
model interpretation quality are not established by these checks.

## C-series interpretation completion

Clarification tests separate answer receipt, interpretation status and factual
resolution. Synthetic cases cover personal/team/observed/denied contribution,
explicit new personal skills, unknown values, independent supporting sources,
attribute preservation, partial dates, distinct follow-ups and effective no-ops.
Execution tests cover concurrent identical requests, live/expired interpretation
leases, bounded capacity and late-result rejection. Model output is tested for
wrong identities, unsupported excerpts, unrelated field changes and manufactured
date precision. These checks do not establish live-model semantic accuracy.

Source reconciliation tests retain both results, require explicit same-kind mapping,
preserve origin/history, and allow dismissal after the previous CV changes. Manual
attachment tests check project-derived skills, fingerprints, explicit detach/reattach
and semantic no-op refresh. Target-bound input checks exercise both target types and
version races without invoking an assessment or roadmap service.

## Saved CV conversation

The CV suite exercises the account-owned conversation store against both the
in-memory repository and disposable MongoDB. Coverage includes resumable and
manual-only conversations, ordered pagination, segment rollover, revision
conflicts, exact retries after a lost response, partial multi-action outcomes,
interrupted processing and recovery after a fact was saved but its chat receipt
was not. Listing history uses projected metadata rather than loading old message
bodies. Transcript activity is checked separately from evidence versions.

Routing and interpretation tests reject foreign source IDs, unsupported excerpts,
invalid actions and malformed or oversized provider responses. They preserve the
full user answer, including negation and team attribution, while appending bounded
source-linked clarification events. Session revocation during processing, stale
target/source context, provider capacity and storage limits are checked before
publishing facts. Corrections and manual additions still require explicit approval.

Frontend tests cover saved history, source choices, confirmation cards, async save
receipts, retries with the original mutation body, stale responses and account/CV
switches. The full-stack `cv-chat.spec.ts` uses the real local gateway, services and
MongoDB with the deterministic model fixture. Its journeys include rich answers,
questions without evidence changes, additional context, correction cancel/save,
reload/resume, skips, manual-only capabilities, ambiguous references, stale cards
and partial failures. Existing saved-upload, Profile and Career journeys remain in
the suite. Boundary browser checks also cover unsent chat drafts through temporary
session failures and the absence of private CV content in browser storage.

Use synthetic accounts and documents for recordings. A recording of this fixture
workflow demonstrates interaction and persistence, not live-model interpretation
quality. Conversational quality and comparative usability still need evaluation
with the configured model and representative users.

## Canonical goal confirmation and compatibility

Career automatic save remains separate from version-specific CV acknowledgement. Confirmation tests must cover exact goal/selection/projection identities, edits between reads and CAS, switches, foreign ownership, changed mutation bodies and lost-response retries. A stale acknowledgement cannot confirm a newer goal. Generic requirements preserve original category/origin and AND/OR alternatives; location/eligibility is not silently converted into qualification evidence. Prior CV facts survive goal changes.

Career's saved-CV adapter tests preserve UUID/ObjectId references, original source identities, attribution, unknown proficiency, fractional months, conflicts and full evidence. More than 200 skills/excerpts are accepted within its existing 512 KiB document/streaming admission bound. Oversized data fails explicitly before unbounded decoding, without truncation. Public CV and internal Career schemas are checked separately. Mixed legacy UUID target/canonical ObjectId history and existing uniqueness indexes need non-destructive compatibility checks.

The integrated browser journey should save a canonical goal using synthetic fixture data, explicitly confirm its current revision through the real API, then use the saved CV conversation. Fixture seeding belongs only to a disposable test database, never an application auth bypass. Existing chat/upload/Profile journeys retain their original assertions through the new disclosures and current Career flow.

## Environment and evidence boundaries

Use disposable databases and synthetic documents/accounts. Never mount a personal environment file into tests. One upstream public-template test has a narrow user-approved exception: run that exact test against a clean tracked public template in an isolated test copy. It does not authorize inspecting modified local examples or other environment files.

On the observed Docker Desktop kernel, MongoDB 8 refused startup because of its known kernel compatibility guard. Isolated MongoDB 7 can establish functional repository behavior, but does not establish intended MongoDB 8 compatibility. MongoDB-backed CI uses a compatible pinned Ubuntu 22.04 runner. Report local functional checks, intended-version CI, browser fixtures and real-service journeys distinctly. Do not bypass the guard or change host settings as an incidental test repair.

The previous C-series captioned recording uses synthetic models and the pre-integration build. It is retained as a workflow reference, not proof of the merged Career confirmation flow or live-model accuracy. Re-record or exercise the integrated journey after the final code changes. Cost, latency, interpretation quality and comparative usability require separately authorized live-model/user evaluation.

## Assessment and Roadmap adviser

Run each service separately because they use independent `app` namespaces. With pinned dependencies installed, repository tests can use:

```sh
cd services/assessment-service
PYTHONPATH=../../packages/elo-shared:. python -m pytest
```

Repeat in `services/roadmap-service`. Shared runtime MongoDB race/recovery tests live under `packages/elo-shared/tests` and require an explicit disposable `MONGODB_TEST_URI`; they create/drop only uniquely named `elo_planning_test_*` databases. Never point these tests at application databases. Existing service tests also need the shared package installed or on `PYTHONPATH`. Career tests need a populated local `TIKTOKEN_CACHE_DIR` so synthetic provider checks never download encodings.

New tests cover shared aliases, exact limitation/evidence references, complete requirement coverage, AND/OR rules, explicit partial research, source-change races, owner isolation, pending-operation restart recovery, idempotent lost-response retry, selected-day allocation/conservation, zero capacity, reduced periods, cycles, unsplittable work, proposal activation, stale proposal rejection and completion/definition history. Frontend tests cover input gates, next-message preservation, partial-analysis choice, old-account response isolation and exact retry identities. `roadmap.spec.ts` exercises chat, proposal activation, task completion/reload, evidence view, preference preview and desktop/mobile layout using synthetic HTTP fixtures.

Generated OpenAPI and result schemas must match the owning service models. Tests establish transport/domain behaviour, not the accuracy or usefulness of a live adviser. Use labelled representative CV/goal cases and separately authorised provider evaluation before making semantic-quality claims. Tests that read environment files must not run when the task prohibits that access.

`infrastructure/testing/planner-smoke.py` starts the real Assessment and Roadmap HTTP applications with synthetic source APIs/model adapters against uniquely named disposable MongoDB databases. It checks cross-service capture, partial research, allocation, activation/replay, completion, process restart persistence and owner isolation, then removes its processes/databases. It requires the new service dependencies and an explicit disposable `MONGODB_TEST_URI`.

Assessment's `evaluate.py` is a separate paid-provider opt-in (`RUN_LIVE_ASSESSMENT_EVAL=1` plus an explicitly configured service key). It reports observed versus labelled outcomes for synthetic fixtures under `tests/fixtures/labelled-comparisons.json`; it does not read environment files. The small diagnostic set is not a representative accuracy benchmark. It has not been run as part of synthetic verification.

Compact progress polling is checked separately from full workspace reads. Provider cooldowns persist across retries; a new message key cannot bypass the saved delay. Reconciled task editors retain their original definition and apply only changed fields after reload, preserving concurrent edits to other fields while rejecting same-field conflicts.

## Career extraction with a local model

The isolated fixture/live-model browser runner and its prerequisites are documented
in [Career tests](../services/career-service/tests/README.md#reproduce-the-complete-career-extraction-journey).
It never loads private environment files. Live inference uses `deepseek-r1:1.5b`;
public retrieval is controlled, so the run does not establish live-search quality.
Each run retains a uniquely named JSON attempt report and browser artifacts;
`--repeat 3` records three fixed attempts per mode without discarding failures.
Current exact-model limitations are recorded in the
[local-model verification](../services/career-service/tests/LOCAL_MODEL_VERIFICATION.md).

Chat display browser tests distinguish safe terminal failure explanations from raw
provider diagnostics: invalid answers show an actionable Retry alert while private
provider text stays hidden. Synthetic research sources include their required
platform metadata so response validation succeeds before scroll/citation checks.
