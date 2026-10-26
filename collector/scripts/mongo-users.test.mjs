import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../deployments/mongo-users.js", import.meta.url), "utf8");
const accounts = ["collector", "batch", "ranker", "reader", "owner"];

function harness() {
  const env = { NEWS_MONGO_DATABASE: "provisioning_test" };
  for (const name of accounts) env[`NEWS_MONGO_${name.toUpperCase()}_PASSWORD`] = randomBytes(32).toString("hex");
  const roles = new Map();
  const users = new Map();
  const writes = [];
  const save = (store, kind, name, value) => {
    store.set(name, JSON.parse(JSON.stringify(value)));
    writes.push(kind);
  };
  const database = {
    getRole: (name) => roles.get(name) ?? null,
    getUser: (name) => users.get(name) ?? null,
    createRole: ({ role, ...value }) => {
      assert(!roles.has(role));
      save(roles, "createRole", role, value);
    },
    updateRole: (name, value) => save(roles, "updateRole", name, value),
    createUser: ({ user, ...value }) => {
      assert(!users.has(user));
      save(users, "createUser", user, value);
    },
    updateUser: (name, value) => save(users, "updateUser", name, value),
  };
  const run = () => runInNewContext(source, {
    process: { env },
    db: { getSiblingDB: (name) => {
      assert.equal(name, env.NEWS_MONGO_DATABASE);
      return database;
    } },
    print: () => {},
  });
  return { env, roles, users, writes, run };
}

test("batch can read articles but cannot write them", () => {
  const state = harness();
  state.run();
  assert.equal(state.roles.size, accounts.length);
  assert.equal(state.users.size, accounts.length);
  const privilege = state.roles.get("news_batch").privileges.find(({ resource }) => resource.collection === "articles");
  assert.deepEqual(privilege.actions, ["find"]);
  assert.deepEqual(state.users.get("batch").roles, [{ role: "news_batch", db: "provisioning_test" }]);
});

test("rerunning repairs existing roles and applies supplied passwords without duplicate creation", () => {
  const state = harness();
  state.run();
  state.roles.get("news_batch").privileges = [];
  state.env.NEWS_MONGO_BATCH_PASSWORD = randomBytes(32).toString("hex");
  state.run();
  assert.equal(state.roles.size, accounts.length);
  assert.equal(state.users.size, accounts.length);
  assert.equal(state.writes.filter((kind) => kind === "createRole").length, accounts.length);
  assert.equal(state.writes.filter((kind) => kind === "updateRole").length, accounts.length);
  assert.equal(state.writes.filter((kind) => kind === "updateUser").length, accounts.length);
  assert(state.roles.get("news_batch").privileges.some(({ resource }) => resource.collection === "articles"));
  assert.equal(state.users.get("batch").pwd, state.env.NEWS_MONGO_BATCH_PASSWORD);
});

test("invalid provisioning inputs fail before any database mutation", () => {
  for (const invalid of ["database", "missing-password", "bad-password", "duplicate-password"]) {
    const state = harness();
    if (invalid === "database") state.env.NEWS_MONGO_DATABASE = "not/a/database";
    if (invalid === "missing-password") delete state.env.NEWS_MONGO_BATCH_PASSWORD;
    if (invalid === "bad-password") state.env.NEWS_MONGO_BATCH_PASSWORD = "not-a-password";
    if (invalid === "duplicate-password") state.env.NEWS_MONGO_BATCH_PASSWORD = state.env.NEWS_MONGO_COLLECTOR_PASSWORD;
    assert.throws(state.run, /NEWS_MONGO_DATABASE|NEWS_MONGO_BATCH_PASSWORD|distinct passwords/);
    assert.equal(state.writes.length, 0);
  }
});
