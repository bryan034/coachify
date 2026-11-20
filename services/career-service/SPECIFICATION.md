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
behaviour is browser-managed, not a saved elo draft.

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
- Website response: at most 2 MiB, standard HTTP/HTTPS ports, identity, gzip or
  deflate encoding (decompressed output is also capped at 2 MiB; other encodings
  and corrupt bodies are rejected), at most three followed redirects and
  five-second network operations. A timed-out request gets one retry within the
  shared 25-second import deadline, including at a redirect destination. Access
  restrictions and TLS certificate failures are not retried. Certificate, TLS and
  other connection failures have distinct safe messages.
- User-requested fetches: an import reads one page a person pasted, so it is not a
  crawler and does not read or apply robots.txt. Requests identify as
  `Mozilla/5.0 (compatible; eloPreview/1.0)`, prefer HTML and send
  `Accept-Language: en-SG,en`. Sites decide access on their own servers: their
  refusals and challenges below always stop the import.
- Blocked sites: page 401/403/429 responses and sign-in, captcha or verification
  pages return: the information could not be extracted from this website; copy and
  paste the job description instead. The job aggregators LinkedIn, Indeed,
  Glassdoor and JobStreet, whose terms forbid automated reading, are refused before
  any network request (including as redirect or renderer destinations) with the
  same first sentence followed by a site-named explanation, for example: LinkedIn
  does not allow its job listings to be read automatically; open the job on
  LinkedIn, copy the description and paste it here. The Career Goal page shows the
  site-specific guidance when present, with a paste option.
  Pin connections to validated globally routable DNS addresses; reject mixed
  private/public results and private/loopback/link-local/metadata destinations.
  HTTPS verifies the original hostname using TLS and never follows unchecked DNS.
  Redirect destinations are validated before the job page is requested. Never use supplied credentials or browser-session cookies. Ordinary HTML parsing does not execute scripts.
