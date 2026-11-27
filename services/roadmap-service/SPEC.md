# Roadmap

Provider configuration: the service now reads its own `*_LLM_BASE_URL`,
`*_LLM_MODEL`, `*_LLM_API_KEY` and `*_LLM_ALLOW_HTTP`. HTTPS is required outside
explicit development HTTP mode for synthetic fixture providers. Providers receive
JSON Output plus the schema in the prompt; all responses still undergo the existing
Pydantic and domain checks. Model calls use a 55-second HTTP timeout; operations use
240-second weekly budgets; combined outline-plus-first-week generation has a 420-second budget. Checkpoints preserve each operation’s full lease with a 30-second margin.


## Product direction — 4 November 2026

The timed roadmap supersedes the 30 October chat-first direction and its "no exact time slots" limit. `/roadmap` is now Configure → Create roadmap → Tasks. Configure is a fixed planner form. A button opens an optional chat helper, which guides the user through the required details and fills in the form; after a plan exists, the same helper requests edits. A Career goal and admissible Assessment evidence are required, and a saved current Assessment is reused for planning. Missing or outdated evaluations require an explicit evaluation command before generation. Evidence may be a selected extracted CV plus saved Profile declarations, or saved Profile declarations alone when no CV is selected.

Jira references: G01/SCRUM-34, R01/SCRUM-41, R02–R09/SCRUM-42–49, E01–E07/SCRUM-50–56 and T01–T06/SCRUM-57–62. Retain existing identifiers/hierarchy/statuses. These stories were not re-read for this slice because Jira was not accessible; check them for conflicts.

## Configure and create

The fixed planner and optional settings chat collect the confirmed schedule. Chat
patches are validated and an invalid patch leaves settings unchanged. Initial
roadmap creation generates the weekly outline and one detailed week, then automatically
activates both. The UI displays scheduled tasks without the projected objective timeline. The old plan/month generation and roll-forward
routes are retired. Existing accepted plans and month blocks remain readable.

## Weekly planning

Outline generation makes at most two domain-generation attempts. Each request lists the
assessment's `permitted_requirement_refs`. The second receives
validation errors and the previous output. If invalid assessment requirement IDs
remain, the backend performs recovery on that second draft without a third outline
model call: it removes invalid gap/exclusion rows and affected dependent milestones,
weeks, routines and beyond-deadline rows. Shared valid work remains linked to valid
gaps. Assessment data is never changed and IDs are never guessed.

A recovered outline must pass all remaining scheduling, structure, evidence and
progress-preservation checks. No usable remainder, ambiguous duplicate identities,
or removal of milestones with saved work means recovery fails safely. Explicit
`partial_review` metadata records omissions and uncovered assessment priorities;
only those recorded omissions permit partial weekly/priority coverage. The UI shows
them before acceptance and retains the notice on the accepted roadmap. Recovery
replaces whole-plan outcome claims with a partial-coverage explanation but never turns a
plan with beyond-deadline work into one that fits; if it would remove every beyond-deadline row, recovery fails.
Omitted beyond-deadline rows have content-derived IDs. Editing and
accepting a partial outline still use the ordinary authenticated validation and CAS
paths. Provider transport/JSON-format repair handling remains unchanged.


`POST /planner/outlines/generate` generates a projected weekly journey and the first
week's detailed tasks in one leased operation. The UI sends `auto_accept: true` for
Create roadmap, updates and regeneration: the operation validates and activates the
outline and first week together, records a history snapshot and pace baseline, and
returns the active tasks without a review step. Updates whose weeks are already
scheduled activate the revised outline while keeping those tasks; they do not require
a redundant first-week preview. Each worker lease captures its own snapshot so a
publication retry cannot mix a prior capture with newly generated outline/week data.
Automatic creation writes its previews to an in-memory working copy, so checkpoints never
save them and a failure leaves any existing preview unchanged.
First-week or activation failure
preserves the saved roadmap, clears failed candidates and retains the exact retry
request. Source freshness, bearer revalidation, workspace CAS and receipts still apply.
Clients omitting `auto_accept` retain the preview and explicit
`POST /planner/outlines/{id}/accept` flow for compatibility. Outline editing invalidates
that first-week preview. `/discard` removes only the preview.

`POST /planner/weeks/generate` takes `week_start`, optional `feedback` (workload,
difficulty and note), and `revision` for an already accepted week. The configured
planning weekday defaults to the last day of a Monday-start week. Planning also opens
when all current-week tasks are complete. Missed planning offers the current week,
clipped to today; no-progress weeks can still be planned and reviewed.

