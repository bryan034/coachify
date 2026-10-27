# Career previews and reviewed target context

## Current scope

The current task extends temporary J01/J06/J07 previews with a reviewed target
foundation for J09 and the SCRUM-310 Career/CV boundary. Full raw or extracted JD
text must not be persisted. Specific-job requirements are manually reviewed;
exploration entries are user guidance. Neither mode claims AI generation,
semantic validation, employer verification or a complete J02–J05/J09 feature.

Career owns input processing. The frontend uses `/career-goal`, directly below
Home, with three methods. Each draft stays in React memory and survives switching
methods while the page remains mounted. Auth/account changes remount or remove
private state. Imports are aborted/ignored after method switch or unmount. Sidebar
link navigation warns before discard; browser refresh/tab close uses beforeunload
where supported. Reload/leave loses input. No source data goes into localStorage,
sessionStorage, Next.js server caches or MongoDB. Browser document history/undo
behaviour is browser-managed, not a saved Coachify draft.

## API and authentication

The preview routes and `/api/v1/career/targets` routes are publicly routed. `/health` is container-only. Each import validates the session by
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

The Career container is non-root and read-only. It joins the backend network for
service APIs and the private database network for its own MongoDB connection.
`MONGODB_URI` connects to its own database; `MONGODB_DATABASE` defaults to
`coachify_career`. No AI key is needed. Private `/tmp` is a bounded 32 MiB tmpfs with
0700 access for the service user. Multipart files use generated spool names and
are always closed by the form context on success/failure. No named upload volume
or original-file retention is introduced. Request/child buffers expire with the
request/process; cleanup after abrupt termination is handled by tmpfs/container
lifecycle. TMPDIR can be changed for direct service runs; keep it private.

## Reviewed structured target boundary

Career owns the physical `career_goals` collection, as named in SCRUM-310, plus
operational `career_target_selections`. Targets use opaque UUIDs and the canonical
Profile account ID. No service reads another service's database.

Creation saves a version-1 draft with role/field, bounded optional company,
location, seniority, URL, interests/preferences, at most 40 structured skills and
20 optional qualification/date conditions.
Specific-job skill evidence must be a verbatim substring of the transient reviewed
source, bounded to 500 characters per item. This verifies excerpt membership, not
semantic correctness. The full source is excluded from persisted records and
mutation fingerprints. `origin` and `requirements_source` are server-owned
`user_reviewed_jd` or `user_guidance`; `generation_version` is `manual-v1`.
Skill IDs use the shared NFKC, collapsed-whitespace and casefold normalization.
Canonical duplicates are rejected. Non-skill conditions remain separate from
skills. Each condition has a bounded label/description, one to four distinct CV
item kinds and one to five specific subject phrases (2–120 characters each).
Phrases must occur in the condition; for a specific job they must occur in its
bounded exact JD excerpt. CV uses the kind and phrase together to establish
relevance, rather than asking every education/work record about every condition.
This matching is conservative text relevance, not semantic eligibility checking.
Exploration conditions are labelled personal guidance and require no JD.

Condition IDs are deterministic UUIDs scoped to the immutable target and normalized
kind/label. Duplicate normalized kind/labels are rejected. The server owns IDs and
origin. Older targets without conditions read as an empty list; no backfill or
data migration occurs. Empty-condition creation retains the previous mutation
fingerprint, allowing retries of older requests.

A separate expected-version confirmation changes a draft with at least one skill
or condition to confirmed
version 2. Empty drafts cannot become ready context. Target content is immutable;
changing reviewed content creates a new target and leaves earlier targets intact.
Confirmation never selects. Selection requires the exact confirmed version and
an expected selection version. No-op selection preserves that version. Owner
selection records use atomic MongoDB compare-and-set on a revision, with durable
mutation fingerprints; replay returns the current selection and cannot restore an
older one. Selection history is bounded to 10,000 mutation receipts per owner,
then further mutation requests fail explicitly. Target documents use deterministic
owner-and-mutation UUIDs for safe creation retries. Concurrent confirmation uses
whole-document version comparison. These operations work on standalone MongoDB
without requiring transactions or multi-document atomic publication.

Selected context contains ID, immutable target version, type, confirmed flag,
canonical skill IDs, bounded conditions, role/field and selection version. A
condition-only context has an empty skill-ID list. Both context routes require
current selection; target-specific reads also check the supplied version. A second
selection read fences concurrent switches. Callers still revalidate this fence
before publishing their own results. Old target snapshots remain readable but
cannot masquerade as current context. No target operation starts assessment,
changes saved CV evidence or regenerates an existing result.

Target payloads are strict JSON with a 256 KiB body bound, at most 20,000 source
characters, and no unknown/server-owned fields. This route-specific limit leaves
existing 16 KiB URL preview and document upload limits unchanged. Validation errors
never echo source values. Authentication runs asynchronously before Mongo work in
a separate eight-slot worker limiter. Mongo calls have bounded connection/server
selection/socket timeouts. Absent configuration or storage failures give sanitized
503 responses; initialization is retried on later requests without a memory
fallback, while preview-only use remains available.

Target history uses a fixed 20-row page, with one database look-ahead record to
produce `next_cursor`. Mongo applies owner filtering, descending creation-time/ID
seek ordering and a 21-row limit before materializing records. Opaque cursors
are bounded to 512 characters and contain only the creation timestamp and target
UUID. Cursor validation checks their types, UTC date format and an exact
owner-scoped anchor; malformed, tampered or foreign-owner anchors receive a
sanitized 422. Stable seek pagination avoids duplicate/skipped older rows when
new targets arrive between page reads. `selected_target` is returned separately
so an older current selection remains visible. No target quota or history deletion
is introduced.

## Future boundary

AI target interpretation, generated exploration guidance, automatic non-skill
interpretation, interview research and gap analysis remain separate work. Future provider
integration must operate on transient source and persist only agreed structured
fields and bounded provenance. Do not reintroduce raw JD persistence to fulfil
older source-recovery criteria.
