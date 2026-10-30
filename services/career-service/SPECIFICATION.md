> The current single-workspace LangGraph flow is described in [ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md). It supplies the canonical goal/workspace. CV clarification uses a separate explicit acknowledgement of that exact current goal revision; preview input safeguards below remain unchanged.

# Career Goal previews and exploration

## Current scope

The user's revised scope on 25 October 2026 supersedes the earlier source-storage
plan for J01/J06/J07 previews. J08 exploration and J09 goal confirmation are also
implemented. Raw or extracted source text must not be persisted. The preview endpoints do not perform AI processing or save structured goals.
Implemented AI/provider workflows and data contracts are described in
[ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md). Raw-source recovery stays excluded; J02–J04 structured review and J08/J09
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

- Job descriptions: 8,000 Unicode code points (temporary CV previews remain 20,000). Pasted input can be edited above the
  limit with a clear error; it is neither submitted nor silently truncated.
  Imported over-limit previews are rejected with a paste-one-description fallback.
- URL input: at most 2,048 characters; request at most 16 KiB.
- Website response: at most 2 MiB, standard HTTP/HTTPS ports, identity encoding,
  at most three followed redirects, five-second network operations and robots checks.
  A timed-out request gets one retry within the shared 25-second import deadline;
  redirect robots checks do not multiply that retry. Access restrictions and TLS
  certificate failures are not retried. Timeout messages identify robots.txt versus
  webpage reads; certificate, TLS and other connection failures have distinct safe
  messages. Robots access checks must complete before fetching HTML job pages.
  Pin connections to validated globally routable DNS addresses; reject mixed
  private/public results and private/loopback/link-local/metadata destinations.
  HTTPS verifies the original hostname using TLS and never follows unchecked DNS.
  Redirect destinations are validated and their robots rules checked before the
  job page is requested. Never use supplied credentials or browser-session cookies. Ordinary HTML parsing does not execute scripts.
