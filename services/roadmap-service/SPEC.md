# Personal career adviser — Roadmap

Provider configuration: the service now reads its own `*_LLM_BASE_URL`,
`*_LLM_MODEL`, `*_LLM_API_KEY` and `*_LLM_ALLOW_HTTP`. HTTPS is required outside
explicit development HTTP mode. Local testing can share the 16K-context
`elo-deepseek-r1:1.5b` Ollama alias, without sending preserved cloud keys.
Non-Gemini providers receive JSON Output plus the schema in the prompt;
all responses still undergo the existing Pydantic and domain checks. Local calls
serialize per service instance and use a 180-second HTTP timeout; operations use
600-second budgets and 630-second leases. Cloud limits remain unchanged.


## Product direction — 30 October 2026

The user's revised flow supersedes mandatory application-date-only planning, equal-seven-day capacity, automatic exhaustive learning plans and a separate assessment screen. One persistent adviser conversation and its plan share `/roadmap`. The user chooses the pace, priorities, scope and learning approach. The LLM offers direction/recommendations based on declared skills and availability; it does not enforce a prescribed career path. Dated preparation targets and explicitly chosen ongoing horizons are supported. Assessment is a separate service feeding this page.

Jira references: G01/SCRUM-34, R01/SCRUM-41, R02–R09/SCRUM-42–49, E01–E07/SCRUM-50–56 and T01–T06/SCRUM-57–62. Retain existing identifiers/hierarchy/statuses. User-selected weekdays replace R07's hours/7 scheduling assumption for this planner; existing Profile planning APIs retain their historical semantics.

## Flow

1. Authenticate through Profile and require completed onboarding. Check selected ready CV and generated Career goal through Assessment's APIs. Missing extraction/selection provides source links; service failure is separate from missing input.
2. Opening performs read-only restoration. The first user message starts or reuses Assessment. Unavailable/stale/partial interview research needs an explicit partial-analysis choice. An all-uncertain assessment remains valid.
3. Adviser reads source-linked outcomes, current goal/date evidence, current plan and latest twelve messages (labelled history window). Persistent structured choices retain earlier preferences. It asks gradually about start, readiness target or ongoing horizon, weekly hours, chosen days, session length and learning preferences. Saved Profile values are suggestions; plan-specific choices do not silently rewrite baseline Profile planning inputs.
4. Career-owned job dates distinguish application, interview and job start. Only exact source date text/evidence enters the goal. Full recognised dates normalize; partial/ranged/relative wording stays text with no invented day/year. Recommend an appropriate preparation target, leaving the choice to the user. Older goals have no backfilled dates because raw JDs are not retained.
5. LLM replies propose only changed/new activity definitions and preference changes. Python assigns task IDs and preserves unrelated tasks, statuses, removal history and user overrides. Each activity has concrete instructions, a completion outcome, positive integer-minute estimate, rationale, source links or explicit personal-development scope, prerequisites and optional milestone. Estimated hours display from the same stored minutes. Removing tasks/excluding scope through chat needs an exact quote from the current user request. Proposals may be edited/discarded; active plans remain intact until Start/Apply.
6. Every proposal is scheduled deterministically. Users inspect fit, unallocated effort, dependencies and milestones beside the chat. Completing a task is self-declared progress, never a new skill assertion. Missed work is retained; rescheduling requires a reviewed proposal.

## Calendar and scheduling

Dates use a captured IANA time zone, initially Asia/Singapore. Workload dates contain no fixed clock times. Weekdays are Monday=0 through Sunday=6. User-selected daily minute budgets may not exceed the weekly budget; no work is allocated on unchosen/zero-capacity days. Profile reduced-period rates scale daily budgets proportionally to the declared plan weekly budget, never increasing capacity. The target date is an exclusive cutoff; an ongoing horizon ends at start + selected weeks. Maximum scheduling horizon is one year.

Allocate tasks in a stable prerequisite order. Splittable tasks retain one identity across positive segments no longer than the chosen session limit. Same-day dependencies have explicit predecessor-before-dependent order. Unsplittable tasks need a whole fitting session; otherwise they remain unscheduled. Never shrink estimates to fit. Missing/cyclic/removed/unscheduled prerequisites block dependent allocations while independent work may proceed. Allocated minutes plus explicit remainder conserve each unfinished task estimate. At most 10,000 allocation segments are retained per proposal; any excess work remains explicitly unscheduled. A found schedule is labelled feasible; failure to allocate is partial, not proof that every possible schedule is infeasible. No-work results contain no filler.

