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
Opening the page or choosing **New chat** shows only a fixed introduction authored
in Python (`app/domain/discovery_conversation.py`). The frontend fetches it using
`GET /discoveries/current?fresh=true`, which returns no previous session/history.
No Gemini or Brave request is triggered by opening the page, consent changes or
New chat. Only sending the first message creates a new private session and starts
conversation processing. The introduction is returned only on this fresh-open request and kept as display-only
frontend state. It is not stored in new transcripts or sent to Gemini; legacy stored
introductions are filtered from responses and model history. Normal session, message
and research responses omit the introduction field.
Each new start key creates a distinct session; retries of that key are idempotent.
No prior memory, scope, suggestions, sources or review are copied into the new chat.

**Reload saved progress** within an active chat reads that specific session ID.
Reopening/reloading the discovery page starts with a clean view; earlier sessions
and evidence remain owner-scoped on the server, and saved goals are preserved.
Other Career chat and JD workflows are unchanged.

Gemini receives the saved structured understanding with user evidence, a compact memory (interests, preferences, rejected
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

Research readiness is explicit and enforced in Python after Gemini interpretation.
Clarification is a numbered bundle of the remaining topics, in this order:

1. Field and, if possible, a specific role or kind of work; offer **keep it broad**.
2. What interests the user about that field.
3. Other interests, related or unrelated to the field.
4. Activities the user strongly wants to avoid.
5. Career stage.
6. Work preferences or constraints.

There is no repeated clarification preface. The field/role question ends with
“You can keep it broad.”; the other questions end with “You can say unsure.”
Already answered topics are omitted. The first topic fills both `field` and
`role_family_or_work`; the remaining required answers are `interest`,
`other_interests`, `avoided_activities`, `career_stage` and `work_preferences`.
Each answer has `status`, `value` and user-message `evidence`; status is
`unanswered`, `known`, `unsure` or `skipped`. Missing answers stay unanswered;
explicit unsure/skip (including a blanket answer about the remaining topics) counts.
User interests, rather than CV, grades, education or current skills, guide discovery.

An explicit broad choice is stored in `role_family_or_work` as known value
`keep it broad`. There is no separate `broad_exploration` dictionary. There is no
`industry` question or dictionary: industry context is interpreted from `field`.
Older dictionaries are ignored on read, preserving an earlier explicit broad choice
when the role was unspecified or simply repeated the field. New `other_interests`
answers still need to be collected for older chats. Location is optional, captured
only if volunteered; it does not add a seventh question or block research.
`skill_ambiguity` remains an internal Gemini assessment, not a required user answer.
A material ambiguity prompts the role/keep-it-broad question; explicit broad choice
allows a comparative sample without pretending every role requires the same skills.

Python grounds proposed answers in this session's USER statements and requires
explicit uncertainty/skip wording for unsure/skipped answers. Semantic interpretation
still relies on Gemini; a matching quotation is not a proof of correct interpretation.
Saved answers survive the bounded recent-message window. A viable field must be
identified before research; otherwise the conversation continues with options.
The readiness gate also applies to the compatibility `/research` endpoint.

Changed fields clear obsolete field/role/field-interest answers and retire previous
active research; other interests, stage, location and general work preferences are
retained. Other interests inform personalisation during synthesis, and do not become
compulsory unrelated industry/job filters or automatically require new Brave searches.
No separate scope confirmation is required once the six topics are addressed. Final
goal confirmation is unchanged. The fixed Python introduction explains that questions
help understand interests and personalise the goal; it remains excluded from LLM input.

Two existing LangGraph flows run inside Career:

1. `understand_intent` → `evaluate_readiness` → `clarify_scope` or `scope_ready`:
   Gemini extracts understanding once; Python conditionally routes without another
   model call. A private checkpoint stores the structured decision and
   payload digest for safe replay. Accepted user/assistant messages and compact
   memory persist in the owner-scoped discovery session. Sessions stop accepting new turns at
   996 transcript entries or 3.5 MB before requiring completion; existing sessions without
   messages/memory remain readable. Earlier raw messages cannot be reconstructed.
2. `plan_research` → `search_job_listings` → `extract_requirements` →
   `aggregate_requirements` → `generate_career_target`: a leased background job
   checkpoints searches, source assessments, adaptive extraction splits and successful extractions independently. Messages remain accepted
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
at once. Searches retain the selected field and area, optional location/stage and
current year; field context disambiguates similarly named occupations.

Discovery has its own Brave retrieval method: each query considers up to 50 search
results using strict relevance ranking, then returns at most five URL contexts
with a 16,384-token total context budget and 2,048 tokens per URL. Opportunity research
keeps its existing three-URL and 8,192-token retrieval settings; other JD/search
paths retain their existing budgets. No top-five cutoff
is used for the Discovery evidence sample.

The five contexts are Brave's relevance-filtered selection from its search results,
not a local slice of the first five unassessed pages. Gemini still validates every
returned candidate; an irrelevant or invalid context is excluded, so a query may
contribute fewer than five useful sources. The existing bounded follow-up queries
can improve coverage; no additional same-query retrieval bypasses the five-URL cap.
All returned candidates across queries are deduplicated before evidence selection.
Known search-index/template URL shapes are excluded in code. Gemini assesses the
remaining candidates against field, area, stage and location. Its assessment schema
contains ref/relevant/score/quote, without a kind taxonomy or employer field. Legacy
model-supplied kind/company fields are ignored rather than validated. Only
positively relevant individual listings enter the target; rejected sources are not
relabeled relevant. Python checks source references and schema bounds, not literal
quote/name equality. Gemini may paraphrase Brave evidence faithfully, preserving
negations, required/preferred wording, conditions and alternatives. Semantic fidelity
is model-interpreted, not independently proven by Python string checks.

Employer names come only from explicit `hiringOrganization` data in structured
snippets returned by Brave; missing or ambiguous names stay null. Brave's `site_name`
is a publisher, potentially a job board, and is not treated as an employer. Gemini
neither supplies nor verifies companies. Known employer/title/location reposts are
deduplicated, and ranking prefers employer diversity when metadata supports it.
Unknown employer coverage is disclosed without guessing names. The selected sample
is bounded by `DISCOVERY_MAX_LISTINGS`.

A rejected candidate, invalid assessment/extraction response, or unsupported listing
triggers one replacement Brave query for the same field/area/stage/location. Accepted
candidates, assessments and completed extractions are retained. Previously returned
URLs do not count as replacements. Invalid output is not regenerated using the same
evidence. The error-replacement budget is one search per research run (persisted
across quota waits/restarts), shared by assessment and extraction. Rejected candidates
are removed individually; accepted candidates and completed extractions are never
invalidated by other sources being rejected. If replacement results are mixed,
irrelevant, invalid, empty, duplicated or unavailable, usable original/replacement
evidence still proceeds to synthesis with an explicit coverage warning. Evidence
recovery fails with `invalid_output` only when no usable listing remains after that
one attempt. Rejected evidence is never relabeled relevant to fill the sample.
Ordinary coverage follow-ups and the existing output-limit splitting below are
separate from this error retry. Rejected pages remain excluded and are disclosed in
coverage warnings. Explicit refresh starts fresh under the new research policy.

Gemini extracts batches of at most three sources. Supporting evidence can be a
faithful paraphrase; exact requirement-name/quote matching is not required. Role title
and location still have source checks, and stage mismatches/senior roles are excluded
from internship/entry-level samples. Schema/reference errors trigger replacement.
If Gemini returns truncated output or a batch exceeds its input budget, the worker
checkpoints a split and processes smaller batches instead of repeating the same
oversized request. A single source gets one compact retry with at most eight
representative requirements; a persistently incomplete source is excluded with a
coverage warning. Successful child extractions survive quota waits/restarts, and
resuming unfinished extraction does not start unnecessary follow-up searches.
No truncated JSON or invented completion is accepted.

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
whitespace normalised) only under the current Discovery relevance policy, preserving the original freshness timestamp. Explicit refresh
bypasses this cache. A worker has a 330-second lease and a 300-second active execution
deadline; rate limits save the actual provider/local retry time and release the worker.
A sweeper resumes due jobs. Quota resumes skip previously completed extractions.
Planning/synthesis outputs retain their existing bounded repair. Assessment/extraction
validation failures use the one replacement-search budget described above; ordinary
failed search requests retain their existing single transport retry.
Candidate assessments, split decisions and successful source extractions remain
available for retry. Previously saved snapshots remain readable. New runs and retries reuse candidates
only from the current bounded-URL relevance policy; failed or completed runs from the
older 20-URL policy are not reused to bypass the per-query limit. Fresh cached
samples from the earlier three-URL cap remain valid under the raised five-URL maximum. Empty relevant evidence produces an
explicit insufficient-coverage review with no invented requirements.

