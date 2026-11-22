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
sequential model calls. The UI uses asynchronous operation polling;
synchronous clients may still exceed this limit when queued. Career preview/import,
Profile, CV, Assessment, Roadmap and Jobs timeouts retain their existing limits. Restart or
reload the gateway after changing its mounted `nginx.conf`.

Jobs requests have a 60-second upstream timeout for bounded live employer-board aggregation. No scheduled catalogue worker is required.

The active gateway also forwards `/api/v1/dashboard` to the stateless dashboard service on the private backend network, with a 60-second upstream timeout. The dashboard validates the owner session and reads Roadmap and Assessment through their APIs.

## Browser session boundary

Profile sets `elo_session=<public marker>.<server credential>` with HttpOnly,
SameSite=Strict and `/api/v1` scope; production also sets Secure and requires HTTPS.
For `X-Elo-Browser: 1` requests, every API location derives Authorization only from
a correctly shaped cookie whose marker matches `X-Elo-Session`. Supplied browser
Authorization headers are ignored. Cookies alone and mismatched/stale markers do
not authenticate. The custom headers require a CORS preflight from foreign origins;
the gateway/services do not enable cross-origin browser API access. Do not add
permissive credentialed CORS. Explicit bearer clients without the browser header
and private service-to-service calls retain their existing protocol.

Deploy the Profile, frontend and gateway changes together, then reload NGINX.
Existing browser sessions must sign in again. No database migration is needed.

Verify cookie/marker matching, CSRF rejection and bearer compatibility without the
application stack or private configuration:

```sh
python3.12 infrastructure/testing/gateway_browser_session_smoke.py
```

This uses disposable Docker resources with synthetic upstreams and removes them on
exit. It needs Docker plus the `nginx:alpine` and `python:3.12-slim` images.
