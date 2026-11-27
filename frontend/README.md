# AFTERLINE reader (frontend)

This folder holds the **AFTERLINE reader**: the web page where you read stories. It is a
React app. It replaces the Stories page that the Go reader (`collector/cmd/reader`) served
before. The Python server in [`../server`](../server) gives it stories and serves the
finished page.

Everything a reader could do before still works:

- a grid of stories on the front page, with a big lead story;
- a full-screen reading view, with related stories and "See all related stories";
- **Fresh**, **Yesterday** and **Archive** views;
- **Professional focus** (only sources tagged with work topics such as `ai` or `software`);
- choosing interests, **More like this**, **Not interested**, and **Reset**;
- three lenses (TF–IDF, SVD and Neural); the server chooses which one starts;
- saved stories with your own notes;
- a light/dark switch that starts from your computer's setting;
- keyboard use: ← and → move between stories, Esc goes back;
- swiping left and right on a phone.

New in this version: a **sign-in screen** (Google) when the server asks for one.

## What you need

- Node.js version 22 (22.22.2 or later), 24 (24.15.0 or later), or 26 or newer. This was
  built with Node 26.13.1.
- npm (it comes with Node). This was built with npm 12.2.3.

## Get started

Run these commands inside this `frontend` folder.

```sh
npm ci            # install the exact versions listed in package-lock.json
npm run dev:mock  # start the app with made-up stories, no server needed
```

Then open <http://localhost:5173>. With `npm ci`, npm 12 prints a warning that it blocked
an install script for `fsevents`. You can ignore it: `fsevents` is an optional file watcher
for macOS and its ready-made copy still works.

### With the real server

Start the Python server first (see [`../server/README.md`](../server/README.md)). It must
listen on `http://127.0.0.1:8090`. Then run:

```sh
npm run dev
```

The page is at <http://localhost:5173>. Vite (the development server) passes every request
for `/api`, `/auth` and `/health` on to `127.0.0.1:8090`, so the browser
sees one website. After Google sign-in, Google sends you back to the address that is set
on the server, which may be the server's own address rather than port 5173.

### The made-up server (mock)

`npm run dev:mock` answers every request with **invented** stories from
[`mock/api.ts`](mock/api.ts). No real article text is used. It is only for trying the app
and is never part of the finished page.

You can change what the mock does while it runs by opening these addresses:

| Address                | What it does                                             |
| ---------------------- | -------------------------------------------------------- |
| `/__mock?auth=on`      | Sign-in is required. You start signed out.               |
| `/__mock?auth=off`     | No sign-in (the starting setting).                       |
| `/__mock?invite=deny`  | Google sign-in comes back with "not on the invite list". |
| `/__mock?invite=fail`  | Google sign-in comes back with "sign-in failed".         |
| `/__mock?invite=allow` | Google sign-in works and signs you in as "Mock Reader".  |

Start with sign-in already on by running `MOCK_AUTH=1 npm run dev:mock`.

## Commands

| Command                | What it does                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| `npm run dev`          | Development server on port 5173, talking to the real server.                                                  |
| `npm run dev:mock`     | Development server with made-up stories.                                                                      |
| `npm run check`        | Biome checks formatting, lint rules and import order. Any warning fails.                                      |
| `npm run lint`         | Only the Biome lint rules.                                                                                    |
| `npm run format`       | Biome rewrites files into the standard format.                                                                |
| `npm run typecheck`    | TypeScript checks the types (app, tests, Vite config and mock).                                               |
| `npm test`             | Runs the tests once (Vitest and Testing Library, in jsdom).                                                   |
| `npm run build`        | Builds the finished page into `dist/`.                                                                        |
| `npm run preview`      | Serves `dist/` on port 4173 with the security policy (CSP) `default-src 'self'; img-src 'self' https: data:`. |
| `npm run preview:mock` | The same, with made-up stories.                                                                               |
| `npm run ci`           | Everything a check-in needs: `biome ci`, types, tests and the build.                                          |

The Python server serves `dist/index.html` at `/` and `/stories`, and the files in
`dist/assets/`.

## How the page talks to the server

All requests go to the same website, with `credentials: "same-origin"`. The browser's own
`Origin` and `Sec-Fetch-Site` headers protect against forged requests, so the page sends
no extra token. Errors come back as `{"error": {"code": "...", "message": "..."}}`.

| Request                            | Used for                                                                               |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| `GET /api/v1/session`              | First thing on start: is sign-in on, and is someone signed in?                         |
| `GET /auth/login?next=<this page>` | The "Sign in with Google" link.                                                        |
| `POST /auth/logout`                | The "Sign out" button (the server answers 204).                                        |
| `GET /api/v1/recommendations/meta` | The snapshot, its dates, lenses, threads and topic tags.                               |
| `POST /api/v1/recommendations`     | Every list of stories: the feed, related stories, the edition and the interest picker. |