## API

All paths below use `/api/v1/career`, require the existing verified owner session,
and return no-store responses. POSTs require UUID `Idempotency-Key`.

| Method and suffix | Purpose |
|---|---|
| `GET /discoveries/current` | Read latest owned session; `fresh=true` returns only fixed introduction/capabilities |
| `POST /discoveries` | Create a clean session with `consent=true`; same-key retries reuse it without AI calls |
| `GET /discoveries/{session_id}` | Read/poll owned conversation, progress, evidence and review |
| `POST /discoveries/{session_id}/messages` | Send `message`, `expected_version`; converse/refine and automatically research only after readiness passes |
| `POST /discoveries/{session_id}/research` | Compatibility retry/refresh for current `scope`, with `confirmed=true`, `expected_version`, optional `refresh`; returns 202 |
| `PATCH /goals/{review_id}/review` | Existing review edits, versioned and owner-scoped |
| `POST /goals/confirm` | Existing shared target confirmation and selection |

Detailed schemas are in `contracts/api/career.yaml`. After confirmation the existing
saved-goal page checks the CV service's owner-scoped assessment status. CV upload and
end-user gap/roadmap generation retain their existing implementation status; this
feature does not implement them.

## Configuration

Use `AI_ENABLED=true`, server-only `CAREER_LLM_API_KEY`, `CAREER_RESEARCH_API_KEY`, and Career
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

