# cv-ingestion

Saved, private CV uploads and effective evidence review for C01–C09. The existing
`/cv` workspace is named **Skills Profile** in navigation and its page heading.
It uploads CVs, extracts potential skills and retains the existing evidence/review
workflow. Search Jobs has its own navigation tab, which also holds application tracking. Target confirmation and gap analysis remain separate.

The Skills Profile page has three entry states. With no CV, profile or manual capability it is an
upload-first screen: a drop zone, **Add skills by chat**, and **What happens next**. While the only CV is
still processing and none is active it shows a reading screen (`skills-states.tsx`) with real progress,
the experiences found so far and skeleton skills, plus **Open review** and **Cancel upload**. When a CV is read but its review is unfinished, the page shows **Finish your CV review** at full page width (no separate CV card; **Upload new CV** scrolls to the upload panel beside **Your CVs**, which shows `x/max` CVs from the policy, 3 by default) instead of skills: a Continue review action, the saved topic progress (read from the CV's current saved conversation, without starting one) and a **Waiting for your review** list of what unlocks. Once the
active CV is reviewed, a **Your CV review is complete** banner reports the questions answered and the skills added, corrected and removed (from the CV's `review_summary`) and offers Generate roadmap and Search jobs. A skill's side panel adds **From your review** when the backend holds a note for it.

`resume-preview.tsx` coordinates the policy, saved CVs, explicit selection and
recoverable upload/processing states. Upload opens guided review immediately and
shows progress until the first question is ready. `cv-conversation.tsx` saves the
conversation for later. **Your CVs** is the one place to switch, make active, rename, delete or review CVs: each row shows its state, review progress, and **Review CV** (**Refine CV** once reviewed). The Skills Profile card only summarises the CV analysed. **View extracted results** opens a read-only results page for that CV (`extracted-results.tsx`): skills by category or by where they came from (CV, added, removed or skipped in review), a detail panel for the selected skill, and the experiences found. **Upload a CV** sits beside a fixed-height **Your CVs** library with a sticky desktop position and an independently scrollable card list. Each card offers a persisted title, Rename with Save/Cancel, Review CV, View extracted results, Make active and Delete CV. Original filenames and source versions remain under File details;
The Skills Profile no longer has a “CV details and corrections” section. Source reconciliation, when a re-upload needs a decision, appears on the results page. Uploading never changes selection. The
active CV is identified separately from the CV currently being
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

The review screen has a white header (logo, **Review your CV**, saved status) and a **Topics** rail: topics covered, a segmented bar (forest = done, mint = current), the percentage reviewed (or how many were reviewed and skipped) and each topic marked Done, Now · question *n* of 3, Up next or Skipped · CV used as written. Each open topic has **Skip**, confirmed inline; a skipped topic has **Review**; **Skip all remaining** sits beside the Topics heading. On phone widths the topic list is hidden, so the composer's **Skip this topic** shortcut, confirmed in the chat, is the way to skip there. The question being asked sits in a forest-outlined bubble with its topic, its position and up to four points the answer can cover; **Why this question?** shows the reason elo gives. Topics end early once elo has enough context ([backend rules](../../../../../services/cv-service/INTERVIEW.md#topic-skips-question-format-and-early-topic-completion)); the user's messages are green-tinted. When every topic is covered, a **Your CV review is complete** card lists what was added, corrected and removed (read from saved conversation actions) with **View Skills Profile** and **Generate roadmap**.

The conversation opens or resumes a CV-owned server record for the viewed CV, or a
manual-only record when no CV is open. A compact header identifies the reviewed file
and the confirmed Career target. An upload starts basic guided questions after extraction
when the review screen is open. **Review CV** can start or resume a saved CV.
Users may answer naturally, add context, ask a side question or propose a correction
at any time. **Skip this question** leaves the current detail uncertain. Skills
Profile review automatically asks a follow-up or moves to the next topic.
The current topic remains visible when an explanation interrupts it. Voice input is
not part of this version; Career target editing remains on Career Goal.

Messages and interpretation outcomes are separate. Accepted messages clear the
composer. Review shows a processing status while pending actions poll saved state;
the next draft stays editable, and Send waits for the saved turn to finish.
The CV summary refreshes when the server revision changes. Save feedback comes from action states, not a
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

The full-screen CV chat gives the conversation at least 70% of the screen height.

Entry now shows `skills-profile-summary.tsx`: profile counts, a bar showing each
category's share, then skills as chips in one card per category
(`skill-cards.tsx`), combining CV skills, skills described in chat and manually
added capabilities. Categories over eight skills start collapsed. Experience sits in
columns by kind. Each opened chip shows the strongest supported baseline level,
or "Level not established", with its source experience; evidence stays behind the
row's details. The backend assigns categories (`skill_groups` on each response) and
the frontend only displays them; a skill missing from the map shows under Other skills.
Experience and clarifications, then the
upload form and saved CVs, follow below, with links to jump between sections.
Upload your CV / Build through chat remain explicit choices. Upload supports drag/drop as well as
keyboard file selection. An accepted upload opens the guided review with progress
and recovery controls. A fresh review starts automatically once extraction is ready
and the review is open. **Save and review later** also works during processing.
The named shortcut returns to the same CV. **View extracted results** opens the
classified results without starting a review. Upload leaves the analysis selection explicit.

Manual chat and CV review use `purpose: skills_profile`. Backend field selection,
semantic evidence checking and source-bound interpretation drive their questions.
The summary has explicit Save profile / Save to Skills Profile actions; partial profiles
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
The transcript scrolls above the composer. **Save and review later** returns to Skills
Profile. Submitted answers and the current question restore from the saved
conversation. Unsent text remains in page memory. Native browser back and direct
reload restore the corresponding view. Baseline selection is a separate action.
The library retains pagination and bounded internal scrolling on mobile.

The upload panel and CV library share the same desktop row height, while only the
library contents scroll. On mobile they stack with independent natural/bounded heights.
After an upload is accepted, `/cv?review=<cv_id>` opens immediately with processing,
retry and failure states. Processing and guided review survive reload. An older
review link containing `uploaded=1` also opens guided review. **View extracted results**
and the completed review’s **Review profile** action open `/cv?cv=<cv_id>`, which
restores the results page directly on reload; its back link returns to the Skills Profile.

Review evidence can contain multiple distinct facts in the same field. Rendering
uses complete fact identities and labels personal/shared attribution, retaining
all values and quotes through updates.

The most recent ready upload is made the active CV automatically (once per upload, no warning; a failed or still-processing newest CV is skipped until ready), so **Make active** is only needed to go back to an older CV. **Make active** warns when the current `effective_version` does not match
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

Uploaded-CV review resumes persistent interview progress from the CV service.
Reopening an active review restores its current question. A paused review offers
**Continue review**. A completed review offers **Review profile**, which opens the
classified results. A segmented progress bar counts experience and project topics.
A topic whose section failed extraction validation is highlighted yellow in the sidebar
with a "Warning · could not be verified" label, and a summary above the list says how
many sections need explaining, which stays visible when the list is hidden on small
screens. The same sections carry a "Warning · unverified" pill and note in the extracted
review, with their extracted text kept. The chat says again, once, that the section is
better explained there. Follow-up questions stay in the same topic. Processing and failed evidence updates
offer explicit retry. Agent questions, evidence updates and stopping
decisions are backend-owned. Chat displays source-specific skill estimates as
conversation-based judgments, while the summary exposes structured roles,
responsibilities, skill evidence and unresolved/partial details with their quotes.
Manual-only intake retains its existing Profile-owned flow. See the
[CV interview harness](../../../../../services/cv-service/INTERVIEW.md).

Manual intake uses the same progress display with its four background areas as topics.

Upload preparation shows a smooth estimated 0–100% bar and a backend activity
message. The existing three-second saved-status poll supplies observed milestones;
the display eases forward toward the next milestone while a stage is running,
with an activity sheen that continues during long waits. Stages cover document reading,
extraction, evidence checks, optional repair and publication. Progress reaches 100%
only after successful publication. Intermediate percentages are explicitly labelled
as estimates, not elapsed-time or token measurements. Estimates stop on failure,
reset for another upload/retry and respect reduced-motion preferences. Older
servers without progress data show an indeterminate bar. The subsequent interview
shows a separate percentage of review topics covered. Activity messages describe
observed work and do not expose private model reasoning.

Interview progress stays visible through answer submission and follow-ups. A topic
counts as covered when the backend publishes a question for another topic, or
finishes the review. Answering a single question, skipping a detail or pausing does
not complete the current topic. Ordinary answers preserve completed-topic progress;
explicit source corrections/re-extraction can reopen affected topics.

Assistant review replies and estimate explanations hide opaque internal source
references, including previously saved replies. Experience titles remain visible;
structured source IDs, original saved messages and literal user text are retained.
The backend prompt also keeps IDs out of visible prose.

Uploaded-CV topics have a backend-enforced maximum of three questions, normally
clarifying only material ambiguities after using the CV’s known facts. Scope,
personal responsibilities and confidence are possible areas, not mandatory prompts.
The agent can finish earlier when details are already known. Confidence is shown
as self-reported information, not assessed proficiency. Evidence/fact/answer IDs
are removed from delivered assistant prose as well as legacy display; structured
backend references and original user messages remain intact.

Review can finish without questions when CV context is clear, or after one answer
resolves an ownership ambiguity. Missing optional fields and listed skills do not
require users to repeat the CV. Discussed topics remain in progress at completion;
older unvisited optional-only topics can disappear after reconciliation.

Baseline review treats each whole project/experience as one topic, with its own
three-question maximum and no overall topic cap. The saved Skills Profile project
summary displays supported `skill_estimates` returned by CV detail; insufficient-
evidence diagnostics remain backend-only. Questions focus on personal responsibilities and concrete
application/depth/support of the project’s known skills. A clear project description
alone is not the same as an established skill baseline. Internal evidence IDs
remain hidden from the summary and conversation.

Conversation and saved baseline sections omit insufficient-evidence entries,
including stale/legacy server responses, and render no empty estimate section.
The API also filters these entries without deleting internal uncertainty. Questions
use the per-project budget for relevant responsibility/skill gaps instead of filling
every field. Supported skill levels and original user/source text remain visible.

Skip this question leaves its targeted detail uncertain and allows other useful
questions or the next project. After a next-step planning failure with no active
question, Skip and continue defers the current experience, preserves the saved
answer and advances/completes with gaps. It is not offered for unrelated evidence
failures or unknown source focus; ownership uncertainty is not graded as competence.

Skills Profile lists the skills you have with the same category layout and jump links as the saved Career Goal.


Skills Profile shows the shared current Assessment with an explicit comparison
action. Saved manual Profile declarations can be compared without selecting a CV;
a selected incomplete CV still blocks admission. Only evidence actually referenced
by the current result is highlighted, and its component explanations remain visible.
This highlight is not an inferred relevance rating. When the saved comparison has a
`skill_profile` (the model's judgement of each skill from the reviewed CV), the skill
chips use its category, sub-category and relevance colour. The skill panel shows its
competence score against the goal's level, plus its explanation. Older results fall
back to the backend's `skill_groups` and requirement outcomes. Existing CV application
levels remain unchanged.


Skills Profile exposes **Review details and corrections** beside the upload/library
controls. It opens the existing source-bound clarification/editor and manual
capability controls without replacing the read-only Extracted results page.
The page marks its initial API loads with `aria-busy`; navigation helpers wait for
that state before choosing between first-upload and saved-CV layouts. Viewing the
Skills Profile after completing review returns to its summary. Equal upload
creation timestamps prefer the active CV, avoiding accidental selection changes
on reload. The saved library scrolls internally on desktop and mobile.
