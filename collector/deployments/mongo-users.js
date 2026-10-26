const databaseName = process.env.NEWS_MONGO_DATABASE || "news";
const accountNames = ["collector", "batch", "ranker", "reader", "owner"];
const passwords = Object.fromEntries(
  accountNames.map((name) => [name, process.env[`NEWS_MONGO_${name.toUpperCase()}_PASSWORD`]])
);

if (!/^[A-Za-z0-9_-]+$/.test(databaseName)) {
  throw new Error("NEWS_MONGO_DATABASE must contain only letters, numbers, _ or -");
}
for (const [name, password] of Object.entries(passwords)) {
  if (!password || !/^[a-f0-9]{64}$/i.test(password)) {
    throw new Error(`NEWS_MONGO_${name.toUpperCase()}_PASSWORD must be 64 hex characters`);
  }
}
if (new Set(Object.values(passwords)).size !== accountNames.length) {
  throw new Error("MongoDB service accounts must have distinct passwords");
}

const read = ["find"];
const write = ["insert", "update"];
const remove = ["remove"];
const readWrite = [...read, ...write];
const crud = [...readWrite, ...remove];

const collections = {
  articles: { collector: crud, batch: [], ranker: [], reader: read, owner: read },
  sources: { collector: crud, batch: [], ranker: [], reader: readWrite, owner: crud },
  collection_runs: { collector: readWrite, batch: [], ranker: [], reader: [], owner: read },
  feed_cache_metadata: { collector: readWrite, batch: [], ranker: [], reader: [], owner: read },
  application_locks: { collector: crud, batch: crud, ranker: [], reader: [], owner: crud },
  read_events: { collector: readWrite, batch: [], ranker: [], reader: [], owner: [...read, ...remove] },
  index_generations: { collector: [], batch: readWrite, ranker: read, reader: [], owner: readWrite },
  pipeline_runs: { collector: [], batch: readWrite, ranker: [], reader: [], owner: read },
  association_rules: { collector: [], batch: crud, ranker: read, reader: [], owner: read },
  story_links: { collector: [], batch: crud, ranker: read, reader: [], owner: read },
  topic_labels: { collector: [], batch: readWrite, ranker: read, reader: [], owner: readWrite },
  readers: { collector: [], batch: [], ranker: [], reader: readWrite, owner: crud },
  reader_sessions: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove] },
  reader_events: { collector: [], batch: read, ranker: [], reader: crud, owner: [...read, ...remove] },
  reader_settings: { collector: [], batch: read, ranker: [], reader: crud, owner: [...read, ...remove] },
  saved_items: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove] },
  editions: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove] },
};

const database = db.getSiblingDB(databaseName);
const ddlPrivileges = [
  {
    resource: { db: databaseName, collection: "" },
    actions: ["createCollection", "listCollections"],
  },
  ...Object.keys(collections).map((collection) => ({
    resource: { db: databaseName, collection },
    actions: ["createIndex", "dropIndex", "listIndexes"],
  })),
];

for (const name of accountNames) {
  const role = `news_${name}`;
  const privileges = Object.entries(collections)
    .filter(([, permissions]) => permissions[name].length > 0)
    .map(([collection, permissions]) => ({
      resource: { db: databaseName, collection },
      actions: permissions[name],
    }));
  if (name === "collector") privileges.push(...ddlPrivileges);

  database.createRole({ role, privileges, roles: [] });
  database.createUser({
    user: name,
    pwd: passwords[name],
    roles: [{ role, db: databaseName }],
  });
}

print(`Provisioned MongoDB service users for database ${databaseName}.`);
