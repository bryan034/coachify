# P04–P06 planning preferences

The `/profile` screen has a separate Planning preferences section. `/roadmap`
displays the saved deadline, normal hours and number of reduced periods and links
back to the editor. Preferences do not generate a roadmap and do not become
occupational/education onboarding requirements. Save occupational status first.
No additional API keys or database credentials are needed.

## API

All paths below are relative to `/api/v1/profile`, through the existing gateway.
Authentication and owner derivation are unchanged. `GET /api/v1/profile` returns
`application_date`, `application_time_zone`, `weekly_hours`, `availability_periods`
and `planning_revision` alongside the existing fields. Legacy snapshots default to
unset planning inputs/revision zero without rewriting saved history.

- `PATCH /`: partial profile/planning updates. Use the actual base path without a
  trailing slash, e.g. `PATCH /api/v1/profile`.
- `POST /availability-periods`: create a period; returns 201 and the resulting profile.
- `PATCH /availability-periods/{period_id}`: update supplied period fields.
- `DELETE /availability-periods/{period_id}?expected_version=N`: delete a period.
- `GET /planning-inputs?time_zone=America%2FLos_Angeles`: source profile version,
  planning revision, declared values, readiness issues and calendar/unit context.
  Both `start_date` and `end_date` may be supplied for an inclusive capacity window.
- Existing `GET /versions/{version}` includes that historical version's planning inputs.

Example planning update after reading the latest profile:

```json
{
  "expected_version": 4,
  "application_date": "2030-06-01",
  "time_zone": "Asia/Singapore",
  "weekly_hours": 14.5
}
```

Example create period (or partial edit using the same field names):

```json
{
  "expected_version": 5,
  "start_date": "2030-02-01",
  "end_date": "2030-02-07",
  "weekly_hours": 0
}
```

Every planning mutation requires an `Idempotency-Key` header: 1–128 letters,
digits, hyphens or underscores. Use a fresh UUID for a new save. On an uncertain
network/storage response, retry the exact same method, target, body/version and
key. A successful replay returns the owner's latest profile without repeating the
mutation or reverting later edits. Reusing a key for different input returns 409.
After a confirmed validation failure, correction is a new save with a new key.
The UI keeps the request key for unchanged retries; Cancel makes no HTTP write.

A changed save creates one immutable full profile version. Unchanged valid saves
and repeated deletions do not advance the version or planning revision. A stale
version returns 409. Stable period IDs and owner-scoped unique mutation receipts
prevent duplicate additions. Profile snapshots hold receipts for changed writes;
`profile_mutations` reserves keys across both changed and no-op saves and records
completed no-op keys without extra profile versions. An incomplete reservation can
be retried; a changed write is successful only when its profile snapshot commits.
Standalone MongoDB remains supported; no replica set/transaction is required.
All competing base/period mutations use the same owner/version uniqueness boundary.

## Dates, numbers and capacity

P04 uses `YYYY-MM-DD` date-only values. The browser obtains the device's current
IANA time-zone identifier at submission. FastAPI validates that the deadline is
strictly after today in that zone. Missing/invalid zone context is a recoverable
422; no Singapore/server-zone fallback is applied. Unchanged valid dates do not
change the original recorded validation zone or planning revision. Saved elapsed
deadlines remain visible and flagged; unrelated profile edits still work.

P05 accepts finite JSON numbers greater than 0 and at most 168 hours/week,
including fractions. Booleans and numeric strings are rejected. Values round-trip
as JSON numbers/MongoDB doubles; they are not rounded to whole hours or fixed
steps. Client input uses `step=any`; proration uses rational arithmetic and converts
only the final capacity to a JSON number. No missing budget is inferred.

P06 dates are inclusive and use **Asia/Singapore**, independently of the P04 device
zone. New/edited periods cannot end before Singapore today. End is on/after start;
period rates are finite, at least 0 and strictly below a saved normal budget.
Inclusive overlaps are rejected; self-edits exclude the current stable ID, and
adjacent/same-day ranges are permitted. Past records remain visible/deletable.

A reduced rate replaces normal capacity on each covered date. Calendar weeks are
Monday–Sunday; use weekly hours / 7 per date when prorating. At 14 normal hours/week,
two dates at 7 hours/week yield 12 hours over that seven-date window. Outside the
period the normal rate resumes; 0 means no capacity. A later base reduction may
invalidate current/future periods: saved periods remain intact, the snapshot lists
the affected IDs, and planning that uses them is not ready. Historical periods alone
do not block future capacity. A window ending before its start is rejected.

The planning snapshot carries the deadline's original validation zone, current
validation zone/date, Singapore capacity as-of date, explicit units, inclusive
boundaries and week/proration rules. Missing or elapsed inputs and unresolved
period conflicts are reported as issues, never replaced with defaults.

## UI and future handoff

Planning forms preserve failed/stale drafts and offer a Load latest action without
replacing them. Successful planning saves preserve unrelated unsaved education
edits. Declared preferences are independent of initial onboarding completion.
Snapshot checks refresh on tab focus and every minute while open; deadline writes
always revalidate at submission. The Roadmap summary shows saved values only.

The future roadmap service must copy the planning snapshot and compare its source
profile version/planning revision with current inputs. Snapshot calendar context
must not be reinterpreted after a device-zone change. Cross-service stale-plan
notifications, automatic generation, scheduling, feasibility and calendar integration
are not implemented in this slice.

## Verification

Run the profile suite with `MONGODB_TEST_URI` pointing to a disposable MongoDB to
include persistence/concurrency tests. Tests use temporary databases and remove
them. Existing frontend unit/browser suites cover regression flows; the separate
`playwright.integration.config.ts` now also exercises real P04–P06 saves, conflict
recovery, overlap rejection, proration, reload, delete and Roadmap display. Target
only a disposable local-test stack; these tests write synthetic profile data.

Import `docs/postman/coachify-planning.postman_collection.json` to test manually.
Read the current profile first. Set future dates and the correct device zone. A
collection pre-request script creates a request key; set `retryMutationKey` to the
original key when deliberately replaying a lost-success request. Never use shared
production credentials for local testing.
