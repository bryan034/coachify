# Assessment — G01–G07

Provider configuration: the service now reads its own `*_LLM_BASE_URL`,
`*_LLM_MODEL`, `*_LLM_API_KEY` and `*_LLM_ALLOW_HTTP`. HTTPS is required outside
explicit development HTTP mode. Local testing can share the 16K-context
`elo-deepseek-r1:1.5b` Ollama alias, without sending preserved cloud keys.
Providers receive JSON Output plus the schema in the prompt;
all responses still undergo the existing Pydantic and domain checks. Local calls
serialize per service instance and use a 180-second HTTP timeout; operations use
600-second budgets and 630-second leases. Cloud limits remain unchanged.


## Scope and authority

Implements Epic G's shared comparison as a separately deployed FastAPI service, per the user's 30 October 2026 architecture decision. This supersedes earlier Career-owned future assessment boundaries. Career continues to own goals, JD dates and public research; CV owns evidence/corrections; Profile owns manual declarations. Assessment owns its MongoDB `skill_gap_analyses` and operational `workspaces`. Stored evidence is an immutable captured input, never a second editable capability authority.

The new pipeline uses `assessment-v1`; Career's older `analysis-v1` contracts/repository remain compatibility code and do not publish new runtime assessments. No existing collection is automatically moved, renamed or deleted. Existing Career-stored historical analysis data, if any, stays with its original service until a separately reviewed migration is needed.

## Inputs and identity

The owner must have a generated Career goal containing at least one skill/condition, and either a selected ready CV or saved Profile declarations when no CV is selected. Read-only GETs do not create assessments. Missing optional proficiency, skipped clarification and missing planning preferences do not block comparison. Pending/failed factual interpretation or CV reconciliation does block source admission; it is not capability uncertainty.

Career exports `/api/v1/career/assessment-input`, containing its exact current goal/selection and current owner-linked research. CV exports `/{id}/assessment-input`, reusing its versioned capability snapshot and rejecting unfinished interpretations. Unlike CV's target-confirmed clarification envelope, this source export does not acknowledge a goal for factual clarification. Assessment separately binds and revalidates the full Career target; no confirmation stamp is silently created.

Capture CV/version/extraction/effective/selection revisions, declarations revision, Profile version, goal/version/selection, research/version/coverage and registry version. Recheck before publication and on current reads. A Singapore comparison date is additionally pinned for conditions or ongoing evidence, so time-sensitive results become stale on a later date. This is API-based revalidation, not a cross-service transaction. History stays immutable; changed sources mark the current comparison and consuming roadmap stale.

`GET /dashboard-source` reads the account's saved result and the current input vector without launching or resuming pending model work. It reports current, stale, missing, not-ready, unavailable or conflicting input states and retains the saved result when input sources cannot be checked. A changed Assessment workspace during capture returns a conflict rather than combining versions. The version and source vector support bounded consumer rechecks; they do not constitute a cross-service atomic snapshot. Its workspace update time and result creation time come from the saved records, not the read time.

All producers expose additive `canonical_skill_id` plus `skill_registry_version` from `packages/elo-shared`. Original `skill_id` keys remain intact for saved clarification/attachment compatibility. The shared registry resolves explicit unambiguous aliases independently of superficial category labels. Unknown identities stay null. Contextual LLM matching is recorded as semantic relevance with a reason; it cannot publish new registry identities or change source records.

## Comparison

Bounded batches of at most eight requirements use schema-constrained LLM interpretation. Every active requirement has one result, with required capability/proficiency/duration/qualification components. Each component retains source references and its explanation. Missing/contradictory evidence remains uncertain. Known shortfall requires an exact explicit limitation quote; basic-use-only evidence is not proof of inability at an advanced level. Supported proficiency/duration/independence requires an exact supporting declaration. Source-linked skill claims preserve attribution/assistance; whole project/experience context cannot bypass those claims. Structural/quotation validation does not independently prove semantic entailment.

