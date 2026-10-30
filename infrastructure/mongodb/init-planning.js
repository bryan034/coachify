// Add scoped users without changing any existing user/password or domain data.
const root = new Mongo('mongodb://elo_admin:' + encodeURIComponent(process.env.MONGO_ROOT_PASSWORD) + '@mongodb:27017/admin');
for (const [service, password] of [['assessment', process.env.ASSESSMENT_DB_PASSWORD], ['roadmap', process.env.ROADMAP_DB_PASSWORD]]) {
  if (!password) throw new Error('Set the Assessment and Roadmap database passwords.');
  const name = 'elo_' + service;
  const db = root.getDB(name);
  if (!db.getUser(name)) db.createUser({user: name, pwd: password, roles: [{role: 'readWrite', db: name}]});
  try { new Mongo('mongodb://' + name + ':' + encodeURIComponent(password) + '@mongodb:27017/' + name).getDB(name).getCollection('workspaces').findOne(); }
  catch (_) { throw new Error('A planning-service password does not match its existing database user. Preserve the original value.'); }
}
print('Assessment and Roadmap database access is ready.');
