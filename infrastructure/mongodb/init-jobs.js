// Add the scoped Jobs user without changing any existing user/password or domain data.
const root = new Mongo('mongodb://elo_admin:' + encodeURIComponent(process.env.MONGO_ROOT_PASSWORD) + '@mongodb:27017/admin');
const password = process.env.JOBS_DB_PASSWORD;
if (!password) throw new Error('Set the Jobs database password.');
const db = root.getDB('elo_jobs');
if (!db.getUser('elo_jobs')) db.createUser({user: 'elo_jobs', pwd: password, roles: [{role: 'readWrite', db: 'elo_jobs'}]});
try { new Mongo('mongodb://elo_jobs:' + encodeURIComponent(password) + '@mongodb:27017/elo_jobs').getDB('elo_jobs').getCollection('job_postings').findOne(); }
catch (_) { throw new Error('The Jobs database password does not match its existing database user. Preserve the original value.'); }
print('Jobs database access is ready.');
