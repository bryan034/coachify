# Frontend

Planned stack: Next.js App Router, React, TypeScript, and a Node.js runtime.

This folder contains no UI implementation. Source files are comment-only placeholders, not valid completed Next.js pages or layouts. Frontend runtime and test dependencies/scripts are configured; see `tests/README.md` for commands. There is no Google OAuth implementation.

## Directories

| Directory | Intended responsibility |
|---|---|
| `src/app/` | Next.js file-based pages and shared layouts |
| `src/app/(auth)/` | Login-related pages; the group name is omitted from URLs |
| `src/app/(workspace)/` | Student screens sharing the workspace layout |
| `src/components/ui/` | Reusable interface primitives |
| `src/components/layout/` | Sidebar, header, and other shared page framing |
| `src/features/` | Feature-specific components and presentation logic |
| `src/lib/api/` | Future typed HTTP clients for FastAPI through the gateway |
| `src/lib/auth/` | Future identity/session integration |
| `src/hooks/` | Future reusable React hooks |
| `src/types/` | Future frontend type definitions |
| `src/styles/` | Styles |
| `public/` | Public static assets only; never uploaded CVs |

## Planned page URLs

`/`, `/login`, `/dashboard`, `/profile`, `/cv`, `/career`, `/roadmap`, `/reviews`.

The initial API client will use `/api/v1` in the browser and an internal gateway URL from server-side code. FastAPI owns business logic and domain database access. No parallel Next.js implementations of roadmap or assessment APIs are planned. Authentication callback route handlers may be added once the identity integration is selected.

`next.config.ts.example` and `Dockerfile.example` are configuration notes, not active runtime configuration. Add real components and runtime configuration in the next implementation stage.
