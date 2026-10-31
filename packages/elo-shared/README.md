# elo shared contracts

Bundled explicit skill aliases and canonical identities used by Profile, CV, Career and Assessment. Service-owned domain logic stays inside its service. `runtime.py` supplies the new Assessment/Roadmap services' bounded authenticated HTTP/model transport and CAS/lease persistence primitives.

Install this package before installing a service locally, or set `PYTHONPATH` to this directory for repository tests. Production Docker builds install the same package from the monorepo root. Registry changes are reviewed code changes and carry a new version. Unknown names remain unresolved; model suggestions cannot mutate the registry.

The shared API factory explicitly names error responses, keeping Assessment and
Roadmap OpenAPI descriptions stable across Python 3.12 and newer interpreters.

Examples: Python → `language.python`; SQL / Structured Query Language → `language.sql`. Preserve legacy `skill_id`, source item IDs and original wording; compare `canonical_skill_id`, never bare names or incompatible old mapping-version labels. Matching identity does not establish matching proficiency, duration or scope.

Assessment/Roadmap model endpoints are independently configured using each service's
`*_LLM_BASE_URL`, `*_LLM_MODEL`, `*_LLM_API_KEY` and explicit development
`*_LLM_ALLOW_HTTP` flag. Local requests omit credentials and serialize per Model
instance. Gemini retains native JSON Schema; compatible local/DeepSeek providers
receive JSON Output with authoritative schema/domain checks after generation.
Synthetic endpoint/credential/concurrency tests live in `tests/test_model.py`.
