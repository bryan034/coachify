# MongoDB service storage

The active stack uses separate `coachify_profile`, `coachify_ingestion` and `coachify_career` databases and scoped service users. Profile initialization handles fresh volumes; the idempotent `mongodb-career-init` job creates missing Career/CV users on existing volumes without resetting credentials or data. Root credentials belong only to MongoDB and its setup job, never application services. See [application setup](../../docs/setup.md).

## Ownership

Profile's existing `accounts` collection is the logical `users` authority, retaining UUID account IDs and manual declarations. CV owns saved `cvs`, processing/history, explicit `cv_selections` and private bounded `cv_conversations`. Career owns canonical `career_goals`, public `interview_research`, future `skill_gap_analyses`, and operational `career_state`, research jobs and checkpoints. Planned Roadmap/Review services own their future records; Dashboard remains stateless.

Services access foreign records through authenticated APIs. CV IDs remain UUID strings; Career's internal CV projection also accepts existing ObjectId references without remapping. Career-owned goal/research identities remain ObjectIds. There is no account or CV-ID migration.

## Canonical goal and historical compatibility

`career_state` holds the current canonical goal pointer/workspace. The version-specific `cv_confirmation` stamp records goal ID/version, selection version, projection hash and confirmation time; bounded receipts support exact retries. Automatic Career saves do not implicitly confirm CV context. A changed goal or selection invalidates the stamp on reads, while earlier CV answers stay source-bound.

Older UUID reviewed-target records and their selection metadata remain historical data, outside the active canonical flow. Canonical history queries filter record shape instead of validating legacy records as new goals. Namespaced canonical `create_key` metadata preserves coexistence with the legacy unique `(user_id, create_key)` index. No index drop, data deletion or automatic historical-target conversion is required.

## Local persistence and setup

MongoDB data persists in its named `/data/db` volume. Preserve stored passwords when reusing it; changing configuration does not change a database user's saved credential. Apply missing service-user setup through the existing one-shot initialization job. Do not use volume deletion as a setup or migration step. Private standalone local MongoDB operations use atomic document updates and version checks rather than assuming distributed transactions.

Agents use separate disposable projects/databases with explicit synthetic settings. MongoDB 8 checks need a compatible Docker/runner kernel; local functional validation on MongoDB 7 is reported separately and does not establish intended-version compatibility. No workaround should silently bypass MongoDB's startup guard or change host settings.

## CV originals and history

Only CV mounts `cv_uploads`, which temporarily retains private original PDF/DOCX files for the documented retry window. MongoDB stores structured extraction and bounded evidence, not a public file URL or full parsing text. Cleanup respects processing leases and records deletion. Expired originals require re-upload; metadata expiry alone cannot remove a filesystem file. Saved conversation segments do not automatically expire and are separate from factual CV versions.

## Production proposal

Atlas may provide external managed MongoDB storage with service-scoped credentials; application hosting remains separate. It would not use the local data volume. Index/topology choices must be validated against the deployed environment. See the [collection diagram](../../docs/architecture/diagrams/mongodb_collections_uml.mmd) and owning service contracts.
