# Frontend

Next.js App Router, React, TypeScript, and a Node.js runtime.

The UI uses the supplied Elo logo and ink/mint palette, with a broad public hero
inspired by the Ebury reference. Shared navigation, forms, chat and saved-goal
briefings use the same visual system. Fonts are bundled in `public/fonts/` with
the Inter OFL licence; no runtime font request is needed. See the
[design guide](../../docs/design/README.md) for tokens and asset provenance.

## Screens and data

| URL | Status |
|---|---|
| `/` | Public account entry, with distinct sign-in and create-account actions |
| `/dashboard` | Protected home with live saved background from the profile API |
| `/career-goal` | Saved career briefing with expandable learning focus, starting-point sidebar, collapsible role/research context, guided refinement and CV handoff; new accounts see JD inputs/exploration |
| `/career-goal/discovery` | Chat with bounded memory, automatic concurrent research, cited skill recommendations and explicit shared-goal confirmation |
| `/career-goal?new=1` | Replace the goal using a new text, URL or document JD; preserve the previous goal until extraction succeeds |
| `/career-goal/chat` | Saved-goal Q&A or separate career exploration; `?refine=1` opens guided goal refinement |
| `/onboarding` | P13/P14 full-screen question-by-question setup, ending with Enter Coachify |
| `/profile` | Occupation, education and employment summary with inline Edit profile, Save changes and Cancel |
| `/profile/edit` | Background/employment editing, planning preferences, directory search and save/retry |
| `/onboarding/preview` | Development-only replay with fresh, unsaved answers |
| `/roadmap` | Saved planning summary and local filters; roadmap generation unavailable |
| `/cv` | Saved CV upload/selection, resumable text review, interpreted clarification, correction/reconciliation and Profile-owned manual capabilities |
| `/chats` | Chats/socials layout and local filters; requests unavailable |
| `/calendar` | Current week/month views; events and task actions unavailable |
| `/career`, `/reviews` | Matching placeholders for existing reserved routes |
| `/login`, `/register` | P09–P16 account screens: email/password, optional Google and email-code verification |

Draft names, scores, achievements, applications, contacts and events are replaced
with empty states. Unimplemented service actions do not make API calls or imply a
successful save. Account screens use the implemented Profile account endpoints.

Career chat renders assistant Markdown (bold, headings, lists and code) using
`react-markdown`, with raw HTML and remote images disabled. In-chat activity reflects
observed loading, research and response states; it does not expose model reasoning.
The initial overview includes saved interview stages and explicitly sourced round
counts; unknown counts stay unknown. Chat sends one recent exchange for follow-up
resolution, with backend topic routing and focused retrieval. The completed answer
replaces the activity indicator, and failures keep the composer
draft available for retry. Existing JSON APIs and research polling are unchanged.

## Profile and authentication

`ProfileProvider` in the root layout owns the account, Coachify session, server auth
mode, profile and load/retry states. Workspace routes withhold private content until
the session is validated. Session bearers survive same-tab reload in sessionStorage;
Google credentials are exchanged only during account access. Logout, expiry and
account changes clear private state and drafts, including other tabs. Normal initial
`pageshow` events preserve drafts; back/forward-cache restores hide private content
until the session and profile are revalidated. Failed logout
stays locally locked and offers retry. Local mode uses explicit synthetic email/password accounts and a captured-email
inbox; Google setup is unnecessary. Its chooser only prefills email. Sign out is available in the sidebar.

The public screens reuse Inter, workspace colours, rounded cards and button styles.
Only a verified-email session can enter setup. The shared guard reads canonical
profile completion: incomplete/legacy profiles go to `/onboarding`, completed users
go to `/dashboard`, and `/profile` remains available for ordinary edits. A partial
save never completes setup; errors remain recoverable. Cross-tab completion hints
trigger server readback rather than trusting a browser flag.

Setup shows status, education path, school, optional course, student year and review
one screen at a time in a clean full-screen layout. A persistent bottom progress
bar shows the current step; there is no setup sidebar. Forward/back transitions
use a short fade and vertical slide, with reduced-motion support. Long questions
scroll above the progress footer. X signs out. Student status
and path save together; other new answers save at step boundaries. Changes to
retained education needing context review wait for final confirmation. Saved
answers resume after reload; unsaved typing is discarded, and an empty optional
course may be offered again. Only **Enter Coachify** completes setup. Employed users also answer separate
workplace and role questions; both are required for new setup completion.

