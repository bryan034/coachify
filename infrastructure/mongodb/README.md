# MongoDB service storage

The active Compose stack uses separate `coachify_profile`, `coachify_career` and
`coachify_ingestion` databases and scoped service users. Profile initialisation runs
on a fresh volume. The one-shot `mongodb-career-init` job also creates missing
Career/CV users on existing volumes, without resetting existing credentials or data.
Root credentials are supplied only to MongoDB and that setup job, not application services.

See [application setup](../../docs/setup.md) for passwords and startup commands.
Preserve existing password values when reusing a volume; changing `.env` does not
change a stored database password. No volume deletion is needed for J08/J09.

Career owns `career_goals`, public `interview_research`, private `skill_gap_analyses`
and operational selection/processing records. CV owns `cvs`; its read API is active,
while dedicated upload/extraction remains planned. Services use authenticated APIs
to access foreign records. Confirmed goals preserve historical revisions; drafts
use expected versions and safe retries. Indexes are installed by their owning workers.

CV attachments on Career Goal are temporary private parser/request buffers, not
MongoDB file storage or dedicated CV extraction. Only bounded structured progress,
filename/hash and approved provenance are saved; full raw JD/CV text is not stored.
MongoDB data persists in the named Docker volume. Production may use Atlas with
service-scoped credentials; it would not use this local database volume.
