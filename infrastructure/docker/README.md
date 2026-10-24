# Docker deployment structure

The active slice includes Profile, Career preview imports and a development-only Mailpit inbox in `infrastructure/docker/compose.yaml`, with `infrastructure/gateway/nginx.conf` and `infrastructure/mongodb/init-profile.js`. See the [application setup guide](../../docs/setup.md). Career uses a read-only container and private, bounded temporary tmpfs; it does not connect to MongoDB or an AI provider. The remaining notes below describe the original scaffold templates.


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

No image pulls, builds, container starts, network creation, or volume creation are performed by this scaffold.
