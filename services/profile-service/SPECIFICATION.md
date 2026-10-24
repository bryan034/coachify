# Profile service rules

P01–P16 are implemented. Jira acceptance criteria remain the product source of
truth. The [README](README.md) lists available endpoints, and the
[OpenAPI contract](../../contracts/api/profile.yaml) defines request/response fields.

## Background and education — P01–P03, P07/P08

- Occupational status is one of Student, National Service, Unemployed or Employed;
  no status is inferred from the CV.
- Students are asked where/what they are studying. Other statuses are asked where/
  what they last studied and do not need a current study year. Non-students may
  have no applicable previous education; a named course is optional.
- Categories are Secondary School, Institute of Technical Education,
  Polytechnic / Diploma, Junior College and University.
- School suggestions come from bundled reference snapshots, not MongoDB or live
  catalogue calls. Missing schools can be entered manually; suggestions do not
  establish enrolment, accreditation or eligibility.
- Catalogue selections use a saved ID; the server supplies the name and source
  date. Custom names and courses are trimmed, limited to 300 characters and reject
  blank/control-character values. Combined programme wording is preserved.
- Current study years are positive whole numbers, including years beyond four;
  labels reflect school category. Calendar time does not advance the year.
- Omitted fields stay unchanged. An optional course or a non-student institution
  can be cleared explicitly; changing status/category retains existing education
  and asks for review before reusing it in the new context.
- Confirmation uses `confirm_education_context`. A mismatched catalogue school or
  study year must be corrected for the new category. Institution changes retaining
  a course/year can also require review.
- `education.study_year` preserves the declaration. `current_study_year` is unset
  for non-students and while education review is pending.

## Application date — P04

- Store a real `YYYY-MM-DD` calendar date, not a timestamp. New saves must be
  strictly after today in the device's current IANA time zone.
- The browser sends `time_zone` at submission; the server validates it. Missing or
  invalid zone context returns a recoverable error with no silent fallback.
- Recheck at submission, including after midnight or a device-zone change. Do not
  shift the saved date through UTC or daylight-saving conversions.
- An elapsed saved deadline stays visible and is flagged before new planning.
  Unrelated profile edits and initial education onboarding remain available.
- An unchanged valid date does not rewrite its recorded zone or planning revision.

## Weekly availability — P05

- Normal weekly hours must be finite JSON numbers greater than 0 and at most 168.
  Fractions are preserved as JSON numbers/MongoDB doubles without whole-hour or
  fixed-step rounding. Booleans and numeric strings are rejected.
- No budget is inferred from occupational status or missing input.
- Lowering the base budget can invalidate current/future reduced periods. Keep
  those periods unchanged, identify them, and require resolution before planning
  that uses them. Historical periods alone do not block a future plan.

## Reduced availability — P06

- Each period has a stable ID, inclusive start/end dates and a weekly-hours rate.
  Dates use Asia/Singapore independently of the deadline's device time zone.
- New/edited periods cannot end before Singapore today. End must be on/after
  start. Historical periods remain visible and can be deleted.
- Require a saved normal budget. Reduced hours are finite, at least 0 and strictly
  below that budget. Zero means no capacity on covered dates.
- Reject inclusive overlaps. Adjacent and same-day ranges are valid; editing a
  period excludes its own ID from overlap checks.
- A reduced weekly rate replaces the normal rate, rather than subtracting from it.
  Calendar weeks are Monday–Sunday; spread weekly hours over seven calendar dates
  for partial windows. With 14 normal hours/week and two days at 7 hours/week,
  capacity is 12 hours over that seven-day window. Normal capacity resumes outside
  periods. Rational arithmetic is converted to a JSON number only at the end.

## Saving, ownership and planning handoff

- Private data is owner-scoped through a revocable Coachify session. Google ID
  tokens are accepted only during nonce-bound account access, never directly on
  private profile endpoints. Development accounts also require explicit sign-in.
- Changed saves create immutable full documents in `profile_versions`. The unique
  owner/version boundary prevents stale or overlapping concurrent writes.
