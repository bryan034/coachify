# Docker deployment structure

The active Compose stack contains the Next.js frontend, NGINX, Profile, saved CV ingestion/review, canonical Career goal/research, Assessment comparisons, Roadmap adviser chat/plans, scoped MongoDB users and an optional development Mailpit inbox. Dashboard and Review remain source scaffolds. See [application setup](../../docs/setup.md).

## Storage and service boundaries

- `web` connects the gateway and frontend; `backend` carries API dependencies and permitted outbound provider traffic; the isolated `database` network keeps MongoDB private.
- Profile owns account/manual-declaration data. CV owns `elo_ingestion`, its worker and private `cv_uploads` volume. Career owns `elo_career` and its public research/checkpoint metadata.
- CV upload routes retain their 11 MiB multipart gateway allowance, disabled buffering and upload rate limit. Provider credentials are server-side. CV parsing dependencies and private writable upload ownership are required.
- Career uses a non-root read-only container and bounded private tmpfs for temporary previews. Its database-user initialization also provisions missing CV users on existing volumes without resetting credentials or deleting data.
- `mongodb_data` persists structured data independently from temporary CV originals. Do not delete it when applying code, routing, credentials or index-compatibility changes.

## Configuration

The public [`.env.example`](.env.example) lists all active deployment inputs, grouped by service: gateway/auth/email, scoped database passwords, Career LLM/research and limits, CV model/storage/usage settings, and separate Assessment/Roadmap database passwords and Gemini model keys. Keep every user-configurable deployment value in the single ignored `infrastructure/docker/.env`; do not add per-service environment files. Agents may maintain the public template. Configure private values yourself, preserving existing database passwords. Agents must not inspect private environment files. Career uses `AI_ENABLED`, `CAREER_LLM_PROVIDER`, `CAREER_LLM_BASE_URL`, `CAREER_LLM_RESPONSE_MODE`, `CAREER_LLM_MODEL`, `CAREER_LLM_API_KEY`, `CAREER_RESEARCH_PROVIDER` and `CAREER_RESEARCH_API_KEY`. The public template selects local DeepSeek-compatible inference plus Brave; production can select DeepSeek cloud plus DeepSeek Search. See [model/search setup](../../docs/setup.md#career-model-and-search-configuration). CV has a separate configurable OpenAI-compatible adapter using `CV_LLM_BASE_URL`, `CV_LLM_MODEL` and `CV_LLM_API_KEY`. Missing model configuration is an actionable unavailable state, not synthetic success.

The local profile uses `elo-deepseek-r1:1.5b` (an Ollama alias with 16,384 context
tokens), `AI_CONTEXT_TOKENS=16384`, `CAREER_LOCAL_TIMEOUT_SECONDS=45` and
`OPPORTUNITY_RUN_SECONDS=600`. Model calls are serialized per Career worker;
cloud providers ignore the local deadline setting. Create the alias and apply private
values using the setup guide above, then rebuild/recreate Career and restart the
gateway for its 610-second Career model-route read timeout. Alias creation reuses
existing weights and does not run inference.

Career credentials are now named `CAREER_LLM_API_KEY` and `CAREER_RESEARCH_API_KEY`.
Rename the previous `GEMINI_API_KEY` / `BRAVE_API_KEY` entries yourself, preserving
values when retaining Gemini / Brave. Compose requires these canonical names; it no
longer relabels a legacy credential when providers change. Direct non-Compose
processes still support each legacy alias only for its own provider and only when
the canonical key is absent. An explicitly blank canonical key disables that credential. Each credential is injected into Career only, never the frontend or CV.
CV keeps its independent `CV_LLM_API_KEY`; no service-specific `.env` file is needed
for Compose. Fixed internal API URLs/database wiring and the CV volume path remain
in Compose. Code-level constants and scaffold services do not gain unused variables.

After applying private setting changes, recreate the affected containers with
`up -d --force-recreate` using both development Compose files. `restart` alone does
not apply changed environment values. Rebuild only when the application image also
needs updated source/dependencies or build-time values (such as the production frontend
Google client ID); hot-reload mounts pick up these Python readers.

After recreating backend containers, restart the gateway once every upstream service
is running. NGINX resolves the configured service names on startup/reload; an unchanged
gateway can keep old container addresses and return 502 for Profile account access.
If a service has exited, fix its startup error first: a missing upstream DNS record
can prevent the gateway from reloading. CV requires its per-owner model concurrency
limit to be strictly lower than its global limit (defaults `1` and `3`).

The implemented services communicate through authenticated APIs. CV receives `CAREER_SERVICE_URL`; Profile receives `CV_SERVICE_URL` for explicit source attachment; Career receives its CV API URL. No service reads another service's database. Tests use `compose.test.yaml` and deterministic synthetic model responses, with explicit synthetic settings and `--env-file /dev/null` in isolated projects.

`compose.yaml.example` remains an inactive historical blueprint. Its schema validity does not prove a deployable application.

For existing installations, read the [rename and data migration notes](../../docs/setup.md#renamed-installations) before rebuilding with the new `elo-profile` project and `elo_*` database defaults. Old volumes are not migrated automatically.

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

## Career URL preview browser

Career installs the pinned Playwright package and Chromium headless shell in its
image. Rebuild/recreate Career after this dependency change, even with hot reload:

```sh
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  -f infrastructure/docker/compose.dev.yaml up --build -d career-service
docker compose --env-file infrastructure/docker/.env \
  -f infrastructure/docker/compose.yaml \
  -f infrastructure/docker/compose.dev.yaml restart gateway
```

No new API keys are required for supported public Greenhouse/Lever GET endpoints.
The browser runs as the existing non-root service user with its Chromium sandbox
on. Career retains its read-only filesystem, 768 MiB memory cap, dropped capabilities
and no-new-privileges; its private tmpfs is 128 MiB and PID/thread limit is 256.
One browser render may run at a time; a container init reaps terminated descendants. Hosts must support unprivileged user namespaces;
if startup is unavailable, URL imports offer paste/upload rather than disabling the
sandbox. Direct Python runs need `playwright install chromium --only-shell` and
`PLAYWRIGHT_BROWSERS_PATH` pointing to that installation.

[career-browser-seccomp.json](career-browser-seccomp.json) is based on Microsoft's
[Playwright v1.64.1 profile](https://github.com/microsoft/playwright/blob/v1.64.1/utils/docker/seccomp_profile.json)
([Apache-2.0 license](career-browser-seccomp.LICENSE)), with `chroot` allowed for Chromium's namespace-local sandbox while
container capabilities remain dropped. It is applied only to Career. See
[Playwright's Docker guidance](https://playwright.dev/python/docs/docker).
Browser profiles are temporary, receive no service secrets and are removed on exit.
This improves JavaScript-page support; it does not guarantee access to blocked sites.

## Assessment and Roadmap adviser services

The active stack now includes separately scoped Assessment and Roadmap services/databases. Apply the [new required settings](../../docs/setup.md#assessment-and-roadmap-adviser) yourself before rebuilding. Their gateway routes stay on `/api/v1`; no additional service host ports are opened. `init-planning.js` creates missing scoped users without resetting existing credentials. Profile/CV/Career images now build from repository root to install the shared skill registry package. Runtime app source mounts remain `/service/app`; shared-package changes require rebuilding the images. No environment files need to be mounted in an image or test.

The all-service local profile points Career, CV, Assessment and Roadmap at the same
1.5B Ollama alias. Assessment/Roadmap receive only their own model endpoint and
HTTP-permission settings plus APP_ENV; keys remain service-scoped. HTTP is explicitly
development-only and local requests omit cloud credentials. Profile, Dashboard and
Review have no active model calls. See the setup guide for switching back to HTTPS.

## Disposable Career flow verification

Use `python infrastructure/testing/run-career-flow.py --mode both` from repository
root. It applies `compose.career-test.yaml` only to its own disposable project, uses
`--env-file /dev/null` and synthetic settings, and cleans up its volumes. The test-only
factory provides controlled empty public retrieval; fixture mode additionally serves
finite labelled SDK responses, while local mode calls `deepseek-r1:1.5b`. Never apply
this override to a normal deployment. See [Career test instructions](../../services/career-service/tests/README.md#reproduce-the-complete-career-extraction-journey).
