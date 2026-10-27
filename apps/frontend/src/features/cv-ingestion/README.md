# cv-ingestion

Saved, private CV uploads and effective evidence review for C01–C09. The existing
`/cv` workspace keeps its Resume & Tracker navigation label; application tracking,
target confirmation and gap analysis are not implemented by this feature.

`resume-preview.tsx` coordinates the policy, saved CVs, explicit selection and
recoverable upload/processing states. Uploading never changes selection. The
selected analysis source is identified separately from the CV currently being
reviewed, including when filenames repeat. Same-source re-upload sends the original
CV ID/version and preserves backend corrections; changed bytes require a separate
new upload. Failed or expired originals offer source resupply.

`cv-review.tsx` presents education, experience, projects and potential skills with
source excerpts, uncertainty and user provenance. Edits/removals and the common
clarification answer/skip lifecycle preserve drafts through failures and require
explicit reconciliation of stale versions. The CV service supplies Career's selected
confirmed target, its version and selection version. The review shows that context
before the user prepares relevant questions, then refreshes the full CV and filtered
question set to the same version before enabling answers. A missing target links to
Career Goal; an unavailable context offers a retry without inventing target data.
Saved explanations and skips remain visible across target changes; irrelevant
unanswered questions are hidden. Skips remain uncertain and can be answered voluntarily.

The explanation receipt is distinct from its interpretation. Review shows the
saved answer, pending/failed interpretation with explicit retry, and the scoped
personal/team/observed/denied contribution changes. Partial and unanswerable facts
remain visibly unknown. Older saved explanations can be interpreted explicitly;
they are not silently backfilled. A successful interpretation does not require a
second confirmation or establish independently verified mastery.

Potential skills render the effective `skills` response, including project/work
sources, source-specific attribution and conflicting values. Source item cards
retain correction/removal controls. Optional dates accept year, month or day
precision, validate known chronology, and never convert employment duration into
skill experience.

`source-reconciliation.tsx` displays retained candidate extractions and previous
statements. Users explicitly map each affected statement to a same-kind source or
keep it in history. Failed/conflicting saves retain choices until the latest
comparison is reviewed. A separate explicit comparison links a replacement CV to
a prior saved source; it does not switch the selected analysis CV.

`capability-declarations.tsx` manages Profile-owned manual capabilities, available
without a CV. Normalized name matches require an explicit attach/distinct choice;
CV attachments retain exact source identity/version. Extra manual descriptions are
shown alongside the original declaration. Independent evidence is never presented
as verified by repeating a claim.

Matching uses all effective skill source identities. `declaration-attachment.tsx`
shows current/changed/removed/unverifiable links and permits explicit reattachment
or retaining a standalone declaration. A changed link never deletes the declaration.

`src/lib/api/cv.ts` validates responses, authenticates requests, bounds network waits
and forwards expiry to the existing Profile session boundary. Account/token changes
unmount private state and abort requests. Drafts stay in page memory; navigation
warns before discarding them. No CV content is written to browser storage. Ready
review refresh runs when returning to the window or reconnecting as well as through
the explicit refresh action. Existing editors retain their drafts and original
write versions, requiring review before saving over changed facts. There is no new
idle timeout. Queued/processing files poll saved state. FastAPI owns all domain interpretation,
ownership, file validation and persistence.

The shared workspace session boundary also preserves correction, explanation,
manual-capability and selected-upload drafts when switching tabs or recovering
from a temporary authentication-service outage. Private content is hidden and
interaction is blocked until validation succeeds. Retry does not refresh the page;
there is no idle timeout. Actual expiry, logout and account changes clear drafts.

Preparation and save responses are scoped to the currently viewed CV and request
sequence. Delayed preparation cannot replace a different CV review. Preparation
retries keep the same mutation identity and exact target/source versions. Saving an
answer never promotes every stored question into the currently relevant set.

See the [CV service](../../../../../services/cv-service/README.md),
[API contract](../../../../../contracts/api/cv.yaml) and
[frontend tests](../../../tests/README.md). Synthetic mocked API tests demonstrate
UI behavior; they do not establish real model extraction accuracy.
