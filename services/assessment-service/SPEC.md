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

Requirement batches use a private response schema that enumerates the exact
evidence keys and requirement references in the captured batch. Nested source IDs
cannot pass schema validation as evidence references; an empty evidence set allows
only an empty reference list. The shared model adapter's bounded schema repairs
handle invalid references before domain validation. Public contracts and saved
source references are unchanged.

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
The approved `evidence-role-v2` rubric below populates these planning estimates.
Historical results remain immutable and retain their earlier rubric identifier.

## Per-skill profile evaluation

After every requirement batch is checkpointed, the worker asks the model to judge
each distinct profile skill. Skills are merged by registry identity, else by name,
across reviewed CV skill claims and Profile declarations. The model reads each
skill's scoped sources: attribution, assistance, application level, review answers
and the experience they came from. It also reads the goal's job-skill requirements
with their priority, stated level and comparison status. Skills go in batches of at
most 15. The result's `skill_profile` (`rubric_version: evidence-role-v2`) holds,
per skill:

- `category`: one of the shared display categories (`elo_shared.skill_groups.GROUP_NAMES`).
- `subcategory`: an optional short label, such as Languages, Frameworks or Tools.
- `relevance`: `high`, `medium`, `low` or `none` for the goal.
- `competence_score` and `required_score`: whole-number planning estimates on one
  0–10 scale, subject to the evidence ceilings below.
- `explanation`: a short user-facing explanation.
- `evidence_refs` and `requirement_refs`: what the judgement relied on.

Local validation requires one judgement per skill. Evidence references must come
from that skill's own sources, and requirement references from the goal. A
competence score needs a cited source. Team, observed and denied sources cannot
support personal competence; ambiguous project participation has only a provisional
level 3, with low confidence, and does not establish capability match status. `required_score`
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

For each job skill, Career supplies a `competence_target` with a level, basis,
explanation and source URLs. Familiarity requires at least level 8; advanced or
proficient work targets 9, expert mastery 10. Explicit beginner requirements target
7; unstated legacy requirements default to 8 (advanced 9). These are elo planning
standards, not claimed employer pass marks. Fresh, nonconflicting medium/high-confidence
public preparation findings naming the same skill can raise the target from their
cited passages; stale, weak or unrelated findings cannot. Research never lowers a
stated target. Without qualifying research the target is labelled inferred or JD-based.

Both requirement and per-profile-skill judgements use these backend ceilings:

- Ambiguous project/experience participation or guided application: 3. Unclear personal
  contribution is explicitly provisional, with low confidence; it never proves a match.
- Explicit independent application without a recorded successful outcome: 4.
- Independent successful delivery: 5.
- Additional skill-specific complexity and problem solving: up to 7.
- Complex successful work with explicit frequency/recency and at least 24 months of
  skill experience: up to 9. Ten is not awarded from these self-reported sources.

Explicit low replication confidence, conflicting facts or failed outcomes constrain
estimates. Team-only, observed or denied work remains unscored. Review `self_rating`
is an optional, quoted skill-specific 1–10 user baseline; it cannot replace the analysis
or inflate the evidence ceiling. General project complexity cannot inflate all skills.
The model can propose a lower level above the basic tiers, but cannot exceed the
backend ceiling or choose a weaker role target. Scores remain planning estimates.

Outcomes store `demonstrated_score` (the evidence level), `required_score` (the role
target), `score_confidence`, and role-relative `competence_score`:
`min(10, floor(100 × demonstrated / required) / 10)`. Level 5 against target 8 is
6.2/10; a provisional 3 is 3.7/10. Only actually meeting/exceeding the role target
reaches 10/10. Profile skill scores remain absolute evidence levels, not this ratio.

`scoring_rubric_version` and the profile `rubric_version` are `evidence-role-v2`.
The input hash includes this version, making older comparisons stale without changing
history. Pre-v2 pending checkpoints restart under v2 only if the exact source revision
vector still matches; changed sources retain the normal rejection. New checkpoints
resume completed v2 work normally. Profile links retain the same ceilings and role
target when filling an unscored requirement. Scores never change match status, gaps
or priorities. The Career Goal page marks current progress on each skill line and
explains that 10/10 satisfies this specific role's goal, based on available evidence.