- Public job API adapters: HTTPS `careers.roblox.com/jobs/{numeric_id}` links,
  `boards.greenhouse.io/{board}/jobs/{id}` and
  `job-boards.greenhouse.io/{board}/jobs/{id}` use Greenhouse's public Job Board API.
  `jobs.lever.co/{site}/{uuid}` and `jobs.eu.lever.co/{site}/{uuid}` use the matching
  global/EU Lever Postings API. No extra keys are needed. API origins and path
  grammars are allowlisted; input cannot choose an arbitrary API host or path.
  Existing IP pinning, verified TLS, size/time limits and one timeout retry apply.
  Reject API redirects, malformed/mismatched jobs and unreadable/over-limit descriptions.
  Greenhouse identity is bound to the board and numeric ID; returned hosted URLs
  must match the board/job path, while provider-published custom employer URLs must
  be public HTTPS destinations and are never followed. Roblox retains its exact
  employer-host/path check. Lever requires the exact job ID and hosted URL host/path.
  Keep title and available metadata, Greenhouse description or Lever description,
  requirements/benefits lists, closing and salary-description sections. Application
  forms/questions are excluded. Preserve the input job URL and API provenance notice.
  No application submissions, paid research or LLM calls are made by these previews.
  Sources: [Greenhouse](https://docs.greenhouse.io/job-board.html),
  [Lever](https://github.com/lever/postings-api).
- HTTP errors distinguish authentication (401), rejected automated access (403),
  missing/expired links (404/410), request throttling (429) and upstream failures.
  A 403 does not claim sign-in is required. Recognisable HTML access verification,
  CAPTCHA and sign-in pages are rejected even with status 200. URL import errors
  offer direct paste/document actions while retaining existing drafts.
- JavaScript fallback: a successful, robots-permitted HTML page with a short script
  shell or a JavaScript-required message may request one isolated Playwright Chromium
  render. Existing JobPosting data and ordinary static pages avoid the browser.
  Access restrictions, challenges, authentication and HTTP failures do not trigger
  rendering. The renderer revalidates destinations and robots rules, including
  redirects, and fulfils all supported browser GET requests through the existing
  public-IP-pinned fetcher. No browser cookies, Authorization or Set-Cookie headers
  are forwarded. Original CORS and content-security headers are retained.
  Service workers, WebSockets, submissions, frames and binary assets
  are blocked. A closed proxy and disabled browser DNS prevent direct HTTP egress.
  Limits: 24 resource/robots reads (each with at most one timeout retry), 8 MiB total
  fetched data, 2 MiB per response/rendered HTML, at most three redirects per chain,
  one renderer per container and the original shared 25-second import budget.
  Missing browser binaries, unsupported dynamic requests or incomplete rendering
  return paste/upload fallback. Availability is best effort, including for Indeed.
  No model calls or persistent preview storage are added.
- HTML extraction prefers one JobPosting JSON-LD description, otherwise a
  description/main/article/body text preview with navigation/scripts excluded.
  Available JobPosting company, job location, work arrangement, employment type,
  industry, qualifications, skills and responsibilities are preserved as labelled text.
  This is best-effort text preparation, not semantic job/skill interpretation;
  users review completeness and remove unrelated content. A URL cannot guarantee
  a real job listing. Blocked/login/paywall/CAPTCHA or inaccessible content gets paste/upload fallback.
  JavaScript pages may use the bounded renderer above; access checks are preserved.
- Document: one file, 10 MiB; multipart total at most 10 MiB + 64 KiB. Limit fields,
  files, formats and actual content. The gateway permits 11 MiB only on the upload
  route. PDF: unencrypted, at most 100 pages; scanned/empty/partial pages are
  explained. DOCX: safe XML, at most 1,000 ZIP members and 32 MiB uncompressed;
  reject encrypted/macro documents, never extract archive members to disk or
  follow external relationships. TXT: UTF-8 (optional BOM), no binary controls.
- Two imports process concurrently per API process; excess work gets 429. Parsing
  runs in disposable child processes with a 20-second timeout; URL imports have a
  30-second worker timeout and a 35-second gateway read timeout to accommodate the
  bounded retry. Static/document workers retain Linux 256 MiB address-space and 12 CPU-second
  limits. The separate renderer uses a 12 CPU-second and 8 MiB per-file limit;
  Chromium's virtual address reservations preclude the static worker's address-space
  limit. The container bounds total memory at 768 MiB, processes/threads at 256 and
  temporary storage at 128 MiB. A container init reaps orphaned descendants. The renderer receives only PATH, private HOME/TMPDIR
  and the browser installation path; provider keys/session tokens are not inherited.
  Parent-owned temporary profiles are removed after the renderer process group and detached browser descendants
  are killed/reaped, including on timeout. Chromium runs as the existing non-root user
  with its sandbox enabled, all capabilities dropped and no-new-privileges retained.
  The version-pinned Playwright Docker seccomp profile permits namespace creation
  and namespace-local chroot. See [deployment notes](../../infrastructure/docker/README.md#career-url-preview-browser).

## Storage and Docker

The Career container is non-root, read-only, on the backend network only and has
backend-only AI settings and a scoped MongoDB connection for J08/J09. Private `/tmp` is a bounded 128 MiB tmpfs with
0700 access for the service user. Multipart files use generated spool names and
are always closed by the form context on success/failure. No named upload volume
or original-file retention is introduced. Request/child buffers expire with the
request/process; cleanup after abrupt termination is handled by tmpfs/container
lifecycle. TMPDIR can be changed for direct service runs; keep it private.

## Structured review boundary — J02–J04

Explicit JD extraction now saves a structured review with metadata, skills,
non-skill conditions and provenance in one effective goal content object. The shared chat
loads that owner-checked review by ID/version; it does not accept raw JD text or
client-authored context. Supporting summaries and labelled inferences remain
permitted. Saved review editing, reclassification and confirmation follow
[ANALYSIS_CONTRACTS.md](ANALYSIS_CONTRACTS.md). Preview parsing still makes no AI
calls or database writes. Sources remain transient, and reload restores only
structured information. J05 importance review and J10 advisory exploration skills use this same review
boundary. J12/J13 research orchestration, versioned storage and review UI are
implemented with Gemini/Brave source adapters and an injectable synthetic test boundary. Unconfigured or unavailable acquisition preserves previous goal/research state.
Gap analysis and roadmap generation remain future work.

## Canonical confirmation for CV review

The canonical goal stays the single active Career authority. Its automatic save is separate from an explicit CV-review acknowledgement. Confirmation stores the exact goal ID/version, selection version and projection hash in `career_state`, with acknowledgement time and bounded idempotency receipts. It does not duplicate goal content or advance goal/selection versions. Current and pinned context reads revalidate all identities, including edits before pointer updates. Stale confirmation requires user review again; earlier source-bound CV answers remain saved.

Projection preserves all bounded goal skills/requirements, their provenance and AND/OR groups. Qualification conditions may support neutral education clarification. Other categories remain generic requirements with conservative exact-description relevance; the service does not infer eligibility/location from unrelated CV text. Unknown values stay unknown. See the [Career README](README.md#explicit-cv-clarification-context--c-series-integration) for endpoints and the generated contract for exact schemas.

CV context is read through its owner-authenticated API. The Career projection has a 512 KiB streaming/document admission bound, preserves complete evidence within that bound and rejects oversize clearly without truncation. It preserves source IDs rather than claiming registry equivalence or assessed mastery. Older UUID target records remain retained history; canonical storage metadata preserves compatibility with the old uniqueness index without index deletion or data migration.
