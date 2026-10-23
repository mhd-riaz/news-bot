import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const scriptURL = new URL("../internal/web/static/stories.js", import.meta.url);
const source = readFileSync(scriptURL, "utf8");
const template = readFileSync(new URL("../internal/web/templates/stories.html", import.meta.url), "utf8");
const elementIDs = new Set([...template.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
const startup = /\n  init\(\);\n\}\)\(\);\s*$/;
assert.match(source, startup, "Update the test hooks if the Stories bootstrap changes.");

// Expose private functions only inside the test VM, without starting the app.
// The small DOM double runs real text/chrome rendering; browser image loading is excluded.
const instrumented = source.replace(startup, `
  renderImage = () => {};
  globalThis.storiesTest = {
    state, emptyProfile, ids, normaliseProfile, readProfile, saveProfile,
    safeURL, articleDate, normaliseMetadata, normaliseArticle, normaliseResponse,
    bodyFor, requestJSON, loadFeed, nextStory, previousStory, changePreference,
    currentArticle, canNext, renderStory, renderChrome
  };
})();
`);

const id = (number) => `00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`;
const identifiers = (length, start = 1) => Array.from({ length }, (_, index) => id(start + index));
const plain = (value) => JSON.parse(JSON.stringify(value));
const article = (number, overrides = {}) => ({
  id: id(number),
  title: `Archived story ${number}`,
  source_name: "Test source",
  url: "https://example.invalid/article",
  text: "Stored article text.",
  text_kind: "Stored summary",
  input_kind: "summary",
  published_at: "2024-03-01T23:30:00Z",
  collected_at: "2024-03-02T00:30:00Z",
  date_kind: "Stored publication date",
  group: "0",
  score: 0.5,
  ...overrides,
});
const selection = (items, overrides = {}) => ({
  snapshot_id: "snapshot-a",
  method: "neural",
  items,
  exhausted: true,
  unavailable_ids: [],
  ignored_viewed_ids: 0,
  ...overrides,
});
const response = (value, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => value,
});

function element() {
  const attributes = new Map();
  const classes = new Set();
  const node = {
    textContent: "",
    hidden: false,
    disabled: false,
    dataset: {},
    children: [],
    options: [],
    classList: {
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    },
    setAttribute: (name, value) => attributes.set(name, String(value)),
    getAttribute: (name) => attributes.get(name) ?? null,
    removeAttribute: (name) => {
      attributes.delete(name);
      if (name === "href") delete node.href;
      if (name === "datetime") delete node.dateTime;
    },
    querySelectorAll: () => [],
    querySelector: () => ({ open: false }),
  };
  Object.defineProperty(node, "innerHTML", {
    set() { assert.fail("Fetched content must use textContent, not innerHTML."); },
  });
  return node;
}

function harness() {
  const nodes = new Map();
  const storage = new Map();
  const timers = new Map();
  const calls = [];
  let nextTimer = 0;
  let fetch = () => assert.fail("Every request must be explicitly mocked.");
  const get = (name) => {
    assert(elementIDs.has(name), `The template must contain #${name}.`);
    if (!nodes.has(name)) nodes.set(name, element());
    return nodes.get(name);
  };
  const window = {
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
    setTimeout: (callback, delay) => {
      const timer = ++nextTimer;
      timers.set(timer, { callback, delay });
      return timer;
    },
    clearTimeout: (timer) => timers.delete(timer),
  };
  const context = createContext({
    URL, AbortController, Intl, Error, TypeError, window,
    document: { getElementById: get },
    fetch: (path, options) => {
      calls.push({ path, options });
      return fetch(path, options);
    },
  });
  runInContext(instrumented, context, { filename: scriptURL.pathname, timeout: 1000 });
  const api = context.storiesTest;
  Object.assign(api.state, {
    meta: { snapshot_id: "snapshot-a", articles: 5000, methods: ["neural", "tfidf", "svd"], topics: [] },
    profile: api.emptyProfile(),
    storageKey: "afterline:profile:snapshot-a",
    method: "neural",
    loading: false,
    feedback: null,
  });
  return { api, state: api.state, get, storage, timers, calls, window, setFetch: (mock) => { fetch = mock; } };
}