- All writes use `expected_version`; stale writes return 409. Validation errors
  return 422 and storage failures 503. Failed/stale UI saves retain drafts.
- Planning writes additionally require an `Idempotency-Key` of 1–128 letters,
  digits, underscores or hyphens. Use a new key for new input and the same key,
  method, target and body for an uncertain-response retry. Different input with
  the same reserved key returns 409.
- Changed-write receipts commit inside profile snapshots. `profile_mutations`
  reserves keys across changed/no-op saves and records completed no-ops. An
  incomplete reservation is retryable; standalone MongoDB needs no transaction.
- Valid unchanged saves and repeated removals create no extra version/review
  changes. A replay returns the latest owner profile without reverting newer data.
- Planning forms retain drafts when loading the latest saved values, and planning
  saves preserve unrelated unsaved education input.
- Planning snapshots include source profile version, planning revision, declared
  inputs, validation zone/date, Singapore capacity date, units, inclusive bounds
  and proration rules. Optional capacity windows require both start and end.
- Missing/elapsed values and applicable period conflicts appear as readiness
  issues. Preferences are independent of initial education onboarding.
- Future Roadmap consumers must retain the snapshot and compare its source
  version/revision. Generation, scheduling and cross-service stale-plan
  notifications remain unimplemented.

## Account access, environment and verification — P09–P12, P15/P16

- Profile owns accounts, sessions and verification behind `/api/v1/profile`; no
  new application microservice is introduced. MongoDB collections are `accounts`,
  `auth_flows`, `auth_sessions` and `auth_limits`. Unique identity/owner indexes
  prevent duplicate registration and conflicting legacy mappings; TTL indexes clean
  expired flows, sessions and rate counters.
- `APP_ENV` is explicitly `development` or `production`; the default is production.
  `AUTH_MODE=local_test` is development-only and uses email/password accounts in a
  separate namespace. Its chooser only prefills an email, never authenticates.
  `email` enables email/password access; `google` additionally enables Google and
  requires its public client ID in production. Invalid/missing production config
  fails startup; errors never enable local fallback. Query/header/browser mode flags
  cannot change the backend mode. Mode changes require fresh explicit sign-in.
- New email accounts require normalized, case-insensitive email and a 12–128
  character password. Passwords are not trimmed. Argon2id stores only hashes (19 MiB,
  two iterations, one lane); invalid password and unknown email return the same 401.
  Credential requests are bounded to ten per identity in a 15-minute window, with a
  gateway IP rate limit. Password reset is not part of this iteration.
- Google verifies audience, expiry, official issuer and the per-attempt nonce. New
  Google accounts also require a verified email claim and Coachify OTP verification.
  Stable `google:<subject>` identity retains existing Google-owned profiles. Earlier
  Google accounts missing email are upgraded only after that exact subject is
  verified, then complete Coachify OTP verification without changing their owner. Email,
  local and Google identities never auto-link by matching name/email.
- Registration creates a pending server-owned account ID. No private token/session
  is usable before `email_verified=true`. Duplicate registration cannot replace a
  password or profile; pending accounts resume through credential-verified sign-in.
  The same registration attempt is idempotent; concurrent different registrations
  for one identity produce one winner and one conflict.
- Start access using random `flow_id`/`attempt_id`, an increasing generation and
  `intent`. The server returns a nonce. Complete with those IDs plus a random
  `session_token`, and either email/password (optional display name on registration)
  or a Google credential. The browser generates 256-bit secrets with Web Crypto.
  Provider attempts initially last ten minutes; a proved credential awaiting email
  verification has a 30-minute access window. New generations supersede old attempts.
- Completion binds account, session hash, mode and a keyed request fingerprint to
  the access attempt. Changed retries, expired/cancelled/superseded callbacks and
  cross-account verification are rejected. An identical committed request can
  recover its own result without creating another session/account.
