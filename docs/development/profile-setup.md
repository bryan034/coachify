# P07/P08: run and configure

Implemented: occupational status, school category, owner-scoped profile save/read,
append-only versions, local school suggestions and international university search.
P01–P03 institution/course/year entry is implemented. Downstream roadmap integration
remains future work. See `education-profile.md` for field and context semantics.

## You do not need to download school files

The repository includes `services/profile-service/app/data/schools.json` and the
Hipo MIT licence. School data is reference data in the service image, not MongoDB.
There are 10,404 suggestions from Singapore MOE and a worldwide community directory,
covering 200 country codes. This is not an exhaustive or accredited-university register.
Some records may be historical or misclassified upstream. Institution suggestions do
not establish enrolment, qualifications or eligibility. Custom institution entry is supported by P01.

The five P08 categories are school/qualification groups, not a verification system.
Mixed-level Singapore institutions can appear in multiple relevant categories.
Millennia Institute is grouped with Junior College as a pre-university option.
ITE colleges/polytechnics are supplemented from official directories. Other Singapore
private institutions are not claimed to be complete. International entries are under
University; non-university school categories currently cover Singapore only.

## Local browser and Postman testing — no Google setup

If you do not already have a local environment file, copy `infrastructure/docker/.env.example` to `infrastructure/docker/.env`. Keep these local-testing values:

```dotenv
APP_ENV=development
AUTH_MODE=local_test
LOCAL_TEST_USER_ID=coachify-local-user
GOOGLE_CLIENT_ID=
```

Fill only `MONGO_ROOT_PASSWORD` and `PROFILE_DB_PASSWORD` with two different random
hex strings (`openssl rand -hex 24`). Each developer runs their own local database
and uses their own passwords; there is no need to share personal `.env` files.
The database user/passwords must match the user's existing local volume. Updating
an env file does not rotate an already-created MongoDB account.

Start the stack with the Compose command below. Import
`docs/postman/coachify-local.postman_collection.json` into Postman. It is set to
**No Auth**, with `baseUrl=http://localhost:8080`. Run **Read profile**, then
**Save background**. The collection captures the current version automatically.

Manual requests:

```http
GET http://localhost:8080/api/v1/profile
```

Then PATCH the same URL with `Content-Type: application/json` and the returned version:

```json
{
  "expected_version": 0,
  "occupational_status": "student",
  "school_category": "university"
}
```

Use the latest `version` for subsequent saves; stale versions return 409. There is
no bearer token or user-ID header. The server assigns all requests to
`local_test:coachify-local-user`. Changing `LOCAL_TEST_USER_ID` and restarting the
profile service selects a different synthetic profile, useful for isolation tests.
Google profiles use a separate `google:` identity namespace and are not modified.

This mode is for a private local instance and synthetic data only: everyone who
can reach that API shares the fixed identity. The gateway binds to loopback in
Compose. Startup rejects `local_test` unless `APP_ENV=development`; absent mode
settings default to Google verification. Mode changes require a service restart.
Never enable it on a shared/public deployment. For a shared hosted database, use
separate scoped accounts and share access through your team's secret manager.

The browser reads the validated server mode from `GET /api/v1/profile/auth-config`.
In local-test mode, open `http://localhost:8080/profile` to load and save the fixed
local profile without Google. This public endpoint exposes only the mode; it cannot
change authentication or select a user. If configuration cannot load, saving stays
locked. Google mode still requires sign-in.

## Google sign-in: one public Web Client ID

No school API key or Google client secret is needed. For real-account/browser
testing, set `AUTH_MODE=google` and supply a Google OAuth Web Client ID:

1. Open https://console.cloud.google.com/ and select/create a project.
2. Configure Google Auth Platform branding/audience. If the app is in testing, add
   your account and teammates as test users where the audience configuration requires it.
3. Create an OAuth client of type **Web application**. Add
   `http://localhost:8080` to its **Authorised JavaScript origins**.
4. Copy the client ID ending in `.apps.googleusercontent.com` into `GOOGLE_CLIENT_ID`
   in the Docker environment below. This flow uses Google's JavaScript button and
   an ID-token callback, so no redirect URI or client secret is used.

The frontend keeps the token only in memory and sends it as a bearer token to
FastAPI. FastAPI verifies signature, audience, issuer and expiry and derives ownership
from Google's stable subject. After reload or expiry, sign in again; saved profile
answers are restored from MongoDB. This initial slice has no long-lived app session
or refresh-token flow. Use HTTPS and configure the actual origin before deployment.
Do not paste credentials into chat or commit real environment files.