Plan-specific preferences remain in Roadmap. Profile retains application-date/normal-capacity/reduced-period defaults and its own revisions. Each plan pins Assessment ID/hash and its captured preferences. Capability/goal changes need reassessment; a stale active plan remains readable. The current implementation conservatively revalidates Profile version as well, which can require reassessment after baseline planning changes.

## Proposals, edits and progress

A draft pins its base active plan identity. Task edits/completion after a proposal invalidate activation of that old proposal; discard and rebuild it to preserve newer work. Apply rechecks source freshness and active identity. Old plan revisions remain immutable and owner-scoped. A new active snapshot never reuses a similarly named task from another source.

Direct edits preserve existing allocations; show missing/excess allocation, dependency and milestone review reasons rather than silently redistributing other tasks. Completed-task definition changes retain earlier completion and definition snapshots and flag review. Start and repeated completion are idempotent; explicit reopen selects not-started or in-progress. Starting is not a timer; completion records no fabricated actual effort. Removal retains the task record/history and marks dependent/milestone implications. Empty or unresolved milestones cannot complete through deletion alone. Generated milestone completion derives from all current required task states.

The UI supports chat, task definition/effort editing, personal activities, requirement links, prerequisites, day budgets, proposal application/discard, start/complete/reopen, and daily/weekly/monthly inspection. Factual capability corrections route back to CV/Profile; chat does not become another capability store.

## Persistence and recovery

`workspaces` is a private operational owner document containing chat, active/draft snapshots, receipts and one leased operation. Immutable committed plan snapshots live in `roadmaps`. One database serves users through owner-scoped records; no per-user database is created. UUID mutation IDs plus expected workspace revisions protect edits, retries and lost responses. Each active-plan change saves history before pointer CAS; request-bound insert recovery returns the same committed snapshot. Current reads do not accidentally select the newest unapproved candidate.

Messages save before model work. Compact `/progress` polling reads only revision and operation metadata, without loading chat, plan or source evidence. Content reloads only when an operation completes or fails. Provider retry delays are persisted and cannot be bypassed with a new message key. Retry keeps the original message identity and adds no duplicate user turn. Durable source assessment operations are reused on retry/restart. Expired leases resume on authenticated reconnect; bearer tokens never enter MongoDB. Session/source checks fence publication. Failure retains saved chat and the earlier active plan. History is bounded to 300 messages, 1,000 operation receipts and 4 MiB/workspace; reaching capacity is explicit and leaves saved data readable. Continuation/archive UI is not implemented.

Frontend data/drafts stay in account-keyed React memory; logout/account switch clears private display and ignores late old-account responses. Unknown save outcomes retry the original mutation before creating another change. Same-account unsent drafts survive ordinary polling but not browser refresh. If Assessment/CV/Career source freshness is unavailable, authenticated users can still read saved chat/plans and record their own task progress. The UI labels freshness unavailable; new advice and proposal activation wait for a successful source check. Profile authentication still fails closed. Private responses use no-store. Provider keys and database credentials are backend-only.

## Configuration and limits

See setup for required service-scoped credentials. The Gemini cloud default uses bounded JSON Schema, 55-second HTTP calls, safe provider errors and schema repairs; no live-provider fallback. Cloud processing uses a 210-second worker execution and renewable 240-second lease; local limits are listed above. Three process-local worker slots and one operation per owner bound concurrency. Requests are at most 64 KiB, upstream responses 1 MiB and model contexts 120,000 UTF-8 bytes. Overflow is explicit, not silent evidence truncation.

## Remaining scope

No exact time slots, external calendar/course integrations, automatic plan replacement, E05 manual allocation editing, scheduled reviews, dashboard projections, actual-time recording, conversation continuation or live semantic-quality claim. Read-view granularity/date focus is currently local to the mounted page. Full backlog-wide A/E/T delivery is not claimed. Live-model recommendations and effort estimates require separate representative evaluation.
