# Service ownership and user-story mapping

| Service | Story groups | Owned data |
|---|---|---|
| Profile | P01-P16; C07 manual declarations | Existing accounts/email verification/revocable sessions, canonical onboarding and education, declared deadline/capacity/temporary availability, profile versions; account-embedded manual capability declarations and their own revision |
| CV | C01-C09, with C07 composition | Saved CVs, ingestion state, extracted facts/skills and bounded evidence, CV-specific correction/removal overlays, clarification questions/answers, processing operations, explicit saved-CV selection and private resumable CV conversations |
| Career | J01–J13; G01–G07; SCRUM-282/310 | Canonical career_goals, one career_state workspace and CV confirmation stamp, public interview/opportunity research, workflow checkpoints and read-only assessment input exports; raw JD text stays transient |
| Assessment | G01–G07 | Private immutable skill_gap_analyses, captured evidence/version vectors, comparison checkpoints and current result |
| Roadmap | R01-R09; E01-E07; T01-T06; A02-A04 | Consumed planning-input snapshots, milestones, tasks, progress history, proposed/applied revisions |
| Dashboard | D01-D06 | No persistent domain records; aggregate responses |
| Review | A01 orchestration; S01-S06 | Manual/scheduled review state, pace analysis, schedules, approval preferences |

## API dependencies

- CV -> Profile: validate account/session, read account declarations with their revision, and submit explicitly confirmed conversational capability additions through the existing declaration API.
- Profile -> CV: validate an explicitly chosen matching CV item/version before a manual attachment; no CV is needed for a plain declaration.
- CV -> Career: authenticate and validate the owner’s selected confirmed target, skill IDs and exact target/selection versions for relevant clarification.
- Career -> Profile: validate the account/session and completed onboarding.
- Career -> CV: read owner-scoped saved metadata and effective evidence through the CV API; preserve CV identifiers and provenance in its internal projection. New Assessment comparison uses shared canonical identities and complete input revalidation; this Career CV projection remains a compatibility read.
- Assessment -> Profile/CV/Career: authenticated source snapshots, current versions, effective evidence and owner-linked research; no foreign database reads.
- Roadmap -> Assessment/Profile: comparison/context and baseline planning inputs; Roadmap owns plan-specific chosen days, proposed/active tasks and daily allocations.
- Planned Career -> Profile: versioned background/planning inputs; manual additions use the Profile declaration API, while CV-specific corrections use CV.
- Roadmap -> Assessment: source assessment ID/hash and freshness; immutable evidence remains addressable through the Assessment API.
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

CV also owns the bounded `cv_upload_capacity` operational ledger. Its journaled
CAS reservation covers record counts and private original bytes before filesystem
publication. Shared POSIX file locks and generation-bound recovery preserve the
standalone MongoDB deployment. Capacity is released only after original bytes are
removed; saved evidence/history remains. Owner/global limits and legacy bootstrap
rules are specified in the CV service, and public listings use projected keyset
pages rather than loading every full history.

The separate CV-owned `cv_model_usage` operational document bounds daily provider
attempts using hashed account identities. A fixed shared POSIX slot pool holds
per-account/global concurrency through each synchronous provider callback.
Routing, extraction and clarification use the same guard; cancellation cannot
release a slot while its thread continues. No Career budget or new capability
authority is introduced.

Effective input retains CV ID, extraction/effective version, selection version and
declaration version. A consumer also retains its confirmed target version and any
Profile version actually used. Revalidation around assembly detects changed
inputs; this is not a cross-service transaction. Historical analysis inputs must
remain immutable. Career persists one canonical current goal in `career_goals` and its pointer/workspace in `career_state`. JD and discovery share that authority. Automatic saving is independent of CV confirmation: `career_state.cv_confirmation` records goal ID, goal version, selection version, projection hash and confirmation time. Reads reject a stale stamp after an edit or replacement, without deleting earlier CV facts. The acknowledgement does not advance the goal or selection version. It has its own bounded retry receipts.

The projection retains up to 200 named skills and 100 complete non-skill requirements, including source identities, categories, origins and AND/OR alternatives. CV derives its name-based skill relevance keys without claiming equivalence to Career's registry or mastery. Qualification conditions use neutral education matching. Other requirement categories stay generic, unresolved context; exact source relevance never infers citizenship, location or eligibility from unrelated CV text. Full descriptions/evidence remain bounded at 600 characters, without truncation.

Older UUID reviewed-target documents and their selection metadata are retained as historical data. They do not form a second active target flow. Canonical history filters their schema explicitly. Namespaced canonical `create_key` metadata keeps the legacy uniqueness index compatible with new writes; no index drop, data deletion or automatic target conversion occurs. CV retains exact goal/selection/extraction versions when preparing prompts and rechecks them before publication. A confirmed goal or completed clarification is not an assessment or readiness claim.

