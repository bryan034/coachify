# Docker deployment structure

The active Compose stack contains the Next.js frontend, NGINX, Profile, saved CV ingestion/review, canonical Career goal/research, scoped MongoDB users and an optional development Mailpit inbox. Roadmap/dashboard/review remain source scaffolds. See [application setup](../../docs/setup.md).

## Storage and service boundaries

- `web` connects the gateway and frontend; `backend` carries API dependencies and permitted outbound provider traffic; the isolated `database` network keeps MongoDB private.
- Profile owns account/manual-declaration data. CV owns `coachify_ingestion`, its worker and private `cv_uploads` volume. Career owns `coachify_career` and its public research/checkpoint metadata.
- CV upload routes retain their 11 MiB multipart gateway allowance, disabled buffering and upload rate limit. Provider credentials are server-side. CV parsing dependencies and private writable upload ownership are required.
- Career uses a non-root read-only container and bounded private tmpfs for temporary previews. Its database-user initialization also provisions missing CV users on existing volumes without resetting credentials or deleting data.
- `mongodb_data` persists structured data independently from temporary CV originals. Do not delete it when applying code, routing, credentials or index-compatibility changes.

## Configuration

The public [`.env.example`](.env.example) lists all active deployment inputs, grouped by service: gateway/auth/email, scoped database passwords, Career LLM/research and limits, and CV model/storage/usage settings. Configure private values yourself, preserving existing database passwords. Agents must not inspect private environment files. Career uses `AI_ENABLED`, `CAREER_LLM_API_KEY`, `GEMINI_REASONING_MODEL` and `CAREER_RESEARCH_API_KEY`; its default reasoning model is `gemini-3.5-flash-lite`. CV has a separate configurable OpenAI-compatible adapter using `CV_LLM_BASE_URL`, `CV_LLM_MODEL` and `CV_LLM_API_KEY`. Missing model configuration is an actionable unavailable state, not synthetic success.

Career credentials are now named `CAREER_LLM_API_KEY` and `CAREER_RESEARCH_API_KEY`.
Rename the previous `GEMINI_API_KEY` / `BRAVE_API_KEY` entries yourself, preserving
values; the providers remain Gemini / Brave. Deprecated names are read only when
the corresponding new variable is absent. An explicitly blank new variable overrides
the legacy key. Each credential is injected into Career only, never the frontend or CV.
CV keeps its independent `CV_LLM_API_KEY`; no service-specific `.env` file is needed
for Compose. Fixed internal API URLs/database wiring and the CV volume path remain
in Compose. Code-level constants and scaffold services do not gain unused variables.

After applying private setting changes, recreate the affected containers with
`up -d --force-recreate` using both development Compose files. `restart` alone does
not apply changed environment values. Rebuild only when the application image also
needs updated source/dependencies or build-time values (such as the production frontend
Google client ID); hot-reload mounts pick up these Python readers.

The three implemented services communicate through authenticated APIs. CV receives `CAREER_SERVICE_URL`; Profile receives `CV_SERVICE_URL` for explicit source attachment; Career receives its CV API URL. No service reads another service's database. Tests use `compose.test.yaml` and deterministic synthetic model responses, with explicit synthetic settings and `--env-file /dev/null` in isolated projects.

`compose.yaml.example` remains an inactive historical blueprint. Its schema validity does not prove a deployable application.

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
