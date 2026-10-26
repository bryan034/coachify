# Conversational Career Discovery

Career discovery creates a researched career target without a specific JD. It sets
a goal, not an assessment of the user's current abilities. Existing legacy
exploration sessions remain readable; the selector's **Explore careers** action
opens `/career-goal/discovery`. No CV ingestion or skill-gap engine is introduced.

## Flow and persistence

Gemini understands the newest message plus the saved structured career direction.
It asks one focused question, suggests up to three areas, or proposes a scope.
Fields and broad areas are valid targets. Neither a model `START_RESEARCH` action
nor an ordinary message can start research: a separate owner-authenticated request
must approve the exact scope displayed to the user.

Two LangGraph flows run inside Career:

1. `understand_intent` → conditional `confirm_career_area`: a private checkpoint
   stores the structured decision; the newest raw message is transient. Replaying
   the same message key recovers the decision without another generation.
2. `plan_research` → `search_job_listings` → `extract_requirements` →
   `aggregate_requirements` → `generate_career_target`: a leased background job
   checkpoints progress and saves completed searches/extractions independently.
   The result is a review, never an automatically confirmed goal.

Gemini plans related titles and searches. Brave LLM Context retrieves bounded
excerpts, with at most four initial queries and two targeted follow-ups, two requests
at once. Searches always retain approved area, location, stage and current year.
Groq extracts batches of at most three sources. Each requirement must quote retrieved
text, with the requirement itself present in that quote. Company/title/location are
checked against the excerpt/title; mismatched career stages and senior roles are
excluded from internship/entry-level samples. Unsupported claims are rejected.

Deterministic aggregation deduplicates source URLs and employer/title/location
reposts, maps only known taxonomy aliases, counts each skill once per listing, and
retains original terms and source IDs. A skill required in at least half the sample
and two distinct listings is core; other required skills are specialisation-specific;
preferred-only skills are optional. These frequencies describe the retrieved sample,
not the entire market. Different qualifications remain separate with a variation
warning; no mandatory universal qualification is inferred. Gemini selects validated
responsibility references; it cannot add facts during summarisation.

Users review title/overview, remove irrelevant skills/conditions/responsibilities,
refine the scope or explicitly refresh research, then confirm their current goal.
The existing `PATCH /goals/{id}/review` and `POST /goals/confirm` handle those saves.
`ReviewStore.goal()` constructs both JD and discovery targets; **both persist through
`GoalStore.persist_target()`**, followed by the existing optimistic selection update.
There is one `CareerGoal` schema. General targets have null company/job URL,
`target_type=career_exploration`, and source-labelled `market_research` requirements.
Canonical skill IDs/readiness and existing downstream version checks still apply.
Unmapped skills remain pending; no fabricated gap-analysis readiness is reported.

## Storage and recovery

No new collection or destructive migration. Existing collections gain additive data:

- `career_goals`: existing reviews and confirmed goals; optional typed `discovery`
  provenance. Research sources/claims are server-owned, and cannot be invented or
  rewritten through the generic review endpoint.
- `research_contexts`: private discovery sessions/jobs and immutable evidence
  snapshots keyed by the goal's `discovery.research_id`. Large evidence stays outside
  the goal. Snapshot history survives later scope changes and refreshes.
- Existing Career checkpoint collections: structured conversation decisions and
  research-node progress, with the existing 24-hour checkpoint TTL. Session/job data
  reconstructs research after restart or checkpoint expiry.
- `ai_user_usage`: numeric Groq reservations/completed usage, never prompts or keys.

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
| `POST /discoveries/{session_id}/messages` | Send `message`, `expected_version`; update direction only |
| `POST /discoveries/{session_id}/research` | Approve exact `scope` with `confirmed=true`, `expected_version`, optional `refresh`; returns 202 |
| `PATCH /goals/{review_id}/review` | Existing review edits, versioned and owner-scoped |
| `POST /goals/confirm` | Existing shared target confirmation and selection |

Detailed schemas are in `contracts/api/career.yaml`. After confirmation the existing
saved-goal page checks the CV service's owner-scoped assessment status. CV upload and
end-user gap/roadmap generation retain their existing implementation status; this
feature does not implement them.

## Configuration

Reuse server-only `AI_*` Groq settings, `GEMINI_API_KEY`, `BRAVE_API_KEY`, and Career
MongoDB. Discovery uses the existing research router and `OPPORTUNITY_GEMINI_MODEL`
(default `gemini-3.5-flash`) rather than routing conversation through Groq.
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
[Gemini 3.5 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash),
[Groq supported models](https://console.groq.com/docs/models), and
[Brave LLM Context](https://api-dashboard.search.brave.com/documentation/services/llm-context).
Configured account access still needs live verification; synthetic tests do not prove billing/plan access.

## Groq waits and research reliability

Groq alone has a local **7,000 input + output tokens per user per rolling 60 seconds**
allowance. Atomic reservations cover input plus bounded output before sending, across
parallel branches and replicas; completion reconciles to actual provider usage,
releasing unused capacity. This replaces the earlier check that admitted a request
at 6,999 used tokens and allowed concurrent calls to overshoot. There is no separate
4,000-token input limit: input must leave at least 128 output tokens within 7,000.
Provider accounting can differ slightly from the local tokenizer estimate.

Completed usage ages out after 60 seconds. Crashed/in-flight reservations conservatively
expire after 120 seconds; unknown read failures reserve the possible paid completion.
Connection/auth/429 rejections release reservations. Numeric usage only is persisted.
Gemini never checks or consumes the Groq ledger. Provider quotas still apply:
[Groq documents `Retry-After` on HTTP 429](https://console.groq.com/docs/rate-limits).
A 407/600-second provider cooldown cannot safely be converted into a local 60-second
reset. The UI distinguishes provider cooldown from the Groq local window.

Saved-goal questions no longer require interview research to finish. When Gemini is
configured for research, it can answer ordinary saved-context questions even with its
legacy chat switch off; explicit enabled chat configuration keeps its chosen model.
Groq remains responsible for reasoning/edits. Missing interview evidence is reported
as missing. Workspace polling does not restart the legacy graph after the durable
Opportunity worker has taken ownership. One invalid opportunity claim no longer
throws away other independently valid citations; wholly invalid batches still fail
bounded validation. Legacy structured recovery now stops after six repairs.

## Verification and limits

From `services/career-service`, run `python -m pytest` with a disposable
`MONGODB_TEST_URI`; external AI/search calls are mocked. From the root run
`npm run typecheck --workspace apps/frontend` and `npm test --workspace apps/frontend`.
The Chromium discovery journey uses mocked API boundaries and checks explicit scope
approval, category review, shared confirmation and narrow-screen layout.

Sources can be sparse, stale or contain only snippets. Coverage warnings and unknown
values are expected; 10–20 listings/five employers are targets, not fabricated quotas.
The latest structured direction is durable; a full raw conversation transcript is not
stored. Provider-imposed limits and existing downstream CV/gap implementation limits
remain. Rebuild Career and frontend to install source changes in the Docker stack.
