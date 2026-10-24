# NGINX gateway

P07/P08 now have an active four-container setup in `infrastructure/docker/compose.yaml`, with `infrastructure/gateway/nginx.conf` and `infrastructure/mongodb/init-profile.js`. See `docs/development/profile-setup.md` from the repository root. The remaining notes below describe the original scaffold templates.


The gateway is a separate planned container. It routes public page requests to the Next.js frontend and `/api/v1` requests to the appropriate FastAPI service.

`nginx.conf.example` contains a commented route plan only. It is not an active NGINX configuration and does not implement authentication, rate limiting, HTTPS, or routing yet.

When implementing, mount/copy the completed configuration into `/etc/nginx/nginx.conf` inside the gateway image. Preserve the agreed public API paths or explicitly coordinate any prefix rewriting with backend routes. Forward browser authentication context and necessary proxy headers; never blindly trust caller-supplied identity headers.

Only the gateway needs a public application port in the proposed deployment. Next.js and backend containers are reached by Docker service name over private networks. Auth/session callback routes must be routed according to the chosen identity integration.