The model writes actionable titles under 12 whitespace-separated words (at most 11, up to 160 characters), brief instructions, a required `description` with detailed numbered steps and practical completion guidance, observable criteria and effort. Description is stored on canonical editable tasks and returned in week previews, task reads and session views. New or edited task titles use the same word limit; historical titles remain readable. Older tasks without descriptions return null; no model-generated guidance is retroactively invented. Descriptions may be edited through the existing task edit API and retained in its change history.

Each generated task also has a required `label` naming what it is for (a project, problem set, course or topic; every step of one project shares the label) and up to eight `materials`: named resources such as LeetCode problems by number and title, book chapters or documentation sections, never URLs. A project named in the learning notes, topics, goal or objective is broken into ordered step tasks. Week validation rejects a task that mentions LeetCode without a problem number. Label and materials are stored on editable tasks and returned in previews, task reads and session views; older and user-created tasks have a null label and no materials.

A week's new tasks must come within one short session or 10% of the week's target minutes, whichever is larger, after routines and carried work, or less after `too_much` workload feedback. Milestone estimates guide the content but do not cap a week: when a milestone's estimate runs out, the model adds work that deepens the same goal instead of leaving hours unused. The outline plans every week with usable time as a full study week, with no rest or contingency weeks. The backend
places sessions within study blocks, then optional extra time (09:00–23:00 by default), giving each study day about an even share of the week's work in date order, so work is not packed into the first days of the week,
respecting blackouts, timezone/DST, existing work, session limits, proportional breaks,
daily limits, rest days, lead time and Profile reduced availability. Weekly hours are
a target; previews explain partial-week, saved-work and capacity shortfalls. Breaks do
not count as study. The extra-time option is enabled for new accounts. Backup blocks
are retired: enabled saved backup blocks become ordinary study blocks; disabled ones
are omitted on read.

Saved sessions, including missed unfinished sessions, count against the weekly capacity of their scheduled dates when drafting, reviewing and accepting a week. New and carried sessions share the remaining capacity. Unfinished work has explicit carry, split, defer or drop proposals. The user can review
choices at `/planner/weeks/{id}/carryover`, then `/accept` or `/discard`. A split keeps
the original ID for this week's portion and creates a linked deferred remainder, so
completing the first portion cannot discard the rest. Notes and edits stay on the
original task; split history links the remainder. Future objective changes are shown
with previous values and applied only on acceptance, retaining outline history.

Mutation receipts and workspace CAS protect retries and concurrent writes. A week
preview depends on its outline, scheduling settings, target-week tasks and unfinished
work; unrelated progress leaves it valid. Accepted future week revisions replace only
untouched future generated tasks, preserving completed, started, edited and note-bearing
work. Legacy month blocks are read for coverage; there are no month generation routes.
Old accepted plans remain readable and gain weekly objectives through outline generation.
Reads never generate tasks. Task completion never changes assessed skill mastery.

Settings live under Settings → Roadmap; core dates, hours, blocks, breaks and planning
day remain on the roadmap form. Appearance offers light, dark and system modes, saved
per browser; system changes are followed while the app is open.

## Capacity (`app/planning/capacity.py`)

This module is the only source of runway numbers; the frontend displays its results.

- The range is start date through target date, both inclusive. The target is the last study day. It must follow the start date, within one year.
- Weeks use the configured start day (Monday by default) in the user's IANA time zone. Partial weeks use remaining schedulable time and explain any reduction from the weekly target.
- A date is available only inside its blocks. Overlaps merge per date, so they count once, and preferred time takes precedence over extra time. Blackouts, time already passed today, local minutes skipped by daylight saving and completed sessions are removed. Repeated local hours count once.
- A week's usable time is `min(cap - completed minutes, merged minutes)`. Preferred time, extra-time capacity and usable time are reported separately.
- A duration resolves to a target date, with months clamped to the month's end. The target is authoritative for planning; a matching duration is reported so both controls stay synchronised.

Current Profile reduced periods lower the weekly target when enabled; zero-hour periods remove their affected dates. A malformed or out-of-range period is skipped on its own; at most the 100 latest-ending periods are applied. Publication rechecks current availability and evaluation freshness, even when the evidence hash has not changed.

### Blackouts

`config.blackouts` holds rules, each a whole day or a time slot, tested against real local dates:

