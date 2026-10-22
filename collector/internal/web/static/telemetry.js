// Impression and dwell telemetry. Progressive enhancement: with JavaScript off
// the pages work and only these two signals are lost. Clicks are recorded
// server-side, so they survive regardless.
//
// An impression — a card shown and not clicked — is the only source of negative
// examples a ranker will ever have, which is why this exists at all.
(() => {
  "use strict";

  const ENDPOINT = "/read-events";
  const MIN_DWELL_MS = 1000;
  const MAX_DWELL_MS = 3600000;

  const queue = [];
  const impressed = new Set();
  const visibleSince = new Map();
  const cards = new Map();

  const enqueue = (id, kind, dwellMs) => {
    const el = cards.get(id);
    if (!el) return;
    queue.push({
      article_id: id,
      kind: kind,
      position: Number(el.dataset.position),
      dwell_ms: dwellMs,
      at: Date.now(),
    });
  };

  // Age, not a timestamp: the server dates the event from its own clock, so a
  // wrong clock here cannot poison the training data.
  const flush = () => {
    if (queue.length === 0) return;
    const now = Date.now();
    const events = queue.splice(0, queue.length).map((e) => ({
      article_id: e.article_id,
      kind: e.kind,
      position: e.position,
      dwell_ms: e.dwell_ms,
      age_ms: Math.max(0, now - e.at),
    }));
    const body = JSON.stringify({ events: events });
    const blob = new Blob([body], { type: "application/json" });
    if (!navigator.sendBeacon || !navigator.sendBeacon(ENDPOINT, blob)) {
      fetch(ENDPOINT, {
        method: "POST",
        body: body,
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    }
  };

  const closeVisible = () => {
    const now = Date.now();
    for (const [id, since] of visibleSince) {
      const ms = Math.min(now - since, MAX_DWELL_MS);
      if (ms >= MIN_DWELL_MS) enqueue(id, "dwell", ms);
    }
    visibleSince.clear();
  };

  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const id = entry.target.dataset.articleId;
      if (entry.isIntersecting) {
        if (!impressed.has(id)) {
          impressed.add(id);
          enqueue(id, "impression", 0);
        }
        visibleSince.set(id, Date.now());
      } else if (visibleSince.has(id)) {
        const ms = Math.min(Date.now() - visibleSince.get(id), MAX_DWELL_MS);
        visibleSince.delete(id);
        if (ms >= MIN_DWELL_MS) enqueue(id, "dwell", ms);
      }
    }
  }, { threshold: 0.5 });

  for (const el of document.querySelectorAll("[data-article-id]")) {
    cards.set(el.dataset.articleId, el);
    observer.observe(el);
  }

  // pagehide rather than unload: unload is unreliable on mobile, where a page
  // is more often backgrounded than closed.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      closeVisible();
      flush();
    }
  });
  window.addEventListener("pagehide", () => {
    closeVisible();
    flush();
  });
})();
