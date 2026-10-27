# Docker deployment structure

The active slice includes Profile, CV saved upload/review, Career previews and reviewed targets, and an optional development Mailpit inbox in `infrastructure/docker/compose.yaml`. See the [application setup guide](../../docs/setup.md). CV and Career use separate database credentials. CV retains private originals temporarily; Career previews use bounded tmpfs and only structured reviewed targets persist. Career makes no AI calls. Remaining services still use inactive scaffold templates.


`compose.yaml.example` is an intentionally inactive deployment blueprint. It uses a `scaffold` profile for application services, and references comment-only Dockerfile examples. It cannot build or start a working Coachify application. Do not interpret Compose schema validity as application readiness.

## Planned components

- NGINX gateway: one public application entry point.
- Next.js frontend: private Node.js server container.
- Six FastAPI service containers.
- Optional local MongoDB container under `local-db`; proposed production database is external Atlas.
- `cv_uploads`: private original-file staging volume, mounted only by the CV service.
- `mongodb_data`: local MongoDB data volume, unrelated to CV staging.

## Networks

- `web`: gateway and frontend.
- `backend`: gateway and backend services; retains outbound access for external identity, Atlas, and LLM connections where needed.
- `database`: local MongoDB and the five data-owning services; isolated network with no MongoDB host port.

## Before making it runnable

1. Choose and pin supported runtime/image and dependency versions.
2. Add valid Next.js pages/layouts and FastAPI startup entry points.
3. Turn the Dockerfile examples into actual service Dockerfiles.
4. Complete NGINX routing and the chosen authentication integration.
5. Add service-scoped environment loading and MongoDB users/credentials.
6. Configure health checks and readiness dependencies.
7. Review the deployment blueprint and then produce an active Compose file.

`compose.test.yaml` is an explicit override for disposable integration tests. It
adds a synthetic model HTTP boundary and permits HTTP only in the development
CV container. It refuses documents without the synthetic fixture marker. Never
apply this override to a personal-data or production stack. See [tests](../../docs/testing.md).
