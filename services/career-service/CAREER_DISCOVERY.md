# Conversational Career Discovery

Career discovery creates a researched career target without a specific JD. It sets
a goal, not an assessment of the user's current abilities. Existing legacy
exploration sessions remain readable; the selector's **Explore careers** action
opens `/career-goal/discovery`. No CV ingestion or skill-gap engine is introduced.

## Flow and persistence

The Explore careers selector opens the same chat layout as the extracted-goal chat,
with a scrollable user/assistant transcript and an always-visible composer. Sending
clears the composer immediately; users can type the next draft while awaiting the
response. Failed messages have a separate retry action that preserves that draft.
Other Career chat and JD workflows are unchanged.

Gemini receives a compact structured memory (interests, preferences, rejected
areas and open questions), the six latest messages clipped to 400 characters each,
the current scope, and at most sixteen projected market facts. It does not receive
the full transcript or source excerpts on each chat turn. Memory fields are bounded
and must describe user statements, not assumptions about their abilities. Interests,
preferences and rejected directions each keep up to six entries; open questions keep
up to three. User skill exclusions/additions keep up to 60/30 entries respectively.
These lists are ordered oldest to newest: case/whitespace-equivalent duplicates do
not use another slot or renew an entry's age; overflow keeps the newest distinct
entries. Every supplied entry is validated before trimming, so invalid entries
cannot be hidden by overflow. Character limits and citation-reference caps stay strict.
Gemini can suggest up to five career directions, each explaining its work and differences.

`open_questions` tracks useful unresolved clarifications, for example whether a user
prefers building applications or analysing data. It is not a required questionnaire.
Gemini is instructed to remove answered, declined, superseded or irrelevant questions,
while continuing research with unknown optional context. The backend validates this
list's format, deduplication and capacity; semantic resolution relies on Gemini.

It asks one focused question only when useful. Broad fields and unspecified stage
or location are valid. Once the direction is clear, the message request atomically
queues research without a separate scope approval. The initial consent checkbox
explicitly includes automatic public research. Final goal confirmation is unchanged.

Two existing LangGraph flows run inside Career:

1. `understand_intent`: a private checkpoint stores the structured decision and
   payload digest for safe replay. Accepted user/assistant messages and compact
   memory persist in the owner-scoped discovery session. Sessions stop accepting new turns at
   996 transcript entries or 3.5 MB before requiring completion; existing sessions without
   messages/memory remain readable. Earlier raw messages cannot be reconstructed.
2. `plan_research` → `search_job_listings` → `extract_requirements` →
   `aggregate_requirements` → `generate_career_target`: a leased background job
   checkpoints searches and extractions independently. Messages remain accepted
   during research and quota waits. Extraction may post one optional, source-linked
   clarification per run while remaining research continues. A user's answer informs
   synthesis; unknown context never blocks the result.

Questions reuse bounded evidence without starting research. Skill refinements
re-synthesise fresh evidence for the same scope; changed scopes start a new run,
reusing a fresh equivalent-scope sample when available. Explicit refresh bypasses
reuse. Every worker checks its run/lease; an older run cannot publish into a changed
direction. Synthesis checks the conversation version and recomputes if new answers
arrive before publication. Research progress never overwrites user messages/memory.
The output is a draft review, never an automatically confirmed goal.

Gemini plans related titles and searches. Brave LLM Context retrieves bounded
excerpts, with at most four initial queries and two targeted follow-ups, two requests
at once. Searches always retain approved area, location, stage and current year.
Gemini extracts batches of at most three sources. Each requirement must quote retrieved
text, with the requirement itself present in that quote. Company/title/location are
checked against the excerpt/title; mismatched career stages and senior roles are
excluded from internship/entry-level samples. Unsupported claims are rejected.

Deterministic aggregation deduplicates source URLs and employer/title/location
reposts, maps known taxonomy aliases, counts each skill once per listing and retains
original terms and source IDs. Frequencies describe the sample, not the whole market.

Gemini consolidates this validated inventory into a coherent recommended skill set,
separating foundations, specialisation-dependent skills and optional tools. It gives
each recommendation a learning priority and relevance explanation, with checked
references to observations. These are saved as suggested `generated_guidance`, with
source URLs and no fabricated employer quote. User-requested additions without
market evidence remain `user_declaration`. Original requirements and immutable evidence
snapshots remain available separately; removing a recommendation does not rewrite
what employers stated. Qualifications remain variable sample conditions.

The chat result shows direction, representative responsibilities, up to eight concise
skill recommendations with inline citations, supported conditions, possible
specialisations and coverage warnings. The review contains the full selected skill
set. Only server-resolved source references become citations; model-written links
cannot introduce sources. No skill-gap assessment or roadmap is generated.

Users review title/overview, remove irrelevant skills/conditions/responsibilities,
refine the scope or explicitly refresh research, then confirm their current goal.
The existing `PATCH /goals/{id}/review` and `POST /goals/confirm` handle those saves.
`ReviewStore.goal()` constructs both JD and discovery targets; **both persist through
`GoalStore.persist_target()`**, followed by the existing optimistic selection update.
There is one `CareerGoal` schema. General targets have null company/job URL,
`target_type=career_exploration`, and source-linked learning recommendations and their original market observations.
Canonical skill IDs/readiness and existing downstream version checks still apply.
Unmapped skills remain pending; no fabricated gap-analysis readiness is reported.

