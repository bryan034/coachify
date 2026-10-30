// Runs only when the MongoDB data volume is first initialised.
const profileDb = db.getSiblingDB('elo_profile');
profileDb.createUser({
  user: 'elo_profile', pwd: process.env.PROFILE_DB_PASSWORD,
  roles: [{ role: 'readWrite', db: 'elo_profile' }],
});
