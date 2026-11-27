import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const scriptURL = new URL("./static/stories.js", import.meta.url);
const source = readFileSync(scriptURL, "utf8");
const template = readFileSync(new URL("./templates/stories.html", import.meta.url), "utf8");
const elementIDs = new Set([...template.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
const elementTags = new Map([...template.matchAll(/<([a-z0-9]+)\b[^>]*\bid="([^"]+)"/g)].map((match) => [match[2], match[1].toUpperCase()]));
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
    currentArticle, canNext, renderStory, renderChrome, renderGrid,
    openStory, closeStory, showStory, onPopState, showRelatedFeed,
    normaliseSaved, readSaved, toggleSaved, saveNote, setTimeZone,
    readSettings, applyTheme, toggleTheme
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

const flush = () => new Promise((resolve) => setImmediate(resolve));
const tileTitles = (grid) => grid.children.map((tile) => tile.children[1].children[1].children[0].textContent);
// Related-reading requests carry a seed; feed requests in these tests do not.
const feedCalls = (calls) => calls.filter((call) => call.options.body && !("seed_id" in JSON.parse(call.options.body)));

// Supports the selectors the reader uses on generated nodes: tag, [data-x], [data-x="y"] and comma lists.
function matches(node, selector) {
  return selector.split(",").some((part) => {
    const match = part.trim().match(/^([a-z][a-z0-9]*)?(?:\[data-([a-z-]+)(?:="([^"]*)")?\])?$/i);
    if (!match || (!match[1] && !match[2])) return false;
    const [, tag, key, value] = match;
    if (tag && node.tagName !== tag.toUpperCase()) return false;
    if (!key) return true;
    const name = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return Object.hasOwn(node.dataset, name) && (value === undefined || node.dataset[name] === value);
  });
}

function element(tag = "", document = null) {
  const attributes = new Map();
  const classes = new Set();
  const styles = new Map();
  const node = {
    tagName: tag.toUpperCase(),
    textContent: "",
    hidden: false,
    disabled: false,
    open: false,
    scrollTop: 0,
    dataset: {},
    children: [],
    options: [],
    parentNode: null,
    connected: false,
    style: {
      setProperty: (name, value) => styles.set(name, String(value)),
      getPropertyValue: (name) => styles.get(name) ?? "",
    },
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    },
    setAttribute: (name, value) => attributes.set(name, String(value)),
    getAttribute: (name) => attributes.get(name) ?? null,
    removeAttribute: (name) => {
      attributes.delete(name);
      if (name === "href") delete node.href;
      if (name === "datetime") delete node.dateTime;
    },
    addEventListener: () => {},
    append: (...nodes) => {
      for (const child of nodes) {
        if (child.parentNode) child.remove();
        child.parentNode = node;
        node.children.push(child);
      }
    },
    replaceChildren: (...nodes) => {
      node.children.forEach((child) => { child.parentNode = null; });
      node.children = [];
      node.append(...nodes);
    },
    remove: () => {
      if (!node.parentNode) return;
      node.parentNode.children = node.parentNode.children.filter((child) => child !== node);
      node.parentNode = null;
    },
    closest: (selector) => {
      for (let current = node; current; current = current.parentNode) if (matches(current, selector)) return current;
      return null;
    },
    querySelectorAll: (selector) => {
      const found = [];
      const walk = (parent) => parent.children.forEach((child) => {
        if (matches(child, selector)) found.push(child);
        walk(child);
      });
      walk(node);
      return found;
    },
    focus: () => {
      if (document) document.activeElement = node;
    },
    showModal: () => { node.open = true; },
    close: () => { node.open = false; },
  };
  Object.defineProperty(node, "isConnected", {
    get() {
      for (let current = node; current; current = current.parentNode) if (current.connected) return true;
      return false;
    },
  });
  Object.defineProperty(node, "className", {
    get: () => [...classes].join(" "),
    set: (value) => {
      classes.clear();
      String(value).split(/\s+/).filter(Boolean).forEach((name) => classes.add(name));
    },
  });
  Object.defineProperty(node, "innerHTML", {
    set() { assert.fail("Fetched content must use textContent, not innerHTML."); },
  });
  return node;
}

function harness({ dark = false } = {}) {
  const nodes = new Map();
  const storage = new Map();
  const timers = new Map();
  const calls = [];
  const history = [];
  const document = { activeElement: null };
  const root = element("html", document);
  let nextTimer = 0;
  let fetch = () => assert.fail("Every request must be explicitly mocked.");
  const get = (name) => {
    assert(elementIDs.has(name), `The template must contain #${name}.`);
    if (!nodes.has(name)) {
      const node = element(elementTags.get(name), document);
      node.connected = true;
      nodes.set(name, node);
    }
    return nodes.get(name);
  };
  Object.assign(document, { getElementById: get, documentElement: root, createElement: (tag) => element(tag, document) });
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
    matchMedia: () => ({ matches: dark }),
    history: {
      pushState: () => history.push("push"),
      back: () => history.push("back"),
    },
  };
  const context = createContext({
    URL, AbortController, Intl, Error, TypeError, window, document,
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
  return { api, state: api.state, get, storage, timers, calls, history, document, window, root, setFetch: (mock) => { fetch = mock; } };
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
    assert.equal(api.normaliseResponse(selection(identifiers(40).map((_, index) => article(index + 1))), "snapshot-a", "neural").items.length, 30);
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
    assert.equal(body.limit, 25);
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

  test("the grid shows a page without marking it viewed; opening, Next and More behave like a reader", async () => {
    const { api, state, setFetch, calls, get } = harness();
    setFetch(async () => response(selection([article(1), article(2), article(3)], { exhausted: false })));
    await api.loadFeed(true);
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 1", "Archived story 2", "Archived story 3"]);
    assert.equal(get("story-grid").children[0].className, "tile tile-lead");
    assert.equal(get("story-grid").children[1].className, "tile");
    assert.equal(get("story-grid").hidden, false);
    assert.equal(get("load-more").hidden, false);
    assert.equal(state.profile.viewed.length, 0, "Showing tiles must not mark them viewed.");
    api.openStory("feed", 1, null);
    await flush();
    assert.equal(get("story-dialog").open, true);
    assert.equal(api.currentArticle().id, id(2));
    assert.deepEqual(plain(state.profile.viewed), [id(2)]);
    assert.deepEqual([get("position-current").textContent, get("position-total").textContent], ["2", "3+"]);
    assert.equal(get("story-title").textContent, "Archived story 2");
    api.previousStory();
    assert.equal(api.currentArticle().id, id(1));
    assert.equal(get("previous-story").disabled, true);
    await api.nextStory();
    await api.nextStory();
    assert.equal(api.currentArticle().id, id(3));
    assert.equal(state.profile.liked.length + state.profile.disliked.length, 0);
    assert.equal(feedCalls(calls).length, 1);
    setFetch(async () => response(selection([article(1), article(4)])));
    await api.nextStory();
    assert.equal(api.currentArticle().id, id(4));
    const more = JSON.parse(feedCalls(calls)[1].options.body);
    assert.equal(more.limit, 24);
    assert.deepEqual([...more.viewed].sort(), [id(1), id(2), id(3)]);
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 1", "Archived story 2", "Archived story 3", "Archived story 4"]);
    assert.equal(api.canNext(), false);
    assert.equal(get("next-story").disabled, true);
    await api.nextStory();
    assert.equal(feedCalls(calls).length, 2);
    api.closeStory();
    assert.equal(get("story-dialog").open, false);
    assert.equal(api.currentArticle(), null);
    assert.equal(get("feed-end").hidden, false);
    assert.equal(get("load-more").hidden, true);
    state.profile.viewed = identifiers(2000);
    api.openStory("feed", 0, null);
    assert.equal(state.profile.viewed.length, 2000);
    assert.equal(state.profile.viewed[0], id(2));
    assert.equal(state.profile.viewed.at(-1), id(1));
  });

  test("preferences toggle opposing choices, cap each side, offer an update, and drop dislikes on close", async () => {
    const { api, state, setFetch, calls, get } = harness();
    setFetch(async () => response(selection([article(1), article(2)])));
    await api.loadFeed(true);
    api.openStory("feed", 0, null);
    await flush();
    state.profile.liked = identifiers(50, 100);
    state.profile.disliked = identifiers(50, 200);
    api.changePreference("liked");
    assert.equal(state.profile.liked.length, 50);
    assert(!state.profile.liked.includes(id(100)));
    assert(state.profile.liked.includes(id(1)));
    assert.equal(state.stale, true);
    assert.equal(get("like-story").getAttribute("aria-pressed"), "true");
    api.changePreference("disliked");
    assert(!state.profile.liked.includes(id(1)));
    assert(state.profile.disliked.includes(id(1)));
    assert.equal(state.profile.disliked.length, 50);
    assert(!state.profile.disliked.includes(id(200)));
    assert.equal(get("dislike-story").getAttribute("aria-pressed"), "true");
    api.changePreference("disliked");
    assert(!state.profile.disliked.includes(id(1)));
    api.changePreference("disliked");
    assert.equal(feedCalls(calls).length, 1, "Changing interests must not trigger automatic prefetch.");
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 1", "Archived story 2"], "The grid must not reflow while reading.");
    api.closeStory();
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 2"]);
    assert.equal(get("refresh-feed").hidden, false);
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
        assert.equal(state.items.length, 0);
        assert.equal(state.profile.viewed.length, 0);
      }
      pending[1].resolve(response(selection([article(22), article(23)])));
      await newer;
      if (!staleFirst) {
        pending[0].reject(new Error("Old request failed after the new one finished."));
        await older;
      }
      assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 22", "Archived story 23"]);
      assert.deepEqual(plain(state.items.map((item) => item.id)), [id(22), id(23)]);
      assert.equal(state.profile.viewed.length, 0);
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
    assert.equal(state.items.length, 0);
    assert.equal(state.exhausted, true);
    assert.equal(state.feedback.kind, "empty");
    assert.equal(get("feed-feedback").hidden, false);
    assert.equal(get("loading-indicator").hidden, true);
    assert.equal(get("story-grid").hidden, true);
    assert.equal(get("load-more").hidden, true);
    assert.equal(state.profile.viewed.length, 1);
    assert.equal(calls.length, 1);
  });

  test("views send their news window, related reading spans every window, and focus sends professional tags", () => {
    const { api, state } = harness();
    state.meta.domains = { ai: 3, "data-science": 1, "Not A Tag": 1 };
    state.profile.viewed = [id(1)];
    const fresh = api.bodyFor();
    assert.equal(fresh.window, "fresh");
    assert.equal(fresh.limit, 25);
    assert(!("domains" in fresh));
    state.professional = true;
    assert.deepEqual(plain(api.bodyFor().domains), ["ai", "data-science"]);
    state.seed = id(4);
    const related = api.bodyFor();
    assert(!("window" in related) && related.seed_id === id(4));
    state.seed = "";
    state.view = "yesterday";
    const edition = api.bodyFor();
    assert.deepEqual([edition.window, edition.limit, edition.viewed.length], ["yesterday", 10, 0]);
    const explore = api.bodyFor(true);
    assert.deepEqual([explore.window, explore.limit], ["yesterday", 24]);
  });

  test("an edition is one fixed page: opened stories stay in it and the reader never refetches", async () => {
    const { api, state, setFetch, calls, get } = harness();
    state.view = "yesterday";
    state.meta.edition_date = "2026-11-22";
    state.profile.viewed = [id(1)];
    const stories = Array.from({ length: 10 }, (_, index) => article(index + 1));
    setFetch(async () => response(selection(stories, { exhausted: false, window: "yesterday", edition_date: "2026-11-23" })));
    await api.loadFeed(true);
    assert.equal(state.items.length, 10);
    assert.equal(state.exhausted, true);
    assert.equal(state.meta.edition_date, "2026-11-23");
    assert.equal(get("selection-label").textContent, "Yesterday’s edition");
    assert.equal(get("page-date").textContent, "Monday 23 November");
    assert.equal(get("load-more").hidden, true);
    assert.equal(get("feed-end").hidden, false);
    assert.match(get("end-message").textContent, /yesterday’s edition: 10 stories published on Monday 23 November/);
    api.openStory("feed", 0, null);
    api.changePreference("liked");
    assert.equal(state.stale, false);
    assert.match(get("reader-status").textContent, /This edition stays as it is/);
    for (let step = 0; step < 9; step += 1) await api.nextStory();
    assert.equal(api.currentArticle().id, id(10));
    assert.equal(api.canNext(), false);
    assert.equal(get("position-total").textContent, "10");
    assert.equal(feedCalls(calls).length, 1);
    api.closeStory();
    assert.equal(state.items.length, 10);
  });

  test("saved stories and notes persist across snapshots, stay literal, and are bounded", async () => {
    const { api, state, setFetch, storage, get } = harness();
    setFetch(async () => response(selection([article(1, { url: "https://example.invalid/one" }), article(2)])));
    await api.loadFeed(true);
    const star = get("story-grid").children[1].children[2];
    assert.equal(star.dataset.save, id(2));
    api.toggleSaved(state.items[1]);
    assert.deepEqual(JSON.parse(storage.get("afterline:saved")).map((item) => item.id), [id(2)]);
    assert.deepEqual([star.textContent, star.getAttribute("aria-pressed")], ["★", "true"]);
    assert.equal(get("open-saved").textContent, "Saved stories (1)");
    api.toggleSaved(state.items[1]);
    assert.deepEqual([star.textContent, star.getAttribute("aria-pressed")], ["☆", "false"]);
    api.openStory("feed", 0, null);
    api.toggleSaved();
    assert.equal(get("save-story").getAttribute("aria-pressed"), "true");
    assert.equal(get("save-label").textContent, "Saved");
    assert.equal(get("save-icon").textContent, "★");
    assert.equal(get("note-editor").hidden, false);
    get("story-note").value = `<b>why</b> ${"x".repeat(2100)}`;
    api.saveNote();
    const stored = JSON.parse(storage.get("afterline:saved"));
    assert.equal(stored.length, 1);
    assert.equal(stored[0].note.length, 2000);
    assert(stored[0].note.startsWith("<b>why</b>"));
    assert.equal(get("note-status").textContent, "Note saved in this browser.");
    state.storageKey = "afterline:profile:snapshot-b";
    assert.equal(api.readSaved()[0].url, "https://example.invalid/one");
    api.toggleSaved();
    assert.deepEqual(JSON.parse(storage.get("afterline:saved")), []);
    assert.equal(get("note-editor").hidden, true);
    const cleaned = api.normaliseSaved([
      { id: id(5), title: "  Kept  ", url: "javascript:alert(1)", note: 7 },
      { id: id(5).toUpperCase(), title: "Duplicate" }, { id: "not-a-uuid" }, null,
    ]);
    assert.deepEqual(plain(cleaned.map((item) => [item.title, item.url, item.note])), [["Kept", "", ""]]);
    assert.equal(api.normaliseSaved(identifiers(250).map((value) => ({ id: value }))).length, 200);
  });

  test("a typed note survives moving to another story or closing the reader without a save click", async () => {
    const { api, setFetch, storage, get } = harness();
    setFetch(async () => response(selection([article(1), article(2)])));
    await api.loadFeed(true);
    api.openStory("feed", 0, null);
    api.toggleSaved();
    get("story-note").value = "typed before swiping";
    await api.nextStory();
    assert.equal(JSON.parse(storage.get("afterline:saved"))[0].note, "typed before swiping");
    assert.equal(get("story-note").value, "");
    api.previousStory();
    assert.equal(get("story-note").value, "typed before swiping");
    get("story-note").value = "typed before closing";
    api.closeStory();
    assert.equal(JSON.parse(storage.get("afterline:saved"))[0].note, "typed before closing");
  });

  test("the theme follows the computer until a reader picks one, and the choice is kept", () => {
    const dark = harness({ dark: true });
    dark.api.applyTheme();
    assert.equal(dark.root.dataset.theme, undefined);
    assert.equal(dark.get("theme-toggle").getAttribute("aria-pressed"), "true");
    dark.api.toggleTheme();
    assert.equal(dark.root.dataset.theme, "light");
    assert.equal(dark.get("theme-toggle").getAttribute("aria-pressed"), "false");
    assert.equal(dark.get("action-status").textContent, "Light theme on. Saved in this browser.");
    assert.deepEqual(JSON.parse(dark.storage.get("afterline:settings")), { professional: false, theme: "light" });
    dark.api.toggleTheme();
    assert.equal(dark.root.dataset.theme, "dark");

    const light = harness();
    light.api.applyTheme();
    assert.equal(light.root.dataset.theme, undefined);
    assert.equal(light.get("theme-toggle").getAttribute("aria-pressed"), "false");
    light.storage.set("afterline:settings", JSON.stringify({ professional: true, theme: "neon" }));
    assert.deepEqual(plain(light.api.readSettings()), { professional: true, theme: "" });
    light.storage.set("afterline:settings", "{broken");
    assert.deepEqual(plain(light.api.readSettings()), { professional: false, theme: "" });
    light.storage.set("afterline:settings", JSON.stringify({ theme: "dark" }));
    Object.assign(light.state, light.api.readSettings());
    light.api.applyTheme();
    assert.equal(light.root.dataset.theme, "dark");
    assert.equal(light.get("theme-toggle").getAttribute("aria-pressed"), "true");
  });

  test("story dates show the edition time zone, label unverified dates, and mark fresh stories", () => {
    const { api, get } = harness();
    api.setTimeZone("Asia/Kolkata");
    api.renderStory(api.normaliseArticle(article(1, { date_verified: false })));
    assert.equal(get("story-date").textContent, "Published 2 March 2024 · date unverified");
    assert.equal(get("story-stamp").textContent, "From the archive");
    api.renderStory(api.normaliseArticle(article(2, { date_verified: true, fresh: true })));
    assert.equal(get("story-date").textContent, "Published 2 March 2024");
    assert.equal(get("story-stamp").textContent, "Fresh · last 30 days");
    api.setTimeZone("Not/AZone");
    api.renderStory(api.normaliseArticle(article(3)));
    assert.equal(get("story-date").textContent, "Published 2 March 2024");
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
      assert.equal(state.items[0].id, id(1));
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
    assert.deepEqual(plain(state.items.map((item) => item.id)), [id(1)]);
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

  test("tiles keep fetched text literal, skip insecure images, and badge freshness only in related reading", async () => {
    const { api, state, setFetch, get } = harness();
    const hostile = "<img src=x onerror=alert(1)>";
    setFetch(async () => response(selection([
      article(1, { title: hostile, source_name: hostile, text: hostile, image_url: "http://example.invalid/image.jpg" }),
      article(2, { text: "", image_url: "https://example.invalid/image.jpg", fresh: true }),
    ])));
    await api.loadFeed(true);
    const [lead, second] = get("story-grid").children;
    const [media, body, save] = lead.children;
    assert.equal(media.children.length, 1, "An insecure image must not be requested.");
    assert.equal(media.children[0].className, "tile-placeholder");
    assert.equal(body.children[0].children[0].textContent, hostile);
    assert.equal(body.children[1].children[0].textContent, hostile);
    assert.equal(body.children[2].textContent, hostile);
    assert.equal(save.dataset.save, id(1));
    assert.equal(save.getAttribute("aria-label"), `Save: ${hostile}`);
    const image = second.children[0].children[1];
    assert.deepEqual([image.tagName, image.src, image.referrerPolicy, image.loading],
      ["IMG", "https://example.invalid/image.jpg", "no-referrer", "lazy"]);
    assert.equal(second.children[1].children.length, 2, "A headline-only story shows no summary line.");
    assert.equal(get("story-grid").querySelectorAll("span").filter((node) => node.className.startsWith("tile-badge")).length, 0);
    state.seed = id(9);
    await api.loadFeed(true);
    const badges = get("story-grid").children.map((tile) => tile.children[0].children.at(-1));
    assert.deepEqual(badges.map((badge) => [badge.className, badge.textContent]),
      [["tile-badge", "From the archive"], ["tile-badge is-fresh", "Fresh"]]);
  });

  test("related reading asks for six stories around the open one and keeps its own trail", async () => {
    const { api, state, setFetch, calls, get, history } = harness();
    state.meta.domains = { ai: 3 };
    state.professional = true;
    setFetch(async () => response(selection([article(1), article(2)], { exhausted: false })));
    await api.loadFeed(true);
    setFetch(async () => response(selection([article(1), article(30, { fresh: true }), article(31)])));
    api.openStory("feed", 0, null);
    await flush();
    const related = JSON.parse(calls.at(-1).options.body);
    assert.deepEqual([related.seed_id, related.limit, related.window, related.domains, related.viewed],
      [id(1), 6, undefined, ["ai"], [id(1)]]);
    assert.deepEqual(tileTitles(get("related-grid")), ["Archived story 30", "Archived story 31"]);
    assert.equal(get("related-grid").children[0].children[0].children.at(-1).textContent, "Fresh");
    api.openStory("related", 1, null);
    await flush();
    assert.equal(api.currentArticle().id, id(31));
    assert.deepEqual([get("position-current").textContent, get("position-total").textContent], ["2", "2"]);
    assert.equal(api.canNext(), false);
    api.previousStory();
    assert.equal(api.currentArticle().id, id(30));
    assert.equal(feedCalls(calls).length, 1);
    assert.deepEqual(history, ["push"], "Opening related stories inside the reader adds no history entries.");
    setFetch(async () => response(selection([article(40), article(41)])));
    api.showRelatedFeed();
    assert.equal(api.currentArticle(), null);
    assert.deepEqual(history, ["push", "back"]);
    await flush();
    const seeded = JSON.parse(calls.at(-1).options.body);
    assert.deepEqual([seeded.seed_id, seeded.limit, seeded.window], [id(30), 25, undefined]);
    assert.equal(get("selection-label").textContent, "Related reading");
    assert.equal(get("selection-note").textContent, "Related to “Archived story 30”");
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 40", "Archived story 41"]);
  });

  test("browser Back closes the reader in place, and focus returns to the tile that opened it", async () => {
    const { api, state, setFetch, get, history, document } = harness();
    setFetch(async () => response(selection([article(1), article(2)])));
    await api.loadFeed(true);
    const opener = get("story-grid").children[1].children[1].children[1].children[0];
    assert.equal(opener.dataset.index, "1");
    api.openStory("feed", 1, opener);
    assert.equal(document.activeElement, get("story-title"));
    api.onPopState();
    assert.equal(state.readerOpen, false);
    assert.equal(get("story-dialog").open, false);
    assert.equal(document.activeElement, opener);
    assert.deepEqual(history, ["push"], "Back already removed the story entry.");
    api.openStory("feed", 0, opener);
    api.closeStory();
    assert.deepEqual(history, ["push", "push", "back"]);
    api.openStory("feed", 0, opener);
    api.onPopState();
    assert.equal(state.readerOpen, true, "The popstate caused by closing must not close a newly opened story.");
    api.onPopState();
    assert.equal(state.readerOpen, false);
  });

  test("marking every story not interested leaves an explained page with an update, not a blank one", async () => {
    const { api, state, setFetch, calls, get } = harness();
    setFetch(async () => response(selection([article(1), article(2)], { exhausted: false })));
    await api.loadFeed(true);
    api.openStory("feed", 0, null);
    api.changePreference("disliked");
    await api.nextStory();
    api.changePreference("disliked");
    api.closeStory();
    assert.equal(state.items.length, 0);
    assert.equal(state.feedback.kind, "empty");
    assert.equal(get("feed-feedback").hidden, false);
    assert.equal(get("feedback-title").textContent, "Nothing left on this page.");
    assert.equal(get("refresh-feed").hidden, false);
    assert.equal(get("feedback-explore").hidden, false);
    assert.equal(feedCalls(calls).length, 1, "Emptying the page must not refetch on its own.");
  });

  test("after not-interested choices, closing focuses the opener's story or the next story kept after it", async () => {
    const { api, setFetch, get, document } = harness();
    setFetch(async () => response(selection([article(1), article(2), article(3), article(4)])));
    await api.loadFeed(true);
    const openButton = (index) => get("story-grid").children[index].children[1].children[1].children[0];
    api.openStory("feed", 1, openButton(1));
    await api.nextStory();
    api.changePreference("disliked");
    api.closeStory();
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 1", "Archived story 2", "Archived story 4"]);
    assert.equal(document.activeElement, openButton(1));
    assert.equal(document.activeElement.textContent, "Archived story 2");
    api.openStory("feed", 1, openButton(1));
    api.changePreference("disliked");
    api.closeStory();
    assert.deepEqual(tileTitles(get("story-grid")), ["Archived story 1", "Archived story 4"]);
    assert.equal(document.activeElement.textContent, "Archived story 4");
  });
});
