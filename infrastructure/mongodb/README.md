# MongoDB storage plan

The profile slice now has an active four-container setup in `infrastructure/docker/compose.yaml`, with `infrastructure/gateway/nginx.conf` and `infrastructure/mongodb/init-profile.js`. See the [application setup guide](../../docs/setup.md). The remaining notes below describe the original scaffold templates.


No database instance, user, collection, index, or connection code is created by this scaffold.

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

A local MongoDB container will write database files to a named volume mounted at `/data/db`. Its data persists independently of replacing the container. Use the `local-db` profile in the future completed Compose configuration. Never use a root credential as a normal application-service credential.

## Production proposal

Use MongoDB Atlas via private service environment configuration. Atlas manages its own database storage, so an Atlas deployment does not use the local `mongodb_data` volume. Hosting for Next.js and FastAPI is separate.

Indexes, validation, and any transaction/topology requirements are implementation work. They must be designed for MongoDB, not copied from the older PostgreSQL proposal.

## CV uploads are separate

The `cv_uploads` volume temporarily holds the original PDF/DOCX. Extracted text and clarified student information are stored in MongoDB. Only the CV service mounts this upload volume. Original files are deleted after successful extraction and persistence; cleanup is not implemented yet.
