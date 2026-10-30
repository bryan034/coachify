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
