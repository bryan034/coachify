# Career Goal

`career-goal.tsx` keeps paste, URL and document previews in page memory. Its input
methods and source-recovery controls remain independent from target persistence.
The account/token key clears previews, target drafts and pending requests when the
signed-in account changes. Leaving the page warns about unsaved inputs.

`target-workspace.tsx` adds an explicit review → save draft → confirm → select
journey. Specific-job skills need exact excerpts from the current reviewed JD;
Career validates the transient full source and retains structured fields and
bounded excerpts. Career-exploration skills are labelled personal guidance and need
no JD. The screen does not claim AI interpretation, verified job requirements,
capability assessment or automatic analysis generation.

Optional qualification/date conditions stay separate from skill requirements.
Each has a reviewed description, relevant CV section and specific subject phrases;
job conditions also require an exact supporting JD excerpt. These fields justify
targeted clarification without implying verified eligibility. A target can contain
only conditions. `condition-fields.tsx` validates and displays the bounded manual
inputs; the backend remains authoritative. Saved condition summaries show whether
the source is a reviewed JD or personal exploration guidance.

Saved target cards show the persisted requirements before confirmation. Confirming
does not select the target. Only a separate selection updates the current context
used by CV clarification. Changing requirements means saving another target draft;
earlier targets and CV explanations stay available. Reload restores saved targets
and selection, while temporary previews are discarded.

Saved history loads twenty targets at a time with explicit load-more controls.
The selected target is returned separately and stays visible even when it is on an
older page. Failed page loads retain existing cards and drafts; refreshing replaces
the first page and cancels stale pagination responses.

`src/lib/api/career-targets.ts` validates target and selection responses, forwards
the bearer token, bounds request waits and sends expected versions and mutation
identities. Interrupted writes keep the draft and retry identity. Selection
conflicts refresh the authoritative state without silently overwriting it.

See the [Career service](../../../../../services/career-service/README.md) and
[contract](../../../../../contracts/api/career.yaml). Unit tests cover exact source
excerpts, separate confirmation/selection, failures, conflicts and account changes.

Failed URL previews offer direct paste/upload actions that switch input methods without discarding existing drafts.

The saved-goal chat keeps submitted questions and earlier replies visible after a
failed answer. Retry fills the original question's reply without adding a duplicate
question or replacing a newer composer draft. Errors explain validation failures,
incomplete responses, timeouts or service problems in plain language and keep the
retry control; raw provider diagnostics stay out of the transcript. This history
remains in page memory and is not restored after leaving or reloading the page.

JD chat retries interrupted operation-status, workspace-progress and saved-research
reads with bounded backoff (up to five attempts). A lost connection or temporary
gateway error no longer ends polling immediately while backend tasks keep running.
Workspace/research read retries show a reconnecting notice and retain observed
progress; successful reads resume the normal updates and completion summary without
refreshing the page. Only reads are retried: questions/JDs are not resubmitted.
Authentication failures and terminal model/validation errors retain the existing
recovery controls. Leaving the chat aborts outstanding reads and retry timers.

The JD chat stays mounted after its temporary input is cleared, including when an
older workspace read is still pending. Research reads continue for pending/running
categories even in a finished historical snapshot, and reload when the workspace
phase changes. Completion automatically starts the summary operation and displays
its reply without a page refresh. The chat shows a Current step label with observed
server activity, repair or quota status and a separate list of observed stages;
these describe workflow progress, not private model reasoning. Temporary progress
disappears once the summary arrives.

The JD chat exposes saved role/skill/date details immediately after extraction,
including while public research is running. API-boundary checks reject malformed
nested responses before rendering; summaries and chat still wait for the linked
research snapshot. `SavedGoal.job_dates` retains the canonical sourced-date shape.
