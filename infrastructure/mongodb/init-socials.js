const root = new Mongo('mongodb://elo_admin:' + encodeURIComponent(process.env.MONGO_ROOT_PASSWORD) + '@mongodb:27017/admin');
const password = process.env.SOCIALS_DB_PASSWORD;
if (!password) throw new Error('Set the Socials database password.');
const db = root.getDB('elo_socials');
if (!db.getUser('elo_socials')) db.createUser({user: 'elo_socials', pwd: password, roles: [{role: 'readWrite', db: 'elo_socials'}]});
try { new Mongo('mongodb://elo_socials:' + encodeURIComponent(password) + '@mongodb:27017/elo_socials').getDB('elo_socials').getCollection('wallets').findOne(); }
catch (_) { throw new Error('The Socials database password does not match its existing database user. Preserve the original value.'); }
print('Socials database access is ready.');
