// Run at first initialization, or explicitly against an existing development
// volume as documented. Never changes an existing database user's credentials.
const cvDatabase = db.getSiblingDB('elo_ingestion');
if (!cvDatabase.getUser('elo_cv')) {
  if (!process.env.CV_DB_PASSWORD) throw new Error('CV_DB_PASSWORD is required');
  cvDatabase.createUser({
    user: 'elo_cv',
    pwd: process.env.CV_DB_PASSWORD,
    roles: [{ role: 'readWrite', db: 'elo_ingestion' }],
  });
}
