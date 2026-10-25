# Docker deployment structure

The active slice includes Profile, Career exploration/goal persistence, CV read APIs, a service-user setup job and a development-only Mailpit inbox in `infrastructure/docker/compose.yaml`, with `infrastructure/gateway/nginx.conf` and `infrastructure/mongodb/init-profile.js`. See the [application setup guide](../../docs/setup.md). Career uses a read-only container and private, bounded tmpfs for temporary uploads. Career and CV connect only to their scoped databases; explicit exploration turns use backend-only AI settings, while previews do not call AI. The remaining notes below describe the original scaffold templates.


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

## Hot reload during development

From the repository root, run this yourself with your existing private configuration:

```sh
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  -f infrastructure/docker/compose.dev.yaml up --build -d
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  -f infrastructure/docker/compose.dev.yaml restart gateway
```

Open `http://localhost:8080`. Build once when switching to this mode. Afterward,
Next.js Fast Refresh updates UI changes and Uvicorn reloads Python changes in
Profile, Career and CV. NGINX forwards the HMR WebSocket. Webpack polling is enabled
for Docker Desktop bind mounts. Some React edits trigger a full refresh and reset
unsaved browser state; Python reloads interrupt in-flight requests.

Only source/public/config paths are mounted, read-only. Dependencies stay in the
image; `.next` uses a separate development cache volume. No environment files are
mounted, and agents must not read them or run commands that load private values.
MongoDB retains its existing data volume; do not use `down -v` to switch modes.

Rebuild for dependency or Dockerfile changes. Recreate containers after changing
runtime settings yourself. Restart the affected API for JSON/data snapshot changes
(Uvicorn's default watcher tracks Python); restart the gateway for NGINX changes.
Continue using both `-f` options for development commands. Omit `compose.dev.yaml`
and rebuild/recreate to return to the production-style configuration.