- Email transport uses SMTP. Development-only Mailpit captures messages without
  forwarding them; only its web inbox is exposed on loopback, not its SMTP port.
  Production requires an external SMTP host, authenticated STARTTLS/SSL, sender
  address and random `OTP_HASH_SECRET` (at least 32 characters). Neither OTPs nor
  passwords/mail credentials are returned, logged, stored raw in MongoDB or saved
  in browser-persistent storage. A development key may be generated per process;
  setting it in the ignored environment file preserves pending codes across restart.
- Each six-digit OTP expires after ten minutes and has at most five incorrect
  guesses across resends in that access attempt. It is bound to account/email,
  challenge ID, access attempt, mode and prospective session. MongoDB stores a
  keyed OTP hash. Resend waits 60 seconds, replaces the old challenge and is capped
  at five mail attempts per email in 15 minutes. Verification requests are bounded
  per mailbox too. Failed SMTP sends remain recoverable and never activate an
  account. Counters are reserved atomically; code publication and consumption are
  conditional, so concurrent or cancelled requests cannot enable an unrelated session.
- Successful code consumption records a keyed receipt, marks the account verified,
  then conditionally publishes its session. A failure between these writes is safe
  to retry with the identical verification request. Only the winning code can recover
  that session; consumption cannot be replayed to create a different one.
- Coachify sessions last 24 hours and store only SHA-256 secret hashes server-side.
  Bearers live in tab-scoped sessionStorage; private API responses use no-store.
  Sessions are validated before private content, after restoration/focus, every 30
  seconds and at their expiry timer. Incompatible modes, pending email/migration,
  expired or revoked sessions are rejected server-side. Existing name-only/old-mode
  credentials are not silently reinterpreted as verified email accounts.
- Logout revokes only its supplied session, is idempotent and preserves profile
  history. Delayed A retries cannot revoke B. The UI clears account/profile/drafts,
  ignores old results and broadcasts a non-secret access epoch across tabs. Failed
  termination keeps a tab-local lock across reload, with retry or explicit sign-in.
  Google itself is not globally signed out.

## Canonical routing and initial completion — P13/P14

- Profile snapshots own `onboarding_complete` and its completion timestamp. Account
  existence, populated fields, a nonzero version and client flags are never proof.
  GET distinguishes `missing`, `incomplete`, `legacy_unconfirmed` and `complete`.
  Legacy snapshots without the marker remain unconfirmed with all values intact.
- `/onboarding` presents the same profile fields in a dedicated question-by-question
  flow without workspace navigation. Protected deep links route an
  unfinished account there; completed users opening it return to `/dashboard` and
  can edit `/profile` voluntarily. Loading, expired authentication and unavailable
  profile storage are distinct. Outages offer retry instead of assuming no profile.
  Arbitrary return URLs are ignored.
- `POST /onboarding/complete` uses `expected_version` and an `Idempotency-Key` and
  atomically appends fields plus completion in one immutable snapshot. A partial
  PATCH/Save progress never marks completion. Retries return the canonical latest
  owner profile; concurrent stale writes conflict and cannot overwrite newer fields
  or downgrade completion. Ordinary later edits preserve initial completion.
- Students need occupational status, school category, an institution and a positive
  study year for that category. Non-students with education need category/institution,
  but no current year. Courses are optional. An explicit `no_previous_education=true`
  choice allows a non-student without category to complete; preserved out-of-context
  education remains stored without being used as current education. Hidden historic
  years cannot block that branch. Planning/CV/job/roadmap data are not prerequisites.
- Validation/conflict/uncommitted failures retain the current account's draft. For
  an uncertain Finish response the UI reads canonical state before retrying, reusing
  its request key. Successful completion is routed by the shared guard. Completion
  hints across tabs cause canonical readback; older versions/incomplete responses
  cannot replace a newer confirmed completion or redirect the next account.

## Explicit legacy fixed-owner mapping — P15

