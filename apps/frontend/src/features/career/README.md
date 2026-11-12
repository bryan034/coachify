# Career Goal

Career Discovery restores the account's latest saved conversation from Career on
opening, refresh and re-entry, including confirmed conversations. Sent messages and
structured progress live in Career's owner-scoped MongoDB records; the browser does
not persist private chat content. Restored messages appear in full. Unsent drafts
remain in page memory.

An account with no conversation sees the Python introduction and an editable composer.
Its first message creates a session with `consent=true`. **New chat** immediately
creates a distinct empty saved session, so refresh also restores that new session
before a message is sent. Creation retries reuse the request key, and failures keep
the previous conversation visible. Opening or creating an empty chat makes no model
or search calls. Completed research and validated refinements automatically publish
all structured goal fields through Career's shared persistence path. There is no
save/confirmation button or separate Career Discovery review/editor panel. Users
request skill changes and direction refinements in the composer. Career Goal reads
the latest fields on navigation, polls for background changes while visible, and
refreshes on tab focus. The separate
CV-context acknowledgement remains explicit and version-bound.

New research summaries use Markdown headings, grouped bullet lists, inline sources,
learning priorities and coverage limitations. The final invitation to ask questions
and refine the goal in this chat is bold.

Career Discovery reveals assistant chat replies word by word after the validated
response arrives. Readers can choose **Show full response** to reveal it immediately;
reduced-motion preferences show the complete answer. Existing replies stay visible
while new replies appear, and scrolling follows new text only while the reader is
at the bottom. This is a display animation, not provider streaming.

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

Career chats give the conversation at least 70% of the screen height, on any screen size. Short screens scroll the page rather than shrinking it.

The saved-goal overview opens with the role and a ring of skills by the backend's priority. There is no side rail: the skills fill the page, and the three goal pages are one pill-shaped tab group. CV status and the comparison live in Skills Profile and Home, and Explore careers is reached from Conversations. Skills form one numbered list sorted by priority, with category filters. Each skill keeps its number when filtered, using the backend's categories in, using the backend's
`current.skill_groups`. Importance (Required, Preferred and so on) is a label on each
row, most important first, with any level the job states.

The JD chat exposes saved role/skill/date details immediately after extraction,
including while public research is running. API-boundary checks reject malformed
nested responses before rendering; the combined summary waits for the linked
research snapshot, while chat remains available. `SavedGoal.job_dates` retains the canonical sourced-date shape.

The saved-goal composer accepts messages during extraction, research, summary
generation and an outstanding reply. A page-memory queue sends one turn at a time
after goal saving, incorporating preceding replies and the latest goal version.
Failed turns retain their own retry receipt and do not block following messages.
Retrying preserves any newer unsent draft. Queued turns and transcript are lost on
reload/navigation; failed or incomplete research is never presented as completed.

## Skills needed and skills you have

The saved goal lists the skills a role needs by the backend's categories, with jump links, importance tags and a count per category. When `GET /assessments/current` returns a fresh comparison, each skill also shows its result: in your profile, covered by an alternative, partly in your profile, not clear yet, or to build. Reads never start a comparison. Until a fresh result exists, skills stay unmarked and the [evaluate banner](../assessment/README.md) shows above the list: **Evaluate skills with career goal** once the goal is set, the selected CV's review is finished (or saved Profile declarations exist without a CV) and research is no longer running; otherwise a link to Skills Profile to finish that step. A scored skill shows its planning estimate, "You: about X / 10 · role needs about Y / 10", the model's explanation and, under **From your Skills Profile**, the profile skills it was linked to. A result reflects saved evidence, not proficiency, and missing proof is never shown as a gap.


The banner's **Evaluate skills** button starts the versioned Assessment operation
from the saved goal. Have / Partial / Gap / Unknown reflect its current evidence outcomes;
satisfied OR alternatives keep their own label. Stale or mismatched goal revisions
receive no skill markings. Goal confirmation remains explicit and version-bound,
and is also available inside CV review.

## Redesigned Career Goal pages — 10 November 2026

Career Goal has three tab pages sharing one dark goal header (role, plain metadata with icons,
Refine goal and Set a new goal): **Skills needed** (`/career-goal`), **Interview preparation**
(`/career-goal/interview`) and **About the role** (`/career-goal/role`).

- Skills needed groups skills by the Skills Profile taxonomy, most important group first.
  Importance is shown by colour (Essential, Important, Nice to have) and marked when elo
  inferred it. Each row shows the Assessment rubric v1 planning estimate when the comparison
  scored it (10 means your evidence meets the level the role states), otherwise its Have,
  Partial, Gap or Unknown status. Expanding a skill shows why it matters, its importance
  source, the competence bar and the "What you need" learning items. Job-description quotes
  are not shown in skill cards. Long lists start with ten skills.
- Interview preparation is always shown, never inside a disclosure: the Stages, Timeline and
  Difficulty tiles, then one always-open card per researched round with questions to expect,
  how to prepare and sources (with no round data, those slots cover the whole process).
  Key terms in findings and AI-made items arrive as `**…**` and render as bold; the tiles
  are already bold, so they show plain text.
- About the role always shows eligibility, work and every role topic (salary, benefits,
  projects, mentorship, hours, progression, conversion and culture), as bullets, not
  extracted paragraphs. Sourced cards are condensed by an AI digest
  (`/goals/{id}/role-summary`) into a short headline and one to three cited bullets (key terms in bold) marked "Summarised by AI from
  the sources"; until then, or if it fails, each item is split into one bullet per sentence.
  Confidence and conflict flags sit beside their bullet; sources are listed once per card.
- Every field the sources leave empty is written by the AI once research settles
  (`/interview-prep` for interview slots and tiles, the `generated` cards of `/role-summary`
  for role topics). Each such field carries a small orange warning icon, explained by a legend
  under the accuracy warning ("made by an AI model based on the context it was provided, and
  not found in any sources"). The legend replaced the grey research-outcome banners. A field
  reads "Not filled yet" only while generating fails. The keyword-only "Interview prep" guide
  card was removed on 11 November 2026.
- Both research tabs carry the accuracy warning. The per-finding quote disclosure and the
  per-category refresh buttons were removed; refresh covers the tab's research.

After **Extract career goal**, the goal conversation (`job-review-chat.tsx`) shows the shared
"Skills needed" processing screen (`ProcessingCard`) while the goal is extracted, the role is
researched and the summary is prepared. Steps and progress come from the observed workspace phase
and server activities. The chat and composer open once the summary is ready; refinement
(`?refine=1`) and failed or empty states go straight to the chat.

Skill rows show a current-position marker and a labelled 10/10 goal endpoint before expansion. Details separate the evidence level from the stricter role target, show estimate confidence and target-source links, and explain that 10/10 satisfies this specific role’s goal. Only 10 receives the target-met band. Old rubric comparisons are stale until explicitly evaluated again.
