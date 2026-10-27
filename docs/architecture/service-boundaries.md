# Service ownership and user-story mapping

| Service | Story groups | Owned data |
|---|---|---|
| Profile | P01-P16; C07 manual declarations | Existing accounts/email verification/revocable sessions, canonical onboarding and education, declared deadline/capacity/temporary availability, profile versions; account-embedded manual capability declarations and their own revision |
| CV | C01-C09, with C07 composition | Saved CVs, ingestion state, extracted facts/skills and bounded evidence, CV-specific correction/removal overlays, clarification questions/answers, processing operations, explicit saved-CV selection |
| Career | J-series; G01-G07 | Transient JD previews, immutable reviewed career_goals and versioned explicit selection; research, AI target generation and gap analyses remain planned |
| Roadmap | R01-R09; E01-E07; T01-T06; A02-A04 | Consumed planning-input snapshots, milestones, tasks, progress history, proposed/applied revisions |
| Dashboard | D01-D06 | No persistent domain records; aggregate responses |
| Review | A01 orchestration; S01-S06 | Manual/scheduled review state, pace analysis, schedules, approval preferences |

## API dependencies

- CV -> Profile: validate account/session and read account declarations with their revision.
- Profile -> CV: validate an explicitly chosen matching CV item/version before a manual attachment; no CV is needed for a plain declaration.
- CV -> Career: authenticate and validate the owner’s selected confirmed target, skill IDs and exact target/selection versions for relevant clarification.
- Career -> Profile: validate the account/session and completed onboarding.
- Planned Career -> CV: consume an explicitly selected effective CV plus declarations and exact source versions.
- Planned Career -> Profile: versioned background/planning inputs; manual additions use the Profile declaration API, while CV-specific corrections use CV.
- Planned Roadmap -> Profile/Career: generation inputs and freshness checks.
- Planned Roadmap -> Review: verify the current automatic-application policy.
- Planned Dashboard -> Roadmap/Career/Review: current progress and dated pace analysis.
- Planned Review -> Profile/Career/Roadmap: read inputs, request a revision, request authorised application.

Records are read through APIs, never another service's collections. Public endpoints
verify ownership. Current CV/Profile calls forward the revocable owner bearer and
keep both services private; public IDs do not confer access. A future autonomous
service caller needs an explicit authenticated service identity plus validated
owner context. This slice does not introduce that separate credential protocol.

## C-facing ownership and compatibility

The supplied logical `users` collection is the existing physical `accounts`
authority. Its UUID `id` is canonical `user_id`; the authentication `owner` string
and all account/P-series records stay intact. No ObjectId migration or second
user collection is required. CV IDs are opaque API strings and application code
validates referenced ownership and versions; MongoDB does not enforce foreign keys.

CV-specific contributions, extraction corrections and removals stay with their
source CV. This replaces the earlier proposed import of all clarified capability
data into Profile. Manual declarations are embedded in the account so they exist
without a CV and survive uploads, replacements and selection changes. Attachments
preserve source identities; repeated text is not independent proof. Unknown
proficiency, duration and independence remain unknown.

One CV-owned `cv_selections` operational record per user stores the selected CV
and its revision. Upload success never changes this record. Declaration mutation
receipts and CV operation/history metadata are operational records allowed beside
the five logical domain collections; they do not add competing capability stores.

Effective input retains CV ID, extraction/effective version, selection version and
declaration version. A consumer also retains its confirmed target version and any
Profile version actually used. Revalidation around assembly detects changed
inputs; this is not a cross-service transaction. Historical analysis inputs must
remain immutable. Career persists reviewed target snapshots in `career_goals` and operational
selection in `career_target_selections`. Confirmation and selection are explicit separate
operations; confirmed snapshots are immutable. A replacement creates a new target,
then an explicit selection switch. CV retains the exact target/selection/extraction
snapshot used to prepare questions and rechecks selection after preparation.
Pending prompts follow current relevance; factual answers/skips remain source-bound.
AI target generation and J/G analysis admission are still unimplemented; neither
saving a target nor finishing clarification claims analysis or readiness.

## Clarification interpretation and reconciliation

CV retains original answers separately from validated, source-scoped interpretations.
Attribution, assistance, known values and uncertainty live at individual skill-source
scope; denied team support does not erase another source. Partial dates retain their
precision and never imply months using a skill. Career's optional confirmed conditions
provide qualification/date relevance with bounded source evidence or labelled guidance.

Changed extraction candidates and explicit replacement comparisons stay in the CV
aggregate until the user accepts mappings or keeps the prior result. Reapplied answers
preserve origin/history and require fresh interpretation. Profile remains the owner
of manual declarations and explicit attachment changes; CV assesses current source
fingerprints through its own records, without editing account data on reads.

The additive target-bound analysis-input envelope includes the confirmed goal and
complete CV/declaration/selection revisions. It rejects unfinished interpretations
and changed inputs during assembly. This is a captured snapshot requiring consumer
revalidation, not distributed atomic admission or result-specific stale tracking.

## P04–P06 ownership decision

The latest Jira stories and subtasks place declared planning preferences in the
existing versioned Profile aggregate. Profile owns the date-only application date,
normal weekly capacity and temporary availability periods; all edits use the same
owner/version boundary. This supersedes the original roadmap-owned P04–P06 mapping.
Roadmap will consume a snapshot through an API and own scheduling/results. It must
retain the source profile version, planning revision and explicit calendar context.
No roadmap generation or cross-service stale-plan notification is implemented yet.
