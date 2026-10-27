# MongoDB storage plan

The active setup is `infrastructure/docker/compose.yaml`. Profile owns `coachify_profile`, CV owns `coachify_ingestion`, and Career owns `coachify_career`. Each uses separate credentials and communicates with other services through APIs. See the [application setup guide](../../docs/setup.md).


The logical `users` entity maps to the existing Profile `accounts` collection and its UUID account ID. The five logical domain collections do not prohibit separate operation, selection, idempotency or immutable-history records. There is no account migration or cross-service collection access.

## Ownership

| Service | Planned database |
|---|---|
| Profile | `coachify_profile` |
| CV ingestion | `coachify_ingestion` |
| Career assessment | `coachify_career` |
| Roadmap and tasks | `coachify_roadmap` |
| Review and scheduling | `coachify_review` |

The dashboard service is stateless and has no MongoDB credentials. Each data-owning service will receive its own database-scoped credentials. Services use APIs to request another service's records rather than reading its collections.

## Local development

A local MongoDB container writes database files to a named volume mounted at `/data/db`. Its data persists independently of replacing the container. Never use a root credential as a normal application-service credential. The current local MongoDB is standalone; code uses atomic document updates and explicit versions, not an assumed multi-document transaction.

`init-profile.js`, `init-cv.js` and `init-career.js` provision credentials only on a fresh volume. For an existing development volume, preserve existing passwords and add any missing `CV_DB_PASSWORD` and `CAREER_DB_PASSWORD` to the Compose environment. Recreate the MongoDB container without deleting the volume so it receives those variables, then run the idempotent provisioning scripts using the existing administrator credential:

```sh
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml up -d mongodb
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml exec mongodb sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /docker-entrypoint-initdb.d/init-cv.js'
docker compose --env-file infrastructure/docker/.env -f infrastructure/docker/compose.yaml exec mongodb sh -c 'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin /docker-entrypoint-initdb.d/init-career.js'
```

The scripts create missing database users and do not reset existing credentials. Do not delete the database volume to apply this change.

Career stores immutable reviewed snapshots in `career_goals` and one operational
selection record per owner in `career_target_selections`. This follows current SCRUM-310;
the earlier `career_targets` diagram name had no implemented data and requires no
rename or migration. Confirmation and selection are separate document operations.
Selection uses compare-and-set and durable idempotency receipts. No cross-service
transaction is implied; consumers retain and revalidate exact source versions.
Full JD text is transient, including on draft creation; only bounded evidence
snippets and structured fields are saved.

## Production proposal

Use MongoDB Atlas via private service environment configuration. Atlas manages its own database storage, so an Atlas deployment does not use the local `mongodb_data` volume. Hosting for Next.js and FastAPI is separate.

Indexes, validation, and any transaction/topology requirements are implementation work. They must be designed for MongoDB, not copied from the older PostgreSQL proposal.

## CV uploads are separate

The `cv_uploads` volume temporarily holds private original PDFs/DOCX files for the documented retry window. Only CV mounts it. MongoDB retains structured extraction and bounded evidence, not the full parsing text or a public file URL. Cleanup respects active processing leases and records deletion; expiring MongoDB metadata alone cannot delete a filesystem upload. Once the original expires, retry requires re-uploading the same source. See the CV service specification for limits and recovery behavior.
