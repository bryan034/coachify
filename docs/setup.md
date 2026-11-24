# Run elo locally

Use Docker Desktop, Node.js 24 and Python 3.12. The active local stack contains
NGINX, the Next.js frontend, Profile, saved CV ingestion/review, Career goal/research, Assessment, Roadmap, Jobs and MongoDB. Dashboard and Review remain placeholders. See the [API overview](api/README.md) and individual service
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

## Career stored-shape upgrade

Career no longer reads records saved in older shapes. Existing installations run a
one-off upgrade once, right after deploying this Career image and before users
continue. It drops the retired `(user_id, create_key)` goal index (until then, saving
a second goal can fail where that index exists) and removes the unused `create_key`
and review `baseline` fields. It also removes stored Discovery introductions, folds
old `broad_exploration`/`industry` answers into current fields, and makes each
account's latest earlier Discovery chat active. Finally it clears version 1
Opportunity reports so the next request researches again, flags reports whose
overall summary failed, completes unfinished three-category research jobs, and
removes links to unverified question research. Historical target documents are kept.

```sh
source infrastructure/docker/dev-shell.sh
dc exec career-service python -m app.workers.upgrade_stored_shapes          # dry run: counts per step
dc exec career-service python -m app.workers.upgrade_stored_shapes --apply  # rewrite
```

The upgrade is idempotent; a second `--apply` reports zero records. Back up
`elo_career` first if the data matters.

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
security values. Leave the Google OAuth settings blank.
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

