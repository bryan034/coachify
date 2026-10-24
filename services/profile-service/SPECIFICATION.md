# Profile service rules

P01–P08 are implemented. Jira acceptance criteria remain the product source of
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

- Private data is owner-scoped. Google tokens are verified by the backend. Explicit
  development-only `local_test` mode uses one fixed server-selected identity;
  multi-account access and persistent sessions are not implemented yet.
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
