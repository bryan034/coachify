# Assessment — G01–G07

## Scope and authority

Implements Epic G's shared comparison as a separately deployed FastAPI service, per the user's 30 October 2026 architecture decision. This supersedes earlier Career-owned future assessment boundaries. Career continues to own goals, JD dates and public research; CV owns evidence/corrections; Profile owns manual declarations. Assessment owns its MongoDB `skill_gap_analyses` and operational `workspaces`. Stored evidence is an immutable captured input, never a second editable capability authority.

The new pipeline uses `assessment-v1`; Career's older `analysis-v1` contracts/repository remain compatibility code and do not publish new runtime assessments. No existing collection is automatically moved, renamed or deleted. Existing Career-stored historical analysis data, if any, stays with its original service until a separately reviewed migration is needed.

## Inputs and identity

The owner must have a selected ready CV and a generated Career goal containing at least one skill/condition. Read-only GETs do not create assessments. Missing optional proficiency, skipped clarification and missing planning preferences do not block comparison. Pending/failed factual interpretation or CV reconciliation does block source admission; it is not capability uncertainty.

Career exports `/api/v1/career/assessment-input`, containing its exact current goal/selection and current owner-linked research. CV exports `/{id}/assessment-input`, reusing its versioned capability snapshot and rejecting unfinished interpretations. Unlike CV's target-confirmed clarification envelope, this source export does not acknowledge a goal for factual clarification. Assessment separately binds and revalidates the full Career target; no confirmation stamp is silently created.

Capture CV/version/extraction/effective/selection revisions, declarations revision, Profile version, goal/version/selection, research/version/coverage and registry version. Recheck before publication and on current reads. A Singapore comparison date is additionally pinned for conditions or ongoing evidence, so time-sensitive results become stale on a later date. This is API-based revalidation, not a cross-service transaction. History stays immutable; changed sources mark the current comparison and consuming roadmap stale.

All producers expose additive `canonical_skill_id` plus `skill_registry_version` from `packages/elo-shared`. Original `skill_id` keys remain intact for saved clarification/attachment compatibility. The shared registry resolves explicit unambiguous aliases independently of superficial category labels. Unknown identities stay null. Contextual LLM matching is recorded as semantic relevance with a reason; it cannot publish new registry identities or change source records.

## Comparison

Bounded batches of at most eight requirements use schema-constrained LLM interpretation. Every active requirement has one result, with required capability/proficiency/duration/qualification components. Each component retains source references and its explanation. Missing/contradictory evidence remains uncertain. Known shortfall requires an exact explicit limitation quote; basic-use-only evidence is not proof of inability at an advanced level. Supported proficiency/duration/independence requires an exact supporting declaration. Source-linked skill claims preserve attribution/assistance; whole project/experience context cannot bypass those claims. Structural/quotation validation does not independently prove semantic entailment.

Python combines components and flat source-defined AND/OR groups. AND requires all conditions for full support; an established unmet mandatory condition remains visible beside unknowns. One supported permitted OR route satisfies the group. OR shortfall requires every route to be established insufficient. Per-component facts remain available. Nested clauses not represented by the producer's group contract must remain explicitly unresolved rather than guessed.

Priorities include only established trainable shortfall components, with source importance and stable identity ties; unused routes in a supported OR group are excluded. LLM recommendations are suggestions, not new employer requirements. Constraint outcomes remain separate. This release does not implement inferred prerequisite learning graphs or automatic roadmap generation from every gap.

Current Opportunity reports are read from their interview category; archived `InterviewSkill` records remain supported. Preparation topics/questions/difficulty inform interview advice, not mandatory JD criteria. Fresh valid empty findings differ from absent/failed/stale/partial research. The caller explicitly sets `allow_partial=true` to accept a labelled partial comparison when research is unavailable. Private CV data never enters public research stores.

## Durability and limits

Each accepted command has UUID mutation identity and expected workspace revision. Persist before model work; a per-owner leased CAS workspace fences replicas. Completed batch outputs and their captured inputs checkpoint durably, so quota/provider retries retain completed comparisons. Model requests use a fixed Gemini HTTPS endpoint, service-scoped key/model, schema validation and up to two schema repairs. Provider quota errors expose safe retry delay; invalid output/failure cannot become successful uncertainty.

A worker runs at most 210 seconds per execution, renewing its 240-second lease at checkpoints. Retry resumes completed batches. Restart recovery occurs when an authenticated GET reconnects after a lease expires; no bearer is persisted. Revocable sessions and exact source revisions are checked before publishing. Immutable result insertion precedes pointer CAS; an interrupted pointer update recovers the same request-bound result, and older writers cannot replace newer pointers.

Limits: 1 MiB upstream response, 120,000 UTF-8 bytes/model context, 512 KiB model response, 64 KiB request body, 4 MiB retained workspace and 1,000 mutation receipts. Excess is explicit; sources are not silently truncated. Private reads/errors use no-store; prompts, response prose, tokens and evidence are not logged. Authentication/ownership is enforced in the backend. Three concurrent executions per process; one active operation per owner.

## Remaining boundaries

G05 factual corrections use the existing CV/Profile review entry points; adviser chat itself does not mutate capability evidence. Inferred dependency ranking, result-specific roadmap notifications and migration of any old Career analysis records remain unimplemented. Tests establish contracts/workflow with synthetic models, not live-model quality.
