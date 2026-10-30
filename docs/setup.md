# Run elo locally

Use Docker Desktop, Node.js 24 and Python 3.12. The active local stack contains
NGINX, the Next.js frontend, Profile, saved CV ingestion/review, Career goal/research, Assessment, Roadmap and MongoDB. Dashboard and Review remain placeholders. See the [API overview](api/README.md) and individual service
READMEs for feature details.

## Renamed installations

The application and its defaults are now named **elo**. Python services depend on
`packages/elo-shared` (`elo_shared` imports), the frontend workspace is
`@elo/frontend`, and Compose uses project `elo-profile`. The fresh-stack MongoDB
administrator is `elo_admin`; databases are `elo_profile`, `elo_ingestion`,
`elo_career`, `elo_assessment` and `elo_roadmap`, with correspondingly named service
users (`elo_cv` for ingestion).

A rebuild does not rename or migrate an existing Docker project, database, user,
volume or saved record. Existing volumes remain intact, while the new project
creates separate volumes. If you need existing data, finish or cancel pending
operations and stop the previous stack first. Back up each service database and
the private CV uploads volume outside this repository. Have the new stack
initialize its scoped users, then restore domain collections into the matching
new databases, preserving document IDs, indexes, original files, service passwords
and `OTP_HASH_SECRET`. Do not restore old database users or replace the new admin
credentials. Copy the uploads into the new `cv_uploads` volume before serving CV
requests. Verify ownership, saved CV originals, goals and plans before retiring
any old volume. This rename does not perform that migration automatically.

Sign out before switching deployments and sign in again afterward: browser
storage keys and cross-tab events now use the `elo` prefix. Persisted IDs remain
unchanged on disk; newly created deterministic IDs use the new namespace. Do not
resume an in-flight pre-rename mutation against a migrated deployment.

Agents may maintain the public `infrastructure/docker/.env.example` template; private environment files remain untouched. Update any privately configured
old database/URI, SMTP sender label, test project variable or file path yourself.
Keep the actual Jira workspace URL unchanged; renaming the product does not move
an external Atlassian workspace.

## Configure and start

From the repository root, copy the environment example if you do not already have
`infrastructure/docker/.env`. Do not overwrite an existing file:

```sh
cp -n infrastructure/docker/.env.example infrastructure/docker/.env
```

The example uses email/password sign-in and sends OTPs to real inboxes through
Gmail SMTP. Fill in these values before starting:

| Variable | What to enter |
|---|---|
| `SMTP_USERNAME`, `SMTP_FROM` | Your Gmail sender address (use the same address for both). |
| `SMTP_PASSWORD` | That sender's Google App Password, without spaces. |
| `OTP_HASH_SECRET` | Generate once with `openssl rand -hex 32`. |
| `MONGO_ROOT_PASSWORD`, `PROFILE_DB_PASSWORD`, `CV_DB_PASSWORD`, `CAREER_DB_PASSWORD` | Generate each separately with `openssl rand -hex 24`. Preserve existing values when reusing your database. |

Keep the supplied `APP_ENV=development`, `AUTH_MODE=email`, SMTP host, port and
security values. No Google OAuth variables or Mailpit variables are needed.
Each teammate keeps their own ignored `.env` and credentials.

MongoDB data survives rebuilds in its volume. Changing an environment password
does not update database users already stored in that volume. Only the gateway
exposes a loopback port; the API and MongoDB stay private.

## Local email/password sign-in and real Gmail delivery

Registration and password reset accept 8–128-character passwords.
Only the app's outgoing sender mailbox needs SMTP configuration. A newly created
email address used to register as a user needs no SMTP setup; it just receives the
verification code. If you created a new Gmail mailbox for the app to send from,
complete the sender setup below before registration emails can be delivered.

Sign-in includes **Forgot password?**. Enter the account email, then the emailed
six-digit reset code and a new password. Codes expire in ten minutes. Resetting
preserves saved data and signs out existing sessions. The email address is required.

