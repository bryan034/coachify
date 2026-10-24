# P01–P03 education profile

P07/P08 is integrated into P01-03. Institution selection, custom entry, course entry
and current study level/year are implemented. The existing ownership, MongoDB and
immutable profile-version foundation is reused. No school directory collection or
live course catalogue is introduced.

## API and Postman

Read `GET /api/v1/profile`, then PATCH the same URL with its current version.
Omitted fields stay unchanged. No separate POST is needed. Example first save:

```json
{
  "expected_version": 0,
  "occupational_status": "student",
  "school_category": "university",
  "education": {
    "institution": {"kind": "custom", "name": "Unlisted International College", "country_code": "SG"},
    "course": "Computing & Design (Double Programme)",
    "study_year": 6
  }
}
```

For a directory institution, search `/api/v1/profile/institutions` and send
`{"kind":"catalogue","id":"the-returned-id"}`. The server derives the saved
name, country and snapshot date. Caller-supplied catalogue names are rejected.
Custom entry requires no catalogue membership or proof. Names/courses are trimmed,
limited to 300 characters and reject control characters. Country codes, when
supplied, are two uppercase letters. Combined programme names and punctuation work.

Example independent update (use the latest version):

```json
{"expected_version": 1, "education": {"course": "Business Analytics & Economics"}}
```

Explicit `null` clears an optional course or a non-student's institution. Blank
strings are errors; use `null` for no applicable course. Study year must be a strict
positive integer, including beyond Year 4; null, strings, booleans, fractions and
nonpositive years are rejected. Labels use Secondary 3, JC 2 or Year 6 as appropriate.
Only Student can submit a new current study year. Non-students need no current year.
Status/category-only saves continue working for older profiles with no education.

The Postman collection in `docs/postman/` captures profileVersion from successful
GET/PATCH responses. Run Read profile before saves, and International university
search before the catalogue-institution request to populate institutionId. If a
save changes the institution while retaining a course/year, run the confirmation
request after reviewing those retained fields before making further education edits.

## Context and history

Changing status/category retains education in its original category/context and
marks `education_review_required`. The profile-level `education_context` represents
the currently selected status, while the nested education retains its declared
context until reviewed. Before editing retained education in a pending context,
explicitly send `confirm_education_context: true`; the UI has a review checkbox.

Catalogue institutions must match a newly confirmed category. A student changing
school category must explicitly enter the year for that new category; the old year
is never silently relabelled. Changing an institution while retaining course/year
values prompts review rather than silently discarding them.

`education.study_year` retains the declaration; the derived response field
`current_study_year` is null for non-students and while review is pending. Returning
to Student requires review before an old year becomes current. Calendar time does
not advance it. Changed saves create immutable history; no-op saves do not.

Stale writes return 409, field validation errors 422 and storage failures 503. The
UI preserves input for retry. Only the owner's data is accessible. Existing Google
and explicit development-only fixed identity modes are reused. No caller-supplied
user ID is accepted. See `profile-setup.md` for runtime/authentication instructions.

## Verification and scope

API tests cover all categories, catalogue/custom inputs, invalid values, independent
updates, context transitions, history, owner isolation and stale writes. Real MongoDB
integration verifies education across a separate connection. Component/browser tests
exercise entry, catalogue selection, extended years, reload and failed-save retry.
Browser tests mock external Google/API boundaries; the real database is verified
separately. The production Next.js build and TypeScript checks are also run.

No new API keys are needed. The local test mode supports Postman; the browser still
uses Google sign-in. Course entry is free text rather than a maintained catalogue.
Assessment/roadmap services remain unimplemented: profile versions prepare their
future freshness checks, but no cross-service roadmap flagging or generation is
implemented here. Jira statuses are unchanged.
