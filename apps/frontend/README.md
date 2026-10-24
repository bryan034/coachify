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
| `/`, `/dashboard` | Home with live saved background from the profile API |
| `/profile` | P01–P08 editing, planning preferences, directory search, save/retry/context review |
| `/roadmap` | Saved planning summary and local filters; roadmap generation unavailable |
| `/cv` | Resume/skills/tracker layout; upload and assessment unavailable |
| `/chats` | Chats/socials layout and local filters; requests unavailable |
| `/calendar` | Current week/month views; events and task actions unavailable |
| `/career`, `/reviews` | Matching placeholders for existing reserved routes |
| `/login` | Redirects to inline account controls at `/profile` |

Draft names, scores, achievements, applications, contacts and events are replaced
with empty states. Unimplemented service actions do not make API calls or imply a
successful save. No new backend endpoints are introduced by this UI integration.

## Profile and authentication

`ProfileProvider` in the workspace layout owns the in-memory Google token, validated
server auth mode, saved profile, school categories and reload/error state. It stays
mounted during Next.js client navigation. Home and the sidebar show saved values;
profile drafts remain local to the editor until PATCH succeeds. Unsaved edits are
not retained when navigating away. Refresh clears Google credentials and requires
sign-in again; no token is stored in local/session storage. Local-test mode needs
no Google configuration. Account controls appear inline on Home and My profile.

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
