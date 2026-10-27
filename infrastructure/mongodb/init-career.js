// Run on first initialization, or explicitly against an existing development
// volume as documented. Preserve existing credentials and unrelated databases.
const careerDatabase = db.getSiblingDB('coachify_career');
if (!careerDatabase.getUser('coachify_career')) {
  if (!process.env.CAREER_DB_PASSWORD) throw new Error('CAREER_DB_PASSWORD is required');
  careerDatabase.createUser({
    user: 'coachify_career',
    pwd: process.env.CAREER_DB_PASSWORD,
    roles: [{ role: 'readWrite', db: 'coachify_career' }],
  });
}
