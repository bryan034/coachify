# Frontend

Next.js App Router, React, TypeScript, and a Node.js runtime.

The first workspace UI adapts `docs/design/coachify-web-v1.html` into reusable
React components, shared navigation and responsive styles. Fonts are bundled in
`public/fonts/` with the Inter OFL licence; no runtime font request is needed.
Typography uses Inter throughout, with medium-weight headings and tighter spacing
inspired by Revolut. Revolut’s exact Aeonik Pro heading face requires licensed
webfont files and is not bundled.

## Screens and data

| URL | Status |
|---|---|
| `/` | Public account entry, with distinct sign-in and create-account actions |
| `/dashboard` | Protected home with live saved background from the profile API |
| `/career-goal` | Temporary pasted text, URL and PDF/DOCX/TXT previews; reviewed target drafts, confirmation and explicit selection; no AI target analysis |
| `/onboarding` | P13/P14 full-screen question-by-question setup, ending with Enter Coachify |
| `/profile` | Occupation, education and employment summary with inline Edit profile, Save changes and Cancel |
| `/profile/edit` | Background/employment editing, planning preferences, directory search and save/retry |
| `/onboarding/preview` | Development-only replay with fresh, unsaved answers |
| `/roadmap` | Saved planning summary and local filters; roadmap generation unavailable |
| `/cv` | Resumable text conversation for CV review, clarification, corrections and manual capabilities; saved uploads/explicit selection and detailed evidence remain accessible; gap analysis remains planned |
| `/chats` | Chats/socials layout and local filters; requests unavailable |
| `/calendar` | Current week/month views; events and task actions unavailable |
| `/career`, `/reviews` | Matching placeholders for existing reserved routes |
| `/login`, `/register` | P09–P16 account screens: email/password, optional Google and email-code verification |

Draft names, scores, achievements, applications, contacts and events are replaced
with empty states. Unimplemented service actions do not make API calls or imply a
successful save. Account screens use the implemented Profile account endpoints.

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
content stays in page memory and is discarded on reload/leave.
CV API access uses `src/lib/api/cv.ts` through `/api/v1/cv` and Profile-owned manual
capabilities. The server policy supplies supported formats/limits. Uploads stay
private; ready CV selection is explicit and independent of the viewed/uploaded
source. Corrections, removals, declarations and clarification answers are saved
with expected versions and mutation identities. Same-source re-upload preserves
corrections; changed documents use a new CV identity. Failed/conflicting writes keep
local drafts, while logout/account changes discard them. Unconfigured extraction
and unavailable confirmed Career context are shown explicitly, without synthetic
results. See [CV feature behavior](src/features/cv-ingestion/README.md).

The CV conversation is the primary review surface. The selected/viewed source and
Career context stay identifiable, and **CV files** and **Your CV summary** provide
access to saved uploads, source evidence and direct correction/reconciliation
controls. Users can answer, add context or ask questions in the same composer.
Ordinary explanations save through validated interpretation; explicit corrections
and manual additions use Save/Cancel action cards. Unknown details and skips do
not become missing skills.

Conversation history is stored by the CV service and resumes after reload. The
client paginates earlier messages and can revisit previous segments without
storing CV text in browser storage. Message receipt, pending processing and applied
changes are distinct states. Recovery retains the original request identity after
an unknown network outcome; delayed responses cannot update a different displayed
conversation. Career target editing stays on `/career-goal`.

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