Profile sends account email directly through Gmail SMTP and requires authentication
and encryption in development. Full-stack browser tests send OTPs to aliases of a
[dedicated Gmail test inbox](testing.md#real-mongodb-and-full-stack-checks).

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

Sessions last 24 hours. Credentials use HttpOnly, SameSite=Strict cookies, Secure
in production; only a public tab marker survives reload in sessionStorage after
server validation. Deploy the frontend, Profile and gateway together for the cookie
transport upgrade, reload NGINX, and sign in again. No database migration is needed.
Sign-out/account changes clear other tabs, which require explicit sign-in. Deploy behind HTTPS; the local Compose file is a development deployment,
not a complete public production hosting configuration. School lookups still need
no API key or download.

## Career goal and CV confirmation

Career supports temporary text/URL/PDF/DOCX/TXT previews without model calls or persisted raw sources. Explicit JD extraction and conversational discovery use the configured model and separate public-research provider and save structured canonical goals/research. The current goal and chat appear at `/career-goal`; successful goal saves are automatic, while a new JD preserves the old goal until validated replacement. Provider failures retain saved progress. See the [Career service](../services/career-service/README.md).

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

Configure the model and key using [OpenRouter setup](#career-model-and-search-configuration) to enable structured extraction, text routing and clarification-answer interpretation. The public template configures `CV_LLM_BASE_URL` for OpenRouter and `CV_LLM_MODEL` from the shared model setting. `CV_LLM_RESPONSE_MODE=json_schema` requests schema-constrained extraction and repair; selected providers/models must support it. A durable LangGraph validates output and allows one repair before reporting failure. Chat and clarification interpretation retain JSON-object output. The server validates schema, string lengths, dates and cited evidence before publication; constrained decoding does not guarantee semantic correctness. See the [CV harness](../services/cv-service/SPEC.md#extraction-runtime-harness). Missing model configuration is a processing error, never a synthetic successful extraction. Automated tests do not call providers.

### CV extraction configuration troubleshooting

CV upload shows progress, then displays classified results when `ready`.
Review CV explicitly starts guided questions; they are optional for displaying
extracted information.

For OpenRouter, use `https://openrouter.ai/api/v1` for all four model endpoints
and select your model or preset, for example `@preset/your-preset-slug`.
Each service uses its non-empty
`*_LLM_API_KEY` first, otherwise `OPENROUTER_API_KEY` for the exact OpenRouter
HTTPS host. Clear obsolete service-specific keys when using the shared key.
Compose supplies this fallback, and direct processes use the same host-restricted
fallback in the shared model adapter. Compose expands `${OPENROUTER_MODEL}`;
direct service processes need each resolved `*_LLM_MODEL` value. See the full
[OpenRouter configuration](#career-model-and-search-configuration).

`not_configured` is reported before a provider request. The service process needs
`CV_LLM_MODEL` and a usable key; it does not load `.env` files automatically.
`GET /api/v1/cv/policy` reports `extraction_configured` without returning a
credential. This confirms settings are present, not provider access or schema
compatibility.

For a managed cloud environment, bind the model key securely and allow its
selected provider host. A secret restricted to another host needs its allowed destination changed to
`openrouter.ai` in environment settings. Changing only
`CV_LLM_BASE_URL` does not update a secret's destination restriction. Apply the
settings and restart the service; extraction, routing and interpretation read
configuration at startup. For Compose, recreate the service as shown below.

Cloud model requests use the process's proxy and CA settings with TLS
verification enabled. Diagnose `connection_error` separately from absent
configuration, provider credential rejections and schema/evidence failures.
After resolving
the cause, retry the saved upload and poll its operation until `ready`;
HTTP 202 means saved for processing, not extracted.

After changing private configuration, recreate the CV container with
`docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up -d --build --no-deps --force-recreate cv-service`
from the repository root with the supporting stack already running.

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

### MongoDB image compatibility

The stack and CI use `mongo:8.2`. MongoDB 8.3 refuses startup on some Docker Desktop hosts with Linux kernels 6.19 and newer (SERVER-121912). Existing installations that still have an 8.2 data volume can reuse that volume and their stored credentials.

For a volume already upgraded to 8.3, verify MongoDB’s downgrade requirements or restore a verified, 8.2-compatible backup from before the upgrade to a separate volume before running 8.2. Keep backups outside Git. [MongoDB downgrade procedure](https://www.mongodb.com/docs/manual/release-notes/8.3-downgrade/)

MongoDB 8.2 reached vendor end of life on 31 July 2026. A future version change should verify host-kernel compatibility and the data upgrade path before deployment. [MongoDB lifecycle](https://www.mongodb.com/legal/support-policy/lifecycles)
See [testing](testing.md) for automated checks and disposable test stacks.

## Career model and search configuration

Career uses one OpenAI-compatible model for extraction, discovery, research planning,
chat, summaries and edits. Model inference and public search are configured independently.
Apply the following settings yourself in the existing private `infrastructure/docker/.env`,
preserving other settings and credentials. Agents do not read or edit that file.

The public template selects OpenRouter through the OpenAI-compatible API for Career, CV, Assessment and Roadmap. Their shared key remains server-side. Career's public search defaults to OpenRouter model-native web search (`CAREER_RESEARCH_PROVIDER=openrouter`), with Brave LLM Context as a fallback that uses its own `CAREER_RESEARCH_API_KEY`.

For a new installation, copy the public template as described above and privately fill `OPENROUTER_API_KEY`. For an existing installation, edit the existing private `infrastructure/docker/.env` yourself rather than copying over its database passwords or other settings. Set the following entries, replacing existing entries of the same names instead of adding duplicates:

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini
AI_ENABLED=true
CAREER_LLM_BASE_URL=https://openrouter.ai/api/v1
CAREER_LLM_MODEL=${OPENROUTER_MODEL}
CAREER_LLM_RESPONSE_MODE=json_schema_strict
CAREER_LLM_TOKEN_PARAMETER=max_tokens
CV_LLM_BASE_URL=https://openrouter.ai/api/v1
CV_LLM_MODEL=${OPENROUTER_MODEL}
CV_LLM_RESPONSE_MODE=json_schema
CV_LLM_ALLOW_HTTP=false
ASSESSMENT_LLM_BASE_URL=https://openrouter.ai/api/v1
ASSESSMENT_LLM_MODEL=${OPENROUTER_MODEL}
ASSESSMENT_LLM_TOKEN_PARAMETER=max_tokens
ASSESSMENT_LLM_ALLOW_HTTP=false
ROADMAP_LLM_BASE_URL=https://openrouter.ai/api/v1
ROADMAP_LLM_MODEL=${OPENROUTER_MODEL}
ROADMAP_LLM_TOKEN_PARAMETER=max_tokens
ROADMAP_LLM_ALLOW_HTTP=false
```

Enter your OpenRouter key only in the private file. With `AI_ENABLED=true`, Career requires a configured model key to start; until you add the key, set `AI_ENABLED=false` if you need to start Career without model inference. Clear any existing `CAREER_LLM_API_KEY`, `CV_LLM_API_KEY`, `ASSESSMENT_LLM_API_KEY`, and `ROADMAP_LLM_API_KEY` values when you want the shared key: a non-empty service-specific key takes precedence and would otherwise be sent to OpenRouter. Shared-key fallback is restricted to HTTPS `openrouter.ai` on the default port or port 443; it is never sent to another endpoint. A service can still use its own key with another configured provider. Direct Python processes use their individual model/base settings; the `OPENROUTER_MODEL` interpolation shown above is provided by Compose, not by Python environment readers.

The sample model is a starting point, not a guarantee of output quality or availability. To switch models from the OpenRouter dashboard, create an [OpenRouter preset](https://openrouter.ai/blog/tutorials/presets/) and set `OPENROUTER_MODEL=@preset/your-preset-slug` in the private file, then recreate the services once. Subsequent changes to that preset can select a different model without changing the application configuration. If you instead use a fixed model ID, change the setting and recreate the services to switch. Service-specific model values can override the shared selection. Request-level settings may override corresponding preset options. Select models/providers that support the JSON response modes used by the services; `CV_LLM_RESPONSE_MODE=json_object` is an explicit compatibility opt-out when schema decoding is unavailable. Domain validation and bounded retries still apply. Live model quality is not established by synthetic tests.

The sample `openai/gpt-4o-mini` has a [16,384-token output limit](https://openrouter.ai/openai/gpt-4o-mini?tab=parameters), while Roadmap generation requests up to 24,000 tokens. Compatibility with that request has not been verified against OpenRouter; the provider could reject or truncate it. Choose a compatible model for Roadmap if needed. No provider call was made to test this setting.

Configure [OpenRouter BYOK routing](https://openrouter.ai/docs/guides/overview/auth/byok) in your OpenRouter account if you want to use your own provider keys. OpenRouter can otherwise fall back to shared capacity and charge credits, depending on account and provider routing settings. Restrict other providers as needed if you intend to use only your own keys.

After updating private settings, build and recreate the four services using your normal Compose files, then restart the gateway. A container restart alone does not apply new environment values. Shared-package changes require rebuilding the images. With the supporting stack already running, use these commands from the repository root (add the development override if you normally use it):

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d --no-deps career-service cv-service assessment-service roadmap-service
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml restart gateway
```

Existing deployments retain their configured providers until their private settings are updated; without the public template, Compose falls back to OpenRouter (`https://openrouter.ai/api/v1`, `openai/gpt-4o-mini`) and requires `OPENROUTER_API_KEY` or a service key.

Keep `AI_ENABLED=true` for Career inference and configure public search independently. SDK retries are disabled; each service retains its own retry, quota, timeout and validation policy.

Career, CV, Assessment and Roadmap share a per-account allowance of 250 cloud model calls per UTC day. Each dispatch, including provider and validation retries, reserves one call for the account. Failed or timed-out attempts consume the reservation. Disabled models do not consume the allowance. Set `MODEL_BUDGET_OWNER_CALLS_PER_DAY` in `infrastructure/docker/.env` to override the Compose default (0 stops cloud calls). Compose supplies the default when the variable is absent or empty. The public `.env.example` documents optional settings and is not loaded into existing private files. Legacy unit-budget and deployment-wide quota variables can be removed from private files. `CAREER_RESEARCH_SEARCHES_PER_ACCOUNT_PER_DAY` caps public searches per account per UTC day (template 80, blank = unlimited; a Brave fallback is part of the same search); a reached allowance pauses research workflows until the next UTC day (rechecked hourly) and is reported immediately in chat, with saved results still available. `CAREER_RESEARCH_MAX_URLS_PER_SEARCH` (1–6) lowers the number of source URLs kept per search; blank keeps the built-in 6/5/3 limits for goal research and chat, Discovery and Opportunity Intelligence.

The counters contain hashed account IDs and reside on the `model_budget` named volume. Keep this volume mounted across restarts and replicas on the same Docker host. Enforcing one per-account allowance across independent hosts requires a coordinated ledger. Provider billing depends on the selected model and its prices. For a direct service run, point `MODEL_BUDGET_PATH` at the same writable SQLite file for all four processes.


Career uses the OpenAI Python SDK for Chat Completions over HTTPS. Every stage defaults
to strict JSON Schema, generated from the existing Pydantic output models. Backend
validation still checks evidence, provenance and allowed references. To swap models,
set base URL, model, response mode and token parameter together. Providers without
native schema support can select `json_object`, which requires validation/repair;
Career Discovery requires `json_schema_strict` and reports `unsupported_structured_output`
otherwise. Select `CAREER_LLM_TOKEN_PARAMETER=max_completion_tokens` for models
requiring that parameter. SDK retries are disabled; the existing workflow owns
retries, deadlines and cooldowns. Requests use `AI_TIMEOUT_SECONDS=60` (maximum 60).
No model credentials reach the frontend.

JD input allows 8,000 characters. Every model stage keeps its own completion safety
cap (for example identification 4,096 and extraction 8,192 tokens);
`AI_MAX_OUTPUT_TOKENS` is blank by default and, when set, can only lower those caps.
`AI_CONTEXT_TOKENS` is blank by default: the full request goes to the provider, which
enforces its own context window. A `length` finish means the output ceiling
was reached; increasing the HTTP timeout alone does not increase that ceiling. When
`AI_CONTEXT_TOKENS` is set, the code measures the full provider prompt, including
instructions/schema/repair feedback, in estimated tokens and reserves output plus a
10% context margin (minimum 1,024). Requests that do not fit fail rather than
silently losing source text.

The gateway permits 610 seconds of upstream inactivity for model-backed Career routes.
For model work, prefer `Prefer: respond-async` and operation polling (as the application
UI does), especially when requests queue. Preview/import timeouts remain unchanged.
Recreate Career to apply environment changes; reload/restart the gateway to apply its
updated mounted NGINX config. Do not recreate databases or delete volumes.

Profile, Dashboard and Review do not currently call an LLM. Rebuild/recreate
`career-service`, `cv-service`, `assessment-service` and `roadmap-service` after
changing model settings. The `*_LLM_ALLOW_HTTP` flags exist only for synthetic
fixture providers in disposable development stacks; they require `APP_ENV=development`
and must not be used as a production shortcut.

`CAREER_RESEARCH_PROVIDER=openrouter` (template default) sends one bounded Chat
Completions request per search to `CAREER_RESEARCH_MODEL` (default
`openai/gpt-4.1-mini`) with the `openrouter:web_search` server tool on engine
`native`, so the model's provider runs its own web search. With an OpenRouter BYOK
key, the provider bills that search to the linked account. The model must support
native search (OpenAI: GPT-4.1 family, GPT-5 and later, o3, o4-mini); OpenRouter
substitutes Exa for older models such as `gpt-4o-mini`. The key is
`CAREER_LLM_API_KEY` when Career's model endpoint is OpenRouter, otherwise
`OPENROUTER_API_KEY`. `CAREER_RESEARCH_MAX_TOOL_CALLS` (1–10, default 3) bounds
server-side tool steps and `CAREER_RESEARCH_TIMEOUT_SECONDS` (5–20, default 15)
is a total deadline for the request. One search, fallback included, finishes within
28 seconds, below Discovery's 30-second per-search limit. Only cited `url_citation` annotations become sources: the
provider's excerpt when returned, otherwise the model's cited answer line, prefixed
"Search model summary of this page, not a quote:" so synthesis and readers do not
take it as page text. OpenRouter results use their own cache policy, so switching
provider does not serve research cached under the other backend. Native search returns few
structured job-posting fields, so Discovery identifies employers less often than
with Brave.

`CAREER_RESEARCH_FALLBACK_PROVIDER=brave` retries the same search with Brave when
OpenRouter returns HTTP 429/402/401/403/5xx, times out, returns an unreadable
response or no cited sources. It needs `CAREER_RESEARCH_API_KEY`; leave either
blank to disable it. With no OpenRouter key, searches go straight to Brave without
logging a fallback. Fallbacks log only a fixed reason code and are not charged as
a second search. `CAREER_RESEARCH_PROVIDER=brave` uses only the existing
`GET /res/v1/llm/context` API. Only returned page snippets are accepted as
evidence. Saved-goal question queries stay within 128 characters while retaining
their public context/focus. Response size, source counts, URL validation, retries
and citation checks remain bounded. Search results are untrusted. No raw JD, private
CV or chat message is sent to search.

Career defaults to OpenRouter (`CAREER_LLM_BASE_URL=https://openrouter.ai/api/v1`, `CAREER_LLM_RESPONSE_MODE=json_schema_strict`). Explicit nonblank model values override
the default, so update the model as well when switching providers.
Direct non-Compose processes may use the deprecated `BRAVE_API_KEY` alias
only for Brave when the canonical key is absent. Compose requires
the canonical `CAREER_*` keys; rename old private entries yourself before recreating
Career. This prevents a provider switch from forwarding another provider's key.
The old `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY`, `AI_RESPONSE_MODE`,
`AI_TOKEN_PARAMETER`, and the obsolete `GEMINI_*` switches
settings remain unused. Assessment, Roadmap and CV retain their independent model settings.

Saved-goal follow-up questions may research automatically when public information is
missing or needs current verification. The router extracts a concise public search
subject, combined with the saved employer/role/location. Empty/irrelevant results or
a model `not_found` answer allow up to three distinct searches in the same turn,
stopping after a supported answer. Cited exact passages append to the existing
owner/version-linked `question_research` JSON; unrelated pages and generated answers
are not saved as evidence. Empty results after this bounded search remain unknown.
Retries of invalid answer formatting reuse the retrieved evidence. Unrelated tasks,
ambiguous questions and goal edits never trigger this automatic search path.

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

For Career interpretation/research, configure `AI_ENABLED`, an OpenRouter key or `CAREER_LLM_API_KEY`, and the separate `CAREER_RESEARCH_API_KEY` yourself. Without those settings, temporary import previews and saved reads remain available; model-backed extraction, discovery and research report their unavailable state. Use the implemented Resume & Tracker upload/review for durable CV context, or deliberately continue Career without a CV. Temporary Career attachments are not durable CV extraction. Structured goals save through the canonical workspace; explicit CV confirmation does not claim job readiness or completed analysis.

## Start afresh (development only)

With the development override (`dc`), every workspace page shows a **Development** strip with a **Start afresh** button. After confirmation it calls `POST /api/v1/<prefix>/dev/reset` on the Career, CV, Assessment, Roadmap, Jobs and Profile services. These delete the signed-in account's goal and chats, CVs and uploaded files, assessments, roadmaps, job applications, and manual skills. The account, session, onboarding answers and shared job postings stay. The routes exist only when `APP_ENV=development` (set by `compose.dev.yaml`), are not in the OpenAPI contracts, and return 404 otherwise. In-flight background work is not cancelled.

The CV reset also releases the account's saved-CV and original-file quota reservations after removing the files. It repairs stale reservations from earlier resets even when the saved-CV list is already empty. Other accounts' reservations remain unchanged. If file cleanup fails, reset returns an error and keeps the affected capacity charged; retry **Start afresh** to finish cleanup.

## Docker hot reload

Use the opt-in [development Compose override](../infrastructure/docker/README.md#hot-reload-during-development)
for Next.js Fast Refresh and Python API reload without rebuilding for source edits.
It keeps the base production-style configuration available and retains MongoDB data.
Run the startup commands yourself with your private settings; agents must not load
or inspect your environment files. Dependencies/image changes still need rebuilding.


## Career LangGraph and research

Rebuild the Career image once after installing the new LangGraph/checkpointer/tokenizer dependencies. Subsequent source edits use the existing Docker hot reload setup. No LangSmith account or additional database server is required.

Use `AI_ENABLED=true`, a configured OpenRouter key or `CAREER_LLM_API_KEY`, and the separate `CAREER_RESEARCH_API_KEY`. Chat
output is bounded at 1,024 tokens, interview synthesis at 2,048 and JD extraction at
4,096; a set `AI_MAX_OUTPUT_TOKENS` can only lower these caps. `AI_TIMEOUT_SECONDS` and `AI_RETRIES` retain their task
limits; a blank `AI_CONTEXT_TOKENS` sends requests whole. Production imposes no local token-per-minute admission limit; provider quotas and bounded requests still apply.
Model/search provider HTTP 429 responses still pause unfinished work using the provider's
retry delay. Saved goals and completed research steps survive a wait.

Every Brave retrieval uses `/llm/context` with the fuller-content parameters in the
[Career contract](../services/career-service/ANALYSIS_CONTRACTS.md).
All model stages, including public query planning and usefulness assessment, use
the configured Career model. Research keeps the six-query/three-useful-source bound and exact
citation checks; no Google grounding or additional credential is introduced.
Rebuild/recreate Career after applying these code/configuration changes.

### Opportunity Intelligence

The saved goal researches interviews, internship experience and company context
using the configured Career model for coordination and reasoning and the selected public-research provider.
`OPPORTUNITY_ENABLED=true` enables this research when model and research credentials
and Career storage are available. All model stages share the configured Career client. Existing JSON fields and immutable saved models are retained.
Explicit guidance maps evidence into each allowed field; missing evidence stays missing.

Compose passes `OPPORTUNITY_ENABLED` (true), gap searches per topic (2), searches per run (25),
concurrency (3), HTTP timeout (30s), transient retries (1), schema repairs (1),
evidence tokens (blank sends every passage), freshness (168h), incomplete freshness (1h) and worker
deadline (300s). See the [complete settings/API/graph contract](../services/career-service/OPPORTUNITY_INTELLIGENCE.md).
MongoDB indexes/job recovery are automatic. Existing goals/research need no destructive
migration. Paid provider access and live response quality require your own setup;
normal tests use synthetic data/providers.
If research is unavailable, its API/UI reports the specific disabled or missing
capability rather than a generic request to configure all keys. Rebuild/recreate
Career and the frontend to apply source changes in production-style Docker;
restarting an existing image alone does not install edited code.

### Conversational career discovery

The configured Career model and research credentials also support the discovery route.
Optional `DISCOVERY_*` sample/freshness limits and rebuild instructions are described
in [Career Discovery](../services/career-service/CAREER_DISCOVERY.md). Rebuild both
Career and frontend after source changes; production containers do not mount source.

## Session and verification boundaries

There is no new five-minute inactivity lock. Recoverable session checks preserve drafts; actual expiry/revocation, sign-out and account changes clear private state. Browser reload/discard and confirmed navigation can lose unsent React-memory drafts. CV history is saved on the server, separately from unsent text.

Startup/configuration commands in this guide are for the user to run with private settings. Agents may read/edit the public `infrastructure/docker/.env.example` template and validate it against Compose. Agents must not read or load private environment files. Automated verification uses isolated resources and explicit synthetic settings. Existing recordings from before an integration demonstrate that earlier build, not the newly merged application.

When retaining a previous key, migrate it to `CAREER_LLM_API_KEY`
and `BRAVE_API_KEY` to `CAREER_RESEARCH_API_KEY` in private settings. Legacy names
are fallback aliases only when the corresponding new name is absent. An explicitly
blank new name suppresses the legacy alias; for an OpenRouter endpoint the blank
model key still permits the shared `OPENROUTER_API_KEY` fallback. Follow the
[OpenRouter migration instructions](#career-model-and-search-configuration) when
changing providers, including clearing old per-service model keys.

## Jobs service

Add one new required value to your private `infrastructure/docker/.env` without changing existing passwords. Compose refuses to start without it, including for the other services:

```sh
JOBS_DB_PASSWORD=   # generate with: openssl rand -hex 24
```

Then rebuild with your usual Compose command. The `mongodb-jobs-init` job adds the Jobs database user to existing volumes without changing other data. `jobs-service` fetches listings when users search, using no provider API key. No catalogue seeding or sync worker is required. Recreate the stack with `--remove-orphans` to stop a previously deployed `jobs-sync` container; existing saved applications are preserved.

To change employers, edit [`sources.json`](../services/jobs-service/app/sources.json) and rebuild `jobs-service`.

## Chats & Socials pilot

Set `SOCIALS_DB_PASSWORD` in `infrastructure/docker/.env` before starting or rebuilding the stack. Generate a separate value with `openssl rand -hex 24`. The `mongodb-socials-init` job creates the scoped `elo_socials` user on both new and existing MongoDB volumes.

Set `SOCIALS_OPERATOR_ACCOUNT_IDS` to the comma-separated IDs of verified, onboarded Profile accounts that operate the pilot, then recreate `socials-service`. The operator API publishes real expert profiles and availability, enrolls pilot members, and lists reports. An empty operator list leaves operator actions unavailable. See the [Socials service guide](../services/socials-service/README.md) for the operator workflow.

## Assessment and Roadmap adviser

All user-configurable deployment inputs belong in the single ignored `infrastructure/docker/.env` file. The public [`infrastructure/docker/.env.example`](../infrastructure/docker/.env.example) documents them, including the new Assessment and Roadmap settings below. If you already have a private `.env`, add only the missing entries yourself; do not overwrite it by copying the template again. No additional environment file is needed in either service folder.

| Variable | Purpose |
|---|---|
| `ASSESSMENT_DB_PASSWORD` | New scoped `elo_assessment` MongoDB user/database |
| `ROADMAP_DB_PASSWORD` | New scoped `elo_roadmap` MongoDB user/database |
| `ASSESSMENT_LLM_API_KEY` | Server-only cloud credential for evidence comparison |
| `ROADMAP_LLM_API_KEY` | Server-only cloud credential for adviser recommendations |
| `ASSESSMENT_LLM_MODEL`, `ROADMAP_LLM_MODEL` | Independent model identifiers; absent settings fall back to OpenRouter defaults |
| `ASSESSMENT_LLM_BASE_URL`, `ROADMAP_LLM_BASE_URL` | Independent OpenAI-compatible HTTPS endpoints |
| `ASSESSMENT_LLM_TOKEN_PARAMETER`, `ROADMAP_LLM_TOKEN_PARAMETER` | `max_tokens` by default; set `max_completion_tokens` for models that reject `max_tokens` |
| `ASSESSMENT_LLM_ALLOW_HTTP`, `ROADMAP_LLM_ALLOW_HTTP` | HTTP permission for synthetic fixture providers only; also requires `APP_ENV=development` |

Generate only the new database passwords locally, then paste the printed lines into `infrastructure/docker/.env`:

```sh
for setting in ASSESSMENT_DB_PASSWORD ROADMAP_DB_PASSWORD; do
  printf '%s=%s\n' "$setting" "$(openssl rand -hex 24)"
done
```

Keep passwords already associated with existing database users. Keep the HTTPS base URLs and disabled HTTP flags, and add keys from your provider account to the same private file:

```dotenv
ASSESSMENT_LLM_API_KEY=YOUR_OPENROUTER_API_KEY
ASSESSMENT_LLM_MODEL=openai/gpt-4o-mini
ROADMAP_LLM_API_KEY=YOUR_OPENROUTER_API_KEY
ROADMAP_LLM_MODEL=openai/gpt-4o-mini
```

For a completely fresh installation only, generate each of `MONGO_ROOT_PASSWORD`, `PROFILE_DB_PASSWORD`, `CAREER_DB_PASSWORD` and `CV_DB_PASSWORD` separately with `openssl rand -hex 24`, and generate `OTP_HASH_SECRET` once with `openssl rand -hex 32`. Never regenerate these merely to rebuild an existing stack.

Both services can use `OPENROUTER_API_KEY` with the OpenRouter endpoint, or their own service-specific provider keys. Neither borrows Career's credential. Empty model settings leave saved data readable with a clear unavailable-adviser state. Use strong distinct database passwords compatible with the existing Compose Mongo URI interpolation (URI-safe characters). The planning initializer creates missing users and checks existing credentials without resetting them. Preserve credentials for existing database users.

Rebuild using the existing Compose workflow after applying configuration. Profile/CV/Career Docker build contexts now use the repository root so all install the same `packages/elo-shared` registry package. New services expose no host ports and access foreign data only through owner-authenticated APIs. Do not rebuild the user's running stack as part of a test. Shared package or dependency changes require image rebuilds.

For direct Python development, install `packages/elo-shared` before installing a service. Assessment and Roadmap each use their own `MONGODB_URI`/`MONGODB_DATABASE`; defaults are `elo_assessment` and `elo_roadmap`. Internal URLs are `PROFILE_SERVICE_URL`, `CV_SERVICE_URL`, `CAREER_SERVICE_URL` and `ASSESSMENT_SERVICE_URL`. The gateway exposes `/api/v1/assessments` and `/api/v1/roadmaps`; the UI stays at `/roadmap`.

To use a real model for Roadmap, configure both Assessment and Roadmap, because generating a roadmap runs Assessment first. With the OpenRouter template they share `OPENROUTER_API_KEY`; CV and Career can use that same key for creating the CV and goal. For direct OpenAI, set each service's `*_LLM_BASE_URL=https://api.openai.com/v1`, its own OpenAI key and an OpenAI model; where required set `*_LLM_TOKEN_PARAMETER=max_completion_tokens`. Rebuild with `docker compose --env-file .env -f compose.yaml up --build -d assessment-service roadmap-service` from `infrastructure/docker`. Roadmap and Assessment call providers through the OpenAI Python SDK; no Google SDK is needed.

Older extracted goals will not gain job dates automatically because their raw JDs are not retained. The adviser can discuss a user-selected preparation target; a new JD extraction can capture sourced application/interview/start wording. Existing CV skill keys and manual attachments are preserved. A null new canonical ID means unresolved mapping, not missing capability.

Career research planning and category structuring each allow up to 4,096 output
tokens, lowered by `AI_MAX_OUTPUT_TOKENS` when it is set. A 60-second model deadline does not
prevent output-token truncation. Planning uses the model deadline in both early
retrieval and durable research; search HTTP deadlines stay separate. Existing private
settings override defaults: apply `AI_TIMEOUT_SECONDS=60` in your private
`infrastructure/docker/.env`, then recreate Career yourself. Remove any obsolete
`CAREER_LLM_PROVIDER` and `CAREER_LOCAL_TIMEOUT_SECONDS` entries; they are no longer read.

### Skills Profile deployment update

The summary-first Skills Profile adds shared Python schemas used by Profile and CV,
plus frontend controls. Rebuild the Profile, CV and frontend images when applying
this update; application-only hot reload does not install a changed shared package.
No new environment setting, database or model credential is required. Existing
`CV_LLM_*` settings also serve guided intake, question writing and semantic support
checks. The owner-embedded profile and namespaced mutation receipts are additive;
existing CV histories, manual declarations and onboarding fields are retained.
