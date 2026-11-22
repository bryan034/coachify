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

`career-goal.tsx` keeps paste, URL and document previews in page memory. The
account/token key clears previews and pending requests when the signed-in account
changes. Leaving the page warns about unsaved inputs.

See the [Career service](../../../../../services/career-service/README.md) and
[contract](../../../../../contracts/api/career.yaml).

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

The saved-goal overview is a dark header (role, facts, a ring of skills by importance, Refine goal / Set a new goal), a line showing how Career Goal, Skills Profile and Roadmap feed each other, the three goal pages as one pill-shaped tab group, a one-line goal confirmation for CV review, and **Skills needed**: every skill under its category, most important first, with the person's level against the role's target (the tick), filters for Ready / Getting there / To build / Not rated, **Talk it through** and **See evidence** per skill. Opening a skill also says why it has its numbers: why the target was set (what the employer expects, up to two things people reported about the skill with their source, and why elo rated it that level, labelled job description, role research or elo's estimate; hidden when the evaluation set a different target) and the evaluation's explanation for the person's level. Under each skill, "Your skills that count" lists every Skills Profile skill that counts towards it (same skill, one of its parts, or linked by the evaluation) and "Breaks down into" lists its smaller skills (learning items), marking the ones the person already has; the Skills Profile uses the same links. A yellow chip warns when the roadmap ends after the job's start date. Levels come from the saved evaluation (`demonstrated_score` against `required_score`); nothing is scored in the browser. Categories come from
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
  Importance is shown by colour (Essential, covering required and preferred skills, or Nice to have) and marked when elo
  inferred it. Each row shows the Assessment rubric v1 planning estimate when the comparison
  scored it (10 means your evidence meets the level the role states), otherwise its Have,
  Partial, Gap or Unknown status. Expanding a skill shows why it matters, its importance
  source, the competence bar and the "What you need" learning items. Job-description quotes
  are not shown in skill cards. Long lists start with ten skills.
- Interview preparation and About the role (`opportunity-intelligence.tsx`, components in
  `research-brief.tsx`, styles in `research-brief.css`) share outlined panels and numbered citations.
  Both tabs render saved category findings from `/goals/{id}/opportunity-research` directly,
  including available findings while research runs. Neither requests a separate brief or summary
  or condenses the findings for display. The backend may shorten overlong round names once as described below. Both headers show "Researched <date> from N sources",
  and one AI disclaimer. Neither tab has a research-start or refresh action. Existing saved findings work without regeneration.
- About the role (`role-research.tsx`): **Who can apply** and **What you would do** show the saved
  goal's extracted requirements and duties verbatim (four duties initially, "Show N more").
  **What it is like** displays the original findings for projects, benefits, mentorship, intern
  hours, company/team culture, management and company hours. **Pay and what comes after** displays
  original intern pay, full-time opportunities, career progression, full-time pay, conversion rates,
  historical cohorts and offer acceptance. There are no generated takeaways, sentiment labels or
  invented missing values. Available findings, citations and uncertainty remain visible during
  research or provider failures; settled missing topics appear under **Not found yet**.
- Interview preparation (`interview-research.tsx`): the reported round count and a numbered,
  linked overview appear first. Each overview box has the reported round name as its heading
  and the saved round-format or stage finding as its description; missing descriptions stay labelled. **Interview rounds** shows one independently padded card per saved
  `round_number`, separated by space, in reported order and headed by its reported name. Each card groups that round's
  **What to expect**, **Questions reported** and **How to prepare** findings. Missing round-specific
  expectations or preparation are labelled; no additional model call invents them. Unassigned
  findings remain in general process, timeline, difficulty, format, question, preparation and
  candidate-experience sections. Older reports without round metadata stay general until refreshed.
  Display names are 1–3 words. The API returns `round_titles` separately from the original
  `round_name`: names already within the limit pass through; overlong names get one cached,
  title-only backend model pass after research finishes. Descriptions, expectations and preparation
  keep their exact saved wording, bold terms, citations and uncertainty. Invalid or unavailable title
  output falls back to a short round label without another model pass. No display-summary word
  limits or truncation apply to the findings. Partial results remain visible. Missing sections appear under
  **Not found yet** once the category settles.
- Inferred findings carry an amber **Estimated** tag; findings where sources disagree carry
  **Conflicting reports**. A settled section with no data is hidden and named under Not found yet.
- Sources are listed 1..N in first-cited reading order, five at first ("Show all N sources").
  Citation numbers are assigned from each tab's saved source IDs without changing findings.
  `research-findings.tsx` shares the safe bold-text rendering, provenance labels and citation mapping.
  A citation chip expands the list if needed, scrolls to its source and briefly highlights it.

As soon as **Extract career goal** is pressed, Career Goal (`career-goal.tsx`) replaces the form
with the shared "Skills needed" processing screen (`ProcessingCard`) while the goal is extracted;
failures return to the form with the draft and a retry. The screen tells the user they can
leave: extraction runs as a server-side Career operation, the leave-page warning is skipped, and
the tab keeps the request body and idempotency key in `sessionStorage` (account-scoped, two-hour
expiry, cleared on success, failure or **← Career Goal**). Returning to Career Goal reopens the
processing screen and reconnects to the same operation with that key, then opens the goal
conversation once it finishes. A new tab or another browser does not reconnect; the goal still
saves server-side. Once saved, the goal conversation
(`job-review-chat.tsx`) shows the same screen while the role is researched and the summary is
prepared. Steps and progress come from the observed workspace phase
and server activities. The chat and composer open once the summary is ready; refinement
(`?refine=1`) and failed or empty states go straight to the chat.

Skill rows show a current-position marker and a labelled 10/10 goal endpoint before expansion. Details separate the evidence level from the stricter role target, show estimate confidence and target-source links, and explain that 10/10 satisfies this specific role’s goal. Only 10 receives the target-met band. Old rubric comparisons are stale until explicitly evaluated again.
