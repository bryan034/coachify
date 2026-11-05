# Roadmap

Provider configuration: the service now reads its own `*_LLM_BASE_URL`,
`*_LLM_MODEL`, `*_LLM_API_KEY` and `*_LLM_ALLOW_HTTP`. HTTPS is required outside
explicit development HTTP mode. Local testing can share the 16K-context
`elo-deepseek-r1:1.5b` Ollama alias, without sending preserved cloud keys.
Non-Gemini providers receive JSON Output plus the schema in the prompt;
all responses still undergo the existing Pydantic and domain checks. Local calls
serialize per service instance and use a 180-second HTTP timeout; operations use
600-second budgets and 630-second leases. Cloud limits remain unchanged.


## Product direction — 5 November 2026

The weekly planner extends the 4 November timed roadmap. After generation, `/roadmap` is a weekly task planner and coach, so plans use `schema_version: roadmap-v3`. This direction replaces the earlier rules against automatic revision and manual session editing, but only for what this document describes: deterministic rescheduling, rolling detail of outline-only weeks and user-made task changes. Every other change to accepted work needs an accepted preview.

Jira references: G01/SCRUM-34, R01/SCRUM-41, R02–R09/SCRUM-42–49, E01–E07/SCRUM-50–56 and T01–T06/SCRUM-57–62. Retain existing identifiers/hierarchy/statuses. These stories were not re-read for this slice because Jira was not accessible from the implementation session; check them for conflicts.

## Flow