- `once` applies on `start_date`. `daily`, `weekly` and `monthly` repeat from `start_date` until the optional `end_date`, every `interval` days, weeks or months.
- `weekly` applies on `weekdays` (Monday 0), counting intervals from the Monday-to-Sunday week of `start_date`. `monthly` applies on the day of `start_date`, or the last day of a shorter month.
- `start_time` and `end_time` limit a rule to a slot on the same day; both empty means all day. `23:59` means through midnight. An overnight blackout needs two rules.
- A slot removes only its overlap from a study block. A rule that cannot apply (ends before it starts, has one time, has a slot that doesn't end after it starts, or is weekly with no weekdays) removes nothing and is reported as a `blackout_invalid` runway issue, which blocks generation. A chat patch containing one changes nothing.
- Saved `blackout_dates` are converted to `once` rules at service start (see [Persistence and recovery](#persistence-and-recovery)), and that format change is not reported as a settings change.

## Model ownership and validation

The model owns gaps, priorities, prerequisite order, effort, milestones, task content and the deadline outcome. Milestone estimates include already saved work; completed effort is subtracted once when calculating remaining scope. The backend owns session placement. It receives the goal, Assessment outcomes and evidence, completed work, self-reported confirmations, settings, exact windows for the first planning week and per-week capacity for the rest. The first planning week is the first configured planning week with usable capacity. Unfinished milestones, checkpoints and routines dated before the planning start are moved up to it before validation, and the moved milestone keys are saved in `generation.clamped_milestones`.

`app/planning/validator.py` returns every error, and the errors plus the rejected output go back to the model, for at most three attempts in total. A failure leaves the active plan, any earlier candidate and settings unchanged. Checks:

- **Assignments:** first-week dates, inside one eligible window, no overlap, not overlapping a blackout, not past and not after the target, within the week's remaining budget, and a known milestone. Extra time requires permission; preferred study blocks are filled first.
- **Milestones:** unique keys, valid windows inside the runway, known acyclic prerequisites finishing first, assignment minutes within effort, and retained if they have completed sessions. For every date range, the remaining effort of milestones wholly inside it must fit usable capacity.
- **Gaps:** `confirmed_gap` needs an Assessment `confirmed_shortfall` or a self-reported "no experience". `uncertain` and `partial` are `unknown`. Supported requirements, satisfied alternatives and non-learning constraints are not study gaps. Inferred requirements are labelled, explained and `unknown` unless the user says otherwise. A material unknown needs a diagnostic of at most 30 minutes or a confirmation question.
- **Competence:** job-skill outcomes may carry Assessment's planning estimate (`competence_score`, where 10 means the evidence meets the goal's level), `demonstrated_score`/`required_score` and linked `profile_skills`. The model uses them to size effort and order work only; they never change a gap's status.
- **Coverage:** every Assessment priority is in a milestone, in `beyond_deadline`, or excluded with an exact quote from the current user message. The backend derives `fits_in_runway`: it is false exactly when `beyond_deadline` lists work, and any value in a draft is replaced.

## Proposals, progress and evidence

A candidate pins its base active plan, settings and inputs. Accept is rejected if the active plan, settings or inputs changed, or a session has passed. Completed sessions and their evidence notes are copied unchanged into each revision and keep their time slots.

Task completion, self-reported milestone outcomes and experience confirmations stay in Roadmap and never write to Profile, CV or Assessment. None of them establishes proficiency. Factual corrections belong in Skills Profile.

### Editable tasks and compatibility

The active timed roadmap owns `editable_tasks`. A task has a stable ID, instructions, completion outcome, estimated minutes, optional assessment requirement references and milestone, prerequisite task IDs, zero or more dated segments, status, history, and a removal record. A personal task needs neither a requirement nor a schedule. Requirements refer to the assessment snapshot; a link is not evidence of coverage. Task reads flag references absent from the current snapshot or carried from a different assessment ID or input hash, and report whether the source is stale or unavailable. Explicitly selecting links again records the current assessment context.

Task mutations use the existing authenticated workspace revision, payload-bound mutation receipt and immutable active-plan snapshot. An exact retry is safe; stale versions and reused keys with different content fail. Edits and removals retain history; dependent tasks and edges remain. A changed completion outcome on a completed task requires a fresh completion confirmation before it counts for readiness. Starting a blocked task and completing directly are allowed; reopening chooses `not_started` or `in_progress`. Each new completion records its definition, time and estimated minutes at that moment. Earlier completion events without an estimate remain unchanged and must not be inferred.

`GET /planner/tasks` accepts inclusive `start_date` and `end_date` for day, week or month queries; a task with unscheduled effort remains visible outside its scheduled segments. It reports readiness reasons and unscheduled minutes. Planned dates do not establish prerequisite completion. Milestone prerequisites require an explicitly recorded, current self-reported outcome as well as valid completed member tasks; first-week sessions alone cannot establish that the projected milestone is complete. A changed milestone outcome definition requires a new confirmation. Valid manual schedules are saved even if they conflict; warnings are returned on task and workspace reads. They do not silently reschedule other work.

Task reads report `freshness` as `current`, `stale`, `not_ready` or `unavailable`. A plan is current only when its inputs are ready and the captured input hash matches. The legacy `stale` and `source_unavailable` booleans retain their earlier meanings for compatibility; clients needing to distinguish missing inputs should use `freshness`.

Adding, removing or moving milestone tasks, or accepting a revision with changed membership, marks an existing demonstrated milestone outcome for review while preserving the earlier self-report. Reconfirmation retains the previous outcome in history. A later valid self-report acknowledges earlier removals when active tasks remain; missing or ambiguous timestamps continue to require review, and removing the final task never proves completion. A `calendar_unavailable` warning means an extreme saved date could not be checked against available study windows; the date remains readable and editable.

Existing `roadmap-v2` assignments are converted in memory for reads, with no migration on read; the first substantive task mutation saves the canonical tasks. Scheduled tasks linked to milestones project to the existing assignment shape. The older assignment-status endpoint updates the corresponding canonical task for single-segment sessions; split tasks require the task-status endpoint. Earlier untimed plans remain read-only. Existing clients need the new task endpoints to display unscheduled or in-progress work.

Split-session compatibility keys are generated without colliding with primary assignment keys. Task and session IDs remain stable: a slot's ID is derived from its position until the schedule is reordered by skipping one session, when the remaining slots save their IDs; secondary assignment keys may change on projection, including for old snapshots. No stored snapshot is migrated by a read.

Revisions retain student-created, edited, started, completed and removed tasks and related dependency records. Model-generated keys do not establish semantic identity. Week validation rejects repeated saved task titles, including completed or removed work. The user reviews the generated tasks and every carry/split/defer/drop choice before acceptance. Changes to carried work or the target week invalidate that preview; unrelated progress does not.

## Reading a legacy generated roadmap

`POST /planner/outlines/generate` and `/planner/weeks/generate` return `{version, operation}`. Poll `GET /progress`, then read `GET /workspace` for `planner.outline_candidate` and `planner.week_candidate`. The API contracts publish saved roadmap shapes.

Each `assignments` item is one to-do: `date`, `start_time`, `duration_minutes`, `task`, `completion_criterion` and `status`, changed with `POST /planner/assignments/status`. `skill_gap_ids` contains a single unambiguous current skill ID or an empty list when an explicit link is absent, stale or ambiguous; older responses without this field can use an unambiguous legacy gap or milestone association. Student changes take precedence over generated source links. Only `first_planning_week` has dated sessions. Later work exists only as milestones with `projected_start` and `projected_end`, until the user plans the next week.

## Persistence and recovery

Saved settings cannot hold the removed `buffer_percent`, `checkin_day`, `checkin_time` or `blackout_dates` fields. `PlannerConfig` rejects them in requests and on read, and new records are written from that model. Earlier records are cleaned once at service start by `app/planning/retired_settings.py`, across workspace settings, previews, active plans and `roadmaps` snapshots. This is the one exception to snapshots being immutable: it removes only fields that never affected a plan, and leaves schedules, progress and workspace versions unchanged. The service does not start if this cleanup cannot reach MongoDB. Any other unexpected saved field still fails validation, so corruption is not hidden.

`workspaces` is a private operational owner document holding chat, `planner` (config, candidate, active, confirmations), receipts and one leased operation. Each accepted or progressed plan is saved as an immutable `roadmaps` snapshot before the pointer CAS. UUID mutation IDs plus expected workspace revisions protect edits, retries and lost responses. Failed operations retain their exact request for retry, without duplicating a user message.

New preview accept and discard receipts include the action in their fingerprint, so reusing a request key for the other action is rejected. Older receipts did not record which of those two identical request bodies succeeded; retries of those ambiguous receipts return `legacy_preview_retry_ambiguous` rather than claiming success. Reload the roadmap and use a new request key for any still-needed action. Other existing receipt formats keep their previous retry behavior.

`GET /dashboard-source` is an authenticated passive read of the current active plan, workspace version, milestone review and task readiness. It does not launch a pending operation, query other sources or save legacy projections. At each new acceptance, `pace_baseline_id` is set to the exact immutable snapshot ID written for that acceptance; ordinary task and status edits retain it. A later acceptance replaces it with the new accepted snapshot. Older plans with no recorded baseline report null; the service does not infer one from generation pointers or current edits. The owner-scoped history endpoint reads a known baseline. Source consumers can compare successive workspace versions and active IDs for bounded race detection, but that does not create a cross-service transaction.

Messages save before model work. Compact `/progress` polling reads only revision and operation metadata. Provider retry delays persist. Expired leases resume on authenticated reconnect, and bearer tokens never enter MongoDB. Source and session checks fence publication. If source freshness is unavailable, saved chat and plans stay readable and progress can be recorded, but new plans and accepting a preview wait. History is bounded to 300 messages, 1,000 operation receipts and 4 MiB per workspace.

## Earlier untimed plans

Workspace `active` and `draft` remain as older untimed plans, shown read-only under "Earlier plan", and `GET /history/{id}` can still read them. No migration runs. The endpoints and code that created or edited them have been removed.

## Configuration and limits

See setup for required service-scoped credentials. All model calls go through the OpenAI Python SDK with the service's own base URL, key and model. `ROADMAP_LLM_TOKEN_PARAMETER` selects `max_completion_tokens` for models that reject `max_tokens`. Weekly planning operations have a total 240-second budget; combined outline-plus-first-week operations have 420 seconds, including Assessment polling and model calls. Assessment is polled at most 60 times at two-second intervals (120 seconds of waiting plus request time), stopping early on completion or failure. Plan calls allow 24,000 output tokens. Outlines use two domain-generation attempts followed by deterministic invalid-ID recovery; weeks retain up to three attempts, subject to the overall operation deadline. Other limits are unchanged: 55-second cloud HTTP calls (local limits above), three worker slots, one operation per owner, 64 KiB requests, 1 MiB upstream responses and 250,000-byte model contexts. Overflow is explicit, not silent truncation.

## Remaining scope

No external calendar or course integrations, automatic revision without a user request, scheduled reviews, actual-time recording, conversation continuation. The frontend supports weekly outline and task reviews, task editing, period views, session scheduling and backlog proposals. Live-model plan quality and effort estimates have not been evaluated, and the local 16K-context model is unlikely to fit full planning.


## Saved evaluation handoff

Roadmap reads Assessment through its owner-scoped API. A saved result must have explicitly
current freshness, a compatible skill profile and `stale=false`. A current result causes no
Assessment command or evaluation model calls. The plan prompt includes saved per-skill
judgements, requirement gaps and evidence-reference metadata; raw evidence text remains in
the immutable Assessment and is not duplicated into the planning prompt. This does not
truncate the authoritative saved evidence.

Roadmap never starts a missing/outdated Assessment automatically. The UI offers Evaluate
skills or Update evaluation, with independent freshness, progress and completeness indicators.
If an explicit evaluation is already pending/running, Roadmap can reconnect with at most 60
polls at two-second intervals. The operation budgets are 240 seconds for a week and 420 seconds for a combined
outline and first week; Assessment's timeouts are unchanged. Publication rechecks the exact source
fingerprint, and accepting a preview requires a current evaluation and unchanged inputs.

### Roadmap views and session planning

The active roadmap offers Today, Week, Month, Milestones and Progress. Plan settings
returns to configuration, source notices and adviser chat. A new candidate remains a
separate read-only preview until accepted. Generation supplies short actionable task
names, explicit skill-gap links and dated milestone checkpoints. Legacy plans derive
names/skills from saved assignments and retain readable progress.

Session writes under `/planner/sessions` reuse the owner's workspace CAS and mutation
receipts: `add`, `save`, `move` and `skip`. Timed and anytime tasks are supported.
Names, done-when criteria, chosen Skills Profile/plan skills, notes and optional
confidence/difficulty self-ratings persist on editable tasks. Original generated
wording is retained for restoration. Notes and ratings never change assessed skills.
`free-times` and `backlog-plan` calculate proposals without persisting them; only an
explicit move applies a proposal. Moves are validated together against the saved
schedule and capacity. Checkpoint reached timestamps are explicit user reports,
separate from demonstrated milestone outcomes.

### Scheduling and retry invariants

Runway calculations, routine placement, week placement, fixed-slot acceptance and
strict session moves share deterministic scheduling constraints. Explicit manual
detail edits retain the existing conflict-warning behaviour. Free-time and backlog
proposals honour the extra-time opt-in. Batch moves validate the final schedule,
including swaps, without retaining the old slots as false conflicts.

Anytime tasks consume their day/week effort budget without occupying invented clock
times. Weekly analytics count only segments belonging to the week being summarised.
Split work retains notes on the original portion and records a linked remainder;
dependents require that remainder before the complete prerequisite is considered done.
Unfinished-work overflow fails explicitly rather than silently omitting tasks.

Explicit evidence confirmation uses stable proposal content as its identity. Unrelated
progress does not reoffer the same confirmed evidence, and an exact confirmation retry
checks the local receipt before making another Profile write. Completion alone never
submits evidence or changes skill estimates.
