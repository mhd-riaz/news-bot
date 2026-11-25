(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const METHODS = {
    neural: { name: "Neural", note: "Neural · similarity in a learned article-content space, not a model of you." },
    tfidf: { name: "TF–IDF", note: "TF–IDF · similarities in weighted words. A more literal lens on article content." },
    svd: { name: "SVD", note: "SVD · similarities in a reduced content space. Another view of the same archive." },
  };
  // ponytail: 50 preferences per side and the last 2,000 views per snapshot; upgrade to server history only if this local ceiling is insufficient.
  const PREFERENCE_LIMIT = 50;
  const HISTORY_LIMIT = 2000;
  // A lead story and eight rows of three, then whole rows; the service caps one request at 30.
  const FIRST_PAGE = 25;
  const MORE_PAGE = 24;
  const MAX_BATCH = 30;
  const EXPLORE_SIZE = 24;
  const EDITION_SIZE = 10;
  const RELATED_SIZE = 6;
  // Saved stories and notes are browser-only for the demo (owner decision D18); C8 moves them to the account.
  const SAVED_KEY = "afterline:saved";
  const SETTINGS_KEY = "afterline:settings";
  const SAVED_LIMIT = 200;
  const NOTE_LIMIT = 2000;
  const DOMAIN_TAG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const THEMES = ["light", "dark"];
  // Without a saved choice the stylesheet follows this query; the script only mirrors it on the toggle.
  const darkQuery = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const VIEWS = {
    fresh: { label: "Fresh", note: "Stories from the last 30 days with a verified publication date. Newest first until you add interests." },
    yesterday: { label: "Yesterday", note: "Up to 10 stories published yesterday, one per story, ranked by your interests." },
    archive: { label: "Archive", note: "Older stories, plus stories whose publication date could not be verified." },
  };
  const ZONE_NAMES = { "Asia/Kolkata": "India time", UTC: "UTC" };
  const countFormat = new Intl.NumberFormat("en-GB");
  const editionFormat = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
  let timeZone = "UTC";
  let fullDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone });
  let shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone });
  let dateTime = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone });
  let dayFormat = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone });
  const state = {
    meta: null,
    profile: emptyProfile(),
    storageKey: "",
    persistence: true,
    method: "",
    view: "fresh",
    professional: false,
    theme: "",
    saved: [],
    noteFor: "",
    topic: "",
    seed: "",
    seedTitle: "",
    items: [],
    exhausted: false,
    stale: false,
    loading: true,
    feedback: { kind: "loading", title: "Opening the stories.", message: "Connecting to the recommendation service." },
    retryKind: "meta",
    retryReplace: true,
    endMessage: "",
    exploreCache: null,
    tasteItems: [],
    selected: new Set(),
    tasteLoading: false,
    tasteReload: false,
    readerOpen: false,
    open: -1,
    readerTrail: null,
    related: [],
    opener: null,
    pushedHistory: false,
  };
  let metaVersion = 0;
  let feedVersion = 0;
  let tasteVersion = 0;
  let displayVersion = 0;
  let relatedVersion = 0;
  let ignoredPops = 0;
  let metaController;
  let feedController;
  let tasteController;
  let relatedController;

  function emptyProfile() {
    return { liked: [], disliked: [], viewed: [], onboarded: false };
  }

  function ids(value, limit) {
    return Array.isArray(value)
      ? [...new Set(value.filter((id) => typeof id === "string" && UUID.test(id)).map((id) => id.toLowerCase()))].slice(-limit)
      : [];
  }

  function normaliseProfile(value) {
    const profile = value && typeof value === "object" ? value : {};
    const disliked = ids(profile.disliked, PREFERENCE_LIMIT);
    return {
      liked: ids(profile.liked, PREFERENCE_LIMIT).filter((id) => !disliked.includes(id)),
      disliked,
      viewed: ids(profile.viewed, HISTORY_LIMIT),
      onboarded: profile.onboarded === true,
    };
  }

  function warnStorage(message) {
    $("storage-warning").textContent = message;
    $("storage-warning").hidden = false;
  }

  function readProfile() {
    let stored;
    try {
      stored = window.localStorage.getItem(state.storageKey);
    } catch {
      state.persistence = false;
      warnStorage("Local storage is unavailable. Interests and viewed history will last only in this open tab, not after you leave.");
      return emptyProfile();
    }
    if (!stored) return emptyProfile();
    try {
      return normaliseProfile(JSON.parse(stored));
    } catch {
      warnStorage("The saved profile could not be read. Starting with empty interests for this snapshot; new choices will replace that unreadable local profile.");
      return emptyProfile();
    }
  }

  function saveProfile() {
    if (!state.persistence || !state.storageKey) return;
    try {
      window.localStorage.setItem(state.storageKey, JSON.stringify(state.profile));
    } catch {
      state.persistence = false;
      warnStorage("Your latest choices could not be saved. Persistence is unavailable; interests and history now last only in this open tab. Older saved choices may return on your next visit.");
    }
  }

  function readSettings() {
    try {
      const value = JSON.parse(window.localStorage.getItem(SETTINGS_KEY) || "{}");
      return { professional: value?.professional === true, theme: THEMES.includes(value?.theme) ? value.theme : "" };
    } catch {
      return { professional: false, theme: "" };
    }
  }

  function saveSettings() {
    try {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        professional: state.professional, ...(state.theme ? { theme: state.theme } : {}),
      }));
    } catch {
      // The setting still applies in this tab; storage problems are reported by profile writes.
    }
  }

  function isDark() {
    return state.theme ? state.theme === "dark" : Boolean(darkQuery?.matches);
  }

  function applyTheme() {
    const root = document.documentElement;
    if (root) {
      if (state.theme) root.dataset.theme = state.theme;
      else delete root.dataset.theme;
    }
    $("theme-toggle").setAttribute("aria-pressed", String(isDark()));
  }

  function toggleTheme() {
    state.theme = isDark() ? "light" : "dark";
    saveSettings();
    applyTheme();
    announce(`${state.theme === "dark" ? "Dark" : "Light"} theme on. Saved in this browser.`);
  }

  function normaliseSaved(value) {
    const seen = new Set();
    const items = [];
    for (const item of Array.isArray(value) ? value : []) {
      if (!item || typeof item.id !== "string" || !UUID.test(item.id) || seen.has(item.id.toLowerCase())) continue;
      seen.add(item.id.toLowerCase());
      items.push({
        id: item.id.toLowerCase(),
        title: typeof item.title === "string" && item.title.trim() ? item.title.trim().slice(0, 500) : "Untitled story",
        source_name: typeof item.source_name === "string" ? item.source_name.slice(0, 200) : "",
        url: safeURL(item.url),
        published_at: typeof item.published_at === "string" ? item.published_at : "",
        note: typeof item.note === "string" ? item.note.slice(0, NOTE_LIMIT) : "",
        saved_at: typeof item.saved_at === "string" ? item.saved_at : "",
      });
    }
    return items.slice(-SAVED_LIMIT);
  }

  function readSaved() {
    try {
      return normaliseSaved(JSON.parse(window.localStorage.getItem(SAVED_KEY) || "[]"));
    } catch {
      warnStorage("Saved stories could not be read in this browser. New saves start a fresh list.");
      return [];
    }
  }

  function writeSaved() {
    try {
      window.localStorage.setItem(SAVED_KEY, JSON.stringify(state.saved));
      return true;
    } catch {
      warnStorage("Saved stories could not be stored in this browser; they last only in this open tab.");
      return false;
    }
  }

  function savedItem(id) {
    return state.saved.find((item) => item.id === id) || null;
  }

  function toggleSaved(article = currentArticle()) {
    if (!article) return;
    const reading = currentArticle()?.id === article.id;
    if (savedItem(article.id)) {
      state.saved = state.saved.filter((item) => item.id !== article.id);
      announce("Removed from saved stories.");
    } else {
      state.saved = [...state.saved, {
        id: article.id, title: article.title, source_name: article.source_name, url: article.url,
        published_at: typeof article.published_at === "string" ? article.published_at : "",
        note: "", saved_at: new Date().toISOString(),
      }].slice(-SAVED_LIMIT);
      announce(reading ? "Saved in this browser. Add a note below if you like." : "Saved in this browser. Open the story to add a note.");
    }
    writeSaved();
    // A related tile can be saved while another story is open; that story's note box stays untouched.
    if (reading) {
      $("story-note").value = savedItem(article.id)?.note || "";
      $("note-status").textContent = "";
    }
    renderSaveButtons(article.id);
    renderChrome();
  }

  function persistNote() {
    // The note box belongs to the story it was filled for, even after navigation has moved on.
    const item = state.noteFor && savedItem(state.noteFor);
    if (!item) return null;
    const note = String($("story-note").value).slice(0, NOTE_LIMIT);
    if (item.note === note) return true;
    item.note = note;
    return writeSaved();
  }

  function saveNote() {
    const saved = persistNote();
    if (saved === null) return;
    $("note-status").textContent = saved ? "Note saved in this browser." : "Note kept for this tab only.";
    announce("Note saved.");
  }

  function setTimeZone(zone) {
    try {
      const next = (options) => new Intl.DateTimeFormat("en-GB", { ...options, timeZone: zone });
      const formats = [
        next({ day: "numeric", month: "long", year: "numeric" }),
        next({ day: "numeric", month: "short", year: "numeric" }),
        next({ day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }),
        next({ weekday: "long", day: "numeric", month: "long" }),
      ];
      [fullDate, shortDate, dateTime, dayFormat] = formats;
      timeZone = zone;
    } catch {
      // An unknown zone keeps the previous formats rather than breaking the page.
    }
  }

  function zoneName() {
    return ZONE_NAMES[timeZone] || timeZone;
  }

  function editionDate() {
    const value = typeof state.meta?.edition_date === "string" ? dateValue(`${state.meta.edition_date}T00:00:00Z`) : null;
    return value ? editionFormat.format(value) : "yesterday";
  }

  function professionalDomains() {
    const domains = state.meta?.domains && typeof state.meta.domains === "object" ? Object.keys(state.meta.domains) : [];
    return domains.filter((tag) => DOMAIN_TAG.test(tag)).slice(0, 8);
  }

  function safeURL(value, image = false) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value.trim());
      if (url.username || url.password) return "";
      return (image ? url.protocol === "https:" : ["http:", "https:"].includes(url.protocol)) ? url.href : "";
    } catch {
      return "";
    }
  }

  function dateValue(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function articleDate(item) {
    const publication = item.date_kind !== "Collected" ? dateValue(item.published_at) : null;
    const date = publication || dateValue(item.collected_at);
    return { date, label: publication ? "Published" : "Collected" };
  }

  function normaliseMetadata(value) {
    if (!value || typeof value.snapshot_id !== "string" || !value.snapshot_id.trim()
        || !Number.isSafeInteger(value.articles) || value.articles < 0 || !Array.isArray(value.methods)) {
      throw new Error("Archive information was incomplete. Please retry the connection.");
    }
    const methods = [...new Set(value.methods.filter((method) => Object.hasOwn(METHODS, method)))];
    if (!methods.length) throw new Error("No supported recommendation lens is available for this archive.");
    const defaultMethod = value.default_method === undefined ? methods[0] : value.default_method;
    if (!methods.includes(defaultMethod)) throw new Error("The archive supplied an unsupported default lens.");
    const seen = new Set();
    const topics = (Array.isArray(value.topics) ? value.topics : []).filter((topic) => {
      if (!topic || typeof topic.id !== "string" || !topic.id || typeof topic.label !== "string" || seen.has(topic.id)) return false;
      seen.add(topic.id);
      return true;
    });
    return { ...value, methods, topics, default_method: defaultMethod };
  }

  function normaliseArticle(value) {
    if (!value || typeof value.id !== "string" || !UUID.test(value.id)) return null;
    const text = typeof value.text === "string" ? value.text.trim() : "";
    const kinds = ["Stored summary", "Excerpt", "Headline only"];
    return {
      id: value.id.toLowerCase(),
      title: typeof value.title === "string" && value.title.trim() ? value.title.trim() : "Untitled archived article",
      source_name: typeof value.source_name === "string" ? value.source_name : "",
      url: safeURL(value.url),
      image_url: safeURL(value.image_url, true),
      published_at: value.published_at,
      collected_at: value.collected_at,
      date_kind: value.date_kind,
      score: typeof value.score === "number" && Number.isFinite(value.score) ? value.score : null,
      reason: typeof value.reason === "string" ? value.reason : "",
      text,
      text_kind: text && kinds.includes(value.text_kind) ? value.text_kind : "Headline only",
      input_kind: ["body", "summary", "headline"].includes(value.input_kind) ? value.input_kind : "headline",
      group: typeof value.group === "string" ? value.group : "",
      date_verified: typeof value.date_verified === "boolean" ? value.date_verified : null,
      fresh: value.fresh === true,
    };
  }

  function normaliseResponse(value, snapshot, method) {
    if (!value || !Array.isArray(value.items)) throw new Error("The archive returned an unreadable selection. Please retry.");
    if (value.snapshot_id !== snapshot) {
      const error = new Error("The archive snapshot changed. Reload archive information to use the matching local profile.");
      error.reloadMetadata = true;
      throw error;
    }
    if (value.method !== method) throw new Error("The archive returned a different lens than requested. Please retry.");
    const seen = new Set();
    const items = value.items.slice(0, MAX_BATCH).map(normaliseArticle).filter((item) => {
      if (!item || seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
    if (value.items.length && !items.length) throw new Error("No valid archived articles were returned. Please retry.");
    return { ...value, items };
  }

  async function requestJSON(path, controller, body) {
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 25000);
    try {
      const response = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: body ? { Accept: "application/json", "Content-Type": "application/json" } : { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      let value;
      try {
        value = await response.json();
      } catch {
        throw new Error("The recommendation service did not return readable JSON. Please retry.");
      }
      if (!response.ok) {
        const message = typeof value?.error?.message === "string" ? value.error.message : "";
        throw new Error(message || (response.status === 503
          ? "The recommendation service is unavailable. No replacement or sample stories are shown."
          : `The archive request failed (HTTP ${response.status}). Please retry.`));
      }
      return value;
    } catch (error) {
      if (timedOut) throw new Error("The archive took too long to respond. Please retry when the recommendation service is ready.");
      if (error instanceof TypeError) throw new Error("Could not reach the recommendation service. Check your connection, then retry.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function stopFeed() {
    feedVersion += 1;
    feedController?.abort();
    feedController = null;
    state.loading = false;
  }

  function stopTaste() {
    tasteVersion += 1;
    tasteController?.abort();
    tasteController = null;
    state.tasteLoading = false;
  }

  function stopRelated() {
    relatedVersion += 1;
    relatedController?.abort();
    relatedController = null;
  }

  function isEdition() {
    return state.view === "yesterday" && !state.seed;
  }

  function bodyFor(explore = false) {
    // A daily edition is a fixed selection: opening a story must not remove it on the next visit.
    const edition = state.view === "yesterday" && (explore || !state.seed);
    // Stories already on the page are left out of the next page without being marked viewed.
    const shown = explore ? [] : state.items.map((item) => item.id);
    const body = {
      liked: explore ? [] : state.profile.liked.slice(-PREFERENCE_LIMIT),
      disliked: state.profile.disliked.slice(-PREFERENCE_LIMIT),
      viewed: edition ? [] : [...new Set([...state.profile.viewed, ...shown])].slice(-HISTORY_LIMIT),
      method: state.method,
      limit: explore ? EXPLORE_SIZE : edition ? EDITION_SIZE : shown.length ? MORE_PAGE : FIRST_PAGE,
    };
    // Related reading spans fresh and archived stories, so older background can surface (C7, R23).
    if (!explore && state.seed) body.seed_id = state.seed;
    else if (VIEWS[state.view]) body.window = state.view;
    if (!explore && state.topic) body.topic = state.topic;
    const domains = state.professional ? professionalDomains() : [];
    if (domains.length) body.domains = domains;
    return body;
  }

  function relatedBody(article) {
    const body = {
      liked: state.profile.liked.slice(-PREFERENCE_LIMIT),
      disliked: state.profile.disliked.slice(-PREFERENCE_LIMIT),
      viewed: state.profile.viewed.slice(-HISTORY_LIMIT),
      method: state.method,
      limit: RELATED_SIZE,
      seed_id: article.id,
    };
    const domains = state.professional ? professionalDomains() : [];
    if (domains.length) body.domains = domains;
    return body;
  }

  function textElement(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  }

  function buildTopics() {
    $("topic-list").querySelectorAll("[data-generated-topic]").forEach((element) => element.remove());
    state.meta.topics.forEach((topic) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "topic-button";
      button.dataset.topic = topic.id;
      button.dataset.generatedTopic = "true";
      button.setAttribute("aria-pressed", "false");
      button.append(textElement("span", "topic-label", topic.label));
      const count = Number.isSafeInteger(topic.count) && topic.count >= 0 ? countFormat.format(topic.count) : "";
      button.title = count ? `${topic.label} · ${count} articles` : topic.label;
      if (count) button.append(textElement("span", "topic-count", count));
      $("topic-list").append(button);
    });
    $("topic-all-count").textContent = countFormat.format(state.meta.articles);
    $("topic-status").textContent = `${state.meta.topics.length} content groups available. These are unsupervised clusters.`;
  }

  function renderMetadata() {
    const meta = state.meta;
    if (typeof meta.edition_timezone === "string" && meta.edition_timezone) setTimeZone(meta.edition_timezone);
    $("corpus-count").textContent = countFormat.format(meta.articles);
    const windows = meta.windows && typeof meta.windows === "object" ? meta.windows : {};
    $("fresh-count").textContent = Number.isSafeInteger(windows.fresh) ? countFormat.format(windows.fresh) : "Not supplied";
    $("edition-label").textContent = `Yesterday’s edition · ${editionDate()}`;
    $("edition-count").textContent = Number.isSafeInteger(windows.yesterday)
      ? `${countFormat.format(windows.yesterday)} stories published that day` : "Not supplied";
    const range = Array.isArray(meta.publication_range) ? meta.publication_range.map(dateValue) : [];
    $("publication-range").textContent = range.length === 2 && range.every(Boolean)
      ? `${shortDate.format(range[0])} — ${shortDate.format(range[1])}` : "Publication range not supplied";
    const cutoff = dateValue(meta.collected_before);
    $("collection-cutoff").textContent = cutoff ? `${dateTime.format(cutoff)} (${zoneName()})` : "Cutoff not supplied";
    $("snapshot-label").textContent = `Snapshot ${meta.snapshot_id.slice(0, 12)}`;
    $("snapshot-label").title = meta.snapshot_id;
    $("profile-note").textContent = `Profiles are saved only in this browser and included in same-origin recommendation requests. Article content and explicit interests only; no account or historical-user learning.${typeof meta.profile_note === "string" ? ` ${meta.profile_note}` : ""}`;
    $("date-note").textContent = `A snapshot taken at a fixed time, not a live feed. Dates are absolute and shown in ${zoneName()}.${typeof meta.date_note === "string" ? ` ${meta.date_note}` : " Collection dates are labelled when publication dates are unavailable."}`;
    for (const option of $("method").options) option.disabled = !meta.methods.includes(option.value);
  }

  function activeList() {
    return state.readerTrail || state.items;
  }

  function currentArticle() {
    return state.readerOpen ? activeList()[state.open] || null : null;
  }

  function findArticle(id) {
    return [state.items, state.related, state.readerTrail || []].flat().find((item) => item.id === id) || null;
  }

  function canPrevious() {
    return Boolean(currentArticle()) && state.open > 0;
  }

  function canNext() {
    if (!currentArticle()) return false;
    if (state.open < activeList().length - 1) return true;
    // Only the main feed grows from the reader; a related trail and a daily edition are fixed lists.
    return !state.readerTrail && !isEdition() && !state.exhausted && !state.loading && state.feedback?.kind !== "error";
  }

  function announce(message) {
    $("action-status").textContent = message;
    $("reader-status").textContent = state.readerOpen ? message : "";
  }

  function renderChrome() {
    const ready = Boolean(state.meta);
    const edition = isEdition();
    $("reader-panel").setAttribute("aria-busy", String(state.loading));
    $("method").disabled = !ready;
    $("method").value = state.method;
    $("lens-note").textContent = state.method ? METHODS[state.method].note : "Loading available content lenses.";
    for (const id of ["start-onboarding", "skip-onboarding", "edit-interests", "open-reset"]) $(id).disabled = !ready || state.loading;
    $("onboarding-invite").hidden = !ready || state.profile.onboarded;
    $("edit-interests").hidden = !state.profile.onboarded;
    $("topic-list").querySelectorAll("button[data-topic]").forEach((button) => {
      button.disabled = !ready;
      button.setAttribute("aria-pressed", String(button.dataset.topic === state.topic));
    });
    for (const view of Object.keys(VIEWS)) {
      $(`view-${view}`).disabled = !ready;
      $(`view-${view}`).setAttribute("aria-pressed", String(!state.seed && view === state.view));
    }
    const domains = ready ? professionalDomains() : [];
    $("focus-control").hidden = !domains.length;
    $("professional-focus").disabled = !ready || !domains.length;
    $("professional-focus").checked = state.professional;
    const focus = state.professional && domains.length ? ` Professional focus: ${domains.join(", ")} sources only.` : "";
    $("view-note").textContent = (state.seed
      ? "Stories close to the one you chose, from fresh news and the archive, so older background can surface."
      : state.view === "fresh" && state.profile.liked.length
        ? "Stories from the last 30 days with a verified publication date, ranked around the stories you like."
        : VIEWS[state.view].note) + focus;
    $("open-saved").disabled = false;
    $("open-saved").textContent = `Saved stories (${state.saved.length})`;
    $("profile-summary").textContent = ready
      ? `${state.profile.liked.length} ${state.profile.liked.length === 1 ? "like" : "likes"} · ${state.profile.disliked.length} not interested · local to this snapshot`
      : "Interests are saved in this browser.";
    if (ready) {
      const viewed = Math.min(state.profile.viewed.length, state.meta.articles);
      const percent = state.meta.articles ? (viewed / state.meta.articles * 100) : 0;
      const coverage = percent > 0 && percent < .1 ? "<0.1" : percent.toFixed(1);
      $("corpus-coverage").textContent = `${countFormat.format(viewed)} of ${countFormat.format(state.meta.articles)} articles opened locally · ${coverage}% of the collection. Stories you only scroll past do not count.`;
    }
    const personal = state.profile.liked.length || state.profile.disliked.length;
    $("selection-label").textContent = state.seed ? "Related reading"
      : edition ? "Yesterday’s edition"
        : state.view === "archive" ? "From the archive"
          : personal ? "For you" : "Latest news";
    $("page-date").textContent = edition ? (state.meta?.edition_date ? editionDate() : "Yesterday") : dayFormat.format(new Date());
    const group = state.meta?.topics.find((topic) => topic.id === state.topic);
    $("selection-note").hidden = !state.seed && !group;
    $("selection-note").textContent = state.seed
      ? state.seedTitle ? `Related to “${state.seedTitle}”` : "Using the article in your link as a content seed."
      : group ? `Thread: ${group.label}` : "";

    const feedback = state.feedback;
    $("feed-feedback").hidden = !feedback;
    $("feed-feedback").classList.toggle("with-story", state.items.length > 0);
    $("loading-indicator").hidden = feedback?.kind !== "loading";
    if (feedback) {
      $("feedback-kicker").textContent = feedback.kind === "error" ? "An honest pause" : feedback.kind === "empty" ? "A little breathing room" : "A moment of context";
      $("feedback-title").textContent = feedback.title;
      $("feedback-message").textContent = feedback.message;
    }
    $("retry-feed").hidden = feedback?.kind !== "error";
    $("retry-feed").textContent = state.retryKind === "meta" ? "Reload archive" : "Try again";
    $("feedback-explore").hidden = feedback?.kind !== "empty" || !ready;
    $("feedback-interests").hidden = feedback?.kind !== "empty" || !ready;
    $("story-grid").hidden = !state.items.length;
    $("load-more").hidden = !state.items.length || state.loading || Boolean(feedback) || state.exhausted || edition;
    $("refresh-feed").hidden = !state.stale || state.loading;
    $("feed-end").hidden = !(state.items.length && !state.loading && !feedback && state.exhausted);
    $("end-message").textContent = state.endMessage || "That’s everything in this selection for now. Try another thread or lens, add interests, or reset local history to revisit the collection.";
    renderReaderChrome();
  }

  function renderReaderChrome() {
    const article = currentArticle();
    $("previous-story").disabled = !canPrevious();
    $("next-story").disabled = !canNext();
    for (const id of ["like-story", "dislike-story", "related-story", "save-story"]) $(id).disabled = !article;
    $("like-story").setAttribute("aria-pressed", String(Boolean(article && state.profile.liked.includes(article.id))));
    $("dislike-story").setAttribute("aria-pressed", String(Boolean(article && state.profile.disliked.includes(article.id))));
    const saved = Boolean(article && savedItem(article.id));
    $("save-story").setAttribute("aria-pressed", String(saved));
    $("save-icon").textContent = saved ? "★" : "☆";
    $("save-label").textContent = saved ? "Saved" : "Save";
    $("note-editor").hidden = !saved;
    const total = activeList().length;
    const more = !state.readerTrail && !isEdition() && !state.exhausted;
    const position = article ? state.open + 1 : 0;
    $("position-current").textContent = String(position);
    $("position-total").textContent = `${total}${more && total ? "+" : ""}`;
    $("story-progress").max = Math.max(1, total);
    $("story-progress").value = position;
    $("story-progress").setAttribute("aria-valuetext", `Story ${position} of ${total}${more ? "; more may be available" : ""}`);
  }

  function hue(text) {
    let value = 0;
    for (const character of String(text)) value = (value * 31 + character.codePointAt(0)) % 360;
    return value;
  }

  function clip(text, limit) {
    if (text.length <= limit) return text;
    const boundary = text.lastIndexOf(" ", limit);
    return `${text.slice(0, boundary > limit * .6 ? boundary : limit).trimEnd()}…`;
  }

  function shortDateLabel(article) {
    const { date, label } = articleDate(article);
    const when = date ? `${label === "Collected" ? "Collected " : ""}${shortDate.format(date)}` : "Date unavailable";
    return `${when}${article.date_verified === false ? " · date unverified" : ""}`;
  }

  function coverImage(article, className) {
    const image = document.createElement("img");
    if (className) image.className = className;
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("load", () => {
      // Logos and tracking pixels look like broken pictures; the coloured placeholder reads better.
      if (image.naturalWidth < 240 || image.naturalHeight < 120) image.remove();
      else image.classList.add("is-loaded");
    }, { once: true });
    image.addEventListener("error", () => image.remove(), { once: true });
    image.src = article.image_url;
    return image;
  }

  function renderSaveButton(button, article) {
    const saved = Boolean(savedItem(article.id));
    button.textContent = saved ? "★" : "☆";
    button.title = saved ? "Saved · select to remove" : "Save for later";
    button.setAttribute("aria-pressed", String(saved));
    button.setAttribute("aria-label", `Save: ${article.title}`);
  }

  function renderSaveButtons(id) {
    const article = findArticle(id);
    if (!article) return;
    for (const grid of [$("story-grid"), $("related-grid")]) {
      grid.querySelectorAll(`button[data-save="${id}"]`).forEach((button) => renderSaveButton(button, article));
    }
  }

  function renderTile(article, index, { list = "feed", lead = false, badge = false, level = 2 } = {}) {
    const tile = document.createElement("article");
    tile.className = lead ? "tile tile-lead" : "tile";
    const media = document.createElement("div");
    media.className = "tile-media";
    media.style.setProperty("--tile-hue", String(hue(article.source_name || article.id)));
    const placeholder = document.createElement("div");
    placeholder.className = "tile-placeholder";
    placeholder.setAttribute("aria-hidden", "true");
    const group = state.meta?.topics.find((topic) => topic.id === article.group)?.label;
    placeholder.append(textElement("span", "tile-placeholder-source", article.source_name || "AFTERLINE"),
      textElement("span", "tile-placeholder-topic", group || "From the collection"));
    media.append(placeholder);
    if (article.image_url) media.append(coverImage(article, "tile-image"));
    if (badge) media.append(textElement("span", article.fresh ? "tile-badge is-fresh" : "tile-badge", article.fresh ? "Fresh" : "From the archive"));
    const body = document.createElement("div");
    body.className = "tile-body";
    const meta = document.createElement("p");
    meta.className = "tile-meta";
    meta.append(textElement("span", "tile-source", article.source_name || "Unlisted source"), textElement("span", "tile-date", shortDateLabel(article)));
    const heading = document.createElement(`h${level}`);
    heading.className = "tile-title";
    const open = textElement("button", "tile-open", article.title);
    open.type = "button";
    open.dataset.open = list;
    open.dataset.index = String(index);
    heading.append(open);
    body.append(meta, heading);
    if (article.text_kind !== "Headline only" && article.text) body.append(textElement("p", "tile-summary", clip(article.text, lead ? 420 : 240)));
    const save = document.createElement("button");
    save.type = "button";
    save.className = "tile-save";
    save.dataset.save = article.id;
    renderSaveButton(save, article);
    tile.append(media, body, save);
    return tile;
  }

  function renderGrid(start = 0) {
    const grid = $("story-grid");
    if (!start) grid.replaceChildren();
    // Freshness badges help only where fresh and archived stories mix: related reading.
    const badge = Boolean(state.seed);
    state.items.slice(start).forEach((article, offset) => {
      grid.append(renderTile(article, start + offset, { lead: start + offset === 0, badge }));
    });
    grid.hidden = !state.items.length;
  }

  function renderRelated() {
    $("related-grid").replaceChildren(...state.related.map((article, index) => renderTile(article, index, { list: "related", badge: true, level: 4 })));
  }

  function renderImage(article) {
    const version = ++displayVersion;
    const image = $("story-image").cloneNode(false);
    image.removeAttribute("src");
    image.hidden = true;
    $("story-image").replaceWith(image);
    const cover = $("story-cover");
    cover.hidden = !article.image_url;
    cover.classList.toggle("is-loading", Boolean(article.image_url));
    $("story-caption").textContent = "";
    if (!article.image_url) return;
    image.addEventListener("load", () => {
      if (version !== displayVersion || currentArticle()?.id !== article.id) return;
      cover.classList.remove("is-loading");
      if (image.naturalWidth < 320 || image.naturalHeight < 160) {
        cover.hidden = true;
        return;
      }
      image.hidden = false;
      $("story-caption").textContent = `Image: ${article.source_name || "the original publisher"}`;
    }, { once: true });
    image.addEventListener("error", () => {
      if (version !== displayVersion || currentArticle()?.id !== article.id) return;
      cover.classList.remove("is-loading");
      cover.hidden = true;
    }, { once: true });
    image.referrerPolicy = "no-referrer";
    image.src = article.image_url;
  }

  function renderStory(article) {
    $("story-title").textContent = article.title;
    $("story-source").textContent = article.source_name || "Unlisted source";
    const { date, label } = articleDate(article);
    const unverified = article.date_verified === false ? " · date unverified" : "";
    $("story-date").textContent = date ? `${label} ${fullDate.format(date)}${unverified}` : "Stored date unavailable";
    if (date) $("story-date").dateTime = date.toISOString();
    else $("story-date").removeAttribute("datetime");
    $("story-stamp").textContent = article.fresh ? "Fresh · last 30 days" : "From the archive";
    $("story-stamp").classList.toggle("is-fresh", article.fresh);
    persistNote();
    state.noteFor = article.id;
    $("story-note").value = savedItem(article.id)?.note || "";
    $("note-status").textContent = "";
    $("story-text-kind").textContent = article.text_kind;
    const text = article.text_kind === "Headline only"
      ? "Only the headline is stored for this story. Open the original for more context; the external page may have changed."
      : article.text;
    let split = text.length;
    if (text.length > 760) {
      const boundary = text.lastIndexOf(" ", 650);
      split = boundary > 400 ? boundary : 650;
    }
    $("story-text").textContent = text.slice(0, split).trim();
    $("remaining-text").textContent = text.slice(split).trim();
    $("more-text").hidden = split === text.length;
    $("more-text").open = false;
    $("match-details").open = false;
    $("story-reason").textContent = article.reason || "Selected using article content and the interests you explicitly choose, not a historical user profile.";
    $("story-score").textContent = article.score === null
      ? `${METHODS[state.method].name} content lens. No match score was supplied.`
      : `${METHODS[state.method].name} match score: ${article.score.toFixed(3)}. Scores are lens-specific, not confidence ratings or a measure of reporting quality.`;
    const inputs = { body: "article body", summary: "stored summary", headline: "headline only" };
    $("story-input").textContent = `Model input: ${inputs[article.input_kind]}. Displayed text: ${article.text_kind.toLowerCase()}.`;
    $("read-original").hidden = !article.url;
    $("original-unavailable").hidden = Boolean(article.url);
    $("read-original-label").textContent = article.source_name ? `Read the full story at ${article.source_name}` : "Read the full story";
    if (article.url) $("read-original").href = article.url;
    else $("read-original").removeAttribute("href");
    renderImage(article);
  }

  function showStory(index) {
    const article = activeList()[index];
    if (!article) return;
    state.open = index;
    state.profile.viewed = [...state.profile.viewed.filter((id) => id !== article.id), article.id].slice(-HISTORY_LIMIT);
    saveProfile();
    renderStory(article);
    renderChrome();
    $("reader-status").textContent = "";
    $("story-dialog").scrollTop = 0;
    $("story-title").focus({ preventScroll: true });
    $("reader-live").textContent = `Story ${index + 1}: ${article.title}. ${$("story-date").textContent}.`;
    loadRelated(article);
  }

  function openStory(list, index, opener = null) {
    const source = list === "related" ? state.related : state.items;
    if (!state.meta || !source[index]) return;
    // A related story opens a trail of its own, so Next stays within that related list.
    state.readerTrail = list === "related" ? source.slice() : null;
    if (!state.readerOpen) {
      state.readerOpen = true;
      state.opener = opener;
      if (!$("story-dialog").open) $("story-dialog").showModal();
      try {
        window.history.pushState({ afterlineStory: true }, "");
        state.pushedHistory = true;
      } catch {
        state.pushedHistory = false;
      }
    }
    showStory(index);
  }

  function closeStory() {
    if (!state.readerOpen) return;
    const pushed = state.pushedHistory;
    finishClose();
    if (pushed) {
      // Drop the story's history entry so Back leaves the page next time; its popstate is ignored.
      ignoredPops += 1;
      window.history.back();
    }
  }

  function finishClose() {
    if (!state.readerOpen) return;
    persistNote();
    state.noteFor = "";
    stopRelated();
    displayVersion += 1;
    state.readerOpen = false;
    state.pushedHistory = false;
    state.readerTrail = null;
    state.open = -1;
    state.related = [];
    $("related-grid").replaceChildren();
    if ($("story-dialog").open) $("story-dialog").close();
    const opener = state.opener;
    state.opener = null;
    let focusIndex = -1;
    // Not-interested stories leave the page once the reader is closed; a daily edition stays fixed.
    if (!isEdition()) {
      const disliked = new Set(state.profile.disliked);
      const kept = state.items.filter((item) => !disliked.has(item.id));
      if (kept.length !== state.items.length) {
        // The rebuild detaches the opener: focus its story's new tile, or the next story kept after it.
        const openerIndex = opener?.dataset?.open === "feed" ? Number(opener.dataset.index) : -1;
        if (openerIndex >= 0 && kept.length) {
          focusIndex = Math.min(state.items.slice(0, openerIndex).filter((item) => !disliked.has(item.id)).length, kept.length - 1);
        }
        state.items = kept;
        renderGrid(0);
        if (!kept.length && !state.loading) {
          state.feedback = {
            kind: "empty",
            title: "Nothing left on this page.",
            message: state.stale
              ? "Every story here is marked not interested. Update the page for your new choices, or try another thread or view."
              : "Every story here is marked not interested. Show all stories, or try another thread or view.",
          };
        }
      }
    }
    renderChrome();
    const tile = focusIndex >= 0 ? $("story-grid").querySelectorAll(`button[data-index="${focusIndex}"]`)[0] : null;
    if (opener?.isConnected) opener.focus({ preventScroll: true });
    else if (tile) tile.focus();
    else $("reader-panel").focus({ preventScroll: true });
  }

  function onPopState() {
    if (ignoredPops > 0) {
      ignoredPops -= 1;
      return;
    }
    if (!state.readerOpen) return;
    state.pushedHistory = false;
    finishClose();
  }

  async function loadRelated(article) {
    stopRelated();
    const version = relatedVersion;
    const controller = new AbortController();
    relatedController = controller;
    state.related = [];
    $("related-grid").replaceChildren();
    $("related-status").textContent = "Finding related reading…";
    const body = relatedBody(article);
    const snapshot = state.meta.snapshot_id;
    try {
      const raw = await requestJSON("/api/v1/recommendations", controller, body);
      if (version !== relatedVersion) return;
      const response = normaliseResponse(raw, snapshot, body.method);
      const disliked = new Set(state.profile.disliked);
      state.related = response.items.filter((item) => item.id !== article.id && !disliked.has(item.id)).slice(0, RELATED_SIZE);
      renderRelated();
      $("related-status").textContent = state.related.length ? "" : "No related stories were found for this one. Another lens may find some.";
    } catch (error) {
      if (version !== relatedVersion) return;
      $("related-status").textContent = `Related reading is unavailable. ${error.message || "Please try again."}`;
    } finally {
      if (version === relatedVersion) relatedController = null;
    }
  }

  async function nextStory() {
    if (!canNext()) return;
    if (state.open < activeList().length - 1) {
      showStory(state.open + 1);
      return;
    }
    const before = state.items.length;
    const position = state.open;
    $("reader-status").textContent = "Loading more stories…";
    await loadFeed(false);
    if (!state.readerOpen || state.readerTrail || state.open !== position) return;
    if (state.items.length > before) showStory(before);
    else $("reader-status").textContent = state.feedback?.kind === "error" ? state.feedback.message : "That’s everything in this selection.";
  }

  function previousStory() {
    if (canPrevious()) showStory(state.open - 1);
  }

  function changePreference(kind) {
    const article = currentArticle();
    if (!article) return;
    const opposite = kind === "liked" ? "disliked" : "liked";
    const hadPreference = state.profile[kind].includes(article.id);
    state.profile[kind] = state.profile[kind].filter((id) => id !== article.id);
    if (!hadPreference) state.profile[kind] = [...state.profile[kind], article.id].slice(-PREFERENCE_LIMIT);
    state.profile[opposite] = state.profile[opposite].filter((id) => id !== article.id);
    // A daily edition is one fixed page: choices shape the Fresh feed and the next edition, not this one.
    const edition = isEdition();
    if (!edition && !state.seed) state.stale = true;
    saveProfile();
    renderChrome();
    const done = hadPreference ? "Choice removed." : kind === "liked" ? "Interest added." : "Marked not interested.";
    announce(edition ? `${done} This edition stays as it is; your choice shapes the Fresh feed and the next edition.`
      : !hadPreference && kind === "disliked" ? `${done} It leaves the page when you close this story.`
        : state.seed ? `${done} It shapes your next selection.`
          : `${done} Back on the stories, “Update for your new choices” re-ranks them.`);
  }

  function scrollToFeed() {
    if (!(window.scrollY > 0) || typeof window.scrollTo !== "function") return;
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
  }

  function showRelatedFeed() {
    const article = currentArticle();
    if (!article) return;
    state.seed = article.id;
    state.seedTitle = article.title;
    state.topic = "";
    state.opener = null;
    closeStory();
    loadFeed(true);
  }

  function exploreAll() {
    if (!state.meta) return;
    state.topic = "";
    state.seed = "";
    state.seedTitle = "";
    loadFeed(true);
  }

  function skipOnboarding() {
    state.profile.onboarded = true;
    saveProfile();
    if ($("taste-dialog").open) $("taste-dialog").close();
    renderChrome();
    $("edit-interests").focus({ preventScroll: true });
    announce("No new interests added. You can choose them any time; opening a story never adds one.");
  }

  function renderServiceNote(response) {
    const notes = [];
    if (Array.isArray(response.unavailable_ids) && response.unavailable_ids.length) notes.push(`${response.unavailable_ids.length} saved or seed article references were not found in this snapshot.`);
    if (Number.isSafeInteger(response.ignored_viewed_ids) && response.ignored_viewed_ids > 0) notes.push(`${response.ignored_viewed_ids} viewed references were ignored by the service; local coverage may differ.`);
    $("service-note").textContent = notes.join(" ");
    $("service-note").hidden = !notes.length;
  }

  function emptyFeedback(edition) {
    if (edition) {
      return { title: "No edition for this selection.", message: `No stories with a verified date from ${editionDate()} (${zoneName()}) match this selection. Try Fresh, another thread, or switch off Professional focus.` };
    }
    if (!state.seed && state.view === "fresh") {
      return { title: "Nothing fresh here yet.", message: "No unseen stories from the last 30 days match this selection. Try the archive, another thread, or switch off Professional focus." };
    }
    return { title: "Room for a different thread.", message: "No unseen articles were returned for this selection. Try another thread or lens, choose interests, or reset your local history to revisit archived stories." };
  }

  async function loadFeed(replace = false) {
    if (!state.meta) return;
    stopFeed();
    const version = feedVersion;
    const controller = new AbortController();
    feedController = controller;
    if (replace) {
      // The like/dislike hint points at the update button; once the stories reload it no longer applies.
      if (state.stale) announce("Updating the stories for your choices.");
      state.items = [];
      state.exhausted = false;
      state.stale = false;
      renderGrid(0);
      scrollToFeed();
    }
    state.loading = true;
    state.endMessage = "";
    state.retryKind = "feed";
    state.retryReplace = replace;
    state.feedback = replace
      ? { kind: "loading", title: "Finding your stories.", message: "Using article content and your explicit choices. Stories you have opened are left out." }
      : { kind: "loading", title: "Finding more stories.", message: "Stories already on this page and stories you have opened are left out." };
    $("service-note").hidden = true;
    renderChrome();
    const body = bodyFor();
    const snapshot = state.meta.snapshot_id;
    try {
      const raw = await requestJSON("/api/v1/recommendations", controller, body);
      if (version !== feedVersion) return;
      const response = normaliseResponse(raw, snapshot, body.method);
      const edition = body.window === "yesterday" && !body.seed_id;
      if (edition && typeof response.edition_date === "string") state.meta.edition_date = response.edition_date;
      const excluded = new Set([...(edition ? [] : state.profile.viewed), ...state.profile.disliked, ...state.items.map((item) => item.id)]);
      if (state.seed) excluded.add(state.seed);
      const items = response.items.filter((item) => !excluded.has(item.id));
      if (!state.seed && !state.topic && !state.profile.liked.length && !state.exploreCache) state.exploreCache = items.slice(0, EXPLORE_SIZE);
      const start = state.items.length;
      state.items = [...state.items, ...items];
      // A filtered-empty batch pauses for a human choice instead of refetching in a loop; an edition is one fixed page.
      state.exhausted = edition || response.exhausted === true || !items.length;
      state.feedback = null;
      renderServiceNote(response);
      renderGrid(start);
      if (items.length) {
        if (edition) {
          state.endMessage = `That’s yesterday’s edition: ${items.length} ${items.length === 1 ? "story" : "stories"} published on ${editionDate()} (${zoneName()}).${items.length < EDITION_SIZE ? ` Only ${items.length} matched this selection.` : ""} Switch to Fresh for today’s news.`;
        }
        $("reader-live").textContent = `${items.length} ${start ? "more " : ""}${items.length === 1 ? "story" : "stories"} loaded.`;
      } else if (!state.items.length) {
        state.feedback = { kind: "empty", ...emptyFeedback(edition) };
        $("reader-live").textContent = "No unseen stories were returned for this selection.";
      } else {
        state.endMessage = "No more unseen stories were returned. Try another thread or lens, or reset local history to revisit the collection.";
        $("reader-live").textContent = "No more unseen stories in this selection.";
      }
    } catch (error) {
      if (version !== feedVersion) return;
      if (error.reloadMetadata) state.retryKind = "meta";
      state.feedback = { kind: "error", title: "The archive needs a moment.", message: error.message || "Could not load recommendations. Please retry." };
      $("reader-live").textContent = `Recommendations unavailable. ${state.feedback.message}`;
    } finally {
      if (version === feedVersion) {
        state.loading = false;
        feedController = null;
        renderChrome();
      }
    }
  }

  async function loadMetadata() {
    const version = ++metaVersion;
    metaController?.abort();
    stopFeed();
    stopTaste();
    if ($("taste-dialog").open) $("taste-dialog").close();
    const controller = new AbortController();
    metaController = controller;
    state.meta = null;
    state.items = [];
    state.exhausted = false;
    state.stale = false;
    state.exploreCache = null;
    state.loading = true;
    state.retryKind = "meta";
    state.feedback = { kind: "loading", title: "Opening the stories.", message: "Loading the snapshot, its dates, and its content groups. No sample stories are used." };
    renderGrid(0);
    renderChrome();
    try {
      const raw = await requestJSON("/api/v1/recommendations/meta", controller);
      if (version !== metaVersion) return;
      const meta = normaliseMetadata(raw);
      state.meta = meta;
      if (!meta.methods.includes(state.method)) state.method = meta.default_method;
      if (!meta.topics.some((topic) => topic.id === state.topic)) state.topic = "";
      const storageKey = `afterline:profile:${meta.snapshot_id}`;
      if (storageKey !== state.storageKey) {
        state.storageKey = storageKey;
        state.profile = readProfile();
      }
      buildTopics();
      renderMetadata();
      await loadFeed(true);
    } catch (error) {
      if (version !== metaVersion) return;
      state.loading = false;
      state.feedback = { kind: "error", title: "No archive connection.", message: error.message || "Archive information is unavailable. Please retry." };
      $("topic-status").textContent = "Archive topics are unavailable until the recommendation service connects.";
      $("reader-live").textContent = state.feedback.message;
      renderChrome();
    } finally {
      if (version === metaVersion) metaController = null;
    }
  }

  function updateTasteSelection() {
    const count = state.selected.size;
    $("taste-count").textContent = `${count} / 5 selected`;
    $("taste-submit").textContent = count ? `Add ${count} ${count === 1 ? "interest" : "interests"} ↗` : "Explore without selecting ↗";
    $("taste-hint").textContent = count === 5
      ? "Five selected. Uncheck one to choose a different story. Offered articles are not marked viewed."
      : "Three to five is a useful start; fewer is fine. Only selected articles become interests, not viewed history.";
    $("taste-list").querySelectorAll("input").forEach((input) => {
      input.disabled = count >= 5 && !input.checked;
    });
  }

  function renderTaste(items) {
    state.tasteItems = items;
    state.tasteReload = false;
    $("taste-list").replaceChildren();
    items.forEach((item) => {
      const label = document.createElement("label");
      label.className = "taste-choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "interest";
      input.value = item.id;
      input.checked = state.selected.has(item.id);
      const thumb = document.createElement("span");
      thumb.className = "taste-thumb";
      thumb.setAttribute("aria-hidden", "true");
      thumb.style.setProperty("--tile-hue", String(hue(item.source_name || item.id)));
      if (item.image_url) thumb.append(coverImage(item, ""));
      const copy = document.createElement("span");
      const { date, label: dateLabel } = articleDate(item);
      const meta = `${item.source_name || "Unlisted source"} · ${date ? `${dateLabel.toLowerCase()} ${shortDate.format(date)}` : "Stored date unavailable"}`;
      copy.append(textElement("span", "taste-title", item.title), textElement("span", "taste-meta", meta));
      label.append(input, thumb, copy);
      $("taste-list").append(label);
    });
    $("taste-loading").hidden = true;
    $("taste-error").hidden = true;
    $("taste-empty").hidden = items.length > 0;
    $("taste-options").disabled = false;
    $("taste-submit").disabled = false;
    updateTasteSelection();
  }

  async function loadExplore() {
    stopTaste();
    const version = tasteVersion;
    const controller = new AbortController();
    tasteController = controller;
    state.tasteLoading = true;
    state.tasteReload = false;
    state.selected.clear();
    state.tasteItems = [];
    $("taste-list").replaceChildren();
    $("taste-options").disabled = true;
    $("taste-submit").disabled = true;
    $("taste-loading").hidden = false;
    $("taste-error").hidden = true;
    $("taste-retry").textContent = "Retry Explore";
    $("taste-empty").hidden = true;
    updateTasteSelection();
    const body = bodyFor(true);
    const snapshot = state.meta.snapshot_id;
    try {
      const raw = await requestJSON("/api/v1/recommendations", controller, body);
      if (version !== tasteVersion || !$("taste-dialog").open) return;
      const response = normaliseResponse(raw, snapshot, body.method);
      const excluded = new Set([...state.profile.viewed, ...state.profile.disliked]);
      state.exploreCache = response.items.filter((item) => !excluded.has(item.id));
      renderTaste(state.exploreCache);
    } catch (error) {
      if (version !== tasteVersion || !$("taste-dialog").open) return;
      $("taste-loading").hidden = true;
      $("taste-error").hidden = false;
      $("taste-error-message").textContent = error.message || "Could not load Explore. Retry, or skip for now.";
      state.tasteReload = error.reloadMetadata === true;
      $("taste-retry").textContent = state.tasteReload ? "Reload archive" : "Retry Explore";
    } finally {
      if (version === tasteVersion) {
        state.tasteLoading = false;
        tasteController = null;
      }
    }
  }

  function openTaste() {
    if (!state.meta || state.loading || $("taste-dialog").open) return;
    state.selected = new Set();
    $("taste-dialog").showModal();
    const cached = state.exploreCache?.filter((item) => !state.profile.disliked.includes(item.id));
    if (cached?.length) renderTaste(cached);
    else loadExplore();
  }

  function renderSaved() {
    $("saved-list").replaceChildren();
    $("saved-empty").hidden = state.saved.length > 0;
    [...state.saved].reverse().forEach((item) => {
      const entry = document.createElement("li");
      entry.className = "saved-item";
      const title = textElement(item.url ? "a" : "p", "saved-title", item.title);
      if (item.url) {
        title.href = item.url;
        title.target = "_blank";
        title.rel = "noopener noreferrer";
        title.referrerPolicy = "no-referrer";
      }
      const date = dateValue(item.published_at);
      const meta = `${item.source_name || "Unlisted source"}${date ? ` · ${shortDate.format(date)}` : ""}`;
      const remove = textElement("button", "text-button muted-button", "Remove");
      remove.type = "button";
      remove.dataset.remove = item.id;
      entry.append(title, textElement("p", "saved-meta", meta),
        textElement("p", item.note ? "saved-note" : "saved-note empty", item.note || "No note yet."), remove);
      $("saved-list").append(entry);
    });
  }

  function changeView(view) {
    if (!state.meta || !VIEWS[view] || (view === state.view && !state.seed)) return;
    state.view = view;
    state.seed = "";
    state.seedTitle = "";
    state.exploreCache = null;
    loadFeed(true);
  }

  function onGridClick(event) {
    const save = event.target.closest?.("button[data-save]");
    if (save) {
      const article = findArticle(save.dataset.save);
      if (article) toggleSaved(article);
      return;
    }
    const open = event.target.closest?.("button[data-open]");
    if (open) openStory(open.dataset.open, Number(open.dataset.index), open);
  }

  function installGestures() {
    let start = null;
    const card = $("story-card");
    card.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch" || event.isPrimary === false || event.target.closest("a, button, input, textarea, summary, details")) {
        start = null;
        return;
      }
      start = { id: event.pointerId, x: event.clientX, y: event.clientY, time: event.timeStamp };
    });
    card.addEventListener("pointermove", (event) => {
      if (start && event.pointerId === start.id && Math.abs(event.clientY - start.y) > 22) start = null;
    });
    card.addEventListener("pointercancel", () => { start = null; });
    card.addEventListener("pointerup", (event) => {
      const swipe = start;
      start = null;
      if (!swipe || swipe.id !== event.pointerId || !state.readerOpen || window.getSelection()?.toString()) return;
      const dx = event.clientX - swipe.x;
      const dy = event.clientY - swipe.y;
      if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.7 || event.timeStamp - swipe.time > 900) return;
      if (dx < 0) nextStory();
      else previousStory();
    });
    document.addEventListener("keydown", (event) => {
      if (!state.readerOpen || event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
          || event.target.closest?.("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox']")
          || window.getSelection()?.toString()) return;
      if (event.key === "ArrowRight" && canNext()) {
        event.preventDefault();
        nextStory();
      } else if (event.key === "ArrowLeft" && canPrevious()) {
        event.preventDefault();
        previousStory();
      }
    });
  }

  function init() {
    const settings = readSettings();
    state.saved = readSaved();
    state.professional = settings.professional;
    state.theme = settings.theme;
    applyTheme();
    $("theme-toggle").addEventListener("click", toggleTheme);
    darkQuery?.addEventListener?.("change", applyTheme);
    const article = new URL(window.location.href).searchParams.get("article");
    if (article && UUID.test(article)) state.seed = article.toLowerCase();
    else if (article) {
      $("link-note").textContent = "That article link is not a valid archive ID. Exploring the collection instead.";
      $("link-note").hidden = false;
    }
    $("topic-list").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-topic]");
      if (!button || button.disabled || !state.meta) return;
      state.topic = button.dataset.topic;
      state.seed = "";
      state.seedTitle = "";
      loadFeed(true);
    });
    $("method").addEventListener("change", () => {
      if (!state.meta?.methods.includes($("method").value)) return;
      state.method = $("method").value;
      loadFeed(true);
    });
    for (const view of Object.keys(VIEWS)) $(`view-${view}`).addEventListener("click", () => changeView(view));
    $("professional-focus").addEventListener("change", () => {
      if (!state.meta) return;
      state.professional = $("professional-focus").checked;
      saveSettings();
      state.exploreCache = null;
      loadFeed(true);
    });
    $("story-grid").addEventListener("click", onGridClick);
    $("related-grid").addEventListener("click", onGridClick);
    $("load-more").addEventListener("click", () => loadFeed(false));
    $("refresh-feed").addEventListener("click", () => loadFeed(true));
    $("close-story").addEventListener("click", closeStory);
    $("story-dialog").addEventListener("cancel", (event) => {
      event.preventDefault();
      closeStory();
    });
    $("story-dialog").addEventListener("close", () => {
      if (state.readerOpen) closeStory();
    });
    window.addEventListener("popstate", onPopState);
    // Closing the reader steps Back in history; restoring that entry's old scroll position would undo scrollToFeed.
    if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
    $("save-story").addEventListener("click", () => toggleSaved());
    $("save-note").addEventListener("click", saveNote);
    // Persist quietly while typing, so a swipe, reload or closed tab cannot lose a note.
    $("story-note").addEventListener("input", persistNote);
    $("story-note").addEventListener("change", saveNote);
    $("open-saved").addEventListener("click", () => {
      if ($("saved-dialog").open) return;
      renderSaved();
      $("saved-dialog").showModal();
    });
    $("close-saved").addEventListener("click", () => $("saved-dialog").close());
    $("saved-list").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-remove]");
      if (!button) return;
      state.saved = state.saved.filter((item) => item.id !== button.dataset.remove);
      writeSaved();
      renderSaved();
      renderSaveButtons(button.dataset.remove);
      renderChrome();
    });
    $("previous-story").addEventListener("click", previousStory);
    $("next-story").addEventListener("click", () => nextStory());
    $("like-story").addEventListener("click", () => changePreference("liked"));
    $("dislike-story").addEventListener("click", () => changePreference("disliked"));
    $("related-story").addEventListener("click", showRelatedFeed);
    $("retry-feed").addEventListener("click", () => {
      if (state.retryKind === "meta") loadMetadata();
      else loadFeed(state.retryReplace);
    });
    for (const id of ["feedback-explore", "end-explore"]) $(id).addEventListener("click", exploreAll);
    for (const id of ["start-onboarding", "edit-interests", "feedback-interests", "end-interests"]) $(id).addEventListener("click", openTaste);
    for (const id of ["skip-onboarding", "taste-skip"]) $(id).addEventListener("click", skipOnboarding);
    $("close-taste").addEventListener("click", () => $("taste-dialog").close());
    $("taste-dialog").addEventListener("close", stopTaste);
    $("taste-retry").addEventListener("click", () => {
      if (state.tasteReload) {
        $("taste-dialog").close();
        loadMetadata();
      } else loadExplore();
    });
    $("taste-list").addEventListener("change", (event) => {
      const input = event.target;
      if (input.type !== "checkbox" || !state.tasteItems.some((item) => item.id === input.value)) return;
      if (input.checked && state.selected.size < 5) state.selected.add(input.value);
      else {
        state.selected.delete(input.value);
        input.checked = false;
      }
      updateTasteSelection();
    });
    $("taste-form").addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.tasteLoading || $("taste-submit").disabled) return;
      const selected = [...state.selected].filter((id) => state.tasteItems.some((item) => item.id === id)).slice(0, 5);
      state.profile.liked = [...state.profile.liked.filter((id) => !selected.includes(id)), ...selected].slice(-PREFERENCE_LIMIT);
      state.profile.disliked = state.profile.disliked.filter((id) => !selected.includes(id));
      state.profile.onboarded = true;
      saveProfile();
      $("taste-dialog").close();
      renderChrome();
      if (selected.length) {
        announce(`${selected.length} ${selected.length === 1 ? "interest" : "interests"} added. Opening a new selection using your choices.`);
        exploreAll();
        $("reader-panel").focus({ preventScroll: true });
      } else {
        $("edit-interests").focus({ preventScroll: true });
        announce("Exploring without new interests. You can add them any time.");
      }
    });
    $("open-reset").addEventListener("click", () => {
      if (state.meta && !state.loading) $("reset-dialog").showModal();
    });
    $("cancel-reset").addEventListener("click", () => $("reset-dialog").close());
    $("reset-form").addEventListener("submit", (event) => {
      event.preventDefault();
      stopFeed();
      stopTaste();
      state.profile = emptyProfile();
      state.exploreCache = null;
      saveProfile();
      $("reset-dialog").close();
      announce("Interests and viewed history cleared for this snapshot. Newly opened stories start a fresh history.");
      exploreAll();
      $("reader-panel").focus({ preventScroll: true });
    });
    installGestures();
    loadMetadata();
  }

  init();
})();