## Storage and recovery

No new collection or destructive migration. Existing collections gain additive data:

- `career_goals`: existing reviews and confirmed goals; optional typed `discovery`
  provenance. Research sources/claims are server-owned, and cannot be invented or
  rewritten through the generic review endpoint.
- `research_contexts`: private discovery sessions (including the transcript and compact memory), jobs and immutable evidence
  snapshots keyed by the goal's `discovery.research_id`. Large evidence stays outside
  the goal. Snapshot history survives later scope changes and refreshes.
- Existing Career checkpoint collections: structured conversation decisions and
  research-node progress, with the existing 24-hour checkpoint TTL. Session/job data
  reconstructs research after restart or checkpoint expiry.

Fresh equivalent scopes reuse evidence within the same owner's sessions (case and
whitespace normalised), preserving the original freshness timestamp. Explicit refresh
bypasses this cache. A worker has a 330-second lease and a 300-second active execution
deadline; rate limits save the actual provider/local retry time and release the worker.
A sweeper resumes due jobs. Quota resumes skip previously completed extractions.
Invalid structured research responses have one repair; failed searches retry once.
Partial results remain available for retry. Empty relevant evidence produces an
explicit insufficient-coverage review with no invented requirements.

## API

All paths below use `/api/v1/career`, require the existing verified owner session,
and return no-store responses. POSTs require UUID `Idempotency-Key`.

| Method and suffix | Purpose |
|---|---|
| `GET /discoveries/current` | Recover latest owned session and capability status |
| `POST /discoveries` | Start/reuse a session with `consent=true` |
| `GET /discoveries/{session_id}` | Read/poll owned conversation, progress, evidence and review |
| `POST /discoveries/{session_id}/messages` | Send `message`, `expected_version`; converse/refine and automatically research a clear direction |
| `POST /discoveries/{session_id}/research` | Compatibility retry/refresh for current `scope`, with `confirmed=true`, `expected_version`, optional `refresh`; returns 202 |
| `PATCH /goals/{review_id}/review` | Existing review edits, versioned and owner-scoped |
| `POST /goals/confirm` | Existing shared target confirmation and selection |

Detailed schemas are in `contracts/api/career.yaml`. After confirmation the existing
saved-goal page checks the CV service's owner-scoped assessment status. CV upload and
end-user gap/roadmap generation retain their existing implementation status; this
feature does not implement them.

## Configuration

Use `AI_ENABLED=true`, server-only `GEMINI_API_KEY`, `BRAVE_API_KEY`, and Career
MongoDB. All discovery/research/chat/extraction stages use `gemini-3.5-flash-lite` through
the same adapter; legacy provider/model/chat switches no longer alter routing.
No new API key, dependency or service is needed. Existing research context creation
is governed by `OPPORTUNITY_ENABLED`. Optional tuning values are passed by Compose:

| Setting | Default |
|---|---:|
| `DISCOVERY_TARGET_LISTINGS` | 10 |
| `DISCOVERY_MAX_LISTINGS` | 20 |
| `DISCOVERY_TARGET_EMPLOYERS` | 5 |
| `DISCOVERY_MAX_FOLLOWUPS` | 2 |
| `DISCOVERY_FRESHNESS_HOURS` | 168 |

Model IDs/endpoints follow the provider documentation:
[Gemini 3.5 Flash Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[Brave LLM Context](https://api-dashboard.search.brave.com/documentation/services/llm-context).
Configured account access still needs live verification; synthetic tests do not prove billing/plan access.

## Provider waits and research reliability

There is no local token-per-minute admission limit. Gemini and Brave may still return HTTP 429 with a retry
delay. Background work checkpoints completed searches/evaluations and resumes the
unfinished step after that provider delay. A 407/600-second provider cooldown is not
shortened or presented as a local token reset.

Saved-goal questions remain available while research runs or waits. The same Gemini
model handles coordination, reasoning and validated edits regardless of the retired
Gemini-chat switch. Missing interview evidence is reported
as missing. Workspace polling does not restart the legacy graph after the durable
Opportunity worker has taken ownership. One invalid opportunity claim no longer
throws away other independently valid citations; wholly invalid batches still fail
bounded validation. Legacy structured recovery now stops after six repairs.

## Verification and limits

From `services/career-service`, run `python -m pytest` with a disposable
`MONGODB_TEST_URI`; external AI/search calls are mocked. From the root run
`npm run typecheck --workspace apps/frontend` and `npm test --workspace apps/frontend`.
The Chromium discovery journey uses mocked API boundaries and checks automatic research, transcript recovery, inline citations and explicit final goal
approval, category review, shared confirmation and narrow-screen layout.

Sources can be sparse, stale or contain only snippets. Coverage warnings and unknown
values are expected; 10–20 listings/five employers are targets, not fabricated quotas.
Discovery messages and structured memory are durable and private to the owner;
only bounded recent context is sent on each chat turn. Provider-imposed limits and existing downstream CV/gap implementation limits
remain. Rebuild Career and frontend to install source changes in the Docker stack.
