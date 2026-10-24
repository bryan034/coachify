# Run Coachify locally

Use Docker Desktop, Node.js 24 and Python 3.12. The active local stack contains
NGINX, the Next.js frontend, the Profile API and MongoDB. Other backend services
are placeholders. See the [API overview](api/README.md) and individual service
READMEs for feature details.

## Configure and start

From the repository root, copy the environment example if you do not already have
`infrastructure/docker/.env`. Do not overwrite an existing file:

```sh
cp -n infrastructure/docker/.env.example infrastructure/docker/.env
```

For local testing without Google, keep these values:

```dotenv
APP_ENV=development
AUTH_MODE=local_test
LOCAL_TEST_USER_ID=coachify-local-user
GOOGLE_CLIENT_ID=
```

Fill `MONGO_ROOT_PASSWORD` and `PROFILE_DB_PASSWORD` with two different random hex
passwords (generate each with `openssl rand -hex 24`). Each teammate can run their
own local database and keep their own `.env`; personal passwords need not be shared.
Keep real environment files and database data out of Git.

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up --build -d
```

Open **http://localhost:8080**. Only the gateway exposes a loopback port; the backend
and database stay private. MongoDB data survives container rebuilds in a volume.
Changing an environment password does not change users in an existing volume;
update those users deliberately. Do not delete a volume containing data you need.

Local-test mode currently uses one fixed identity for all requests to that private
instance. Changing `LOCAL_TEST_USER_ID` and restarting selects another synthetic
profile; it is not an account-login flow. Account creation, logout and multi-account
onboarding are backlog work. Local mode is rejected unless `APP_ENV=development`.
This Compose setup is not a public production deployment.

## Google access

For Google mode, set `AUTH_MODE=google`. In Google Cloud Console create an OAuth
**Web application** client, configure the branding/audience and add your test users
where required. Add `http://localhost:8080` as an authorised JavaScript origin.
Set `GOOGLE_CLIENT_ID` to that Web Client ID and rebuild the stack so frontend and
backend receive matching configuration. No client secret or callback redirect URI
is used by the current Google button/ID-token flow.

Tokens remain in browser memory; reload/expiry requires sign-in again. Persistent
application sessions are not implemented. For deployment, configure HTTPS and the
actual origin. School lookups require no runtime API key or extra download.

## Stop without deleting data

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml down
```

The MongoDB container includes an `rseq` compatibility setting for this machine's
Docker Desktop kernel. Review the deployment environment before production.
See [testing](testing.md) for automated checks and disposable test stacks.
