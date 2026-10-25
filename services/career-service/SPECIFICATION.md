# Career Goal previews and exploration

## Current scope

The user's revised scope on 25 October 2026 supersedes the earlier source-storage
plan for J01/J06/J07 previews. J08 exploration and J09 goal confirmation are also
implemented. Raw or extracted source text must not be persisted. The preview endpoints do not perform AI processing or save structured goals.
Internal AI/provider and data-contract foundations are described in
[ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md). Saved-source recovery and JD interpretation criteria remain deferred; J08/J09
structured exploration/goal persistence is implemented separately.

Career owns input processing. The frontend uses `/career-goal`, directly below
Home, with three methods. Each draft stays in React memory and survives switching
methods while the page remains mounted. Auth/account changes remount or remove
private state. Imports are aborted/ignored after method switch or unmount. Sidebar
link navigation warns before discard; browser refresh/tab close uses beforeunload
where supported. Reload/leave loses input. No preview source data goes into localStorage,
sessionStorage, Next.js server caches or MongoDB. Browser document history/undo
behaviour is browser-managed, not a saved Coachify draft.

## API and authentication

The original preview POST routes remain available; J08/J09 routes are listed in
the service README and generated OpenAPI contract. `/health` is container-only. Each import validates the session by
calling Profile's existing `/api/v1/profile/auth/session` over the private backend
network, forwarding the bearer. It then reads `/api/v1/profile` and requires the
canonical `onboarding_complete=true` marker before processing (otherwise 403).
Require a verified account, reject revoked or
invalid sessions and fail closed on Profile outages/malformed responses. No client
owner ID, shared database access, new auth bypass or new Google flow is used.

No-store headers apply to success/errors. Validation and processing errors avoid
returning traceback/secret/source internals. Gateway and Career access logs are
disabled for imports; request bodies/URL fields/documents are not logged.

## Limits and processing

- Descriptions: 20,000 Unicode code points. Pasted input can be edited above the
  limit with a clear error; it is neither submitted nor silently truncated.
  Imported over-limit previews are rejected with a paste-one-description fallback.
- URL input: at most 2,048 characters; request at most 16 KiB.
- Website response: at most 2 MiB, standard HTTP/HTTPS ports, identity encoding,
  at most three followed redirects, bounded network operations and robots checks.
  Pin connections to validated globally routable DNS addresses; reject mixed
  private/public results and private/loopback/link-local/metadata destinations.
  HTTPS verifies the original hostname using TLS and never follows unchecked DNS.
  Redirect destinations are validated and their robots rules checked before the
  job page is requested. Never use supplied credentials, cookies or page scripts.
- HTML extraction prefers one JobPosting JSON-LD description, otherwise a
  description/main/article/body text preview with navigation/scripts excluded.
  This is best-effort text preparation, not semantic job/skill interpretation;
  users review completeness and remove unrelated content. A URL cannot guarantee
  a real job listing. Blocked/login/paywall/CAPTCHA/JS-only or inaccessible content
  gets fallback, not circumvention.
- Document: one file, 10 MiB; multipart total at most 10 MiB + 64 KiB. Limit fields,
  files, formats and actual content. The gateway permits 11 MiB only on the upload
  route. PDF: unencrypted, at most 100 pages; scanned/empty/partial pages are
  explained. DOCX: safe XML, at most 1,000 ZIP members and 32 MiB uncompressed;
  reject encrypted/macro documents, never extract archive members to disk or
  follow external relationships. TXT: UTF-8 (optional BOM), no binary controls.
- Two imports process concurrently per API process; excess work gets 429. Parsing
  and URL work run in disposable child processes with a 20-second timeout, Linux
  256 MiB address-space and 12 CPU-second limits. This also bounds DNS/parser
  stalls. Processes are killed on timeout and no background operations persist.

## Storage and Docker

The Career container is non-root, read-only, on the backend network only and has
backend-only AI settings and a scoped MongoDB connection for J08/J09. Private `/tmp` is a bounded 32 MiB tmpfs with
0700 access for the service user. Multipart files use generated spool names and
are always closed by the form context on success/failure. No named upload volume
or original-file retention is introduced. Request/child buffers expire with the
request/process; cleanup after abrupt termination is handled by tmpfs/container
lifecycle. TMPDIR can be changed for direct service runs; keep it private.

## Future boundary

The provider adapter and structured schemas are now defined. Later J stories
will connect confirmed source in memory to the internal adapter. Persist only the approved
structured information and agreed provenance. Do not quietly reintroduce source
text persistence to fulfil earlier criteria. The shared chat route supports J08 adaptive career exploration and temporary
J02/J03 JD extraction/review. Reviewed JD text is sent only on explicit extraction
or chat actions. Outputs are Pydantic-validated candidates with source grounding;
changes require user approval. No canonical skill registry, confirmed skill
persistence or J04/J05 condition editing is supplied by this temporary workflow.

J08 optional-CV exploration and J09 confirmation are implemented as described in
[ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md); this document retains the existing
preview/parser safeguards. No source text is written to domain records.