If email sending fails, verify your private `infrastructure/docker/.env` yourself:
Gmail requires the full sender address as `SMTP_USERNAME`, the same `SMTP_FROM`,
and a valid Google App Password as `SMTP_PASSWORD`. The literal username `elo`
is not a Gmail login. Restart/recreate Profile after changing settings. SMTP
authentication failures now report that the mail server rejected its credentials.
Other errors distinguish connection, TLS, sender and recipient rejection without
exposing provider responses or credentials. Form details remain available for retry.

Google sign-in is disabled for the current local setup. Users register with their
email address and a elo password, then verify the email with an OTP.

To use real accounts locally, edit the ignored `infrastructure/docker/.env`:

```dotenv
APP_ENV=development
AUTH_MODE=email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=YOUR_SENDER@gmail.com
SMTP_PASSWORD=YOUR_GOOGLE_APP_PASSWORD
SMTP_FROM=YOUR_SENDER@gmail.com
```

Keep your existing MongoDB passwords and `OTP_HASH_SECRET`. Fill in the values
above before rebuilding. `SMTP_FROM` should match the sender mailbox. Use the
Google App Password without its display spaces, not your normal Gmail password.
Keep credentials in this ignored file; do not paste them in chat or commit them.
Each developer supplies their own credentials.

1. Enable 2-Step Verification on the sender's Google account, then generate a
   [Google App Password](https://myaccount.google.com/apppasswords). If the option
   is unavailable, check Google's account/organisation restrictions or use
   another authenticated SMTP provider. No OAuth project, client ID, client
   secret or Gmail API is required to send these verification emails.
2. Rebuild after saving your environment settings:

   ```sh
   docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d
   docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml --profile development stop mailpit
   docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml restart gateway
   ```

Open `http://localhost:8080/register`. Enter any valid email address and a elo password.
Gmail is only the outgoing mail provider; recipients can use other providers.
The OTP goes to that registered address, not necessarily `SMTP_USERNAME`. Check
that inbox (and spam folder), verify the code, and complete initial setup. Sign in
later with the same email and elo password; no Google account popup appears.
There is no development account chooser in email mode. Switching from local-test
or Google mode invalidates sessions from that mode; existing provider-specific
records are preserved and are not automatically merged by email. An account
created through Google does not automatically acquire a password.

Mailpit is optional capture-only infrastructure, not a forwarding service. With
these settings the backend sends directly to Gmail SMTP and Mailpit is unused.
Automated tests continue using fake mail/Mailpit so they do not email real users.
No Gmail API, client secret or new Python package is needed. Gmail settings are
checked for authentication and encryption even in development.

References: [App Password requirements](https://support.google.com/mail/answer/185833),
[Gmail SMTP transport](https://developers.google.com/workspace/gmail/imap/imap-smtp).

## Production email/password

Set `APP_ENV=production`, keep `AUTH_MODE=email`, and configure:

| Variable | What to supply |
|---|---|
| `AUTH_MODE` | `email` for email/password sign-in. |
| `SMTP_HOST`, `SMTP_PORT` | Your mail provider's SMTP hostname and port. |
| `SMTP_SECURITY` | `starttls` (commonly port 587) or `ssl` (commonly 465). |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Provider-issued SMTP credentials, server-side only. |
| `SMTP_FROM` | A sender address authorised by your provider. |
| `OTP_HASH_SECRET` | A random server-only key of at least 32 characters. |

Use the SMTP settings from your chosen provider; no particular paid provider or
API key is required by the code. A real mailbox delivery test needs those settings.
Production rejects plaintext/development SMTP and incomplete configuration.

Sessions last 24 hours and survive same-tab reload in sessionStorage after server
validation. Sign-out/account changes clear other tabs, which require explicit
sign-in. Deploy behind HTTPS; the local Compose file is a development deployment,
not a complete public production hosting configuration. School lookups still need
no API key or download.

## Career goal and CV confirmation

Career supports temporary text/URL/PDF/DOCX/TXT previews without model calls or persisted raw sources. Explicit JD extraction and conversational discovery use configured Gemini/Brave and save structured canonical goals/research. The current goal and chat appear at `/career-goal`; successful goal saves are automatic, while a new JD preserves the old goal until validated replacement. Provider failures retain saved progress. See the [Career service](../services/career-service/README.md).

Before using that goal for target-relevant CV clarification, review the saved goal and explicitly confirm its current revision for CV review. Career stores acknowledgement of the exact goal ID/version/selection, not a second target record. Editing or replacing the goal requires confirmation again. Previously saved CV answers remain source-bound. Old reviewed-target snapshots are retained historical data rather than another active selection screen.

Career accesses CV only through its owner-authenticated API. The internal projection preserves original source identities and uncertainty, with a separate 512 KiB intake limit. Oversized data produces an actionable error without truncation; CV review itself remains available. This is not skill mastery or an assessment computation. Private preview buffers use bounded tmpfs; canonical goals/research use the scoped Career database.

## Saved CV upload and review

Open `/cv` after signing in and completing initial setup. CV records are stored
in `elo_ingestion`; manual capability declarations stay with the existing
Profile account. Uploading a file never changes the selected CV. Choose a ready
CV explicitly before using its versioned capability input.

The Compose file uses a 10 MiB file limit and an 11 MiB gateway request limit
to allow multipart overhead. PDF/DOCX parsing is bounded; OCR is not included.
Originals use the private `cv_uploads` volume for the documented retry window.
Only structured extraction and bounded evidence are saved in MongoDB.

Configure `CV_LLM_MODEL` and `CV_LLM_API_KEY` yourself in private settings to enable structured extraction, text routing and clarification-answer interpretation.
`CV_LLM_BASE_URL` defaults to
`https://api.groq.com/openai/v1`. Choose a model supporting JSON object output;
the server validates the schema and cited evidence before publication. Keys
stay on the server. Missing configuration is an actionable processing error,
never a synthetic successful extraction. No provider calls are needed for
automated tests. See [Groq compatibility](https://console.groq.com/docs/openai)
and [structured output modes](https://console.groq.com/docs/structured-outputs).

CV obtains the current canonical goal projection through Career using the same owner session, after explicit confirmation of its exact goal/version/selection revision. Compose supplies `CAREER_SERVICE_URL=http://career-service:8000`; set it
explicitly for direct service runs. On the CV screen, start a guided chat review, answer naturally or skip; detailed evidence and direct review controls remain in the summary. The raw answer is saved before interpretation.
Supported changes appear against the relevant source, including personal/team
attribution, assistance, explicit skill details and optional partial dates. A failed
interpretation leaves the answer available for retry; a saved answer alone does
not mean the uncertainty is resolved. Reload restores answers and skips. Changing or replacing the confirmed goal updates relevance without deleting those source facts or repeating resolved
questions. No confirmed current goal defers preparation; an unavailable service shows a retry.
Reprocessing or explicitly comparing a replacement can require a source-by-source
review before applying a candidate. Manual capability links report changed or
removed sources and can be explicitly relinked or detached without losing the
declaration. The target-bound analysis input checks current revisions and requires
the future consumer to revalidate them. Assessment admission, gap analysis,
saved-result staleness and roadmap generation remain unimplemented. See the
[CV specification](../services/cv-service/SPEC.md).

## Stop without deleting data

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml down
```

MongoDB 8 requires a compatible kernel. Do not treat a local startup compatibility failure as an application test pass or silently bypass the server's guard. CI's MongoDB jobs use the compatible pinned runner; local MongoDB 7 functional checks are reported separately.
See [testing](testing.md) for automated checks and disposable test stacks.

## Gemini reasoning configuration

All Career model stages default to `gemini-3.5-flash-lite` through Google's OpenAI-compatible
endpoint: JD extraction, skills, discovery, research, summaries, chat and goal edits.
Set these server-only values in `infrastructure/docker/.env` yourself. Rename the previous model-variable entry to `CAREER_LLM_MODEL`, preserving your selected model value; only this new model-variable name is read:

```dotenv
AI_ENABLED=true
CAREER_LLM_MODEL=gemini-3.5-flash-lite
CAREER_LLM_API_KEY=YOUR_PRIVATE_GEMINI_KEY
CAREER_RESEARCH_API_KEY=YOUR_PRIVATE_BRAVE_KEY
```

The old `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY`, `AI_RESPONSE_MODE`,
`AI_TOKEN_PARAMETER`, `GEMINI_ENABLED`, `GEMINI_MODEL` and
`OPPORTUNITY_GEMINI_MODEL` values are no longer used by production reasoning.
JSON Schema and backend citation,
provenance and ownership validation preserve the current data models.
The default is [Gemini 3.5 Flash Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
using the explicit `gemini-3.5-flash-lite` model ID for all stages. An existing
`CAREER_LLM_MODEL` value overrides the default: change it to the Lite ID
and recreate the Career container when switching from another model.
If Google reports model access/NOT_FOUND, set `CAREER_LLM_MODEL` to an accessible
Gemini model ID. The same setting applies to every reasoning and coordination stage;
legacy `GEMINI_MODEL` and `AI_MODEL` do not override it.

A `provider_configuration` response previously hid Google's numeric error/status/details.
The adapter now returns safe `provider_error` metadata (provider, HTTP status, known
machine code and rejected field names) without provider prose or submitted content.
`API_KEY_INVALID` maps to `provider_auth`, `NOT_FOUND` to `model_unavailable`,
project preconditions to `provider_access`, and known rejected schema/parameter names
to `provider_schema` / `provider_parameter`. An unknown rejection remains
`provider_configuration`; inspect its safe metadata rather than assuming a token limit.
No schema-free fallback or provider change is attempted.

The public [Docker example](../infrastructure/docker/.env.example) contains only
active stack inputs, including email/auth, database passwords, Career model/research
credentials and limits, and CV model/upload/usage settings.
Preserve existing database passwords and private keys; do not overwrite a working
private configuration with blank template values. The template lists supported optional tuning defaults; fixed internal wiring remains in Compose.

Keep `AI_ENABLED=false` if you only need current previews. No credentials are
needed for automated AI tests. Only Career receives the key; never prefix it
`NEXT_PUBLIC_` or commit it. The service's
[contract guide](../services/career-service/ANALYSIS_CONTRACTS.md) explains response
modes and limits. Recreate Career after editing settings (rebuild as well only if its image code changed):

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up -d --force-recreate --no-deps career-service
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml restart gateway
```

SCRUM-310 defines the models; J08/J09 now connect Career persistence and CV reads
using separate service credentials. See the setup section below. Profile data is unchanged.

## J08/J09 database setup

Add two new **different** random passwords to your ignored infrastructure `.env`
(generate each with `openssl rand -hex 24`):

```dotenv
CAREER_DB_PASSWORD=YOUR_NEW_RANDOM_PASSWORD
CV_DB_PASSWORD=ANOTHER_NEW_RANDOM_PASSWORD
```

Keep existing MongoDB/SMTP/OTP credentials. Compose runs `mongodb-career-init` to
create missing Career and CV database users on new **or existing** volumes. It
verifies existing credentials and never resets passwords or removes data. Do not
use `down -v` to apply this change. Rebuild the whole stack because CV reads and
gateway routing are now included:

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml restart gateway
```

For Career interpretation/research, configure `AI_ENABLED`, `CAREER_LLM_API_KEY` and `CAREER_RESEARCH_API_KEY` yourself. Without those settings, temporary import previews and saved reads remain available; model-backed extraction, discovery and research report their unavailable state. Use the implemented Resume & Tracker upload/review for durable CV context, or deliberately continue Career without a CV. Temporary Career attachments are not durable CV extraction. Structured goals save through the canonical workspace; explicit CV confirmation does not claim job readiness or completed analysis.

## Docker hot reload

Use the opt-in [development Compose override](../infrastructure/docker/README.md#hot-reload-during-development)
for Next.js Fast Refresh and Python API reload without rebuilding for source edits.
It keeps the base production-style configuration available and retains MongoDB data.
Run the startup commands yourself with your private settings; agents must not load
or inspect your environment files. Dependencies/image changes still need rebuilding.


## Career LangGraph and research

Rebuild the Career image once after installing the new LangGraph/checkpointer/tokenizer dependencies. Subsequent source edits use the existing Docker hot reload setup. No LangSmith account or additional database server is required.

Use `AI_ENABLED=true`, `CAREER_LLM_API_KEY` and `CAREER_RESEARCH_API_KEY`. Chat output stays
bounded at 1,024 tokens, interview synthesis at 2,048 and JD extraction at 4,096;
`AI_MAX_OUTPUT_TOKENS` remains the overall ceiling. `AI_TIMEOUT_SECONDS`,
`AI_RETRIES` and `AI_CONTEXT_TOKENS` retain their task limits. Production imposes no local token-per-minute admission limit; provider quotas and bounded requests still apply.
Google/Brave HTTP 429 responses still pause unfinished work using the provider's
retry delay. Saved goals and completed research steps survive a wait.

Every Brave retrieval uses `/llm/context` with the fuller-content parameters in the
[Career contract](../services/career-service/ANALYSIS_CONTRACTS.md).
All model stages, including public query planning and usefulness assessment, use
Gemini 3.5 Flash Lite. Research keeps the six-query/three-useful-source bound and exact
citation checks; no Google grounding or additional credential is introduced.
Rebuild/recreate Career after applying these code/configuration changes.

### Opportunity Intelligence

The saved goal researches interviews, internship experience and company context
using Gemini 3.5 Flash Lite for both coordination and reasoning, plus Brave LLM Context.
`OPPORTUNITY_ENABLED=true` enables this research when the Gemini/Brave credentials
and Career storage are available. All model stages share the configured Gemini client. Existing JSON fields and immutable saved models are retained.
Explicit guidance maps evidence into each allowed field; missing evidence stays missing.

Compose passes `OPPORTUNITY_ENABLED` (true), max searches (2), follow-ups (1),
concurrency (3), HTTP timeout (30s), transient retries (1), schema repairs (1),
evidence tokens (8192), freshness (168h), incomplete freshness (1h) and worker
deadline (300s). See the [complete settings/API/graph contract](../services/career-service/OPPORTUNITY_INTELLIGENCE.md).
MongoDB indexes/job recovery are automatic. Existing goals/research need no destructive
migration. Paid provider access and live response quality require your own setup;
normal tests use synthetic data/providers.
If research is unavailable, its API/UI reports the specific disabled or missing
capability rather than a generic request to configure all keys. Rebuild/recreate
Career and the frontend to apply source changes in production-style Docker;
restarting an existing image alone does not install edited code.

### Conversational career discovery

The existing Gemini/Brave keys also support the new discovery route.
Optional `DISCOVERY_*` sample/freshness limits and rebuild instructions are described
in [Career Discovery](../services/career-service/CAREER_DISCOVERY.md). Rebuild both
Career and frontend after source changes; production containers do not mount source.

## Session and verification boundaries

There is no new five-minute inactivity lock. Recoverable session checks preserve drafts; actual expiry/revocation, sign-out and account changes clear private state. Browser reload/discard and confirmed navigation can lose unsent React-memory drafts. CV history is saved on the server, separately from unsent text.

Startup/configuration commands in this guide are for the user to run with private settings. Agents may read/edit the public `infrastructure/docker/.env.example` template and validate it against Compose. Agents must not read or load private environment files. Automated verification uses isolated resources and explicit synthetic settings. Existing recordings from before an integration demonstrate that earlier build, not the newly merged application.

Career key migration: rename `GEMINI_API_KEY` to `CAREER_LLM_API_KEY` and
`BRAVE_API_KEY` to `CAREER_RESEARCH_API_KEY` yourself in private settings, preserving
their values. Legacy names are fallback aliases only when new names are absent; an
explicitly blank new key takes precedence. The key rename does not change providers
or the existing `CAREER_LLM_MODEL` setting. CV uses its separate `CV_LLM_*`
settings from the same infrastructure configuration.

## Assessment and Roadmap adviser

All user-configurable deployment inputs belong in the single ignored `infrastructure/docker/.env` file. The public [`infrastructure/docker/.env.example`](../infrastructure/docker/.env.example) documents them, including the new Assessment and Roadmap settings below. If you already have a private `.env`, add only the missing entries yourself; do not overwrite it by copying the template again. No additional environment file is needed in either service folder.

| Variable | Purpose |
|---|---|
| `ASSESSMENT_DB_PASSWORD` | New scoped `elo_assessment` MongoDB user/database |
| `ROADMAP_DB_PASSWORD` | New scoped `elo_roadmap` MongoDB user/database |
| `ASSESSMENT_LLM_API_KEY` | Server-only Gemini credential for evidence comparison |
| `ROADMAP_LLM_API_KEY` | Server-only Gemini credential for adviser recommendations |
| `ASSESSMENT_LLM_MODEL`, `ROADMAP_LLM_MODEL` | Optional independent model identifiers; both default to `gemini-3.5-flash-lite` |

Generate only the new database passwords locally, then paste the printed lines into `infrastructure/docker/.env`:

```sh
for setting in ASSESSMENT_DB_PASSWORD ROADMAP_DB_PASSWORD; do
  printf '%s=%s\n' "$setting" "$(openssl rand -hex 24)"
done
```

Keep passwords already associated with existing database users. The LLM keys come from your Gemini provider account. Add them and the model settings to the same private file:

```dotenv
ASSESSMENT_LLM_API_KEY=YOUR_GEMINI_API_KEY
ASSESSMENT_LLM_MODEL=gemini-3.5-flash-lite
ROADMAP_LLM_API_KEY=YOUR_GEMINI_API_KEY
ROADMAP_LLM_MODEL=gemini-3.5-flash-lite
```

For a completely fresh installation only, generate each of `MONGO_ROOT_PASSWORD`, `PROFILE_DB_PASSWORD`, `CAREER_DB_PASSWORD` and `CV_DB_PASSWORD` separately with `openssl rand -hex 24`, and generate `OTP_HASH_SECRET` once with `openssl rand -hex 32`. Never regenerate these merely to rebuild an existing stack.

The model credential may be the same provider key applied explicitly to both service settings. Neither service borrows Career's credential implicitly. Empty model settings leave saved data readable with a clear unavailable-adviser state. Use strong distinct database passwords compatible with the existing Compose Mongo URI interpolation (URI-safe characters). The planning initializer creates missing users and checks existing credentials without resetting them. Preserve credentials for existing database users.

Rebuild using the existing Compose workflow after applying configuration. Profile/CV/Career Docker build contexts now use the repository root so all install the same `packages/elo-shared` registry package. New services expose no host ports and access foreign data only through owner-authenticated APIs. Do not rebuild the user's running stack as part of a test. Shared package or dependency changes require image rebuilds.

For direct Python development, install `packages/elo-shared` before installing a service. Assessment and Roadmap each use their own `MONGODB_URI`/`MONGODB_DATABASE`; defaults are `elo_assessment` and `elo_roadmap`. Internal URLs are `PROFILE_SERVICE_URL`, `CV_SERVICE_URL`, `CAREER_SERVICE_URL` and `ASSESSMENT_SERVICE_URL`. The gateway exposes `/api/v1/assessments` and `/api/v1/roadmaps`; the UI stays at `/roadmap`.

Older extracted goals will not gain job dates automatically because their raw JDs are not retained. The adviser can discuss a user-selected preparation target; a new JD extraction can capture sourced application/interview/start wording. Existing CV skill keys and manual attachments are preserved. A null new canonical ID means unresolved mapping, not missing capability.
