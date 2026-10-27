// Run at first initialization, or explicitly against an existing development
// volume as documented. Never changes an existing database user's credentials.
const cvDatabase = db.getSiblingDB('coachify_ingestion');
if (!cvDatabase.getUser('coachify_cv')) {
  if (!process.env.CV_DB_PASSWORD) throw new Error('CV_DB_PASSWORD is required');
  cvDatabase.createUser({
    user: 'coachify_cv',
    pwd: process.env.CV_DB_PASSWORD,
    roles: [{ role: 'readWrite', db: 'coachify_ingestion' }],
  });
}
