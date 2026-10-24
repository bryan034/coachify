# Development status

P07/P08 now have a working Next.js profile section, FastAPI/MongoDB persistence,
Google ID-token verification, snapshot-based school browsing and an active local
four-container Compose setup. Test tooling and CI include frontend unit/browser
checks, backend unit tests and a real MongoDB integration job.

Start here: [P07/P08 setup and credentials](profile-setup.md).

School data is already downloaded; no school API key is needed at runtime. Google
sign-in needs a Web Client ID; local Postman testing can instead use the explicit
development-only fixed identity without Google credentials. Real sign-in remains unverified until credentials
are configured. Browser automation mocks the external identity/API boundaries;
backend integration tests exercise real MongoDB separately.

P01–P03 institution/course/year entry, CV ingestion, target-job assessment,
roadmaps, dashboards and reviews remain unimplemented. Reserved page routes have
minimal exports so the frontend builds; they do not implement those features.
No live external AI calls, scheduled execution, production deployment or roadmap
freshness integration exists. Keep durable agent rules in root AGENTS.md.
