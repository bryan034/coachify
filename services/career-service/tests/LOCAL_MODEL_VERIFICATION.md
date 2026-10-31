# Career verification — 1 November 2026

The JSON-contract/SDK implementation is present, and deterministic verification
passes. The requested complete UI journey with **exactly `deepseek-r1:1.5b` remains
unsuccessful**. Scope classification success must not be treated as extraction or
research quality. Private environment files were never read or loaded.

## Implementation and regression results

The `changing_models` checkout was clean at `1ad8027` before this continuation.
The earlier SDK adapter, runtime response validation, `job_dates` types and isolated
full-stack harness were already committed. Relevant SCRUM-29/30/31/286 stories and
their subtasks were read; no Jira records were changed.

This continuation fixes schema compaction discarding Pydantic field descriptions,
including the date wording/evidence contract. It also adds per-attempt reports,
unique browser artifact paths, fixed-count repetitions, failure retention and
immediate browser failure when extraction returns a terminal error. Experimental
prompt changes that still produced incorrect extractions were removed.

| Check actually run | Result |
|---|---|
| Frontend TypeScript | Passed, including the final integration-test change |
| Frontend Vitest | 354 passed |
| Career pytest against isolated MongoDB 8.0 | 1,236 passed; one paid-provider test skipped |
| Career browser boundary suites | 12 passed |
| Fixture-backed browser → gateway → services → MongoDB journey | Passed twice; final test 13.0 seconds |
| Exact-model scope suite, eight cases × three fixed repetitions | 24/24 passed |
| Exact-model complete UI journey | Both attempts failed during extraction |

The initial backend run without a tokenizer cache failed because offline tests
cannot download tokenizer data. After caching public tokenizer data, three genuine
schema-description regressions remained; preserving descriptions fixed them. The
final suite includes real persistence, owner isolation, retry and concurrency checks.
The skipped test requires configured paid providers and was not enabled.

The fixture journey verifies real account/email verification and onboarding, TXT
preview, extraction, automatic persistence, research completion, summary, grounded
skills Q&A, versioned location editing, reload, mobile width and unauthenticated
rejection. It also submits malformed model output and verifies the previous goal
survives. Research uses an explicitly empty synthetic source: neither this test
nor the local run establishes live search or citation quality. Boundary/unit tests
separately exercise sourced responses, URL previews, cancellation and recovery.

## Exact-model observations

Ollama lists both the exact tag and the optional `elo-` alias. All live attempts in
this continuation used the exact tag. Its observed loaded context was 32,768 tokens;
the application admitted requests against its explicit 16,384-token budget. Requests
with native JSON Schema and `max_tokens` were accepted. Responses separated reasoning
from final JSON, reported token counts, and finished with `stop` even when the final
facts were incorrect. No alias comparison was performed.

The labelled input names a Singapore Software Engineer internship at Synthetic
ExampleCo, Python required, Git preferred, a required computing diploma and an
application deadline of 31 December 2026.

| Live extraction attempt | Observed result |
|---|---|
| Original full UI journey | Seven extraction calls / six corrections; terminal `invalid_output` / `schema_validation`. The browser's old success wait then expired. |
| Direct final-contract extraction, 6.97 s | Invalid date evidence; misclassified employment/qualification facts and omitted the named skills. |
| Experimental schema-in-prompt, 5.47 s | Structurally accepted, but empty skills/qualifications and a schema key used as the career field. |
| Experimental field guidance, 9.63 s | Diploma emitted as a skill, required skills omitted and deadline classified as a start date. |
| Experimental complete unrelated example, 11.03 s | Git promoted to required; wrong employment/date semantics. |
| Separately labelled advert, 11.31 s | Employer changed; qualification/date omitted; invented skill and conflicting priorities. |
| Final full UI journey with only the verified schema fix | Failed in 61.92 s overall after repeated schema-invalid responses and six corrections; terminal provider `unavailable`. No goal was published. |

Direct diagnostic attempts used only synthetic text, did not persist anything and
did not exercise downstream UI/research. Prompt experiments are diagnostic evidence,
not retained production changes or successful evaluations. The original and final
full-stack attempts both failed; later scope successes do not erase them.
After cleanup, the local Ollama endpoint was unreachable, consistent with the final
provider-unavailable error. No further successful inference is claimed.

Final per-attempt timings, token counters, correction records and terminal codes are
retained locally at
`apps/frontend/test-results/career-flow/reports/elo-career-flow-b686821a.json`.
Its uniquely named artifact directory contains the passing mobile screenshot and
the failed local journey's Playwright trace/error context. These artifacts are
ignored by Git; reproduce with:

```sh
python3 infrastructure/testing/run-career-flow.py --mode both --repeat 3
```

## Remaining limits

A successful live extraction → saved goal → research/summary → Q&A → edit → reload
journey is **not established** for the exact 1.5B model. Its downstream stages were
not reached through the UI. Faithful required/preferred distinctions, qualifications,
date semantics and completeness also remain unresolved in direct trials. Native
schema decoding enforces output shape, not factual accuracy. General skill evidence
may be faithful paraphrases under the existing contract; backend validation is not
a semantic completeness proof. Validators and meaningful assertions were preserved.

Live public search was not run: private provider configuration is out of bounds,
and the isolated harness intentionally substitutes empty retrieval. No cloud model,
larger local model, deployment change or private setting was substituted to obtain
a passing result. The original task's live-model completion criterion remains open.