University search starts with a name and an editable country suggestion from
browser locale/time zone, not verified location. Matching schools are grouped
under country headings with name-only buttons; **Show more schools** extends the
same groups. Unlisted schools can be entered manually. Keyboard focus, responsive
layouts and reduced-motion preferences are supported.

Profile API access uses `src/lib/api/profile.ts`; temporary Career imports use
`src/lib/api/career.ts` through `/api/v1/career` at the gateway. Career source
content stays in the account-scoped Career route provider, never browser storage.
**Extract career goal** starts the LangGraph JD workflow. Validated role/skill/condition
information immediately becomes the account's latest goal. The browser stays in chat while the saved goal overview is populated. Saved skills appear in expandable learning-focus rows; eligibility, responsibilities and cited research are in collapsible context sections. The starting-point sidebar distinguishes available CV skills, a missing CV, saved CVs without available skills, and unavailable status. Its links open the implemented CV workspace without claiming a per-skill assessment. See the [briefing data map and proposed extensions](../../docs/design/career-briefing.md). Research status updates on this page without hiding the extracted goal. **Refine goal** opens guided chat; **Set a new goal** opens fresh JD inputs while preserving the current goal until successful replacement.
The validated JD summary, cited research and follow-up composer open together only after both extraction and research finish. Progress is visible meanwhile.
Unavailable sources produce a retry state; no-findings stays explicit. One current
conversation is loaded from `/api/v1/career/workspace`; there is no session picker. The saved goal overview has a separate explicit confirmation for using the current revision in CV clarification. A new successfully interpreted JD resets that conversation.
Manual changes happen through guided chat. The agent asks for missing details, then
automatically validates and saves the requested fields; users can cancel a pending edit
in chat. The manual form and Apply button are removed. Message keys make retries
idempotent, and the workspace can restore the latest pending question after reload. Research remains distinct from JD requirements and personal skills.
The details panel exposes interview topics, stages, assessments, uncertainty and
source evidence. Ordinary follow-up requests send only session/version, the current
message and at most one recent exchange; the backend retrieves only the relevant
saved fields. Independent questions omit that history from model input.
The extracted-goal chat clears submitted text immediately and keeps the composer
editable while a reply is pending. Replies preserve the next draft; failures restore
the submitted message only when no newer draft exists, with retry available separately.
Recent JD turns are temporary. Reload restores the latest structured goal/research,
not the original JD or a full chat transcript. Exploration uses its own LangGraph
path; choosing a suggested direction makes it current, then generates advisory skills
and research for the same workspace. Temporary workflow checkpoints expire after
24 hours of inactivity; saved goals remain available for structured resume.
FastAPI owns validation, resource ownership and database writes. See
[application setup](../../docs/setup.md) for environment and Docker setup.

## Structure

- `src/app/`: file-based routes and shared workspace layout.
- `src/components/layout/`: shared sidebar/navigation and workspace frame.
- `src/components/ui/`: icons, headings, empty states and disabled actions.
- `src/features/`: profile logic and feature-specific screen presentation.
- `src/lib/api/`, `src/lib/auth/`: API client and Google identity integration.
- `src/styles/`: draft design tokens, responsive primitives and profile form styling.
- `public/`: public assets only; never uploaded CVs.

See `tests/README.md` for unit, browser and disposable full-stack test commands.

P04–P06 use `PlanningPreferences` and the existing Profile API. See the [Profile service README](../../services/profile-service/README.md) for its endpoints and service rules.

**Edit profile** opens a single-column form directly on `/profile`, with stacked
status, employment and education fields. School search stays collapsed until you
change the school or select a new education path. Clearing the optional course
removes it; only students see a study-year field. Country search uses **All countries**.
**Save changes** uses the versioned Profile PATCH API and returns to the updated
summary after success. Failed saves keep the draft; **Cancel** discards unsaved
changes. `/profile/edit` remains available for direct links and planning preferences.
Reloading `/profile` returns to the saved summary.

The profile dashboard shows the current student year only for Student status, and
workplace/role only for Employed status. Earlier completed accounts may add missing
work details through **Edit profile** without repeating real onboarding.

**Preview onboarding** appears only when the Profile backend reports
`development_tools_enabled=true` (`APP_ENV=development`, including email mode).
The guarded preview starts from empty answers, makes no profile writes and never
resets completion. Exit/finish returns to the profile without signing out.
Production hides the button and redirects direct preview URLs to the profile.

