# Phase 3 contract proposal

Status: contract direction and ratio rubric approved by the user on 10 November 2026. Implementation and verification in progress.
Existing service ownership, authentication, CAS versions and mutation receipts remain.
No new deployment settings or service databases are proposed.

## Career

Add an optional bounded `learning_items` array to each goal skill: item ID, name,
importance, importance origin, reason and source references. Preserve existing JD
priority/evidence; inferred learning advice must not become employer requirements.
Old goals return an empty array until explicitly refined or re-extracted.
Cache the validated presentation summary by owner, exact goal/selection version,
research ID/version and presentation version in existing Career operational storage.
Discovery exposes paginated owner-only session summaries; before replacing an
existing goal, a versioned publish command confirms the replacement. Research may
finish and remain saved without changing the current goal. Starting a new chat is
not publication consent. Goal chat accepts career and elo questions, but retains
backend scope, input limits and injection safeguards.

## Roadmap

Extend PlannerConfig with an explicit overflow window (proposed 08:00–22:00 in the
user's IANA zone, editable), and schedule preferred blocks first, then enabled
backup blocks, then overflow within that window. All paths subtract blackouts,
elapsed time, protected work and completed work. Weekly caps remain hard limits.
The UI must show this changed interpretation before generation. Existing saved
plans are preserved; changing capacity requires revalidation.
Use a versioned, idempotent roll-forward command on the first authenticated visit
after a planning week finishes, not model calls in GET handlers. It prepares and
applies the next week while preserving completed, edited, removed and in-progress
work. Concurrent source/config changes abort publication. Background execution
without an active session is outside this proposal.
Expose evidence proposals from completed sessions/notes as Roadmap-owned proposals;
only explicit user confirmation writes through Profile's declaration API. A
completed session alone never establishes competence.
Learning-focus suggestions are backend-derived from the captured skills taxonomy,
with custom notes retained. CV selection uses CV's existing versioned API.

## Skills and Assessment

Keep evidence/application estimates in CV and goal-relative results in Assessment.
Expose canonical skill identities and deterministic subcategory metadata; categories
with more than eight skills expand into stable subcategories, without changing IDs.
Merge only known unambiguous aliases; Azure and AKS remain distinct unless their
actual canonical identities agree. Preserve all source evidence on merged rows.

Proposed scoring rubric v1: guided=3, independent=6, complex=9 on an evidence scale.
Required beginner/intermediate/advanced map to guided/independent/complex respectively; expert has no supported equivalent and stays unscored. When BOTH the supported evidence level and the goal's required level are explicit,
score=min(10, round(10 * evidence_level / required_level)). Otherwise score stays
null, with not_reviewed or insufficient_evidence. This is a planning estimate, not
measured mastery. No default required level may be invented.
Relevance uses validated requirement mappings: required=high, preferred=medium,
advisory/inferred=low; no relationship=none only after a complete current comparison.
No goal, stale/incomplete mapping or unavailable sources remain unknown/null.

## Jobs and applications

Add nullable applied_at, deadline, follow_up_at and bounded notes to application
snapshots and version-checked PATCH; keep existing status/history and ownership.
A Closed board column groups rejected/withdrawn without inventing a new status.
Recommendation and per-job skill matches are computed by Jobs through authenticated
Career/Profile/CV APIs from canonical identities and listing terms; distinguish
name overlap from Assessment competence. Add an explicit recommended sort and
version its cursor so pagination does not mix sort orders. No private evidence is
sent to public listing providers. Use-as-goal opens Career's existing URL intake
for review; it must not replace a goal directly.

## Other pages

Conversation and calendar views aggregate owning APIs, not foreign databases.
Onboarding's optional goal/CV handoffs begin after canonical background completion
and can be skipped; no partially completed account may bypass the guard.
Profile links to the implemented password recovery flow. Account deletion/export
remain explicitly unavailable until a separate lifecycle design is approved.
