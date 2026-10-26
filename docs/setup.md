# Run Coachify locally

Use Docker Desktop, Node.js 24 and Python 3.12. The active local stack contains
NGINX, the Next.js frontend, the Profile API, the Career preview API and MongoDB. Other backend services
are placeholders. See the [API overview](api/README.md) and individual service
READMEs for feature details.

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
| `MONGO_ROOT_PASSWORD`, `PROFILE_DB_PASSWORD` | Generate each separately with `openssl rand -hex 24`. Preserve existing values when reusing your database. |

Keep the supplied `APP_ENV=development`, `AUTH_MODE=email`, SMTP host, port and
security values. No Google OAuth variables or Mailpit variables are needed.
Each teammate keeps their own ignored `.env` and credentials.

MongoDB data survives rebuilds in its volume. Changing an environment password
does not update database users already stored in that volume. Only the gateway
exposes a loopback port; the API and MongoDB stay private.

## Local email/password sign-in and real Gmail delivery

Google sign-in is disabled for the current local setup. Users register with their
email address and a Coachify password, then verify the email with an OTP.

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

Open `http://localhost:8080/register`. Enter any valid email address and a Coachify password.
Gmail is only the outgoing mail provider; recipients can use other providers.
The OTP goes to that registered address, not necessarily `SMTP_USERNAME`. Check
that inbox (and spam folder), verify the code, and complete initial setup. Sign in
later with the same email and Coachify password; no Google account popup appears.
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

## Career Goal previews

The normal Compose command also builds and starts `career-service`. No new
credentials, MongoDB users or Groq key are required. Open `/career-goal` after
sign-in and initial profile setup. Paste a description, import a public URL, or
upload a PDF/DOCX/TXT document. All previews are temporary; refreshing or leaving
the page discards them. No descriptions or original files are saved in MongoDB.
Only future approved structured information will be persisted after its schema
is agreed. The [Career service README](../services/career-service/README.md)
explains endpoints and current limitations.

Career verifies sessions through Profile over the internal Docker network. Its
private temporary upload directory is a bounded tmpfs, not a persistent volume.
If running Career independently, install `.[test]` from `services/career-service` in a
separate Python environment, set `PROFILE_SERVICE_URL=http://localhost:8080` with
the Profile stack already running, then run `uvicorn app.main:app --port 8001
--no-access-log` from the Career service directory (one command line). Explicitly
load any service-specific environment file when running outside Compose. Use a
verified Coachify session for API tests. There are no save/analysis endpoints yet.

