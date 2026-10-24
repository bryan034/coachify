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
| `/onboarding` | P13/P14 initial setup, Save progress and explicit Finish setup |
| `/profile` | P01–P08 editing, planning preferences, directory search, save/retry/context review |
| `/roadmap` | Saved planning summary and local filters; roadmap generation unavailable |
| `/cv` | Resume/skills/tracker layout; upload and assessment unavailable |
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
account changes clear private state and drafts, including other tabs. Failed logout
stays locally locked and offers retry. Local mode uses explicit synthetic email/password accounts and a captured-email
inbox; Google setup is unnecessary. Its chooser only prefills email. Sign out is available in the sidebar.

The public screens reuse Inter, workspace colours, rounded cards and button styles.
Only a verified-email session can enter setup. The shared guard reads canonical
profile completion: incomplete/legacy profiles go to `/onboarding`, completed users
go to `/dashboard`, and `/profile` remains available for ordinary edits. A partial
save never completes setup; errors remain recoverable. Cross-tab completion hints
trigger server readback rather than trusting a browser flag.

All API access uses `src/lib/api/profile.ts` through `/api/v1/profile` at the gateway.
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