Run `scripts/map_legacy_owner.py --account-id <verified-local-id>
--legacy-owner local_test:<old-id>` in the Profile environment; without `--apply`
this is a dry run. Back up the database and perform mapping during maintenance.
The script requires development/local mode and an existing verified target account
with no profile data. Re-run with `--apply` only for that intended owner. It changes
only the account's owner binding, preserving all profile versions and mutation
receipts under their original owner. It revokes old sessions and requires fresh
sign-in. Re-running the same mapping is a no-op; another account cannot claim it.
A failed mapping leaves maintenance locked for explicit retry/review. No automatic
mass copying, Google/email linking or deletion occurs. Earlier name-only local
accounts remain preserved; they do not become password/verified-email accounts by
inference. This helper maps the original `local_test:<id>` records only.

## Current email registration policy

The local deployment uses `AUTH_MODE=email`: no Google sign-in button or OAuth
credentials. New email/password registrations accept any valid email address and require
OTP verification before receiving a session. OTP proves inbox access; the Gmail
sender does not restrict recipient domains. Synthetic addresses remain supported
in explicit local-test mode for automated tests.
Real delivery uses authenticated encrypted Gmail SMTP; Mailpit is capture-only.

## Employment and profile summary

- Profile owns `employment.employer`, `employment.role`, `employment.industry` and
  nullable boolean `previously_employed`. PATCH merges supplied work fields only;
  text is trimmed, limited to 300 characters and rejects blank/control characters.
  Explicit null clears a text field. Work edits apply to Employed status, or to
  Unemployed with an explicitly true previous-employment answer. Other statuses
  retain historical details without treating them as current work.
- Entering Unemployed from another status resets the previous-employment answer to
  unanswered unless supplied explicitly. Never infer it from retained work details.
  A false answer preserves historical details but hides them and prevents work edits.
- Initial completion requires company, role and industry for Employed, or Unemployed
  with previous employment. Unemployed users must explicitly answer yes/no first.
  The UI asks each question separately before education. Existing completed profiles
  stay completed; missing new fields can be added in ordinary editing.
- Public `/companies` and `/industries` searches use bundled reference JSON with
  case/accent-insensitive matching, query length up to 150 and limit 1–100. These
  suggestions never restrict accepted profile text. Search is independent of MongoDB
  and external network services; failure does not prevent manual entry.
- `/profile` is a summary with inline editing, save and cancel. `/profile/edit`
  remains available for direct links and planning preferences. Student status alone
  permits a study-year row; its value uses canonical current-study-year context.
  Non-students see last education; employed users see current employment, and unemployed users with a confirmed work history see previous employment.
- `auth-config.development_tools_enabled` comes solely from the validated server
  environment. It is false in production, including when browser/query flags ask
  otherwise. The development onboarding replay never PATCHes a profile, posts
  completion or clears the canonical completion marker. No reset endpoint exists.

## Graduation year and larger employer directory

- `education.graduation_year` is a nullable strict integer, 1900 through the current
  year in Singapore. It can be edited for Unemployed + `previously_employed=false`
  with a selected last institution. Other statuses retain historical values but
  cannot change them or display them as current information.
- This branch asks graduation immediately after school, before optional course.
  Initial completion requires the year when education applies; explicit no previous
  education skips it. Existing completed accounts remain completed. Ordinary edits
  can clear it; a changed school marks retained graduation information for review.
  The profile summary/editor use the same versioned Profile API and MongoDB history.
- Company suggestions use the bundled employee-ranked Wikidata snapshot; name
  search preserves that ordering and returns a bounded list, not the entire file.
  Latest dated non-deprecated counts take priority over older/undated observations.
  Dates, country codes and provenance stay in the snapshot. Identical names are
  deduplicated; flagged outliers remain searchable without a ranking count. These
  are approximate historical reference counts, not a live global employer ranking.
  See [snapshot sources and refresh](app/data/README.md#employment-reference-snapshot).

The Singapore employer supplement also retains businesses without employee counts.
Its reviewed seed IDs and country/headquarters source queries live alongside the
reference snapshot. Refresh preserves these names and their Singapore-source flag;
unknown headcounts sort after known counts. The public search response remains
`id`/`name`; reference metadata is not stored in user profiles or MongoDB.