### Discovery token budgets

| Boundary | Current Discovery budget |
|---|---:|
| Brave URL contexts per query | At most 5 |
| Brave context per query | At most 16,384 approximate tokens total |
| Brave context per URL | 2,048 approximate tokens |
| Gemini input, including instructions/schema/context | At most 32,768 estimated tokens per call |
| Gemini extraction output | At most 8,192 tokens per call |
| Gemini discovery conversation output | At most 4,096 tokens, bounded by shared configured output cap |
| Gemini relevance assessment output | At most 2,048 tokens |

Gemini input uses the existing tokenizer as an estimate, not a byte-count proxy;
actual provider counts can differ. The effective input budget is the smaller of
32,768 and `AI_CONTEXT_TOKENS` minus the output allowance and safety margin.
Evidence is split rather than silently shortened at this boundary. Discovery extraction
always sends an explicit 8,192-token maximum, independently of the shared
`AI_MAX_OUTPUT_TOKENS` default. This is a ceiling, not a target length or minimum:
Gemini may finish earlier. Other stages/workflows retain their existing caps and
shared configuration behavior. There is no new setting, provider, dependency or
local tokens-per-minute limit.

Brave currently documents a 32,768-token total context maximum and 8,192 per URL.
Gemini 3.5 Flash-Lite documents 1,048,576 input and 65,536 output tokens; these are
provider maxima, not the amounts elo sends or requests.

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
The Chromium discovery journey uses mocked API boundaries and checks a fresh introduction without inference, clean re-entry, automatic research, inline citations and explicit final goal
approval, category review, shared confirmation and narrow-screen layout.

Sources can be sparse, stale or contain only snippets. Coverage warnings and unknown
values are expected; 10–20 listings/five employers are targets, not fabricated quotas.
Discovery messages and structured memory are durable and private to the owner;
only bounded recent context is sent on each chat turn. Provider-imposed limits and existing downstream CV/gap implementation limits
remain. Rebuild Career and frontend to install source changes in the Docker stack.
