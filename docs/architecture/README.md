# Current Coachify architecture

This is the current design: Next.js App Router + React + TypeScript frontend, NGINX gateway, six Python FastAPI services, and MongoDB. It supersedes PostgreSQL/frontend-runtime assumptions in the earlier `outputs/` documents. P01–P08 are implemented in the frontend/profile slice; other services remain placeholders.

```mermaid
flowchart TB
    Student[Student browser]
    Auth[Identity provider with Google sign-in]
    LLM[External LLM provider]
    Atlas[(MongoDB Atlas: production proposal)]

    subgraph Deployment[Application deployment: eight containers]
        Gateway[NGINX gateway]
        Frontend[Next.js / React / TypeScript / Node.js]
        Profile[FastAPI profile service]
        CV[FastAPI CV ingestion service]
        Career[FastAPI career assessment service]
        Roadmap[FastAPI roadmap and task service]
        Dashboard[FastAPI stateless dashboard service]
        Review[FastAPI review and scheduling service]
        Uploads[(Private temporary CV volume)]
        Gateway --> Frontend
        Gateway --> Profile
        Gateway --> CV
        Gateway --> Career
        Gateway --> Roadmap
        Gateway --> Dashboard
        Gateway --> Review
        CV --> Uploads
    end

    Student --> Gateway
    Student -. Sign in .-> Auth
    Frontend -. Initial server-side API reads via internal gateway .-> Gateway
    Profile --> Atlas
    CV --> Atlas
    Career --> Atlas
    Roadmap --> Atlas
    Review --> Atlas
    CV --> LLM
    Career --> LLM
    Roadmap --> LLM
```

## Boundaries

- Next.js supplies pages, shared layouts, rendering, and interactive React components. It does not directly write domain records in MongoDB.
- Browser API calls use the gateway's `/api/v1` routes. Server-side Next.js reads may use an internal gateway URL.
- Each backend service owns its data and deploys independently. The dashboard aggregates through APIs and has no independent database.
- Five logical databases may share an Atlas deployment with service-scoped credentials. Local development can use one additional MongoDB container.
- Background execution initially belongs inside the responsible service container, backed by durable operation records. It is not implemented.
- The original CV is staged in a private host-backed Docker volume. Extracted and clarified information persists in MongoDB. Successful processing triggers eventual original-file deletion and cleanup.
- Task completion and reopening trigger automatic dashboard refetches. Scheduled reviews analyse pace separately and generate candidate revisions; a current approval policy controls application.
- Replanning preserves completed work and student edits. It does not silently change target jobs, deadlines, or availability.
- No additional AI microservice, message broker, or vector database is part of the first scaffold.

## Authentication status

The profile slice supports verified email/password accounts and optional Google. New accounts complete an emailed OTP step before obtaining a revocable 24-hour Coachify session. Development uses a private Mailpit inbox; production uses authenticated encrypted SMTP. Canonical profile completion controls initial onboarding and workspace access. Session bearers live in tab-scoped sessionStorage and are validated before private data loads. Sign-out/account changes clear other tabs. Set the matching Google Web Client ID on both sides for Google mode. See the [application setup guide](../setup.md) for setup and remaining integration limits.

See [service boundaries](service-boundaries.md), [API planning](../api/README.md), and [MongoDB guidance](../../infrastructure/mongodb/README.md).