describe("AFTERLINE focused UI checks", { concurrency: true }, () => {
  test("standard-reader links and the noscript fallback escape the Stories redirect via /archive", () => {
    const links = [...template.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)]
      .filter((match) => /standard reader/i.test(match[2]));
    assert.equal(links.length, 2);
    for (const link of links) assert.match(link[1], /\bhref="\/archive"/);
    const noscript = template.match(/<noscript>([\s\S]*?)<\/noscript>/i);
    assert(noscript, "A JavaScript-free fallback must remain available.");
    assert.match(noscript[1], /<a\b[^>]*\bhref="\/archive"/);
  });

  test("profile sanitization enforces limits, UUID uniqueness, and opposing choices", () => {
    const { api } = harness();
    const profile = api.normaliseProfile({
      liked: identifiers(60),
      disliked: [...identifiers(59, 100), id(60)],
      viewed: identifiers(2050),
      onboarded: "true",
    });
    assert.equal(profile.liked.length, 49);
    assert.equal(profile.liked[0], id(11));
    assert(!profile.liked.includes(id(60)));
    assert.equal(profile.disliked.length, 50);
    assert.equal(profile.viewed.length, 2000);
    assert.equal(profile.viewed[0], id(51));
    assert.equal(profile.viewed.at(-1), id(2050));
    assert.equal(profile.onboarded, false);
    assert.deepEqual(plain(api.ids([id(0xabcdef).toUpperCase(), id(0xabcdef), "invalid", null], 50)), [id(0xabcdef)]);
    assert.deepEqual(plain(api.normaliseProfile(null)), plain(api.emptyProfile()));
  });

  test("storage reads only the active snapshot and recovers visibly from corrupt JSON", () => {
    const { api, state, storage, get } = harness();
    state.profile.liked = [id(1)];
    api.saveProfile();
    const snapshotA = state.storageKey;
    state.storageKey = "afterline:profile:snapshot-b";
    assert.equal(api.readProfile().liked.length, 0);
    state.profile = api.emptyProfile();
    state.profile.disliked = [id(2)];
    api.saveProfile();
    state.storageKey = snapshotA;
    assert.deepEqual(plain(api.readProfile().liked), [id(1)]);
    assert.equal(api.readProfile().disliked.length, 0);
    assert.equal(storage.size, 2);
    storage.set(snapshotA, "{invalid-json");
    assert.equal(api.readProfile().liked.length, 0);
    assert.equal(get("storage-warning").hidden, false);
    assert.match(get("storage-warning").textContent, /could not be read/);
  });

  test("blocked storage reads and quota failures report session-only persistence", () => {
    for (const failure of ["getter", "getItem", "setItem"]) {
      const { api, state, window, get } = harness();
      if (failure === "getter") {
        Object.defineProperty(window, "localStorage", { get() { throw new Error("Storage blocked"); } });
      } else {
        window.localStorage[failure] = () => { throw new Error("Storage unavailable"); };
      }
      if (failure === "setItem") {
        api.saveProfile();
        assert.match(get("storage-warning").textContent, /Older saved choices may return/);
      } else assert.equal(api.readProfile().viewed.length, 0);
      assert.equal(state.persistence, false);
      assert.equal(get("storage-warning").hidden, false);
      assert.match(get("storage-warning").textContent, /only in this open tab/);
      assert.doesNotThrow(() => api.saveProfile());
    }
  });

  test("external links allow only HTTP(S), images only HTTPS, without credentials", () => {
    const { api } = harness();
    for (const value of [null, "", "/relative", "//example.invalid", "javascript:alert(1)", "data:text/html,unsafe", "file:///etc/passwd", "https://name:password@example.invalid"]) {
      assert.equal(api.safeURL(value), "", String(value));
      assert.equal(api.safeURL(value, true), "", String(value));
    }
    assert.equal(api.safeURL("http://example.invalid/article"), "http://example.invalid/article");
    assert.equal(api.safeURL("http://example.invalid/image", true), "");
    assert.equal(api.safeURL(" https://example.invalid/image ", true), "https://example.invalid/image");
  });

  test("metadata rejects invalid counts or missing lenses and deduplicates real groups", () => {
    const { api } = harness();
    for (const articles of [-1, 1.5, "3"]) {
      assert.throws(() => api.normaliseMetadata({ snapshot_id: "a", articles, methods: ["neural"] }), /incomplete/);
    }
    assert.throws(() => api.normaliseMetadata(null), /incomplete/);
    assert.throws(() => api.normaliseMetadata({ snapshot_id: "a", articles: 0, methods: ["unknown", "__proto__"] }), /No supported/);
    const meta = api.normaliseMetadata({
      snapshot_id: "a", articles: 0, methods: ["tfidf", "unknown", "tfidf", "svd"],
      topics: [{ id: "0", label: "space / research / science" }, { id: "0", label: "duplicate" }, null],
    });
    assert.deepEqual(plain(meta.methods), ["tfidf", "svd"]);
    assert.equal(meta.topics.length, 1);
    assert.equal(meta.topics[0].label, "space / research / science");
  });

  test("responses enforce the snapshot, requested lens, valid IDs, and a bounded batch", () => {
    const { api } = harness();
    assert.throws(() => api.normaliseResponse({}, "snapshot-a", "neural"), /unreadable/);
    assert.throws(() => api.normaliseResponse(selection([], { snapshot_id: "b" }), "snapshot-a", "neural"), (error) => error.reloadMetadata === true);
    assert.throws(() => api.normaliseResponse(selection([], { method: "svd" }), "snapshot-a", "neural"), /different lens/);
    assert.throws(() => api.normaliseResponse(selection([{ id: "invalid" }]), "snapshot-a", "neural"), /No valid/);
    const deduplicated = api.normaliseResponse(selection([article(1), article(1), { id: "invalid" }, article(2)]), "snapshot-a", "neural");
    assert.deepEqual(deduplicated.items.map((item) => item.id).join(","), [id(1), id(2)].join(","));
    assert.equal(api.normaliseResponse(selection(identifiers(40).map((_, index) => article(index + 1))), "snapshot-a", "neural").items.length, 24);
  });

  test("metadata selects the evaluated baseline default and rejects an unsupported default", () => {
    const { api } = harness();
    const metadata = {
      snapshot_id: "snapshot-a", articles: 20, methods: ["tfidf", "svd", "neural"],
      default_method: "tfidf", topics: [],
    };
    assert.equal(api.normaliseMetadata(metadata).default_method, "tfidf");
    assert.equal(api.normaliseMetadata({ ...metadata, default_method: undefined }).default_method, "tfidf");
    assert.throws(() => api.normaliseMetadata({ ...metadata, default_method: "unsupported" }), /unsupported default/);
  });

  test("initial loading renders before the server chooses a default lens", () => {
    const { api, state, get } = harness();
    state.meta = null;
    state.method = "";
    state.loading = true;
    state.feedback = { kind: "loading", title: "Opening the archive.", message: "Loading real metadata." };
    assert.doesNotThrow(() => api.renderChrome());
    assert.match(get("lens-note").textContent, /Loading/);
    assert.equal(get("method").disabled, true);
    assert.equal(get("reader-panel").getAttribute("aria-busy"), "true");
  });

  test("story rendering keeps fetched text literal, labels absolute dates, and handles headline-only input", () => {
    const { api, get } = harness();
    const hostile = "<img src=x onerror=alert(1)>";
    const item = api.normaliseArticle(article(1, {
      title: hostile, text: hostile, reason: hostile, source_name: hostile,
      url: "javascript:alert(1)", image_url: "http://example.invalid/image",
      date_kind: "Collected", published_at: "2031-01-01", score: Infinity,
    }));
    api.renderStory(item);
    for (const name of ["story-title", "story-text", "story-reason", "story-source"]) assert.equal(get(name).textContent, hostile);
    assert.equal(get("story-date").textContent, "Collected 2 March 2024");
    assert.equal(get("story-date").dateTime, "2024-03-02T00:30:00.000Z");
    assert.equal(get("read-original").hidden, true);
    assert.equal(get("original-unavailable").hidden, false);
    assert.equal(item.image_url, "");
    assert.equal(item.score, null);
    api.renderStory(api.normaliseArticle(article(2, { text: "", published_at: "invalid", collected_at: "" })));
    assert.equal(get("story-text-kind").textContent, "Headline only");
    assert.match(get("story-text").textContent, /Only the headline is stored/);
    assert.equal(get("story-date").textContent, "Stored date unavailable");
    assert.equal(api.articleDate(article(3)).label, "Published");
  });

  test("request bodies cap profiles and use same-origin JSON with the selected seed, topic, and lens", async () => {
    const { api, state, setFetch, calls, timers } = harness();
    state.profile = { liked: identifiers(70), disliked: identifiers(70, 100), viewed: identifiers(2050) };
    state.seed = id(4);
    state.topic = "0";
    state.method = "svd";
    const body = api.bodyFor();
    assert.deepEqual([body.liked.length, body.disliked.length, body.viewed.length], [50, 50, 2000]);
    assert.equal(body.limit, 24);
    assert.equal(body.method, "svd");
    assert.equal(body.seed_id, id(4));
    assert.equal(body.topic, "0");
    const explore = api.bodyFor(true);
    assert.equal(explore.liked.length, 0);
    assert.equal(explore.disliked.length, 50);
    assert.equal(explore.viewed.length, 2000);
    assert(!("seed_id" in explore) && !("topic" in explore));
    setFetch(async () => response({}));
    await api.requestJSON("/api/v1/recommendations/meta", new AbortController());
    await api.requestJSON("/api/v1/recommendations", new AbortController(), body);
    assert.equal(calls[0].options.method, "GET");
    assert.equal(calls[1].path, "/api/v1/recommendations");
    assert.equal(calls[1].options.method, "POST");
    assert.equal(calls[1].options.headers["Content-Type"], "application/json");
    assert.equal(calls[1].options.credentials, "same-origin");
    assert.equal(calls[1].options.cache, "no-store");
    assert.deepEqual(JSON.parse(calls[1].options.body), plain(body));
    assert.equal(timers.size, 0);
  });

  test("navigation counts only displayed stories, revisits history, and reaches an explicit end", async () => {
    const { api, state, setFetch, calls, get } = harness();
    setFetch(async () => response(selection([article(1), article(2), article(3)])));
    await api.loadFeed(true);
    assert.deepEqual(plain(state.profile.viewed), [id(1)]);
    assert.equal(state.queue.length, 2);
    assert.equal(get("position-current").textContent, "01");
    assert.equal(get("position-total").textContent, "03");
    api.nextStory();
    assert.equal(api.currentArticle().id, id(2));
    assert.equal(state.profile.viewed.length, 2);
    assert.equal(state.profile.liked.length, 0);
    assert.equal(state.profile.disliked.length, 0);
    api.previousStory();
    assert.equal(api.currentArticle().id, id(1));
    assert.equal(state.profile.viewed.length, 2);
    api.nextStory();
    api.nextStory();
    assert.equal(api.currentArticle().id, id(3));
    assert.equal(get("feed-end").hidden, false);
    assert.equal(get("next-story").disabled, true);
    api.nextStory();
    assert.equal(calls.length, 1);
    state.profile.viewed = identifiers(2000);
    state.queue = [api.normaliseArticle(article(5000))];
    api.nextStory();
    assert.equal(state.profile.viewed.length, 2000);
    assert.equal(state.profile.viewed[0], id(2));
    assert.equal(state.profile.viewed.at(-1), id(5000));
  });

  test("preference toggles remove opposing choices, cap each side, and discard stale unseen rankings", async () => {
    const { api, state, setFetch, calls, get } = harness();
    setFetch(async () => response(selection([article(1), article(2)])));
    await api.loadFeed(true);
    state.profile.liked = identifiers(50, 100);
    state.profile.disliked = identifiers(50, 200);
    api.changePreference("liked");
    assert.equal(state.profile.liked.length, 50);
    assert(!state.profile.liked.includes(id(100)));
    assert(state.profile.liked.includes(id(1)));
    assert.equal(state.queue.length, 0);
    assert.equal(state.exhausted, false);
    assert.equal(get("like-story").getAttribute("aria-pressed"), "true");
    api.changePreference("disliked");
    assert(!state.profile.liked.includes(id(1)));
    assert(state.profile.disliked.includes(id(1)));
    assert.equal(state.profile.disliked.length, 50);
    assert(!state.profile.disliked.includes(id(200)));
    assert.equal(get("dislike-story").getAttribute("aria-pressed"), "true");
    api.changePreference("disliked");
    assert(!state.profile.disliked.includes(id(1)));
    assert.equal(calls.length, 1, "Changing interests must not trigger automatic prefetch.");
  });

  test("cancelled requests cannot replace current content, clear a newer loading state, or mark stale items viewed", async () => {
    for (const staleFirst of [true, false]) {
      const { api, state, setFetch, get, timers } = harness();
      const pending = [];
      setFetch((_path, options) => new Promise((resolve, reject) => pending.push({ resolve, reject, options })));
      const older = api.loadFeed(true);
      const newer = api.loadFeed(true);
      assert.equal(pending[0].options.signal.aborted, true);
      assert.equal(get("reader-panel").getAttribute("aria-busy"), "true");
      if (staleFirst) {
        pending[0].resolve(response(selection([article(11)])));
        await older;
        assert.equal(state.loading, true);
        assert.equal(api.currentArticle(), null);
        assert.equal(state.profile.viewed.length, 0);
      }
      pending[1].resolve(response(selection([article(22), article(23)])));
      await newer;
      if (!staleFirst) {
        pending[0].reject(new Error("Old request failed after the new one finished."));
        await older;
      }
      assert.equal(api.currentArticle().id, id(22));
      assert.deepEqual(plain(state.profile.viewed), [id(22)]);
      assert.equal(state.queue[0].id, id(23));
      assert.equal(get("story-title").textContent, "Archived story 22");
      assert.equal(state.feedback, null);
      assert.equal(state.loading, false);
      assert.equal(timers.size, 0);
    }
  });

  test("filtered-empty batches exclude viewed/disliked IDs and pause without a refetch loop", async () => {
    const { api, state, setFetch, calls, get } = harness();
    state.profile.viewed = [id(1)];
    state.profile.disliked = [id(2)];
    setFetch(async () => response(selection([article(1), article(2)], { exhausted: false })));
    await api.loadFeed(true);
    assert.deepEqual(JSON.parse(calls[0].options.body).viewed, [id(1)]);
    assert.deepEqual(JSON.parse(calls[0].options.body).disliked, [id(2)]);
    assert.equal(api.currentArticle(), null);
    assert.equal(state.exhausted, true);
    assert.equal(state.feedback.kind, "empty");
    assert.equal(get("feed-feedback").hidden, false);
    assert.equal(get("loading-indicator").hidden, true);
    assert.equal(get("next-story").disabled, true);
    assert.equal(state.profile.viewed.length, 1);
    assert.equal(calls.length, 1);
  });

  test("service errors, invalid JSON, and connection failures show retryable errors and recover", async () => {
    const failures = [
      [async () => response({ error: { code: "unavailable", message: "Recommendation service is not ready." } }, 503), /not ready/],
      [async () => response({}, 503), /unavailable/],
      [async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("Bad JSON"); } }), /readable JSON/],
      [async () => { throw new TypeError("Failed to fetch"); }, /Check your connection/],
    ];
    for (const [mock, expected] of failures) {
      const { api, state, setFetch, get, timers } = harness();
      setFetch(mock);
      await api.loadFeed(true);
      assert.equal(state.feedback.kind, "error");
      assert.match(get("feedback-message").textContent, expected);
      assert.equal(get("retry-feed").hidden, false);
      assert.equal(get("reader-panel").getAttribute("aria-busy"), "false");
      assert.equal(state.profile.viewed.length, 0);
      setFetch(async () => response(selection([article(1)])));
      await api.loadFeed(true);
      assert.equal(state.feedback, null);
      assert.equal(get("retry-feed").hidden, true);
      assert.equal(api.currentArticle().id, id(1));
      assert.equal(timers.size, 0);
    }
  });

  test("a changed snapshot requires metadata reload without applying new items to the old profile", async () => {
    const { api, state, setFetch, get } = harness();
    setFetch(async () => response(selection([article(1)], { exhausted: false })));
    await api.loadFeed(true);
    const originalProfile = plain(state.profile);
    setFetch(async () => response(selection([article(22)], { snapshot_id: "snapshot-b" })));
    await api.loadFeed();
    assert.equal(state.feedback.kind, "error");
    assert.equal(state.retryKind, "meta");
    assert.equal(get("retry-feed").textContent, "Reload archive");
    assert.match(get("feedback-message").textContent, /snapshot changed/);
    assert.equal(api.currentArticle().id, id(1));
    assert.deepEqual(plain(state.profile), originalProfile);
    assert.equal(get("reader-panel").getAttribute("aria-busy"), "false");
  });

  test("timeouts abort the request, clear busy state and timers, and leave retry available", async () => {
    const { api, state, setFetch, timers, calls, get } = harness();
    setFetch((_path, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("Aborted")), { once: true });
    }));
    const pending = api.loadFeed(true);
    assert.equal(state.loading, true);
    assert.equal(timers.size, 1);
    const timer = [...timers.values()][0];
    assert.equal(timer.delay, 25000);
    timer.callback();
    await pending;
    assert.equal(calls[0].options.signal.aborted, true);
    assert.equal(state.loading, false);
    assert.equal(state.feedback.kind, "error");
    assert.match(get("feedback-message").textContent, /took too long/);
    assert.equal(get("retry-feed").hidden, false);
    assert.equal(get("reader-panel").getAttribute("aria-busy"), "false");
    assert.equal(state.profile.viewed.length, 0);
    assert.equal(timers.size, 0);
  });
});