- Public job API adapters: HTTPS `careers.roblox.com/jobs/{numeric_id}` links,
  `boards.greenhouse.io/{board}/jobs/{id}` and
  `job-boards.greenhouse.io/{board}/jobs/{id}` use Greenhouse's public Job Board API.
  `jobs.lever.co/{site}/{uuid}` and `jobs.eu.lever.co/{site}/{uuid}` use the matching
  global/EU Lever Postings API. MyCareersFuture job links
  (`[www.]mycareersfuture.gov.sg/job/[{category}/][{slug}-]{32-hex uuid}`) use the
  public `api.mycareersfuture.gov.sg/v2/jobs/{uuid}` job API. No extra keys are needed. API origins and path
  grammars are allowlisted; input cannot choose an arbitrary API host or path.
  Existing IP pinning, verified TLS, size/time limits and one timeout retry apply.
  Reject API redirects, malformed/mismatched jobs and unreadable/over-limit descriptions.
  Greenhouse identity is bound to the board and numeric ID; returned hosted URLs
  must match the board/job path, while provider-published custom employer URLs must
  be public HTTPS destinations and are never followed. Roblox retains its exact
  employer-host/path check. Lever requires the exact job ID and hosted URL host/path.
  Keep title and available metadata, Greenhouse description or Lever description,
  requirements/benefits lists, closing and salary-description sections.
  MyCareersFuture requires the exact UUID, a non-empty description and a returned
  MyCareersFuture HTTPS job URL ending in that UUID; it keeps company, region,
  employment type, position level, work arrangement, job category, minimum
  experience, salary range, skill tags and other requirements, and omits company,
  address and salary whenever the employer marked them hidden. Application
  forms/questions (including MyCareersFuture screening questions) are excluded. Preserve the input job URL and API provenance notice.
  No application submissions, paid research or LLM calls are made by these previews.
  Sources: [Greenhouse](https://docs.greenhouse.io/job-board.html),
  [Lever](https://github.com/lever/postings-api),
  [MyCareersFuture](https://www.mycareersfuture.gov.sg).
- HTTP errors distinguish authentication (401), rejected automated access (403),
  missing/expired links (404/410), request throttling (429) and upstream failures.
  A 403 does not claim sign-in is required. Recognisable HTML access verification,
  CAPTCHA and sign-in pages are rejected even with status 200. URL import errors
  offer direct paste/document actions while retaining existing drafts.
- JavaScript fallback: a successful HTML page with a short script
  shell or a JavaScript-required message may request one isolated Playwright Chromium
  render. Existing JobPosting data and ordinary static pages avoid the browser.
  Access restrictions, challenges, authentication and HTTP failures do not trigger
  rendering. The renderer revalidates destinations, including redirects and blocked
  job sites, and fulfils all supported browser GET requests through the existing
  public-IP-pinned fetcher. No browser cookies, Authorization or Set-Cookie headers
  are forwarded. Original CORS and content-security headers are retained.
  Service workers, WebSockets, submissions, frames and binary assets
  are blocked. A closed proxy and disabled browser DNS prevent direct HTTP egress.
  Limits: 64 resource reads (each with at most one timeout retry), 16 MiB total
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
- Import parsing runs in disposable child processes with a 20-second timeout; URL imports have a
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
implemented with model/Brave source adapters and an injectable synthetic test boundary. Unconfigured or unavailable acquisition preserves previous goal/research state.
The separate Assessment and Roadmap services now own comparison and user-directed planning; Career only supplies versioned inputs. See their service specifications.

## Canonical confirmation for CV review

The canonical goal stays the single active Career authority. Its automatic save is separate from an explicit CV-review acknowledgement. Confirmation stores the exact goal ID/version, selection version and projection hash in `career_state`, with acknowledgement time and bounded idempotency receipts. It does not duplicate goal content or advance goal/selection versions. Current and pinned context reads revalidate all identities, including edits before pointer updates. Stale confirmation requires user review again; earlier source-bound CV answers remain saved.

Projection preserves all bounded goal skills/requirements, their provenance and AND/OR groups. Qualification conditions may support neutral education clarification. Other categories remain generic requirements with conservative exact-description relevance; the service does not infer eligibility/location from unrelated CV text. Unknown values stay unknown. See the [Career README](README.md#explicit-cv-clarification-context--c-series-integration) for endpoints and the generated contract for exact schemas.

CV context is read through its owner-authenticated API. The Career projection has a 512 KiB streaming/document admission bound, preserves complete evidence within that bound and rejects oversize clearly without truncation. It preserves source IDs rather than claiming registry equivalence or assessed mastery. Older UUID target records remain retained history; canonical storage metadata preserves compatibility with the old uniqueness index without index deletion or data migration.

## Role competence targets

Career prepares each skill's `competence_target` (level, basis, a short explanation, public source URLs and, when research rated it, `employer_demand`, up to two `reported_examples` with their source URL, and `rating_reason`) on the same 1–10 competence scale as CV: 1 not competent, 5 independent with understanding, 10 the most complex work. After public research, a model stage decides the level for every non-user-declared goal skill from public role metadata, each skill's priority, stated proficiency, stated experience and the employer's short stated context for that skill, validated findings, and its own knowledge of the role. It returns a whole-number level, what the employer expects (`employer_demand`), up to two `reported_examples` that each restate one finding of the report (rejected when they cite an unknown finding), the reason for the level (`rationale`) and finding references, persisted in `intelligence.skill_levels`. No CV, private chat or full JD text enters this rating call.

The model is guided by a weighted reference score (a guideline, not a rule), computed in `app/domain/competence.py` (whose tables hold every weight) and sent with each skill as `reference_level` and `reference_factors`:

- Baseline from the role band, matched on seniority level then title: internship 5, entry/graduate 5, mid 6, senior 7, lead/staff/manager 8, principal/director 9; otherwise by employment type (5 for every type).
- Skill adjustments: essential (required or preferred) +2, nice to have +1; stated experience up to 12 months +1, 13–36 months +2, 37+ months +3.
- Research adjustments (fresh research only): discussed in findings from 3+ distinct public sources +1; mentioned in interview findings +1. A finding mentions a skill when it contains the skill's whole name as a phrase.

The reference does not judge how selective the hiring is or whether a skill defines the role; the rating model weighs both. There is no seniority cap: the reference and the model's level are clamped only to 1–10.

The model starts from that reference but decides the level against the real hiring bar (the reference is not a ceiling; selective internships often screen their defining skills at 7–9), moving away from it when the evidence or the role justifies it. Without a fresh model rating (before research, on rating failure, or once research expires), the reference is the target. Employer-stated wording bounds either: expert 9, advanced/proficient 7 and intermediate 5 are floors; beginner/basic is a ceiling of 3. Other origins state no bound.

Basis is `job_description` when a stated bound sets the level, `research` when the level rests on cited public sources, otherwise `inferred`. The explanation is short: any stated bound, then the model's rationale when rated, or the role facts behind the reference (without weights) when not. Ratings saved before the three parts existed still give their rationale. Saving a goal reuses a skill's saved target only when its wording, origin, priority, proficiency, experience and the goal's role, seniority and employment type are unchanged. Rating failure preserves completed research and the reference targets; cached summary rebuilds reuse saved ratings without another call. A rating stays tied to the skill name, so editing a skill's priority or experience after research does not re-rate it until the next research run. These remain planning estimates, never employer pass marks. Assessment pins goal/research versions and owns the comparison.

The canonical `GET /goals/current`, workspace and Assessment handoff reads use the
same calibrated target projection. Reading the current goal cannot disagree with
its workspace simply because public research enriched its displayed target.