1. **Configure.** The planner form has fixed sections: Timeline and Study time (required), then Blackout days and times, Learning focus and Weekly check-in (optional). It is the confirmed record and shows the goal and skills sent to the model. The chat helper fills it in through a validated patch and never starts generation.
2. **Runway.** `POST /planner/runway` calculates available weeks, eligible, planned and buffer hours without a model call. Generation is disabled, with reasons, when the goal or CV is missing, dates are invalid, no usable time exists or the model is unavailable.
3. **Generate.** One durable operation reuses or runs Assessment, then runs two validated stages. `PlanOutline` gives gaps, milestones, one row per week through the target date, the achievable outcome and deferred scope. `WindowDetail` gives dated tasks for the current and next week. Stages are `assessing`, `writing`, `detailing` and `correcting`; rolling detail reports `rolling` and check-in or chat proposals report `revising`. Only a fully validated result becomes a candidate, so an incomplete generation is reported as failed and never offered for acceptance.
4. **Review.** Shows the next assignment, remaining time, milestones, each week's outline, the projected outcome, deferred scope and gaps. The current roadmap stays active until the candidate is accepted.
5. **Run.** See [The weekly planner](#the-weekly-planner).

## Capacity (`app/planning/capacity.py`)

This module is the only source of runway numbers; the frontend displays its results.

- **Buffer.** Each week's eligible time is its enabled block time, capped by the weekly maximum. `buffer_percent` (default 20, range 0–50) rounds up and is reserved for catch-up and rescheduling. The remainder is the planned workload that generation may use. Backup time needs permission and adds capacity only where the weekly maximum allows it.
- **Daylight saving.** All scheduling uses wall-clock minutes on local dates in the plan's time zone. Minutes a forward change skips are unavailable and can't be chosen. A repeated hour counts once. Weeks, missed-task days and check-in times follow local dates and wall-clock time, so a clock change never moves them.

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
- Saved `blackout_dates` are read as `once` rules without a migration, and that format change is not reported as a settings change.

## Model ownership and validation

The model owns gaps, priorities, prerequisite order, effort, milestones, assignments, coaching text and the deadline outcome. The backend owns date arithmetic, capacity, schedule validation, progress totals and finish-date projections, and the model may never assert that a schedule fits. It receives the goal, Assessment outcomes and evidence, prior completed work with outcomes, linked skills, dates and feedback, self-reported confirmations, settings, planned capacity for the outline stage and exact windows for the detail stage. Skills Profile evidence is unchanged by any of this.

`app/planning/validator.py` returns every error, and the errors plus the rejected output go back to the model, for at most three attempts per stage. A failure leaves the active plan, any earlier candidate and settings unchanged. Checks:

- **Outline:** one row for every week through the target, targets within each week's planned workload and at least the milestones' effort, known milestones.
- **Assignments:** inside the requested weeks, inside one eligible window, no overlap with each other or fixed items, not overlapping a blackout, not past and not after the target, within the week's planned workload, known milestones, dependencies known and finishing first. Backup needs permission and no free preferred window that could hold the session. Each requested week with planned time and unfinished work needs a task. A task repeating completed work needs a `refresher_reason`.
- **Milestones:** unique keys, valid windows inside the runway, known acyclic prerequisites finishing first, and assignment minutes within effort. For every date range, the effort of milestones wholly inside it must fit planned capacity after the buffer.
- **Gaps:** `confirmed_gap` needs an Assessment `confirmed_shortfall` or a self-reported "no experience". `uncertain` and `partial` are `unknown`. Supported requirements, satisfied alternatives and non-learning constraints are not study gaps. Inferred requirements are labelled, explained and `unknown` unless the user says otherwise. A material unknown needs a diagnostic of at most 30 minutes or a confirmation question.
- **Coverage:** every Assessment priority is in a milestone, in `beyond_deadline` (saved as deferred scope), or excluded with an exact quote from the current user message. `fits_in_runway` is false exactly when work remains beyond the deadline.

## The weekly planner

A plan keeps four values apart: the target date the user chose, the outcome achievable by it, remaining work beyond it (`deferred_scope`, with effort and dependencies), and the projected finish for all remaining scope. The target date only changes through an accepted preview. Deferred scope stays outside the dated schedule until a scope or date preview is accepted.

### Reconciliation on access (`app/planning/schedule.py`)

There is no scheduler. `GET /workspace` reconciles after authentication, and every mutation reconciles in its own write. The version fence decides between concurrent requests, and the loser reloads and finds nothing left to do. Event ids derive from the task and its old placement, so repeated access adds no duplicate moves or history entries. Reconciliation waits while an operation is pending.

- A scheduled task is missed once its local calendar day has ended.
- Generated, unpinned tasks move to the earliest eligible future slot on or before the target, preferred time first within each week and then permitted backup time. Duration is preserved and tasks never split. Buffer may be used, up to the weekly maximum. Blackouts, occupied time, paused weeks and dependency order are avoided.
- Order is prerequisites first, then original scheduled time, then the stable task id.
- A prerequisite must finish before a dependent that is still in the future. With no such slot, or no slot at all, the task goes to Backlog with the reason.
- `auto_moves` is separate from `manual_moves`. After two automatic moves the task asks the user instead. Completed, pinned and custom tasks never move automatically, and missed pinned and custom tasks show action needed.
- **Undo** restores the prior placement if the task hasn't changed since. Otherwise it explains the conflict and the user can place the task manually. An undone task is marked as needing action, so reconciliation leaves that occurrence alone.

### Task actions

Completion takes one click; notes, proof and Too easy, About right or Too hard feedback are optional, and feedback informs later planning. Skipped tasks leave the schedule, don't count as completed, and can return to Backlog. Pinning and notes are available on any unfinished task.

Manual moves and placements must be in the future, on or before the target, outside blackouts, free of other tasks, within the weekly maximum for included hours, in dependency order, and on a local time that exists. Each failure is explained. A time outside enabled blocks or in a paused week asks for confirmation first; the latter becomes an exception to the pause.

Custom tasks can be added to any week, with an optional time; without one they wait in Backlog with their week preference. They count towards weekly hours unless excluded, and excluded tasks still occupy their time. AI revisions never change or delete them. Starting a new roadmap carries unfinished custom tasks forward without their milestone link, which is an implementation decision so that they aren't lost.

### Rolling detail

The current and next week have dated tasks. A window week with no generated task, available time and unfinished accepted effort starts a saved operation, with an id derived from the plan and weeks, so repeats are idempotent. It adds tasks without a preview, because it stays within accepted scope and workload and never changes an existing task. A failure keeps the plan, is not retried on reads, and offers an explicit retry. After weeks away, missed work is reconciled first, then only what is still missing is written. Mutations wait while this operation runs, as they do for other operations.

### Progress and pace (`app/planning/metrics.py`)

Roadmap progress reports completed against planned hours, generated tasks and milestones, using estimated durations. Custom-task hours are reported separately and count towards roadmap progress only when linked to a milestone and included in hours. Milestones can be completed without proof. With unfinished tasks the user chooses to keep them scheduled or remove them from scope, and the choice is recorded. Completion never writes to the Skills Profile.

- **Status** compares completed hours with work due by now. Each task's due time is its baseline placement. Automatic moves keep the baseline, so moving work doesn't hide slippage. A manual move within the same week resets it, and an accepted proposal resets it for moved tasks. Past weeks that never got detail count their outline target, and paused weeks and tasks removed from scope don't count. With nothing due, status is Insufficient data.
- **Recent pace** averages the latest four finished calendar weeks, including zero-completion weeks and excluding paused weeks. It needs two finished weeks. Zero throughput reports that no estimate is available. The forecast covers accepted work, is capped by future capacity and respects pauses and blackouts. Beyond the target it reports “At this pace you’ll finish N weeks late”, rounded up, and offers Cut scope, Add hours and Move the date.
- **Scheduled projections** use planned workload, overrides and recurring settings continuing beyond the target, and are labelled as such.

### Weekly check-in (`app/planning/checkin.py`)

A check-in opens on the configured local day and time, if that follows acceptance and the week isn't paused. It stays open until completed or next week's first scheduled task starts; with no task next week it expires at the start of that week. Saved answers survive expiry, the workload target stays the same, and rolling detail continues.

Answers save first. A separate saved operation then writes a `TaskRevision` proposal for next week, so a failure keeps the answers and the schedule and offers retry. More and Less change next week's target by about 25%, within eligible capacity and the weekly maximum. They are per-week overrides that leave settings alone. The proposal shows use of the buffer and offers a new block when the request exceeds capacity. Under half of due work done, with The same chosen, suggests Less. Completed, pinned and custom tasks are fixed and their time is counted. Accept applies hours and tasks in one write; Adjust returns to the answers; Discard closes the check-in with nothing changed.

### Proposals (`app/planning/proposals.py`)

Pause, unpause, Edit plan, Cut scope, Add hours, Move the date and bringing in deferred scope are deterministic previews built on a private copy. Check-ins and chat task revisions use the model. Each shows affected tasks, capacity, dates and the finish-date effect. Each stores only the changed fields and the base plan revision. Accept is rejected if the plan changed or the check-in closed. Any task change raises the revision.

Pausing sets the week's automatic capacity to zero and moves its generated, unpinned tasks later or to Backlog. Completed work stays. The user keeps pinned and custom tasks as explicit exceptions or sends them to Backlog to place. The target date doesn't change.

### New roadmaps and archives

Start new roadmap opens the form pre-filled with current settings, starting today. The current roadmap stays active while the candidate is generated and reviewed. A candidate is blocked if progress changed after it was prepared. Automatic moves alone don't block it. Accepting saves the former plan's final state to `roadmaps` under a request-derived id, then swaps the workspace in one CAS. A retried request reuses that id, so it can't produce a second archive. Archives are read-only and listed in `planner.archived`; finished and skipped work stays in bounded `planner.completed_work` for later planning.

### Experience answers and evidence

Self-reported milestone outcomes and experience confirmations stay in Roadmap and never write to Profile, CV or Assessment. None of them establishes proficiency. Factual corrections belong in Skills Profile.

## Persistence and recovery

`workspaces` is a private operational owner document holding chat, `planner` (config, candidate, active, proposal, archived, completed_work, confirmations), receipts and one leased operation. Each accepted plan and each archived plan is saved as an immutable `roadmaps` snapshot before the pointer CAS. Progress on an active plan stays in the workspace, under its version fence. UUID mutation IDs plus expected workspace revisions protect edits, retries and lost responses. Failed operations retain their exact request for retry, without duplicating a user message.

Messages save before model work. Compact `/progress` polling reads only revision and operation metadata. Provider retry delays persist. Expired leases resume on authenticated reconnect, and bearer tokens never enter MongoDB. Source and session checks fence publication. If source freshness is unavailable, saved chat and plans stay readable and progress can be recorded, but new plans and accepting a preview wait. History is bounded to 300 messages, 1,000 operation receipts and 4 MiB per workspace.

## Earlier plans

`roadmap-v2` plans stay viewable and aren't reconciled or migrated. New-schema mutations return `legacy_plan`, and the page prompts the user to start a new roadmap. Accepting one archives the old plan unchanged.


Workspace `active` and `draft` remain as older untimed plans, shown read-only under "Earlier plan", and `GET /history/{id}` can still read them. No migration runs. The endpoints and code that created or edited them have been removed.

## Configuration and limits

See setup for required service-scoped credentials. All model calls go through the OpenAI Python SDK with the service's own base URL, key and model. `ROADMAP_LLM_TOKEN_PARAMETER` selects `max_completion_tokens` for models that reject `max_tokens`. Planning operations have a 450-second budget for Assessment polling plus up to three model calls per stage. Outline calls allow 24,000 output tokens and detail calls 12,000. Events are bounded to 500 per plan. Other limits are unchanged: 55-second cloud HTTP calls (local limits above), three worker slots, one operation per owner, 64 KiB requests, 1 MiB upstream responses and 120,000-byte model contexts. Overflow is explicit, not silent truncation.

## Remaining scope

Out of scope: a customisable Home dashboard, actual-time logging, calendar export, email or push reminders, external integrations, AI-suggested links, application and networking task types, evidence transfer to the Skills Profile, daily streaks and modelled non-zero reduced periods. Mutations wait while a saved operation runs, so task actions pause briefly during rolling detail. Task dependency order is enforced at task level, while milestone order is checked at generation. Live-model plan quality and effort estimates have not been evaluated, and the local 16K-context model is unlikely to fit full planning.