Google documentation:
https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

## Start the four-container development slice

Docker Desktop must be running. From the repository root:

```sh
cp -n infrastructure/docker/.env.example infrastructure/docker/.env
```

Choose local testing mode or Google mode as described above, then fill the relevant values:

| Variable | What to supply |
|---|---|
| `GOOGLE_CLIENT_ID` | Leave blank for local testing mode; Web Client ID for Google mode |
| `MONGO_ROOT_PASSWORD` | A random hex password, e.g. generated with `openssl rand -hex 24` |
| `PROFILE_DB_PASSWORD` | A different random hex password |

Hex avoids URI escaping issues. The profile service uses its own database user;
it does not receive the root password. MongoDB initialisation creates the user only
on a fresh volume. Changing passwords later requires updating existing DB users;
editing the environment alone does not rotate credentials. Do not delete a volume
containing data you want to keep.

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d
```

Open **http://localhost:8080/profile**. Only the gateway binds a loopback host port;
backend/database ports remain private. The active Compose file runs only frontend,
profile, gateway and MongoDB. The old `.example` blueprint remains historical.
This is a local setup, not a production TLS/deployment configuration.

The Mongo container uses `GLIBC_TUNABLES=glibc.pthread.rseq=1` for compatibility
with this machine's Docker Desktop kernel (MongoDB SERVER-121912). This was
validated with the local image; reassess Mongo/kernel support before production.

## Local tests

Frontend:

```sh
npm ci
npm run typecheck --workspace apps/frontend
npm run test --workspace apps/frontend
npx playwright install chromium
NEXT_PUBLIC_GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com npm run test:e2e --workspace apps/frontend
```

The Playwright suite mocks Google and HTTP boundaries, not production authentication.
It builds/runs Next.js and exercises the actual UI. Its test-only client ID is not
valid for a real Google login.

Backend (Python 3.12; run in `services/profile-service`):

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest
```

For real MongoDB integration, set `MONGODB_TEST_URI` to an isolated disposable
MongoDB instance and rerun pytest. Tests create/drop a randomly named
`coachify_test_*` database. Never use a production URI. CI runs the full profile
suite with a disposable MongoDB service, in addition to normal unit suites.

## Refresh snapshots explicitly

With profile-service dependencies installed, from `services/profile-service`:

```sh
.venv/bin/python scripts/refresh_schools.py
```

This fetches MOE data plus the pinned Hipo Git revision, normalises/deduplicates
records, and atomically replaces the snapshot after a successful build. No runtime
API calls are made. The script can accept `--moe-file` and `--universities-file`
for previously downloaded JSON inputs. It preserves names and country identifiers;
IDs are derived from country and name. Renames need explicit reconciliation once
P01 stores selections; do not silently rewrite users' saved display names.

Secondary classification includes mixed-level schools such as `P1-S4`, alongside
secondary-only and secondary/JC schools. The current MOE snapshot contains 147
secondary schools, including Catholic High, CHIJ St. Nicholas Girls’ and Maris Stella High.

Review the diff/counts, run tests, and redeploy the profile service. Snapshots are
loaded once per process. To upgrade worldwide data, update `HIPO_REVISION` to a
reviewed commit and check the upstream licence. Keep attribution and licence files.
MOE refreshes work without a key at current public limits; optionally set
`DATA_GOV_SG_API_KEY` for higher limits. See https://guide.data.gov.sg/developer-guide/api-overview.
No university API key is required.

## Versions and downstream integration

`PATCH /api/v1/profile` requires `expected_version`; stale writes return 409.
Each changed save atomically inserts an immutable full snapshot into MongoDB
`profile_versions`. Unique owner/version indexing prevents concurrent overwrites.
Unrelated fields and existing education remain untouched. A context switch sets
`education_review_required` and never silently relabels retained education.
Profile versions allow future consumers to identify stale assessment/roadmap inputs;
no roadmap is updated or automatically regenerated by this slice.

## Full-stack browser regression

The `local-ui-integration` CI job starts a disposable Docker stack and verifies a
browser save through NGINX and FastAPI into MongoDB, then reloads the saved profile.
To run against your own **disposable** local-test stack (this writes profile data):

```sh
cd apps/frontend
PROFILE_E2E_BASE_URL=http://localhost:8081 npx playwright test --config playwright.integration.config.ts
```

Set `GATEWAY_PORT=8081` and use a separate Compose project, database volume and
local identity for that stack. Do not point this test at a personal or production profile.