Python combines components and flat source-defined AND/OR groups. AND requires all conditions for full support; an established unmet mandatory condition remains visible beside unknowns. One supported permitted OR route satisfies the group. OR shortfall requires every route to be established insufficient. Per-component facts remain available. Nested clauses not represented by the producer's group contract must remain explicitly unresolved rather than guessed.

Priorities include only established trainable shortfall components, with source importance and stable identity ties; unused routes in a supported OR group are excluded. LLM recommendations are suggestions, not new employer requirements. Constraint outcomes remain separate. This release does not implement inferred prerequisite learning graphs or automatic roadmap generation from every gap.

Current Opportunity reports are read from their interview category; archived `InterviewSkill` records remain supported. Preparation topics/questions/difficulty inform interview advice, not mandatory JD criteria. Fresh valid empty findings differ from absent/failed/stale/partial research. The caller explicitly sets `allow_partial=true` to accept a labelled partial comparison when research is unavailable. Private CV data never enters public research stores.

## Durability and limits

Each accepted command has UUID mutation identity and expected workspace revision. Persist before model work; a per-owner leased CAS workspace fences replicas. Completed batch outputs and their captured inputs checkpoint durably, so quota/provider retries retain completed comparisons. Model requests use a configured OpenAI-compatible endpoint (OpenRouter HTTPS by default), service-scoped model/key settings, schema validation and up to two schema repairs. Provider quota errors expose safe retry delay; invalid output/failure cannot become successful uncertainty.

A worker runs at most 210 seconds per execution, renewing its 240-second lease at checkpoints. Retry resumes completed batches. Restart recovery occurs when an authenticated GET reconnects after a lease expires; no bearer is persisted. Revocable sessions and exact source revisions are checked before publishing. Immutable result insertion precedes pointer CAS; an interrupted pointer update recovers the same request-bound result, and older writers cannot replace newer pointers.

Limits: 1 MiB upstream response, 120,000 UTF-8 bytes/model context, 512 KiB model response, 64 KiB request body, 4 MiB retained workspace and 1,000 mutation receipts. Excess is explicit; sources are not silently truncated. Private reads/errors use no-store; prompts, response prose, tokens and evidence are not logged. Authentication/ownership is enforced in the backend. Three concurrent executions per process; one active operation per owner.

### Evidence-validation correction

Each assessment batch allows one correction after an `assessment_output` evidence
validation failure. The model receives the unchanged requirements and evidence,
its rejected output and fixed local validation guidance. An unknown evidence
reference names the requirement, component and exact rejected references in
that guidance only; the user-facing error stays generic. A repeated reference
within one component is collapsed rather than rejected. The corrected batch
passes every original check before checkpointing. A second failure ends the
operation without publishing a partial assessment. Provider, authentication and
quota failures bypass this correction. Existing schema-level retries remain separate.

## Remaining boundaries

G05 factual corrections use the existing CV/Profile review entry points; adviser chat itself does not mutate capability evidence. Inferred dependency ranking, result-specific roadmap notifications and migration of any old Career analysis records remain unimplemented. Tests establish contracts/workflow with synthetic models, not live-model quality.

## Phase 2 comparison sources and reserved scoring fields

Comparison can run independently of Roadmap using the existing versioned command.
When no CV is selected, saved Profile capability declarations (including published
manual intake) are sufficient. Draft intake is excluded. A selected pending/failed
CV still blocks admission; it never silently falls back to manual evidence.
`inputs.source_mode` distinguishes `cv_and_profile` from `profile_only`. CV identity,
extraction and effective versions are nullable in the latter; selection, declarations,
Profile, goal and research revisions still participate in staleness/publication checks.
Historical input vectors without source_mode remain readable with the CV default.

