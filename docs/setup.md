# Run Coachify locally

Use Docker Desktop, Node.js 24 and Python 3.12. The active local stack contains
NGINX, the Next.js frontend, the Profile API, the Career API, the CV API and MongoDB. Other backend services
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
| `MONGO_ROOT_PASSWORD`, `PROFILE_DB_PASSWORD`, `CV_DB_PASSWORD`, `CAREER_DB_PASSWORD` | Generate each separately with `openssl rand -hex 24`. Preserve existing values when reusing your database. Existing volumes need the [CV/Career user provisioning steps](../infrastructure/mongodb/README.md). |

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

## Career Goal previews and reviewed targets

The normal Compose command starts Career with its private `coachify_career`
database and `CAREER_DB_PASSWORD`. Existing volumes need the idempotent
[Career user provisioning step](../infrastructure/mongodb/README.md#local-development).
No Career AI key is needed for reviewed targets.

Open `/career-goal` after sign-in and initial setup. Paste a description, import a
public URL, or upload a PDF/DOCX/TXT document. Previews are temporary and disappear
on reload or navigation. Review the role, field, optional company and skills in
structured fields. Specific-job skills and optional qualification/date conditions
need bounded excerpts from the reviewed JD; exploration entries are labelled
personal guidance. Conditions specify which CV source kinds and phrases they
apply to. Save the draft, review and
confirm it, then explicitly select it or switch from the previous target.
Confirmation alone never changes selection. Saved targets survive reload; full JD
text and original files do not persist. To change a saved target, create another
snapshot and explicitly select it. A target needs at least one usable skill or
condition before confirmation.
AI JD interpretation, exploration chat and gap analysis remain separate work.

Career authenticates through Profile's API. Private temporary uploads use bounded
tmpfs. For direct service runs, install `.[test]` in a separate Python environment,
set `PROFILE_SERVICE_URL`, `MONGODB_URI` and `MONGODB_DATABASE=coachify_career`,
and run `uvicorn app.main:app --port 8001 --no-access-log` from its service directory.
Use the [Career environment example](../services/career-service/.env.example) and
[service README](../services/career-service/README.md) for the contract and limits.

## Saved CV upload and review

Open `/cv` after signing in and completing initial setup. CV records are stored
in `coachify_ingestion`; manual capability declarations stay with the existing
Profile account. Uploading a file never changes the selected CV. Choose a ready
CV explicitly before using its versioned capability input.

The Compose file uses a 10 MiB file limit and an 11 MiB gateway request limit
to allow multipart overhead. PDF/DOCX parsing is bounded; OCR is not included.
Originals use the private `cv_uploads` volume for the documented retry window.
Only structured extraction and bounded evidence are saved in MongoDB.

Set `CV_LLM_MODEL` and `CV_LLM_API_KEY` in the ignored Docker environment file
to enable real structured extraction and clarification-answer interpretation.
`CV_LLM_BASE_URL` defaults to
`https://api.groq.com/openai/v1`. Choose a model supporting JSON object output;
the server validates the schema and cited evidence before publication. Keys
stay on the server. Missing configuration is an actionable processing error,
never a synthetic successful extraction. No provider calls are needed for
automated tests. See [Groq compatibility](https://console.groq.com/docs/openai)
and [structured output modes](https://console.groq.com/docs/structured-outputs).

CV obtains the selected confirmed target through Career using the same owner
session. Compose supplies `CAREER_SERVICE_URL=http://career-service:8000`; set it
explicitly for direct service runs. On the CV review, prepare relevant questions,
then save an explanation or skip. The raw answer is saved before interpretation.
Supported changes appear against the relevant source, including personal/team
attribution, assistance, explicit skill details and optional partial dates. A failed
interpretation leaves the answer available for retry; a saved answer alone does
not mean the uncertainty is resolved. Reload restores answers and skips. Switching
targets updates relevance without deleting those source facts or repeating resolved
questions. No target defers preparation; an unavailable service shows a retry.
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

The MongoDB container includes an `rseq` compatibility setting for this machine's
Docker Desktop kernel. Review the deployment environment before production.
See [testing](testing.md) for automated checks and disposable test stacks.
