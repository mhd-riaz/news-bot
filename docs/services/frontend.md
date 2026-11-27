# Reader app (frontend)

The folder [`frontend/`](../../frontend/README.md) holds **AFTERLINE**, the web page
where people read stories. It is a React app written in TypeScript and built with
Vite. Biome checks its style. The web server in `server/` sends the finished page to
the browser and answers its requests.

This page is a short summary. The full guide is
[`frontend/README.md`](../../frontend/README.md). Hard words are explained in the
[glossary](../glossary.md).

## What a reader can do

- See a grid of stories with a big lead story. "More stories" adds more.
- Open a story in a full-screen reading view, with six related stories and "See all
  related stories".
- Switch between **Fresh** (verified date, up to 30 days old), **Yesterday** (up to
  10 stories from yesterday, India time) and **Archive** (everything else).
- Turn on **Professional focus** to keep only sources tagged `ai`, `data-science`,
  `software` or `technology`.
- Choose interests, press **More like this** or **Not interested**, or **Reset**.
- Switch between the three ranking methods (TF-IDF, SVD and Neural).
- Save stories with a note of up to 2,000 characters.
- Switch between light and dark. It starts from the computer's setting.
- Use the keyboard (← and → move, Esc goes back) or swipe on a phone.
- Sign in with Google, when the server asks for it.

## What stays in the browser

There are no accounts on the server for these yet. They live in the browser's local
storage, with the same names the old Go reader used:

| Key | What it holds |
| --- | --- |
| `afterline:profile:<snapshot>` | Up to 50 likes, 50 "not interested" choices and the last 2,000 opened stories. One per snapshot |
| `afterline:saved` | Up to 200 saved stories with notes. Kept across snapshots |
| `afterline:settings` | Professional focus, and the light/dark choice |

Clearing the browser's storage loses them. They do not move to another browser or
device.

## What it sends

The app sends only what the reader chose: likes, "not interested" choices, the view,
the method, Professional focus, and the story asked about. It also lists the stories
already opened in this browser, so the server can leave them out. It sends no
reading reports: nothing about what was on screen, what was clicked or for how long
(roadmap requirement R6).

It talks only to its own website: `GET /api/v1/session`,
`GET /auth/login`, `POST /auth/logout`,
`GET /api/v1/recommendations/meta` and `POST /api/v1/recommendations`.

## Safety

- Text from publishers is always shown as text. The code never uses
  `dangerouslySetInnerHTML`, and a test checks this.
- Story links must be `http` or `https`, and pictures must be `https`.
- The page has no inline scripts or styles, so it works under the server's strict
  Content Security Policy.

## Work on it

You need Node.js 22 (22.22.2 or later), 24 (24.15.0 or later) or 26 and newer, with
npm. From `frontend/`:

```bash
npm ci             # install the exact versions in package-lock.json
npm run dev:mock   # made-up stories, no server needed: http://localhost:5173
npm run dev        # talks to the real server on 127.0.0.1:8090
npm run ci         # Biome, type check, tests and build: run before you finish
```

`npm run build` writes the finished page to `frontend/dist/`. The web server serves it
from there.

## Not done yet

- A browser check against the real Python server (roadmap RS5).
- JavaScript test coverage for M9.1 is **not met**. Measuring it needs one more
  dependency.
- Likes, settings and saved stories on the server, so they follow a signed-in reader
  (roadmap M3).
