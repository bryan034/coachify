# NGINX gateway

The profile slice now has an active four-container setup in `infrastructure/docker/compose.yaml`, with `infrastructure/gateway/nginx.conf` and `infrastructure/mongodb/init-profile.js`. See the [application setup guide](../../docs/setup.md). The remaining notes below describe the original scaffold templates.


The gateway is a separate planned container. It routes public page requests to the Next.js frontend and `/api/v1` requests to the appropriate FastAPI service.

`nginx.conf.example` contains a commented route plan only. It is not an active NGINX configuration and does not implement authentication, rate limiting, HTTPS, or routing yet.

When implementing, mount/copy the completed configuration into `/etc/nginx/nginx.conf` inside the gateway image. Preserve the agreed public API paths or explicitly coordinate any prefix rewriting with backend routes. Forward browser authentication context and necessary proxy headers; never blindly trust caller-supplied identity headers.

Only the gateway needs a public application port in the proposed deployment. Next.js and backend containers are reached by Docker service name over private networks. Auth/session callback routes must be routed according to the chosen identity integration.

The active config forwards `/_next/hmr` and `/_next/webpack-hmr` WebSocket upgrades to Next.js for
the opt-in [Docker development setup](../docker/README.md#hot-reload-during-development).
Reload/restart NGINX after config edits. Production Next.js does not expose an HMR server.

Model-backed Career routes allow 610 seconds of upstream inactivity to accommodate
local inference and sequential model calls. The UI uses asynchronous operation polling;
synchronous clients may still exceed this limit when queued. Career preview/import,
Profile, CV, Assessment and Roadmap timeouts retain their existing limits. Restart or
reload the gateway after changing its mounted `nginx.conf`.
