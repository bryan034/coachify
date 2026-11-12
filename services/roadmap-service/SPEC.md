# Roadmap

Provider configuration: the service now reads its own `*_LLM_BASE_URL`,
`*_LLM_MODEL`, `*_LLM_API_KEY` and `*_LLM_ALLOW_HTTP`. HTTPS is required outside
explicit development HTTP mode. Local testing can share the 16K-context
`elo-deepseek-r1:1.5b` Ollama alias, without sending preserved cloud keys.
Providers receive JSON Output plus the schema in the prompt;
all responses still undergo the existing Pydantic and domain checks. Local calls
serialize per service instance and use a 180-second HTTP timeout; operations use
600-second budgets and 630-second leases. Cloud limits remain unchanged.


## Product direction — 4 November 2026

The timed roadmap supersedes the 30 October chat-first direction and its "no exact time slots" limit. `/roadmap` is now Configure → Generate → Review. Configure is a fixed planner form. A button opens an optional chat helper, which guides the user through the required details and fills in the form; after a plan exists, the same helper requests edits. A Career goal and admissible Assessment evidence are required, and Assessment runs before planning. Evidence may be a selected extracted CV plus saved Profile declarations, or saved Profile declarations alone when no CV is selected.

Jira references: G01/SCRUM-34, R01/SCRUM-41, R02–R09/SCRUM-42–49, E01–E07/SCRUM-50–56 and T01–T06/SCRUM-57–62. Retain existing identifiers/hierarchy/statuses. These stories were not re-read for this slice because Jira was not accessible; check them for conflicts.

## Flow

1. **Configure.** The planner form has fixed sections: Timeline and Study time (required), Blackout days and times, and Learning focus (optional). It is the confirmed record and shows the goal and skills sent to the model. The chat helper asks for whatever `runway.issues` reports as missing (`missing_target`, `no_budget`, `no_blocks`), then offers the optional details once. It proposes settings through a validated patch; an invalid patch changes nothing and is explained. Chat never starts generation.
2. **Runway.** `POST /planner/runway` calculates calendar time and usable hours without a model call. Generation is disabled, with reasons, when the goal or CV is missing, dates are invalid, no usable time exists or the model is unavailable. Incomplete interview research needs the existing explicit partial choice.
3. **Generate.** One durable operation reuses or runs Assessment, then asks the model for a structured `PlanDraft`, validates it and stores it as a candidate. Reads make no model calls. Stages are `assessing`, `writing` and `correcting`.
4. **Review.** Shows the next assignment, remaining calendar time and study hours, a milestone timeline with a target-date marker, the projected outcome, work beyond the deadline, gaps and confirmation questions. The user accepts, or returns to configuration with the candidate retained.
5. **Revise.** Reads report signals for changed settings, progress, evidence or a finished week. The user requests a preview, from a button or the chat helper, and nothing applies until accepted.

## Capacity (`app/planning/capacity.py`)

This module is the only source of runway numbers; the frontend displays its results.

- The range is start date through target date, both inclusive. The target is the last study day. It must follow the start date, within one year.
- Weeks run Monday to Sunday in the user's IANA time zone. Dates are real dates, so a partial week has no proration and still has the weekly cap.
- A date is available only inside its blocks. Overlaps merge per date, so they count once, and preferred time takes precedence over backup. Blackouts, time already passed today, local minutes skipped by daylight saving and completed sessions are removed. Repeated local hours count once.
- A week's usable time is `min(cap - completed minutes, merged minutes)`. Preferred time, extra backup capacity and usable time under the current toggle are reported separately.
- A duration resolves to a target date, with months clamped to the month's end. The target is authoritative for planning; a matching duration is reported so both controls stay synchronised.

Non-zero Profile reduced periods appear as a notice and do not change capacity. Zero-hour periods can be added as a daily blackout over that range.

### Blackouts

`config.blackouts` holds rules, each a whole day or a time slot, tested against real local dates:

- `once` applies on `start_date`. `daily`, `weekly` and `monthly` repeat from `start_date` until the optional `end_date`, every `interval` days, weeks or months.
- `weekly` applies on `weekdays` (Monday 0), counting intervals from the Monday-to-Sunday week of `start_date`. `monthly` applies on the day of `start_date`, or the last day of a shorter month.
- `start_time` and `end_time` limit a rule to a slot on the same day; both empty means all day. `23:59` means through midnight. An overnight blackout needs two rules.
- A slot removes only its overlap from a study block. A rule that cannot apply (ends before it starts, has one time, has a slot that doesn't end after it starts, or is weekly with no weekdays) removes nothing and is reported as a `blackout_invalid` runway issue, which blocks generation. A chat patch containing one changes nothing.
- Saved `blackout_dates` are converted to `once` rules at service start (see [Persistence and recovery](#persistence-and-recovery)), and that format change is not reported as a settings change.

## Model ownership and validation

The model owns gaps, priorities, prerequisite order, effort, milestones, assignments and the deadline outcome. It receives the goal, Assessment outcomes and evidence, completed work, self-reported confirmations, settings, exact windows for the first planning week and per-week capacity for the rest. The first planning week is the first Monday-to-Sunday week with usable capacity.

`app/planning/validator.py` returns every error, and the errors plus the rejected output go back to the model, for at most three attempts in total. A failure leaves the active plan, any earlier candidate and settings unchanged. Checks:

- **Assignments:** first-week dates, inside one eligible window, no overlap, not overlapping a blackout, not past and not after the target, within the week's remaining budget, and a known milestone. Backup needs permission and no free preferred window that could hold the session.
- **Milestones:** unique keys, valid windows inside the runway, known acyclic prerequisites finishing first, assignment minutes within effort, and retained if they have completed sessions. For every date range, the remaining effort of milestones wholly inside it must fit usable capacity.
- **Gaps:** `confirmed_gap` needs an Assessment `confirmed_shortfall` or a self-reported "no experience". `uncertain` and `partial` are `unknown`. Supported requirements, satisfied alternatives and non-learning constraints are not study gaps. Inferred requirements are labelled, explained and `unknown` unless the user says otherwise. A material unknown needs a diagnostic of at most 30 minutes or a confirmation question.
- **Competence:** job-skill outcomes may carry Assessment's planning estimate (`competence_score`, where 10 means the evidence meets the goal's level), `demonstrated_score`/`required_score` and linked `profile_skills`. The model uses them to size effort and order work only; they never change a gap's status.
- **Coverage:** every Assessment priority is in a milestone, in `beyond_deadline`, or excluded with an exact quote from the current user message. `fits_in_runway` is false exactly when work remains beyond the deadline.

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

Split-session compatibility keys are generated without colliding with primary assignment keys. Task and session IDs remain stable; secondary assignment keys may change on projection, including for old snapshots. No stored snapshot is migrated by a read.

Revisions retain student-created, edited, started, completed and removed tasks and related dependency records. Model-generated keys do not establish semantic identity. A preview flags new work that might repeat student-created, removed, edited, started or completed work, including reused protected keys; `/planner/tasks/reconcile` records an explicit keep/discard decision before acceptance. A changed active plan invalidates an earlier preview. This conservative review can include work that is actually unrelated.

## Reading a generated roadmap

`POST /planner/generate` returns `{version, operation}` straight away. Poll `GET /progress` until `operation.status` is `succeeded` or `failed`, then read `GET /workspace`: the preview is `planner.candidate`, with `planner.candidate_review` and `planner.candidate_blockers`. `POST /planner/accept` makes it `planner.active`. `roadmap.yaml` and `models/roadmap-plan.schema.json` publish these shapes.

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

See setup for required service-scoped credentials. All model calls go through the OpenAI Python SDK with the service's own base URL, key and model. `ROADMAP_LLM_TOKEN_PARAMETER` selects `max_completion_tokens` for models that reject `max_tokens`. Planning operations have a 330-second budget for Assessment polling plus three model calls, and plan calls allow 24,000 output tokens. Other limits are unchanged: 55-second cloud HTTP calls (local limits above), three worker slots, one operation per owner, 64 KiB requests, 1 MiB upstream responses and 120,000-byte model contexts. Overflow is explicit, not silent truncation.

## Remaining scope

No external calendar or course integrations, automatic revision without a user request, scheduled reviews, actual-time recording, conversation continuation or modelled non-zero reduced periods. Task editing, period views, review decisions and recovery still need frontend implementation. The dashboard backend provides read-only projections; its frontend remains unimplemented. Live-model plan quality and effort estimates have not been evaluated, and the local 16K-context model is unlikely to fit full planning.
