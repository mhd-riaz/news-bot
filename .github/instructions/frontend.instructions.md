---
applyTo: "frontend/**"
---

# Frontend (React)

- React and TypeScript, built with Vite. Biome is the only linter and formatter: `npm run check` must show zero errors and zero warnings. Do not add ESLint or Prettier.
- Run `npm run ci` before you finish. It runs Biome, the type check, the Vitest tests and the build.
- Render third-party text (titles, summaries, publisher names) as text. Never use `dangerouslySetInnerHTML` (hard rule 7). The server sends a strict security policy, so no inline scripts and no `<style>` tags.
- The app sends only the reader's explicit choices: likes, dislikes, chosen topics and sources. No reading reports, timers or other hidden signals (requirement R6).
- Keep the browser-storage keys and value formats stable, so readers keep their saved stories, notes and settings.
- The server owns the API: `/api/v1/session`, `/api/v1/recommendations`, `/api/v1/recommendations/meta`, `/auth/google/login` and `/auth/logout`. Use same-origin `fetch`; there is no CSRF token to send.
- Keep dependencies few. Each new one needs a one-line reason in roadmap §8 (hard rule 9).
