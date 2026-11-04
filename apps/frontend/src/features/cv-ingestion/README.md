# cv-ingestion

Saved, private CV uploads and effective evidence review for C01–C09. The existing
`/cv` workspace is named **Skills Profile** in navigation and its page heading.
It uploads CVs, extracts potential skills and retains the existing evidence/review
workflow. Search Jobs has its own navigation tab; application tracking is not
implemented or presented here. Target confirmation and gap analysis remain separate.

`resume-preview.tsx` coordinates the policy, saved CVs, explicit selection and
recoverable upload/processing states. The initial experience is the skills summary; upload or explicit review opens the text
conversation in `cv-conversation.tsx`. **Upload a CV** sits beside a fixed-height **Your CVs** library with a sticky desktop position and an independently scrollable card list. Each card offers a persisted title, Rename with Save/Cancel, Review CV, Set as active baseline and Delete CV. Original filenames and source versions remain under File details;
**Your CV summary** exposes the effective evidence, detailed corrections,
reconciliation and manual declarations when needed. Uploading never changes selection. The
active baseline is identified separately from the CV currently being
reviewed, including when filenames repeat. Same-source re-upload sends the original
CV ID/version and preserves backend corrections; changed bytes require a separate
new upload. Failed or expired originals offer source resupply. **Delete CV** is
available for each loaded saved file, including failed/processing uploads. It asks
for explicit confirmation identifying the source and retained historical copies.
Deletion removes that source's original/evidence/history and CV chat, clears its
selection without a fallback, and releases quota after backend cleanup. Manual
capabilities and existing analysis/roadmap snapshots remain. Failed/ambiguous
responses preserve the mutation identity; conflicts refresh versions for review.
Deleting the viewed source clears its private review/chat/resupply drafts and
invalidates in-flight reads so an old response cannot restore it.

## Saved conversation

The conversation opens or resumes a CV-owned server record for the viewed CV, or a
manual-only record when no CV is open. A compact header identifies the reviewed file
and the confirmed Career target. **Review CV** starts basic guided questions explicitly.
Users may answer naturally, add context, ask a side question or propose a correction
at any time. **Skip this question** and **Continue review** are explicit commands.
The current topic remains visible when an explanation interrupts it. Voice input is
not part of this version; Career target editing remains on Career Goal.

Messages and interpretation outcomes are separate. Accepted messages clear the
composer; pending actions continue polling saved state and refresh the CV summary
when the server revision changes. Save feedback comes from action states, not a
model's claim to have saved. Explicit corrections and manual additions use compact
Save/Cancel cards. Ambiguous source references and matching capabilities require an
explicit choice. Failed actions can be retried individually; stale proposals cannot
write over newer sources. The backend owns routing, validation and factual updates.

History is paginated, with earlier segments available read-only. Full segments offer
continuation while retaining previous messages. Conversation revisions are separate
from CV evidence versions. Unsent text stays in memory and is retained on recoverable
errors; interrupted sends reuse their request identity. The UI never puts transcript
or CV content into browser storage. Account/token changes abort the conversation and
clear private drafts; changing the viewed CV warns before discarding unsent input.

Conversation controls retain keyboard focus, offer Enter/Shift+Enter input, announce
status without re-announcing the transcript, and keep the composer visible beneath
the scrollable history on mobile. Long input is rejected visibly without truncation.

Existing clarification answers remain available as saved source records in the
summary. They are not reconstructed into invented assistant messages.

## Evidence and existing actions

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

## Summary-first Skills Profile

Entry now shows `skills-profile-summary.tsx`, including saved/draft manual
background, source-specific CV skills and clarifications, unknowns, and explicit
Upload your CV / Build through chat choices. Upload supports drag/drop as well as
keyboard file selection. An accepted upload opens the full-page review immediately, shows processing/recovery status, and starts chat automatically once extraction is ready. It does not change the analysis selection.
Review CV starts/resumes basic guided review only after extraction is ready;
failed/processing files expose View processing status instead.

Manual chat and CV review use `purpose: skills_profile`. Backend field selection,
semantic evidence checking and source-bound interpretation drive their questions.
The summary has explicit Save profile / Save CV profile actions; partial profiles
retain uncertainty. Returning to the summary preserves an unsent chat draft in page
memory. An upload/source switch retains the existing discard-confirmation behavior.
The old per-capability editor is retained as an advanced declaration control, not
the primary no-CV intake. Career confirmation is needed for target-specific
clarification/comparison, not for basic profile building or review.

## CV titles and full-page review

CV titles use CV-owned optional `display_name` metadata, falling back to the original
`file_name` for existing uploads. `PATCH /api/v1/cv/{cv_id}/title` is authenticated,
owner/version checked and idempotent. Titles are trimmed, bounded to 200 characters
and reject control characters. Renaming preserves original files, evidence versions,
source identity and review history; processing and failed CVs can also be renamed.

Review CV opens `/cv?review=<cv_id>` as a full-viewport review screen, hiding the
workspace sidebar, upload/library and summary. Manual intake uses `?review=manual`.
The transcript scrolls above the composer; Back to Skills Profile restores the
summary and retains the mounted unsent draft. Native browser back and direct reload
restore the corresponding view. Upload and review do not change the active baseline.
The library retains pagination and bounded internal scrolling on mobile.

The upload panel and CV library share the same desktop row height, while only the
library contents scroll. On mobile they stack with independent natural/bounded heights.
After an upload is accepted, `/cv?review=<cv_id>` opens immediately with processing,
retry and failure states. Conversation creation and automatic clarification wait
until the CV is ready. Returning to Skills Profile does not alter the active baseline.

**Set as active baseline** warns when the current `effective_version` does not match
`profile_reviewed_effective_version`. The warning explains that AI interpretation
may infer skills or experience inaccurately when any roles or responsibilities are
not clearly stated in the CV, so the baseline may not reflect current skills,
and asks whether to continue. Cancel preserves the baseline; a saved review of the
current effective version avoids the warning. Later evidence changes require review
again. This is guidance, not a new backend restriction on source selection.

Evidence excerpts can share a source-block ID (for example, several excerpts from
`b1`). The shared `EvidenceList` renderer keys each occurrence separately, preserving
all excerpts without React key collisions in review and source reconciliation.

## Agent-led uploaded-CV interview

Uploaded-CV review resumes persistent interview progress from the CV service. Paused
or completed interviews do not automatically restart on refresh; Continue review
or a new message resumes interaction. Agent questions, evidence updates and stopping
decisions are backend-owned. Chat displays source-specific skill estimates as
conversation-based judgments, while the summary exposes structured roles,
responsibilities, skill evidence and unresolved/partial details with their quotes.
Manual-only intake retains its existing Profile-owned flow. See the
[CV interview harness](../../../../../services/cv-service/INTERVIEW.md).
