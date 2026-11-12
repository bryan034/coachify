# elo shared contracts

Bundled explicit skill aliases and canonical identities used by Profile, CV, Career and Assessment. Service-owned domain logic stays inside its service. `runtime.py` supplies the new Assessment/Roadmap services' bounded authenticated HTTP/model transport and CAS/lease persistence primitives.

`skill_groups.py` decides each skill's display category from its name (the supplied category is only a fallback): AI & ML, Languages, Data & analytics, Cloud & DevOps, Technical coding, Software & project management, Design, Communication & leadership, Business & finance, or Other skills. Every service returns the same `skill_groups` map, so the Skills Profile and Career Goal share one taxonomy.

Install this package before installing a service locally, or set `PYTHONPATH` to this directory for repository tests. Production Docker builds install the same package from the monorepo root. Registry changes are reviewed code changes and carry a new version. Unknown names remain unresolved; model suggestions cannot mutate the registry.

The shared API factory explicitly names error responses, keeping Assessment and
Roadmap OpenAPI descriptions stable across Python 3.12 and newer interpreters.

Examples: Python → `language.python`; SQL / Structured Query Language → `language.sql`. Preserve legacy `skill_id`, source item IDs and original wording; compare `canonical_skill_id`, never bare names or incompatible old mapping-version labels. Matching identity does not establish matching proficiency, duration or scope.

Assessment/Roadmap model endpoints are independently configured using each service's
`*_LLM_BASE_URL`, `*_LLM_MODEL`, `*_LLM_API_KEY` and explicit development
`*_LLM_ALLOW_HTTP` flag. Local requests omit credentials and serialize per model
instance. All providers (OpenRouter, local, DeepSeek)
receive JSON Output with authoritative schema/domain checks after generation.
Synthetic endpoint/credential/concurrency tests live in `tests/test_model.py`.

`model_sdk.py` supplies bounded sync/async OpenAI SDK transport for all four AI
services, including Career's existing adapter. It disables SDK retries, prevents
redirects, bounds rejection bodies to 16 KiB and leaves injected HTTP clients open.
Services retain their own successful-response limits, validation and retry policy.
Vendor extensions use `extra_body`; local requests omit Authorization.

## Model response errors

`model_errors.raise_for_completion_error` checks an already-decoded provider envelope
for top-level or selected-choice errors before content is trusted. CV, Career,
Assessment and Roadmap call it after their existing bounded response reads.
It performs no I/O, retry or output repair. Actual transport status remains distinct
from a validated embedded error code. Only fixed reason/parameter labels and a
validated numeric code leave the helper; private provider prose, CV/JD text and
arbitrary metadata are discarded. `error: null` in successful Responses API
results is allowed. Bounded OpenRouter `metadata.raw` is classified one level deep.

This handles [OpenRouter errors delivered inside HTTP 200](https://openrouter.ai/docs/api_reference/errors-and-debugging),
which otherwise look like missing completion fields. Synthetic coverage includes
privacy, malformed/oversized error details, unchanged successful output, and
provider failures bypassing schema-correction retries. Permanent payment/quota failures
do not enter Career's cooldown loop; temporary rate limits retain the bounded
provider `Retry-After` value.
