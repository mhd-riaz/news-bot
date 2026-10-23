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
  const BATCH_SIZE = 24;
  const countFormat = new Intl.NumberFormat("en-GB");
  const fullDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const state = {
    meta: null,
    profile: emptyProfile(),
    storageKey: "",
    persistence: true,
    method: "neural",
    topic: "",
    seed: "",
    seedTitle: "",
    history: [],
    position: -1,
    queue: [],
    exhausted: false,
    loading: true,
    feedback: { kind: "loading", title: "Opening the archive.", message: "Connecting to the recommendation service. These are stored articles, not current news." },
    retryKind: "meta",
    retryReplace: true,
    endMessage: "",
    exploreCache: null,
    tasteItems: [],
    selected: new Set(),
    tasteLoading: false,
    tasteReload: false,
  };
  let metaVersion = 0;
  let feedVersion = 0;
  let tasteVersion = 0;
  let displayVersion = 0;
  let metaController;
  let feedController;
  let tasteController;

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
    const seen = new Set();
    const topics = (Array.isArray(value.topics) ? value.topics : []).filter((topic) => {
      if (!topic || typeof topic.id !== "string" || !topic.id || typeof topic.label !== "string" || seen.has(topic.id)) return false;
      seen.add(topic.id);
      return true;
    });
    return { ...value, methods, topics };
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
    const items = value.items.slice(0, BATCH_SIZE).map(normaliseArticle).filter((item) => {
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

  function bodyFor(explore = false) {
    const body = {
      liked: explore ? [] : state.profile.liked.slice(-PREFERENCE_LIMIT),
      disliked: state.profile.disliked.slice(-PREFERENCE_LIMIT),
      viewed: state.profile.viewed.slice(-HISTORY_LIMIT),
      method: state.method,
      limit: BATCH_SIZE,
    };
    if (!explore && state.seed) body.seed_id = state.seed;
    if (!explore && state.topic) body.topic = state.topic;
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
    state.meta.topics.forEach((topic, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "topic-button";
      button.dataset.topic = topic.id;
      button.dataset.generatedTopic = "true";
      button.title = topic.label;
      button.setAttribute("aria-pressed", "false");
      const disc = textElement("span", "topic-disc", String(index + 1).padStart(2, "0"));
      disc.setAttribute("aria-hidden", "true");
      const count = Number.isSafeInteger(topic.count) && topic.count >= 0 ? `${countFormat.format(topic.count)} articles` : "Content group";
      button.append(disc, textElement("span", "topic-label", topic.label), textElement("span", "topic-count", count));
      $("topic-list").append(button);
    });
    $("topic-all-count").textContent = `${countFormat.format(state.meta.articles)} articles`;
    $("topic-status").textContent = `${state.meta.topics.length} content groups available. These are unsupervised clusters.`;
  }

  function renderMetadata() {
    const meta = state.meta;
    $("corpus-count").textContent = countFormat.format(meta.articles);
    const range = Array.isArray(meta.publication_range) ? meta.publication_range.map(dateValue) : [];
    $("publication-range").textContent = range.length === 2 && range.every(Boolean)
      ? `${shortDate.format(range[0])} — ${shortDate.format(range[1])}` : "Publication range not supplied";
    const cutoff = dateValue(meta.collected_before);
    $("collection-cutoff").textContent = cutoff ? `Before ${fullDate.format(cutoff)} (UTC)` : "Cutoff not supplied";
    $("snapshot-label").textContent = `Snapshot ${meta.snapshot_id.slice(0, 12)}`;
    $("snapshot-label").title = meta.snapshot_id;
    $("profile-note").textContent = `Profiles are saved only in this browser and included in same-origin recommendation requests. Article content and explicit interests only; no account or historical-user learning.${typeof meta.profile_note === "string" ? ` ${meta.profile_note}` : ""}`;
    $("date-note").textContent = `Archived, not current news. Dates are absolute and displayed in UTC.${typeof meta.date_note === "string" ? ` ${meta.date_note}` : " Collection dates are labelled when publication dates are unavailable."}`;
    for (const option of $("method").options) option.disabled = !meta.methods.includes(option.value);
  }

  function currentArticle() {
    return state.history[state.position] || null;
  }

  function canNext() {
    return Boolean(currentArticle()) && !state.loading && state.feedback?.kind !== "error"
      && (state.position < state.history.length - 1 || state.queue.length > 0 || !state.exhausted);
  }

  function announce(message) {
    $("action-status").textContent = message;
  }

  function renderChrome() {
    const ready = Boolean(state.meta);
    const article = currentArticle();
    $("reader-panel").setAttribute("aria-busy", String(state.loading));
    $("method").disabled = !ready;
    $("method").value = state.method;
    $("lens-note").textContent = METHODS[state.method].note;
    for (const id of ["start-onboarding", "skip-onboarding", "edit-interests", "open-reset"]) $(id).disabled = !ready || state.loading;
    $("onboarding-invite").hidden = !ready || state.profile.onboarded;
    $("edit-interests").hidden = !state.profile.onboarded;
    $("topic-list").querySelectorAll("button[data-topic]").forEach((button) => {
      button.disabled = !ready;
      button.setAttribute("aria-pressed", String(button.dataset.topic === state.topic));
    });
    $("profile-summary").textContent = ready
      ? `${state.profile.liked.length} likes · ${state.profile.disliked.length} not interested · local to this snapshot`
      : "Interests are saved in this browser.";
    if (ready) {
      const viewed = Math.min(state.profile.viewed.length, state.meta.articles);
      const percent = state.meta.articles ? (viewed / state.meta.articles * 100) : 0;
      const coverage = percent > 0 && percent < .1 ? "<0.1" : percent.toFixed(1);
      $("corpus-coverage").textContent = `${countFormat.format(viewed)} of ${countFormat.format(state.meta.articles)} articles viewed locally · ${coverage}% of the collection. Offered stories do not count.`;
    }
    $("selection-label").textContent = state.seed ? "Related reading" : state.topic ? "Following a thread"
      : state.profile.liked.length || state.profile.disliked.length ? "Your edition" : "Explore the archive";
    const group = state.meta?.topics.find((topic) => topic.id === state.topic);
    $("selection-note").hidden = !state.seed && !group;
    $("selection-note").textContent = state.seed
      ? state.seedTitle ? `Related to “${state.seedTitle}”` : "Using the article in your link as a content seed."
      : group ? `Content group: ${group.label}` : "";

    const feedback = state.feedback;
    $("feed-feedback").hidden = !feedback;
    $("feed-feedback").classList.toggle("with-story", Boolean(article));
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
    $("story-card").hidden = !article;
    $("story-navigation").hidden = !article;
    $("navigation-hint").hidden = !article;
    $("previous-story").disabled = state.loading || state.position <= 0;
    $("next-story").disabled = !canNext();
    for (const id of ["like-story", "dislike-story", "related-story"]) $(id).disabled = state.loading || !article;
    $("like-story").setAttribute("aria-pressed", String(Boolean(article && state.profile.liked.includes(article.id))));
    $("dislike-story").setAttribute("aria-pressed", String(Boolean(article && state.profile.disliked.includes(article.id))));

    const total = state.history.length + state.queue.length;
    $("position-current").textContent = String(state.position + 1).padStart(2, "0");
    $("position-total").textContent = `${String(total).padStart(2, "0")}${!state.exhausted && total ? "+" : ""}`;
    $("story-progress").max = Math.max(1, total);
    $("story-progress").value = Math.max(0, state.position + 1);
    $("story-progress").setAttribute("aria-valuetext", `Story ${state.position + 1} of ${total} loaded${!state.exhausted ? "; more may be available" : ""}`);
    const atEnd = article && !state.loading && !feedback && state.exhausted
      && !state.queue.length && state.position === state.history.length - 1;
    $("feed-end").hidden = !atEnd;
    $("end-message").textContent = state.endMessage || "No more unseen stories are available in this selection. Try another thread or lens, add interests, or reset local history to revisit the collection.";
  }

  function renderImage(article) {
    const version = ++displayVersion;
    const image = $("story-image").cloneNode(false);
    image.removeAttribute("src");
    image.hidden = true;
    $("story-image").replaceWith(image);
    $("story-cover").classList.remove("has-image");
    $("cover-copy").hidden = false;
    $("story-image-note").textContent = article.image_url ? "Opening stored image" : "Text-first edition";
    if (!article.image_url) return;
    image.addEventListener("load", () => {
      if (version !== displayVersion || currentArticle()?.id !== article.id) return;
      image.hidden = false;
      $("story-cover").classList.add("has-image");
      $("cover-copy").hidden = true;
      $("story-image-note").textContent = "Stored article image";
    }, { once: true });
    image.addEventListener("error", () => {
      if (version !== displayVersion || currentArticle()?.id !== article.id) return;
      image.hidden = true;
      image.removeAttribute("src");
      $("story-cover").classList.remove("has-image");
      $("cover-copy").hidden = false;
      $("story-image-note").textContent = "Text edition · image unavailable";
    }, { once: true });
    image.referrerPolicy = "no-referrer";
    image.src = article.image_url;
  }

  function renderStory(article) {
    $("story-title").textContent = article.title;
    $("story-source").textContent = article.source_name || "Unlisted source";
    const { date, label } = articleDate(article);
    $("story-date").textContent = date ? `${label} ${fullDate.format(date)}` : "Stored date unavailable";
    if (date) $("story-date").dateTime = date.toISOString();
    else $("story-date").removeAttribute("datetime");
    $("cover-index").textContent = String(state.position + 1).padStart(2, "0");
    $("cover-topic").textContent = state.meta.topics.find((topic) => topic.id === article.group)?.label || "An article from the collection";
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
    $("story-card").querySelector(".match-details").open = false;
    $("story-reason").textContent = article.reason || "Selected using article content and the interests you explicitly choose, not a historical user profile.";
    $("story-score").textContent = article.score === null
      ? `${METHODS[state.method].name} content lens. No match score was supplied.`
      : `${METHODS[state.method].name} match score: ${article.score.toFixed(3)}. Scores are lens-specific, not confidence ratings or a measure of reporting quality.`;
    const inputs = { body: "article body", summary: "stored summary", headline: "headline only" };
    $("story-input").textContent = `Model input: ${inputs[article.input_kind]}. Displayed text: ${article.text_kind.toLowerCase()}.`;
    $("read-original").hidden = !article.url;
    $("original-unavailable").hidden = Boolean(article.url);
    if (article.url) $("read-original").href = article.url;
    else $("read-original").removeAttribute("href");
    renderImage(article);
  }

  function showPosition(position) {
    if (position < 0 || position >= state.history.length) return;
    state.position = position;
    state.feedback = null;
    const article = currentArticle();
    state.profile.viewed = [...state.profile.viewed.filter((id) => id !== article.id), article.id].slice(-HISTORY_LIMIT);
    saveProfile();
    renderStory(article);
    renderChrome();
    $("reader-live").textContent = `Archived story ${position + 1}: ${article.title}. ${$("story-date").textContent}.`;
  }

  function showNextQueued() {
    const article = state.queue.shift();
    if (!article) return;
    state.history.push(article);
    if (state.history.length > HISTORY_LIMIT) state.history.shift();
    showPosition(state.history.length - 1);
  }

  function renderServiceNote(response) {
    const notes = [];
    if (Array.isArray(response.unavailable_ids) && response.unavailable_ids.length) notes.push(`${response.unavailable_ids.length} saved or seed article references were not found in this snapshot.`);
    if (Number.isSafeInteger(response.ignored_viewed_ids) && response.ignored_viewed_ids > 0) notes.push(`${response.ignored_viewed_ids} viewed references were ignored by the service; local coverage may differ.`);
    $("service-note").textContent = notes.join(" ");
    $("service-note").hidden = !notes.length;
  }

  async function loadFeed(replace = false) {
    if (!state.meta) return;
    stopFeed();
    const version = feedVersion;
    const controller = new AbortController();
    feedController = controller;
    if (replace) {
      state.history = [];
      state.position = -1;
      state.queue = [];
      state.exhausted = false;
      displayVersion += 1;
    }
    state.loading = true;
    state.endMessage = "";
    state.retryKind = "feed";
    state.retryReplace = replace;
    state.feedback = { kind: "loading", title: "Finding your next story.", message: "Using article content and your explicit choices. Previously viewed articles are excluded from this request." };
    $("service-note").hidden = true;
    renderChrome();
    const body = bodyFor();
    const snapshot = state.meta.snapshot_id;
    try {
      const raw = await requestJSON("/api/v1/recommendations", controller, body);
      if (version !== feedVersion) return;
      const response = normaliseResponse(raw, snapshot, body.method);
      const excluded = new Set([...state.profile.viewed, ...state.profile.disliked, ...state.history.map((item) => item.id)]);
      const items = response.items.filter((item) => !excluded.has(item.id));
      if (!state.seed && !state.topic && !state.profile.liked.length && !state.exploreCache) state.exploreCache = items.slice();
      state.queue = items;
      // A filtered-empty batch pauses for a human choice instead of refetching in a loop.
      state.exhausted = response.exhausted === true || !items.length;
      state.feedback = null;
      renderServiceNote(response);
      if (items.length) {
        showNextQueued();
      } else if (!currentArticle()) {
        state.feedback = { kind: "empty", title: "Room for a different thread.", message: "No unseen articles were returned for this selection. Try another topic or lens, choose interests, or reset your local history to revisit archived stories." };
        $("reader-live").textContent = "No unseen archived stories were returned for this selection.";
      } else {
        state.endMessage = "No unseen stories were returned for this request. Try a different topic or lens, or reset local history to revisit the collection.";
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
    state.history = [];
    state.position = -1;
    state.queue = [];
    state.exploreCache = null;
    state.loading = true;
    state.retryKind = "meta";
    state.feedback = { kind: "loading", title: "Opening the archive.", message: "Loading the snapshot, its dates, and its content groups. No sample stories are used." };
    displayVersion += 1;
    renderChrome();
    try {
      const raw = await requestJSON("/api/v1/recommendations/meta", controller);
      if (version !== metaVersion) return;
      const meta = normaliseMetadata(raw);
      state.meta = meta;
      if (!meta.methods.includes(state.method)) state.method = meta.methods.includes("neural") ? "neural" : meta.methods[0];
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

  function nextStory() {
    if (!canNext()) return;
    if (state.position < state.history.length - 1) showPosition(state.position + 1);
    else if (state.queue.length) showNextQueued();
    else loadFeed();
  }

  function previousStory() {
    if (!state.loading && state.position > 0) showPosition(state.position - 1);
  }

  function changePreference(kind) {
    const article = currentArticle();
    if (!article || state.loading) return;
    const opposite = kind === "liked" ? "disliked" : "liked";
    const hadPreference = state.profile[kind].includes(article.id);
    state.profile[kind] = state.profile[kind].filter((id) => id !== article.id);
    if (!hadPreference) state.profile[kind] = [...state.profile[kind], article.id].slice(-PREFERENCE_LIMIT);
    state.profile[opposite] = state.profile[opposite].filter((id) => id !== article.id);
    state.queue = [];
    state.exhausted = false;
    state.feedback = null;
    saveProfile();
    renderChrome();
    announce(hadPreference ? "Choice removed. Your next new story will use your updated interests."
      : kind === "liked" ? "Interest added. Your next new story will use this choice."
        : "Marked not interested. This article is excluded from new selections; your next new story will use this choice.");
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
    announce("No new interests added. You can choose them later; Next only marks a story viewed.");
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
      const copy = document.createElement("span");
      const { date, label: dateLabel } = articleDate(item);
      const meta = `${item.source_name || "Unlisted source"} · ${date ? `${dateLabel.toLowerCase()} ${shortDate.format(date)}` : "Stored date unavailable"}`;
      copy.append(textElement("span", "taste-title", item.title), textElement("span", "taste-meta", meta));
      label.append(input, copy);
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

  function installGestures() {
    let start = null;
    $("story-card").addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch" || event.isPrimary === false || event.target.closest("a, button, input, summary, details")) {
        start = null;
        return;
      }
      start = { id: event.pointerId, x: event.clientX, y: event.clientY, time: event.timeStamp };
    });
    $("story-card").addEventListener("pointermove", (event) => {
      if (start && event.pointerId === start.id && Math.abs(event.clientY - start.y) > 22) start = null;
    });
    $("story-card").addEventListener("pointercancel", () => { start = null; });
    $("story-card").addEventListener("pointerup", (event) => {
      const swipe = start;
      start = null;
      if (!swipe || swipe.id !== event.pointerId || document.querySelector("dialog[open]") || window.getSelection()?.toString()) return;
      const dx = event.clientX - swipe.x;
      const dy = event.clientY - swipe.y;
      if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.7 || event.timeStamp - swipe.time > 900) return;
      if (dx < 0) nextStory();
      else previousStory();
    });
    document.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
          || event.target.closest?.("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], dialog")
          || document.querySelector("dialog[open]") || window.getSelection()?.toString()) return;
      if (event.key === "ArrowRight" && canNext()) {
        event.preventDefault();
        nextStory();
      } else if (event.key === "ArrowLeft" && !state.loading && state.position > 0) {
        event.preventDefault();
        previousStory();
      }
    });
  }

  function init() {
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
    $("previous-story").addEventListener("click", previousStory);
    $("next-story").addEventListener("click", nextStory);
    $("like-story").addEventListener("click", () => changePreference("liked"));
    $("dislike-story").addEventListener("click", () => changePreference("disliked"));
    $("related-story").addEventListener("click", () => {
      const current = currentArticle();
      if (!current || state.loading) return;
      state.seed = current.id;
      state.seedTitle = current.title;
      state.topic = "";
      state.queue = [];
      state.exhausted = false;
      loadFeed();
    });
    $("read-original").addEventListener("click", () => {
      const current = currentArticle();
      if (!current?.url) return;
      state.profile.viewed = [...state.profile.viewed.filter((id) => id !== current.id), current.id].slice(-HISTORY_LIMIT);
      saveProfile();
      renderChrome();
    });
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
        announce(`${selected.length} interests added. Opening a new selection using your choices.`);
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
