# Conversational Career Discovery

Current provider configuration (31 October 2026): all model stages use the selected
Career model, including local OpenAI-compatible or DeepSeek cloud inference. Retrieval
uses Brave LLM Context for testing or DeepSeek Search for production. Earlier model/Brave
names below describe the original path. DeepSeek retrieval accepts original page content
only, leaves missing employer metadata unknown and uses a distinct cache policy. See
[model/search setup](../../docs/setup.md#career-model-and-search-configuration).


Career discovery is a career guidance conversation that can create a researched
career target without a specific JD. It welcomes greetings, usage help and questions
about careers, jobs, internships, applications, interviews and related learning.
Users can start with partial information or no direction. The agent answers useful
questions and gradually learns the user's interests and preferences; missing research
fields never block conversation. It sets a goal without verifying current abilities. Existing legacy
exploration sessions remain readable; the selector's **Explore careers** action
opens `/career-goal/discovery`. No CV ingestion or skill-gap engine is introduced.

## Flow and persistence

The Explore careers selector opens the same chat layout as the extracted-goal chat,
with a scrollable user/assistant transcript and an always-visible composer. Sending
clears the composer immediately; users can type the next draft while awaiting the
response. Failed messages have a separate retry action that preserves that draft.
Opening or refreshing the page reads `GET /discoveries/current`, restoring the
owner's latest saved session, transcript, understanding and research/review progress.
Leaving and returning uses the same conversation, including after automatic goal publication.
Restored replies display in full; newly received replies reveal word by word.
An account with no session sees a fixed introduction authored in Python
(`app/domain/discovery_conversation.py`) and an editable composer without a consent
checkbox. Its first message creates a private session with `consent=true`.

**New chat** immediately calls `POST /discoveries` with a new idempotency key to
persist an empty conversation. Refresh before sending a message restores that empty
session. The previous chat stays visible if creation fails; retry uses the same key.
Every distinct start key creates a separate session without copying memory, scope,
suggestions, sources or review. Earlier sessions, evidence and confirmed goals remain
saved. There is no history picker. **Reload saved progress** reads the displayed
session ID, and initial load failures must be recovered before sending.

Opening the page or creating an empty session makes no model or public-search calls.
The fixed introduction is returned for empty current/start responses and the legacy
`GET /discoveries/current?fresh=true` display-only read. That compatibility read does
not create a conversation or change which one is current. The introduction is not
stored in new transcripts or sent to the model; legacy stored introductions are
filtered from responses and model history. Responses with messages omit it.

Messages and structured memory persist privately in Career's `research_contexts`
records with `kind=career_discovery`, independently of the 24-hour workflow checkpoint
TTL. Only bounded recent context enters model input. No new collection, migration or
browser chat storage is required. Unsent drafts remain in page memory. Legacy confirmed
sessions accept follow-up messages. Validated direction/skill refinements automatically
update the current goal in the same conversation; incomplete or failed work retains
the prior valid goal.
Other Career chat and JD workflows are unchanged.

The configured model receives the saved structured understanding with user evidence, a compact memory (interests, preferences, rejected
areas and open questions), recent whole conversation messages selected within a token budget,
the current scope, and at most sixteen projected market facts. It does not receive
the full transcript or source excerpts on each chat turn. Up to fourteen recent exchanges
(28 individual messages) are considered, with an 8,192 estimated-token history allowance.
The adapter drops the oldest messages, preferring complete user/assistant exchanges,
until both the history allowance and the effective full-request budget fit. It never
clips individual messages or removes the newest user input, saved understanding,
memory or research facts to fit. If those alone exceed the request budget, it reports
`context_limit`. The 64k model context setting is request capacity, not persistent memory;
the app continues to supply selected history and saved context on each turn. Memory fields are bounded
and must describe user statements, not assumptions about their abilities. Interests,
preferences and rejected directions each keep up to six entries; open questions keep
up to three. User skill exclusions/additions keep up to 60/30 entries respectively.
These lists are ordered oldest to newest: case/whitespace-equivalent duplicates do
not use another slot or renew an entry's age; overflow keeps the newest distinct
entries. Every supplied entry is validated before trimming, so invalid entries
cannot be hidden by overflow. Character limits and citation-reference caps stay strict.
The model can suggest up to five career directions, each explaining its work and differences.

`open_questions` tracks useful unresolved clarifications, for example whether a user
prefers building applications or analysing data. It is not a required questionnaire.
The model is instructed to remove answered, declined, superseded or irrelevant questions,
while continuing research with unknown optional context. The backend validates this
list's format, deduplication and capacity; semantic resolution relies on the model.

Research readiness is explicit and enforced in Python after model interpretation.
The agent naturally asks one useful missing topic at a time, using existing answers:

1. Field and, if possible, a specific role or kind of work; offer **keep it broad**.
2. What interests the user about that field.
3. Other interests, related or unrelated to the field.
4. Activities the user strongly wants to avoid.
5. Career stage.
6. Work preferences or constraints.

There is no full missing-fields questionnaire or repeated clarification preface. The agent
offers a broad direction and accepts unsure/skip answers without repeating a scripted
suffix each turn. Backend fallback questions explicitly offer “You can keep it broad.”
or “You can say unsure.”
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
`skill_ambiguity` remains an internal model assessment, not a required user answer.
A material ambiguity prompts the role/keep-it-broad question; explicit broad choice
allows a comparative sample without pretending every role requires the same skills.

Python grounds proposed answers in this session's USER statements and requires
explicit uncertainty/skip wording for unsure/skipped answers. Semantic interpretation
still relies on the model; a matching quotation is not a proof of correct interpretation.
Saved answers survive the bounded recent-message window. A viable field must be
identified before research; otherwise the conversation continues with options.
The readiness gate also applies to the compatibility `/research` endpoint.

Exact greetings, thanks and basic usage-help messages are answered in Python with
career-focused copy and, on a first message only, one missing-topic follow-up. Later
greetings continue the chat without another introduction or checklist question. These turns
make no model call, retain understanding/memory/scope, and do not start research.
Matching covers only the whole message; a greeting followed by a question or task
still goes through the model. Other turns use `discovery_turn` to classify scope.
The turn prompt builds on the previous question and all supported preferences rather
than reintroducing the assistant or following a fixed question order. A stated kind
of work can address role scope without a specific job title. Suggestions remain
tentative until supported by the user's own statements. The response renderer
appends a separate follow-up only when it is not already present in the reply,
ignoring case, whitespace and punctuation differences.
Career questions use `ANSWER` before research is ready. Contextual short
answers and hobbies supplied during interest discovery are relevant without career
keywords. Mixed requests receive only career-related guidance. Wholly unrelated tasks
or instruction overrides use `REJECT_OUT_OF_SCOPE`: Python replaces the model reply
with a fixed career redirect, ignores all proposed context/actions and retains the
previous decision, memory, scope, review and research run. The user/redirect pair and
idempotency receipt are saved. No new research is started for that request. Scope
detection for model-routed turns requires this model call; it is not a keyword filter or a guarantee
of perfect semantic classification. Existing research may continue independently.
Discovery uses its own stage-specific system prompts; these scope instructions are
sent in that prompt, rather than relying on the generic Career prompt.
All five Discovery model stages request schema-constrained generation from their
Pydantic contracts. Local inference uses native JSON Schema through the compatible
Chat Completions transport.
DeepSeek Discovery uses `/responses` with `text.format.type=json_schema`, independently
of the JSON-only Chat Completions setting used by other Career workflows.
DeepSeek's standard `/v1` base alias is normalized to its documented provider root
for Responses calls; custom proxy paths are preserved. Generic
compatible endpoints must explicitly use verified `json_schema_strict` support;
Discovery never silently downgrades to JSON-only mode. Unsupported configurations
return `unsupported_structured_output`. No additional credentials or dependencies
are required. User-configurable values remain in the single private Docker environment
file, which agents must not inspect.

Chat requests a top-level `Decision` object including `action`, `scope`, `question`
and `reply`. Required response keys do not require known user answers: scope/question
can be null and understanding can remain unanswered. Context is supplied as a JSON
object rather than an escaped JSON string. Backend evidence and ownership checks
remain authoritative; decoder constraints cannot prove relevance or factual support.

Validation failures are isolated to independent sections: top-level fields, each
memory list, each understanding answer, and individual recommendations, assessments
and extracted listings. Valid sections are retained unchanged. Only failed sections
are requested again, using a reduced schema with literal keys such as `scope` or
`skills.1`, for at most **two correction attempts after initial generation**. Accepted
sections cannot be overwritten by a repair. Corrections share the original operation
deadline; no extra correction starts without enough remaining time. Worker-level
whole-response retries do not multiply this budget. No rejected model text is replayed.

After exhaustion, failed memory/understanding updates retain prior values; unsupported
research items are omitted, and missing assessments remain rejected. Failed control
sections cannot launch research or change scope. Failed classification cannot publish
potentially unrelated text, and unresolved citation references cannot publish the
dependent answer. Other valid sections remain usable with a plain-language partial
result notice. A missing reply uses an explicit incomplete-answer message rather than
invented content. Valid search titles survive a failed query section, but no search
queries are invented. Provider failures during correction preserve accepted sections;
authentication/configuration errors, stale input and cancellation remain failures.
Malformed/truncated JSON is never salvaged by guessing its missing contents.

Changed fields clear obsolete field/role/field-interest answers and retire previous
active research; other interests, stage, location and general work preferences are
retained. Other interests inform personalisation during synthesis, and do not become
compulsory unrelated industry/job filters or automatically require new Brave searches.
No separate scope confirmation is required once the six topics are addressed.
Completed validated results automatically update the current goal without a separate
save or confirmation action. The fixed Python introduction explains that questions
help understand interests and personalise the goal; it remains excluded from LLM input.

Two existing LangGraph flows run inside Career:

1. `understand_intent` → `evaluate_readiness` → `clarify_scope` or `scope_ready`:
   Python handles exact social/help turns; otherwise the model interprets the message,
   with at most two corrections for failed sections. Python then routes the result.
   Guidance replies bypass missing-field clarification. Partial answers
   retain the model's acknowledgement and follow-up; a premature research action
   falls back to one missing-topic question. A private checkpoint stores the structured decision and
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
The output publishes the validated goal automatically; readiness and the separate CV-context acknowledgement remain independent.

The model plans related titles and searches. Brave LLM Context retrieves bounded
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
not a local slice of the first five unassessed pages. The model still validates every
returned candidate; an irrelevant or invalid context is excluded, so a query may
contribute fewer than five useful sources. The existing bounded follow-up queries
can improve coverage; no additional same-query retrieval bypasses the five-URL cap.
All returned candidates across queries are deduplicated before evidence selection.
Known search-index/template URL shapes are excluded in code. The model assesses the
remaining candidates against field, area, stage and location. Its assessment schema
contains ref/relevant/score/quote, without a kind taxonomy or employer field. Legacy
model-supplied kind/company fields are ignored rather than validated. Only
positively relevant individual listings enter the target; rejected sources are not
relabeled relevant. Python checks source references and schema bounds, not literal
quote/name equality. The model may paraphrase Brave evidence faithfully, preserving
negations, required/preferred wording, conditions and alternatives. Semantic fidelity
is model-interpreted, not independently proven by Python string checks.

Employer names come only from explicit `hiringOrganization` data in structured
snippets returned by Brave; missing or ambiguous names stay null. Brave's `site_name`
is a publisher, potentially a job board, and is not treated as an employer. The model
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

The model extracts batches of at most three sources. Supporting evidence can be a
faithful paraphrase; exact requirement-name/quote matching is not required. Role title
and location still have source checks, and stage mismatches/senior roles are excluded
from internship/entry-level samples. Schema/reference errors trigger replacement.
If the model returns truncated output or a batch exceeds its input budget, the worker
checkpoints a split and processes smaller batches instead of repeating the same
oversized request. A single source gets one compact retry with at most eight
representative requirements; a persistently incomplete source is excluded with a
coverage warning. Successful child extractions survive quota waits/restarts, and
resuming unfinished extraction does not start unnecessary follow-up searches.
No truncated JSON or invented completion is accepted.

Deterministic aggregation deduplicates source URLs and employer/title/location
reposts, maps known taxonomy aliases, counts each skill once per listing and retains
original terms and source IDs. Frequencies describe the sample, not the whole market.

The model consolidates this validated inventory into a coherent recommended skill set,
separating foundations, specialisation-dependent skills and optional tools. It gives
each recommendation a learning priority and relevance explanation, with checked
references to observations. These are saved as suggested `generated_guidance`, with
source URLs and no fabricated employer quote. User-requested additions without
market evidence remain `user_declaration`. Original requirements and immutable evidence
snapshots remain available separately; removing a recommendation does not rewrite
what employers stated. Qualifications remain variable sample conditions.

The chat result uses Markdown headings for direction, research coverage, typical
work, recommended skills, supported conditions, possible specialisations and research
limitations. Empty sections are omitted. Skill names and learning priorities are
bold, and responsibilities/skills/conditions use bullet lists with inline citations.
The summary highlights up to eight recommendations and explicitly states the full
count when more are saved in the server review. Its final line is always bold:
“You can ask questions and refine your career goal through this chat.” The 12,000
character message bound reserves space for this invitation. Only server-resolved
source references become citations; model-written links cannot introduce sources.
No skill-gap assessment or roadmap is generated.

There is no review/editor panel or save action in the chat. Users request skill
additions/removals and direction refinements through messages. Once synthesis succeeds,
Career uses `ReviewStore.goal()` and the shared `GoalStore.confirm()` persistence
orchestration internally to publish the goal's metadata, responsibilities, skills,
conditions, summary, discovery evidence and declared interests/preferences. The
Career Goal page reads the same current pointer, polls lightweight progress while
visible, and refreshes on tab focus. Ordinary
questions do not republish unchanged guidance. Generic review/confirmation endpoints
remain compatibility APIs, with no Discovery UI dependency.

Publication pins the selection revision captured when research begins, and checks
`career_state.active_discovery` in the atomic current-pointer update. New chat changes
that marker; a new JD input explicitly clears it. An older run cannot replace a newer
conversation or goal. A bounded 30-second `publication_until` lease excludes message
mutations during publication; callers retain their retry identity. Stable publication
receipts allow replay if a worker stops after updating the goal and before completing
its transcript entry, without selecting the goal twice. Failures preserve the previous
current goal and retained evidence. Existing latest pre-upgrade conversations can be
adopted on their next refinement when their goal context has not been replaced.
The existing `review` status now means synthesis and automatic publication completed;
it does not request a user save. Automatic saving never acknowledges CV context.

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
Model schema/reference failures use section correction before publication. Unusable
assessment/extraction evidence then uses the one replacement-search budget described above; ordinary
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

Detailed schemas are in `contracts/api/career.yaml`. After automatic publication the existing
saved-goal page checks the CV service's owner-scoped assessment status. CV upload and
end-user gap/roadmap generation retain their existing implementation status; this
feature does not implement them.

## Configuration

Use `AI_ENABLED=true`, server-only `CAREER_LLM_API_KEY`, `CAREER_RESEARCH_API_KEY`, and Career
MongoDB. All discovery/research/chat/extraction stages use the configured Career model through
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
| The model input, including instructions/schema/context | At most 32,768 estimated tokens per call |
| The model extraction output | At most 8,192 tokens per call |
| The model discovery conversation output | At most 4,096 tokens, bounded by shared configured output cap |
| The model relevance assessment output | At most 2,048 tokens |

The model input uses the existing tokenizer as an estimate, not a byte-count proxy;
actual provider counts can differ. The effective input budget is the smaller of
32,768 and `AI_CONTEXT_TOKENS` minus the output allowance and safety margin.
Evidence is split rather than silently shortened at this boundary. Discovery extraction
always sends an explicit 8,192-token maximum, independently of the shared
`AI_MAX_OUTPUT_TOKENS` default. This is a ceiling, not a target length or minimum:
The model may finish earlier. Other stages/workflows retain their existing caps and
shared configuration behavior. There is no new setting, provider, dependency or
local tokens-per-minute limit.

Brave currently documents a 32,768-token total context maximum and 8,192 per URL.
Model context limits depend on the configured OpenRouter model; they are
provider maxima, not the amounts elo sends or requests.

Model IDs/endpoints follow the provider documentation:
[OpenRouter models](https://openrouter.ai/models),
[Brave LLM Context](https://api-dashboard.search.brave.com/documentation/services/llm-context).
Configured account access still needs live verification; synthetic tests do not prove billing/plan access.

## Provider waits and research reliability

There is no local token-per-minute admission limit. The model and Brave may still return HTTP 429 with a retry
delay. Background work checkpoints completed searches/evaluations and resumes the
unfinished step after that provider delay. A 407/600-second provider cooldown is not
shortened or presented as a local token reset.

Saved-goal questions remain available while research runs or waits. The same model
model handles coordination, reasoning and validated edits regardless of the retired
legacy chat switch. Missing interview evidence is reported
as missing. Workspace polling does not restart the legacy graph after the durable
Opportunity worker has taken ownership. One invalid opportunity claim no longer
throws away other independently valid citations; wholly invalid batches still fail
bounded validation. Legacy structured recovery now stops after six repairs.

## Verification and limits

From `services/career-service`, run `python -m pytest` with a disposable
`MONGODB_TEST_URI`; external AI/search calls are mocked. From the root run
`npm run typecheck --workspace apps/frontend` and `npm test --workspace apps/frontend`.
The Chromium discovery journey uses mocked API boundaries and checks an initial
introduction without inference, restored history after refresh/navigation, explicit
New chat, automatic research, inline citations, chat-based skill removal, summary
headings/bold invitation, automatic goal updates without save requests and
narrow-screen layout.

Sources can be sparse, stale or contain only snippets. Coverage warnings and unknown
values are expected; 10–20 listings/five employers are targets, not fabricated quotas.
Discovery messages and structured memory are durable and private to the owner;
only bounded recent context is sent on each chat turn. Provider-imposed limits and existing downstream CV/gap implementation limits
remain. Rebuild Career and frontend to install source changes in the Docker stack.