## Clarification interpretation and reconciliation

CV retains original answers separately from validated, source-scoped interpretations.
Attribution, assistance, known values and uncertainty live at individual skill-source
scope; denied team support does not erase another source. Partial dates retain their
precision and never imply months using a skill. Career's confirmed projection preserves qualification/date relevance and generic requirement context, bounded evidence, original provenance and alternative groups.

Changed extraction candidates and explicit replacement comparisons stay in the CV
aggregate until the user accepts mappings or keeps the prior result. Reapplied answers
preserve origin/history and require fresh interpretation. Profile remains the owner
of manual declarations and explicit attachment changes; CV assesses current source
fingerprints through its own records, without editing account data on reads.

The additive target-bound analysis-input envelope includes the confirmed goal and
complete CV/declaration/selection revisions. It rejects unfinished interpretations
and changed inputs during assembly. This is a captured snapshot requiring consumer
revalidation, not distributed atomic admission or result-specific stale tracking.

## Conversational CV review

The CV service owns `cv_conversations` as operational records, separate from the
five logical domain authorities. A conversation references one CV or has no CV for
manual-capability entry. Profile remains the authority for those declarations;
CV never writes Profile's database. Conversation messages and action receipts
are private, owner-scoped data, not shared interview research or a second skill store.

Conversation revisions do not advance CV evidence versions. Messages are saved
before provider routing; typed action proposals pass ownership, source, version
and domain validation before execution. Ordinary clarification answers use the
existing interpretation lifecycle. Explicit corrections, removals and manual
additions require a user action. A reply explaining a question changes no evidence.
Additional factual turns retain earlier explanations and their provenance; a
correction changes only the affected source/fields.

History is paginated and bounded per segment. A full segment remains readable
while an explicitly started continuation links back to it. Saved conversations
do not expire automatically. Raw message content stays off browser storage and
logs. Existing saved clarifications are displayed as earlier records, not invented
assistant dialogue. Detailed limits and API states belong in the
[CV specification](../../services/cv-service/SPEC.md) and API contract.

Each action has an independent receipt. A message requesting several actions may
partially succeed, particularly across CV and Profile; recovery retries unfinished
actions rather than claiming a distributed transaction. Pending action cards
remain tied to the original source/version context. Career continues to own
canonical goal editing, confirmation and future analysis; finishing a CV conversation does
not generate an assessment or roadmap.

## P04–P06 ownership decision

The latest Jira stories and subtasks place declared planning preferences in the
existing versioned Profile aggregate. Profile owns the date-only application date,
normal weekly capacity and temporary availability periods; all edits use the same
owner/version boundary. This supersedes the original roadmap-owned P04–P06 mapping.
Roadmap will consume a snapshot through an API and own scheduling/results. It must
retain the source profile version, planning revision and explicit calendar context.
The Roadmap adviser now supports reviewed plan generation and daily workloads through Assessment. Result-specific push notifications and scheduled adaptation remain planned.

## Career research and discovery

LangGraph runs inside Career. Career model inference supports local OpenAI-compatible, DeepSeek cloud and Gemini adapters; search independently selects Brave LLM Context or DeepSeek Search. Public retrieval uses only permitted public role/employer context, with owner-linked reports and typed citations. Private CV evidence, manual declarations and CV conversation messages do not enter shared research. Discovery and JD intake publish through the same goal persistence path. Current goals use owner/version-checked edits; research revisions remain immutable and compact progress/evidence reads avoid repeating full source payloads.

Career's 512 KiB CV transport/projection admission limit is separate from CV's 12 MiB stored-record boundary and conversation limits. An over-limit response is actionable failure, not an empty CV or permission to truncate sources. Model-specific context selection remains separately bounded. Synthetic provider tests do not measure live-provider quality, cost or comparative usability.

## Assessment and adviser boundary — 30 October 2026

The user's revised architecture separates Assessment from Career and places its UI in Roadmap. Assessment owns a separate database containing `skill_gap_analyses` and operational `workspaces`; Roadmap owns `roadmaps` and its own `workspaces`. Career's old analysis-v1 contracts remain compatibility code, with no automatic data migration. Producer exports preserve owner/reference/version checks. Shared canonical IDs/registry versions are additive; legacy CV/Profile skill keys and source IDs remain stable.

Profile continues to own baseline P04–P06 defaults. User-chosen preparation target/ongoing horizon, weekly/day budgets and learning preferences are specific to the Roadmap plan and do not silently edit the Profile baseline. Day-specific scheduling supersedes the old equal-seven-day assumption only in this planner. The adviser provides recommendations and the user chooses scope and activation; completion does not mutate assessed capability. See [Assessment](../../services/assessment-service/SPEC.md) and [Roadmap](../../services/roadmap-service/SPEC.md) for implemented behaviour and remaining limits.