If sign-in is on and nobody is signed in, the page shows only the sign-in screen. If the
address has `?auth_error=not_invited`, it says the email is not on the invite list. If it
has `?auth_error=sign_in_failed` (or any other error), it says sign-in failed and offers to
try again. If any request answers 401 with the code `sign_in_required`, the page goes back
to the sign-in screen.

## What stays in your browser

The page keeps these in the browser's local storage, with the **same names and formats**
as the Go reader, so nothing is lost when you switch:

| Key                            | What it holds                                                                                                                          |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `afterline:profile:<snapshot>` | Likes (up to 50), not-interested choices (up to 50), the last 2,000 opened stories, and whether you chose interests. One per snapshot. |
| `afterline:saved`              | Up to 200 saved stories, each with a note of up to 2,000 characters. Kept across snapshots.                                            |
| `afterline:settings`           | Professional focus on or off, and your light/dark choice.                                                                              |

## No reading data is sent

The page sends **no reading data**. It never tells the server which stories appeared on
your screen, which ones you clicked, or how long you read. There are no reading reports
and no requests to `/read-events`. This follows requirement R6 in the
[roadmap](../docs/project/roadmap.md): only explicit choices, and no implicit signals
(signals guessed from what you do).

Each `POST /api/v1/recommendations` request carries only what you chose yourself:

- the stories you liked, and the ones you marked not interested;
- the view (Fresh, Yesterday or Archive), the thread, the lens and professional focus;
- for related reading, the story you asked about.

As in the Go reader, each request also lists the stories you have opened in this browser
(up to the last 2,000), so the server can leave them out of the new list.

## Safety rules

- Text from publishers (titles, summaries, sources, notes) is always shown as text. The
  code never uses `dangerouslySetInnerHTML`; a test checks this.
- Links to articles must be `http` or `https`, and pictures must be `https`. Links open in
  a new tab without sending where you came from.
- The finished page has no inline scripts or styles, so it works under the server's
  strict Content Security Policy (CSP). Colours made per publisher are set with React's
  `style` prop, which the CSP allows.

## Folder map

| Path                      | What it is                                                                  |
| ------------------------- | --------------------------------------------------------------------------- |
| `index.html`              | The page shell. React fills in `<div id="root">`.                           |
| `src/main.tsx`            | Starts React.                                                               |
| `src/App.tsx`             | Asks the server about sign-in, then shows the sign-in screen or the reader. |
| `src/api.ts`              | Requests to the server, the session and signing out.                        |
| `src/reader/store.ts`     | The reader's state and actions, ported from the Go reader's `stories.js`.   |
| `src/reader/normalise.ts` | Checks every answer from the server and from browser storage.               |
| `src/components/`         | The screens: the feed, story tiles, the reading view, dialogs, sign-in.     |
| `src/styles.css`          | The look, ported from the Go reader's `stories.css`.                        |
| `mock/api.ts`             | The made-up server for `dev:mock`.                                          |
| `test/`                   | Tests. Many are ported from `collector/internal/web/stories.test.mjs`.      |

## Packages and why each one is here

Two packages run in the browser; the rest are only for building and checking.

| Package                       | Version | Why                                                                         |
| ----------------------------- | ------- | --------------------------------------------------------------------------- |
| `react`                       | 19.3.1  | Builds the page from components.                                            |
| `react-dom`                   | 19.3.1  | Puts React's components into the web page.                                  |
| `vite`                        | 8.4.0   | Development server and the production build; it also compiles TSX.          |
| `typescript`                  | 7.0.2   | Checks types (`npm run typecheck`).                                         |
| `@biomejs/biome`              | 2.6.9   | Formats and lints the code, the CSS and the HTML (the owner's chosen tool). |
| `vitest`                      | 5.1.2   | Runs the tests with Vite's settings.                                        |
| `jsdom`                       | 31.0.1  | A browser-like page for the tests.                                          |
| `@testing-library/react`      | 16.3.3  | Renders components in tests and finds things the way a reader would.        |
| `@testing-library/dom`        | 10.4.2  | Required by `@testing-library/react`.                                       |
| `@testing-library/user-event` | 14.6.13 | Clicks and types in tests like a real person.                               |
| `@types/react`                | 19.3.3  | Types for React.                                                            |
| `@types/react-dom`            | 19.3.0  | Types for React DOM.                                                        |
| `@types/node`                 | 26.6.11 | Types for the Vite config and the mock server, which run in Node.           |

There is no UI kit, CSS framework or state library. There is also no
`@vitejs/plugin-react`: Vite 8 compiles JSX by itself. The only cost is that the page
reloads fully after an edit during development.
