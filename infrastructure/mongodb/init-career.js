// Safe for an existing volume: create missing service users; never reset passwords.
const rootUri = 'mongodb://coachify_admin:' + encodeURIComponent(process.env.MONGO_ROOT_PASSWORD) + '@mongodb:27017/admin';
const adminConnection = new Mongo(rootUri);
for (const item of [
  { database: 'coachify_career', user: 'coachify_career', password: process.env.CAREER_DB_PASSWORD },
  { database: 'coachify_ingestion', user: 'coachify_cv', password: process.env.CV_DB_PASSWORD },
]) {
  if (!item.password) throw new Error('Set the Career and CV database passwords before starting.');
  const scoped = adminConnection.getDB(item.database);
  if (!scoped.getUser(item.user)) scoped.createUser({ user: item.user, pwd: item.password, roles: [{ role: 'readWrite', db: item.database }] });
  try {
    const uri = 'mongodb://' + item.user + ':' + encodeURIComponent(item.password) + '@mongodb:27017/' + item.database;
    new Mongo(uri).getDB(item.database).getCollection('career_setup_check').findOne();
  } catch (_) {
    throw new Error('A configured service password does not match its existing database user. Preserve the original value.');
  }
}
print('Career and CV database access is ready.');