Each outcome reserves nullable `relevance`, `competence_score` (0–10), `required_score` (0–10, the role's stated level on the same scale, null when no level is stated),
`score_explanation` and `scoring_rubric_version`, plus `score_status`.
No scoring rubric has been approved: relevance/scores/rubric stay null, with an
explicit explanation. Existing evidence statuses remain the implemented comparison;
CV source-specific application levels remain unchanged. These fields do not claim
measured mastery. Future score population requires rubric review.

## Per-skill profile evaluation

After every requirement batch is checkpointed, the worker asks the model to judge
each distinct profile skill. Skills are merged by registry identity, else by name,
across reviewed CV skill claims and Profile declarations. The model reads each
skill's scoped sources: attribution, assistance, application level, review answers
and the experience they came from. It also reads the goal's job-skill requirements
with their priority, stated level and comparison status. Skills go in batches of at
most 15. The result's `skill_profile` (`rubric_version: skill-profile-llm-v1`) holds,
per skill:

- `category`: one of the shared display categories (`elo_shared.skill_groups.GROUP_NAMES`).
- `subcategory`: an optional short label, such as Languages, Frameworks or Tools.
- `relevance`: `high`, `medium`, `low` or `none` for the goal.
- `competence_score` and `required_score`: whole-number planning estimates on one
  0–10 scale, where 3 is guided use, 6 is independent use and 9 is complex use.
- `explanation`: a short user-facing explanation.
- `evidence_refs` and `requirement_refs`: what the judgement relied on.

Local validation requires one judgement per skill. Evidence references must come
from that skill's own sources, and requirement references from the goal. A
competence score needs at least one cited source that is personal and certain;
team, observed, denied and uncertain sources cannot support one. `required_score`
is dropped when relevance is `none`. A rejected batch gets one correction with
fixed feedback. If it still fails, that batch is left out and `status` becomes
`partial`, or `failed` when no batch passed. The requirement comparison is
still published either way. A profile with no skills is `empty` and makes no
model call. Provider and quota failures end the operation, and a retry resumes
from the checkpointed requirement and skill batches. Results saved before this
step have no `skill_profile`. These are planning estimates, not tested mastery.

## Explicit evaluation and goal-skill competence

A comparison starts only from the versioned `POST` command. Career Goal and Skills
Profile send it from the **Evaluate skills with career goal** banner. No read starts
one: `GET /current` resumes a pending operation, and `GET /dashboard-source` and
`/context` are passive. Changed inputs mark the saved result stale until the user
evaluates again.

`GET /context` reports what the banner needs to show either the evaluate action or
the one setup step still open:

- `ready` and `issues` (each with `source` `career` or `cv` and an `href`): whether a
  goal and a skills source exist;
- `cv_reviewed`: the selected CV's review covers its current effective version (true
  when there is no CV and saved declarations exist);
- `research_pending`: goal research is still pending or processing;
- `model_available`.

`cv_reviewed` and `research_pending` are null until both sources exist. The client
offers evaluation only when the inputs are ready, the review is finished and research
has settled. The command itself does not require a finished review, because Roadmap
also starts comparisons through it. Each result is saved immutably in
`skill_gap_analyses`. Roadmap reads it through `GET /current` and plans from its
`job_skill_gaps`.

For each job skill, the requirement batch also returns `demonstrated_level` and
`required_level`. These are whole numbers on one 1–10 scale (3 guided, 6
independent, 9 complex use), plus a short `score_explanation`. A demonstrated level
needs a cited component reference that is personal, certain and source-scoped.
Otherwise the batch goes through the existing single correction. Outcomes then store
`demonstrated_score`, `required_score` and `competence_score` (rubric v1: `min(10,
round(10 × demonstrated / required))`, so 10 means the evidence meets the goal's
level), with `scoring_rubric_version: llm-ratio-v1`. The model's levels are ignored
for interview-preparation and constraint outcomes. Without both levels, the
earlier `application-ratio-v1` estimate applies.

After the per-skill evaluation, each job-skill outcome lists `profile_skills`: the
Skills Profile skills whose judgement cited that requirement. An outcome still
unscored takes the strongest linked profile skill's competence against the
outcome's (or that skill's) required level (`profile-link-v1`). Scores never change
match status, gaps or priorities.
