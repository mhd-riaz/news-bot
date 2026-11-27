---
name: add-news-source
description: Add a new RSS or Atom news feed for the collector to read. Use when someone asks to add, change or remove a news source or feed.
---

# Add a news source

All feeds live in `collector/configs/sources.yaml`. The collector applies this file every time it starts. It matches entries on `feed_url`, so changing an entry updates the stored source instead of making a copy.

## 1. Check the feed first

- It is RSS or Atom and opens without a login.
- The articles are in English (this app is English only).
- The publisher's `robots.txt` allows reading the feed. The collector obeys `robots.txt` and its own rate limits anyway.
- The publisher's terms allow showing a short summary and a link (roadmap D6, still an open owner decision).

## 2. Add the entry

Required keys: `name`, `feed_url`, `type` (`rss` or `atom`), `language` (two letters, e.g. `en`) and `country` (two letters, e.g. `IN`).
Optional keys: `state`, `city`, `enabled`, `priority` (0–100), `fetch_interval_seconds` (60–604800) and `domains`. `domains` takes only `technology`, `software`, `ai` and `data-science`.

```yaml
  - name: Example News — Technology
    feed_url: https://example.com/technology/rss.xml
    type: rss
    language: en
    country: IN
    priority: 60
    domains: [technology]
```

## 3. Check it

```sh
make -C collector seed-check                        # validates the file without writing to any database
cd collector && go test ./internal/bootstrap/        # TestShippedSourcesFileIsValid checks every entry
```

## 4. Use it

- On this computer: restart the collector (`./run.sh stop` then `./run.sh`). It applies the file on start.
- In production: the file is built into the collector image, so the new feed arrives with the next release from `main`.
- Never test collection against the production database.
