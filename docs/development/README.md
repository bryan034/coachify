# Development status

## What exists

- Next.js/React/TypeScript frontend directory structure and commented page/layout placeholders.
- Six independently organised Python service packages.
- Project metadata, environment examples, ignore rules, and Docker/NGINX templates.
- Current architecture, API route planning, and empty OpenAPI contracts.

## What is deliberately absent

No application logic, runnable entry points, UI, endpoint handlers, database clients/queries, Google OAuth, LLM calls, background-job execution, scheduled tasks, tests, live databases, or deployed infrastructure. Dependencies and image versions have not been selected or installed. A normal build cannot succeed until actual startup/UI code is added.

## Source organisation

Each FastAPI service has `app/api/v1`, `app/schemas`, `app/domain`, `app/clients`, and `app/core`. Data-owning services also have `app/repositories`. CV, career, roadmap, and review have worker placeholders. CV additionally has parsing and clarification folders; roadmap has planning and revisions; review has scheduling. Dashboard deliberately has no repository, database credential, or worker folder.

`__init__.py` package markers are empty. Other Python, TypeScript/TSX and CSS source placeholders are comments only. `tests/README.md` reserves a future test location; it is not a test suite.

## Next implementation stage

Select versions and dependency pins, implement minimal valid entry points, and activate runtime configuration before building product functionality. Agree the identity/session provider and how Google sign-in is verified by FastAPI. Preserve backend ownership checks and service boundaries even if Next.js supplies server-rendered pages.

Do not add secrets to tracked examples. Do not put uploaded CVs in Next.js `public/` or the source tree. No Git repository was initialised, dependencies installed, or containers launched during scaffolding.