## Stop without deleting data

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml down
```

The MongoDB container includes an `rseq` compatibility setting for this machine's
Docker Desktop kernel. Review the deployment environment before production.
See [testing](testing.md) for automated checks and disposable test stacks.

## Optional Groq configuration

SCRUM-282 adds the backend adapter; existing JD previews still make no AI calls.
To prepare the adapter, create a key in the
[Groq console](https://console.groq.com/keys), choose an available model from
[Groq's models page](https://console.groq.com/docs/models), and set these in your
ignored `infrastructure/docker/.env`:

```dotenv
AI_ENABLED=true
AI_PROVIDER=groq
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=YOUR_SUPPORTED_MODEL_ID
AI_API_KEY=YOUR_PRIVATE_GROQ_KEY
AI_RESPONSE_MODE=json_object
```

Model access depends on your account. Verify the exact ID in Groq's authenticated
`GET /openai/v1/models` list; a model appearing in public documentation does not
guarantee access. This account was verified with `AI_MODEL=openai/gpt-oss-120b`
and `AI_RESPONSE_MODE=json_object`. If you receive `model_unavailable`, choose an
accessible model and recreate Career; restarting alone does not reload Compose env.
Never print your API key or full `.env` while debugging. JD extraction on the
supported Groq GPT-OSS models uses a native strict schema even when the general
mode is `json_object`; no environment change is required. An `invalid_output`
response now has a safe `diagnostic.reason`, such as `schema_validation` or
`source_quote`, without JD/model contents. It automatically attempts one bounded
correction before showing the error.

Keep `AI_ENABLED=false` if you only need current previews. No credentials are
needed for automated AI tests. Only Career receives the key; never prefix it
`NEXT_PUBLIC_` or commit it. The service's
[contract guide](../services/career-service/ANALYSIS_CONTRACTS.md) explains response
modes and limits. Rebuild Career after editing settings:

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d --no-deps career-service
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

For exploration turns set `AI_ENABLED=true` and your own `AI_MODEL`/`AI_API_KEY`.
Without AI configuration transient JD import previews still work;
exploration and JD extraction/clarification require a configured provider. Open
Career Goal → Explore careers, or select **Extract career goal** after preparing a JD
to use the same chat page. Extraction sends the JD to the configured AI; results
remain temporary candidates until a future publishing workflow. Use a processed CV if one exists, continue
without one, or attach a temporary CV with the accuracy warning. Dedicated Resume
& Tracker uploads remain planned. Temporary originals/text are discarded; saved
progress may require the same CV to be reattached after reload. Every confirmed
goal stays requirements pending until J03/J10 skill generation is implemented.

## Docker hot reload

Use the opt-in [development Compose override](../infrastructure/docker/README.md#hot-reload-during-development)
for Next.js Fast Refresh and Python API reload without rebuilding for source edits.
It keeps the base production-style configuration available and retains MongoDB data.
Run the startup commands yourself with your private settings; agents must not load
or inspect your environment files. Dependencies/image changes still need rebuilding.


## Career LangGraph and research

Rebuild the Career image once after installing the new LangGraph/checkpointer/tokenizer dependencies. Subsequent source edits use the existing Docker hot reload setup. No LangSmith account or additional database server is required.

Use the existing Groq settings (`AI_ENABLED=true`, `AI_PROVIDER=groq`, `AI_MODEL` and backend-only `AI_API_KEY`). Coachify caps each Groq request at 4,000 estimated input tokens and checks a per-user 7,000-token rolling-minute input/output allowance before each call, without output reservations. Groq quotas remain separate. No new environment settings are needed for these limits. Chat output is capped at 1024 tokens, interview synthesis at 2048, and JD extraction defaults to 4096; a lower `AI_MAX_OUTPUT_TOKENS` remains the overall ceiling. Add `BRAVE_API_KEY`; `BRAVE_SEARCH_MODE=llm_context` is the default and requires LLM Context API access. Change any existing explicit `search` or `answers` value yourself to `llm_context` and recreate the career-service container. Answers remains opt-in for an Answers-plan API key. Research sends deduplicated, bounded snippets to the model, rather than full pages. Brave is the only interview-research API; no Reddit credentials are needed. Keep credentials server-side and enter them yourself in your local configuration.

Compose passes these settings only to Career. Without Brave configured or with denied Answers access the goal saves but research/chat preparation reports unavailable. Brave Answers has separate provider billing; its answer becomes context for the Groq extraction and counts toward Groq input once sent. Groq 429 responses pause background research using the provider retry delay; direct chat offers retry. Legacy `AI_TOKENS_PER_MINUTE`, `AI_REQUESTS_PER_MINUTE` and `AI_CONCURRENCY` values are ignored and may be removed from your configuration. Old token-budget records are unused; `ai_user_usage` now tracks rolling usage by user automatically, with no manual database setup. User-limit responses include seconds until enough usage expires. See the [Career configuration contract](../services/career-service/ANALYSIS_CONTRACTS.md) for defaults and persistence rules.


### Optional Gemini chat context

In the infrastructure configuration, set `GEMINI_ENABLED=true`,
`GEMINI_MODEL=gemini-3.5-flash-lite` and your server-only `GEMINI_API_KEY` from Google
AI Studio. Keep the existing `AI_*` settings for Groq extraction/reasoning and the
Brave Search settings. Recreate the Career service container after changing these
values. No frontend key, Google sign-in credential or new dependency is needed.
See the [Career service](../services/career-service/README.md) for model routing and
Groq-only usage limits. Gemini has no local 4,000-input or 7,000/minute cap and never spends the Groq allowance; its provider quota and context/output limits still apply. Without Gemini enabled, the existing single-provider chat works.

With Gemini enabled and `BRAVE_SEARCH_MODE=llm_context`, interview research also uses
Gemini to plan/refine up to six Brave searches and assess a three-source target.
Keep your existing keys with appropriate LLM Context access; Google grounding is not used. Only actual interview evidence with a matching supporting quote counts toward the three-source target. Searches stop early after two rounds without new useful evidence or when another round would leave insufficient synthesis time. Valid limited-coverage research is cached too; later retrieval failures preserve already assessed evidence.

### Opportunity Intelligence

The saved goal can automatically research interviews, internship experience and
company context using Gemini coordination, the configured Groq reasoner and Brave
LLM Context. Keep the existing enabled server `AI_*` settings with
`AI_MODEL=openai/gpt-oss-120b` (or a supported configured replacement),
`GEMINI_API_KEY` and compatible `BRAVE_API_KEY` access. `OPPORTUNITY_ENABLED=true`
is the default: the existing keys are sufficient for research configuration.
`GEMINI_ENABLED` controls optional chat only; it need not be enabled for research.
The dedicated research client always uses LLM Context regardless of the legacy
`BRAVE_SEARCH_MODE` value. Provider subscription/model access is checked on calls.
`OPPORTUNITY_GEMINI_MODEL=gemini-3.5-flash` controls research separately from
`GEMINI_MODEL` chat context. Model credentials remain independent/backend-only.
Recreate Career after applying configuration; no environment files were read or
edited during implementation. No new SDK or API credential is required.

Compose passes `OPPORTUNITY_ENABLED` (true), max searches (2), follow-ups (1),
concurrency (3), HTTP timeout (30s), transient retries (1), schema repairs (1),
evidence tokens (1000), freshness (168h), incomplete freshness (1h) and worker
deadline (300s). See the [complete settings/API/graph contract](../services/career-service/OPPORTUNITY_INTELLIGENCE.md).
MongoDB indexes/job recovery are automatic. Existing goals/research need no destructive
migration. Paid provider access and live response quality require your own setup;
normal tests use synthetic data/providers.
If research is unavailable, its API/UI reports the specific disabled or missing
capability rather than a generic request to configure all keys. Rebuild/recreate
Career and the frontend to apply source changes in production-style Docker;
restarting an existing image alone does not install edited code.
