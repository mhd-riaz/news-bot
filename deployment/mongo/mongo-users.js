const databaseName = process.env.NEWS_MONGO_DATABASE || "news";
const accountNames = ["collector", "batch", "ranker", "reader", "owner", "mcp"];
// The MCP program's login: MongoDB itself must refuse any write it attempts (D21).
const readOnlyAccounts = ["mcp"];
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
  articles: { collector: crud, batch: read, ranker: [], reader: read, owner: read, mcp: read },
  sources: { collector: crud, batch: [], ranker: [], reader: readWrite, owner: crud, mcp: [] },
  collection_runs: { collector: readWrite, batch: [], ranker: [], reader: [], owner: read, mcp: [] },
  feed_cache_metadata: { collector: readWrite, batch: [], ranker: [], reader: [], owner: read, mcp: [] },
  application_locks: { collector: crud, batch: crud, ranker: [], reader: [], owner: crud, mcp: [] },
  read_events: { collector: readWrite, batch: [], ranker: [], reader: [], owner: [...read, ...remove], mcp: [] },
  index_generations: { collector: [], batch: readWrite, ranker: read, reader: [], owner: readWrite, mcp: [] },
  pipeline_runs: { collector: [], batch: readWrite, ranker: [], reader: [], owner: read, mcp: [] },
  association_rules: { collector: [], batch: crud, ranker: read, reader: [], owner: read, mcp: [] },
  story_links: { collector: [], batch: crud, ranker: read, reader: [], owner: read, mcp: [] },
  topic_labels: { collector: [], batch: readWrite, ranker: read, reader: [], owner: readWrite, mcp: [] },
  readers: { collector: [], batch: [], ranker: [], reader: readWrite, owner: crud, mcp: [] },
  reader_sessions: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove], mcp: [] },
  reader_events: { collector: [], batch: read, ranker: [], reader: crud, owner: [...read, ...remove], mcp: [] },
  reader_settings: { collector: [], batch: read, ranker: [], reader: crud, owner: [...read, ...remove], mcp: [] },
  saved_items: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove], mcp: [] },
  editions: { collector: [], batch: [], ranker: [], reader: crud, owner: [...read, ...remove], mcp: [] },
};

for (const [collection, permissions] of Object.entries(collections)) {
  for (const name of accountNames) {
    if (!Array.isArray(permissions[name])) {
      throw new Error(`${collection} must list permissions for ${name}`);
    }
  }
  for (const name of readOnlyAccounts) {
    if (permissions[name].some((action) => !read.includes(action))) {
      throw new Error(`${name} must stay read-only, but ${collection} grants it more`);
    }
  }
}

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

  const roleDefinition = { privileges, roles: [] };
  if (database.getRole(role)) database.updateRole(role, roleDefinition);
  else database.createRole({ role, ...roleDefinition });
  const userDefinition = {
    pwd: passwords[name],
    roles: [{ role, db: databaseName }],
  };
  if (database.getUser(name)) database.updateUser(name, userDefinition);
  else database.createUser({ user: name, ...userDefinition });
}

print(`Provisioned MongoDB service users for database ${databaseName}.`);
