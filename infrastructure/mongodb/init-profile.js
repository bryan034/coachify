// Runs only when the MongoDB data volume is first initialised.
const profileDb = db.getSiblingDB('coachify_profile');
profileDb.createUser({
  user: 'coachify_profile', pwd: process.env.PROFILE_DB_PASSWORD,
  roles: [{ role: 'readWrite', db: 'coachify_profile' }],
});