Onboarding uses 75% of desktop viewport width, with mobile gutters. Employment asks
company, role and industry on separate screens. Unemployed users first answer
whether they have worked before; a yes collects last-job details, a no skips to
education. Profile summaries and the single-page editor distinguish previous from
current work. Company/industry suggestions come from Profile reference endpoints;
manual entry works even when the suggestion service is unavailable.

Never-employed unemployed users with a last school answer graduation year immediately after choosing it. The year is saved in education, displayed on My profile and editable in the same single-page form. Explicit no previous education skips this question.

## Session recovery and drafts

Ordinary tab switches and periodic session checks preserve mounted forms and unsent CV/Career drafts. Temporary validation failures offer retry; authentication expiry, revocation, sign-out and account changes clear private state. There is no five-minute inactivity lock or forced refresh policy. Unsent drafts remain in React memory, so explicit browser refresh, browser/OS tab discard or confirmed navigation may discard them. CV upload/source switches ask before discarding an unsent draft.

## Docker Fast Refresh

The [development Compose override](../../infrastructure/docker/README.md#hot-reload-during-development)
uses the Dockerfile's `development` target, Next.js dev with Webpack polling,
read-only source mounts and a separate `.next` cache. The gateway forwards the
HMR WebSocket. React edits usually preserve state; edits requiring a full refresh
can reset unsaved inputs. Production uses the existing build/start target.

Career replies reveal word by word after the validated API response arrives. Markdown
headings/lists format the first JD overview; older replies stay fully visible. Users
can choose Show full response, and reduced-motion preferences disable animation.
Token-limit errors, safe request-conflict explanations and a fixed disabled-AI explanation are shown. Other failures keep quiet retry
controls and retained drafts; provider diagnostic codes/details remain in Network responses.
The transient JD request key stays in the career session across chat navigation.
Reopening the same pending JD reconnects to its running extraction; different-input
conflicts show a safe explanation instead of only an unexplained Retry button.

Interview research uses provider-neutral progress and summary labels. Original source
links and AI-summary attribution remain visible in research details.

The initial career-goal explanation reports useful interview source coverage. If the
research budget cannot find three distinct useful URLs, it labels the findings as limited.

The overview checks `GET /api/v1/career/context/assessment` for owner-scoped CV availability. Missing, pending, failed and successfully extracted sources remain distinct from a service failure. The link opens the implemented saved-CV review screen. The compatibility status named `evaluated` indicates available extracted skill input; it does not establish mastery, an assessment computation or a readiness score.

Opportunity Intelligence adds five expandable sections beneath the saved goal
cards: interviews, internship experience, career progression/conversion salary, historical conversion rates and company/team culture. Category findings
show original citations, confidence/evidence type, dates, context limitations and
missing fields; summaries select only validated finding refs. Category status
polls independently, retaining successful findings during other failures/refresh.
Whole-report and individual refresh use versioned UUID-idempotent commands.
`?refine=1` sends explicit refinement mode, allowing guided edits before research
finishes; ordinary questions still require interview evidence. Employment type
is shown only when established. No-company employer sections are not applicable.

Career Discovery uses Gemini for direction setting and no CV inputs. Its research
review groups core, specialisation-specific and optional skills, with sample counts,
coverage, qualifications, responsibilities and source links. Removing a requirement
saves through the existing review API; explicit confirmation uses `/goals/confirm`.
The initial chat response and composer wait for extraction and complete research;
saved-goal backend APIs remain available during research waits/failures. A
pending chat request's own quota recovery pauses that submission. Wait labels identify
legacy wait state versus current provider cooldown. See the service's
[discovery specification](../../services/career-service/CAREER_DISCOVERY.md).


JD extraction now stays in `/career-goal/chat?source=jd`: observed intake/research steps
are shown in chat, with no provider/tool names or simulated model reasoning. The saved
JD summary and final sourced research summary use word-by-word validated Markdown
(reduced-motion support and Show full response). The Career Goal button explicitly
opens populated cards; ordinary questions and refinement become available after the
combined initial response is ready. The frontend requests `/workspace/summary` after
extraction and research finish, then renders a concise Gemini overview of the key
points with validated citations and the final line “Ask me anything about this goal set!”
Follow-up fact markers such as `[f1, f3]` also render as source-domain links beside the supported claim.
The summary uses short bullets throughout, including its role overview, rather than an opening paragraph.
Each summary point has inline source-domain links generated by the backend from its
saved-fact references. Plain model text is escaped; URLs and Markdown written by the
model cannot create citations. Saved URLs containing parentheses remain intact.
A saved report loading after workspace completion shows a loading state, never a
spurious Resume research button. Finished partial reports can be summarised with
coverage limits. Report-read and summary retries do not restart completed research. Progress is removed once this answer is ready. Summary retries preserve their
operation key. Follow-up questions stay in the same conversation and can initiate public
Brave research through Gemini's backend context route; their observed steps disappear
when the cited reply arrives. Public answers do not silently edit the saved goal.
Polling continues while any research category is pending, even after interview completion.
Unrelated document intake shows a fixed career-only scope explanation. Client scope
labels are backed by server validation; private technical diagnostics remain hidden.

Chat follows word-by-word replies while the reader is at the bottom. Scrolling up
pauses following across message and progress updates; **Jump to latest** resumes it.
Saved research findings, interview topics and evidenced process details include
inline domain citations linking to their original URLs. Missing provenance receives
no invented citation. External Markdown source links also display their domain;
internal navigation links retain their labels.

Career clients read goal content from `current.goal`. Progress polling uses `/workspace/progress`
and opportunity `/progress` endpoints; changed versions trigger content loading. Source excerpts
and verified quotes load only when a finding's evidence disclosure opens. Goal edits retain the
current goal ID and use its version. There is no original-content restore action.

Saved goal details in chat remain readable when research fails or the workflow expires,
including when AI is disabled. The combined response and composer still require completed
research; the details panel does not present unfinished findings as complete.

Opportunity category notices distinguish irrelevant sources, absent facts, validation
failures and provider failures/timeouts using the backend outcome. Legacy saved
reports without an outcome retain their existing status messages.

The initial chat overview is generated from the saved goal and completed research.
The backend validates its structured points and attaches the saved source links;
the frontend renders the returned wording without paraphrasing it. Detailed
Opportunity Intelligence preserves individual saved findings and their citations.

Explore careers uses the goal-chat layout at `/career-goal/discovery`. Discovery alone
keeps its owner-scoped transcript on the server, permits chat during automatic research,
and clears the composer on send without overwriting the next draft. Final goal saving
still requires explicit review and confirmation. See [Career Discovery](../../services/career-service/CAREER_DISCOVERY.md).

## Saved conversational CV review

The CV workspace starts with a text conversation. **CV files** provides uploads and explicit source selection; **Your CV summary** provides saved evidence and direct review tools. Users can answer, add context or ask questions in one composer. Ordinary explanations save through validated interpretation; corrections, removals and manual additions retain explicit action cards. Unknown details and skips remain uncertain.

History is stored by CV and resumes after reload, including manual-only conversations with no uploaded CV. Messages are paginated in retained bounded segments. The client does not store CV text in browser storage. Message receipt, interpretation progress and factual save are distinct. Retry retains the original request after an unknown network outcome, and delayed responses cannot update a different displayed CV/account. Older loaded action pages refresh their statuses; full segments expose outstanding work before continuation.

Career remains the single goal authority. The saved goal overview shows whether the current goal/version/selection has been confirmed for CV review. Confirmation is explicit and independent of Career's automatic saving. A changed or replaced goal requires a fresh confirmation; earlier source-bound CV answers remain saved. CV context preserves requirement provenance and alternatives rather than treating unknown eligibility or location as a qualification fact. No second active target editor is required.

Career Discovery opens with only the fixed Python-supplied introduction. **New chat**
clears the visible history, scope, suggestions and draft; the first sent message
creates a new private session. Opening the page performs no LLM or Brave calls.
Reload saved progress within an active chat reads its session ID; reopening the page
starts a clean view. Earlier sessions and confirmed goals remain saved.

The Discovery introduction is fetched only on fresh opening and kept separately from
the transcript. Subsequent session responses omit it, and it never enters model history.

Career Discovery collects its six research-readiness topics in a numbered bundle,
omitting topics already answered. Role scope offers “keep it broad”; other questions
end with “You can say unsure.” There is no repeated clarification preface. Explicit unsure/skip answers count, missing answers do not. The Career
backend gates automatic research; final goal confirmation is unchanged.
