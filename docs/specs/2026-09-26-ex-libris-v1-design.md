# Ex Libris v1: design

*A friendly catalogue for the books you own.* Scan a barcode with your phone and the book is on the shelf.

## Intent

**What the owner asked for**
- A packaged, open-source release of a home book catalogue that anyone can run as one simple Docker container.
- It should look nice.
- Books are added by scanning barcodes in a phone's web browser.
- No details of the author's own setup appear anywhere.
- Hosting and security are the user's job. The README recommends Cloudflare Access (or a VPN) for the editing side and explains the public read-only side.
- Genres come from optional AI, off by default.
- Published under the owner's personal GitHub account as `ex-libris`.
- Screenshots may show the owner's books.

**Assumed**
- Users are self-hosters: a home server, NAS, Raspberry Pi or small VPS.
- One household per instance.
- English UI.
- MIT licence.

**Success**
- `docker compose up` gives a working library within a minute, with no configuration needed.
- A phone on an https address scans a book in one go.
- The public view can't change anything or show private fields.
- The app idles under 150 MB of memory on amd64 and arm64.
- The repo contains nothing identifying the owner, and a check enforces this.

## 1. What it is

**One container, one data folder (`/data`), two ports:**

| Port | App | Who it's for |
|---|---|---|
| **8080** | **Library:** everything (browse, add, scan, edit, stats, export, backups) | The household. Put it behind Cloudflare Access, a VPN or the home network; the README says so plainly. |
| **8081** | **Public view:** read-only browse, search, book pages, author pages, stats | Anyone the user shares it with |

- **No built-in login.** The app never pretends to secure 8080: the first-run page and the README both say it must not be exposed unprotected.
- **The public view is a separate ASGI app** (its own FastAPI instance) on its own port. It has **no write routes registered at all**, so nothing it serves can change data, rather than relying on a check.

**Settings** are environment variables, all optional:
- `EXLIBRIS_TITLE`: the library's name, shown in the header (default "Our books")
- `EXLIBRIS_PUBLIC`: `on` or `off` for the 8081 app (default `on`)
- `EXLIBRIS_OPENLIBRARY_CONTACT`: an email for Open Library's faster rate tier
- `EXLIBRIS_AI_URL`, `EXLIBRIS_AI_MODEL`, `EXLIBRIS_AI_KEY`: any OpenAI-compatible endpoint; unset means no AI
- `EXLIBRIS_GOOGLE_BOOKS`: `on` or `off` for the cover fallback (default `on`)
- `TZ`

## 2. Features (v1)

**Adding books**
- **Phone scanner** (`/scan`):
  - Camera barcode reading: native BarcodeDetector where available, a ZXing fallback (vendored, not from a CDN; see section 6).
  - ISBN-13 and hand-typed ISBN-10.
  - **Add** mode, with *Add automatically* for working through a pile.
  - **"Do I own this?"** mode: *yes, this edition* / *a different edition* / *no*. An exact match needs no network.
  - A room picker remembered per device.
- **Search and add:** by title, author or ISBN via Open Library.
- **Editions:** one row per copy. ISBN is unique; several editions of the same work are allowed. The edition's own details (format, publisher, year, pages, cover, series) come from Open Library.
- **CSV import** (`title, authors, isbn, …`) with a preview before anything is written. CSV export at any time.

**Looking after them**
- **Edit panel:**
  - title, authors, year, pages, ISBN, format, publisher, genre, series and number, room, lent to/since, notes;
  - **Refresh from Open Library** (fills blanks only);
  - **change cover:** a photo or a picked image, resized with Pillow;
  - remove.
- **Covers found automatically** for books without one: Google Books by ISBN, the Open Library work, Google Books by title, Open Library search. Placeholders are refused, each book is tried once, and images are stored locally.
- **Genres:** hand-set, from a fixed list of 15 plus custom. With AI configured, a background task fills empty genres from Open Library subjects and never overwrites a hand-set genre.
- **Series:** parsed from editions (publisher imprints skipped), with gaps shown.
- **Lending:** who has a book and since when; loans older than 60 days are flagged at the top of the library.

**Browsing** (both apps)
- The **cover grid** is the default view, with a list view too.
- **Group by** author, genre, series (with gaps), decade, format; plus room on 8080.
- **Filter chips.**
- **Search:** SQLite FTS5. The public view searches only public columns.
- **Author pages;** on 8080 these add "More by this author" from Open Library.
- **Stats:**
  - orange highlight cards (pages, reading time, shelf length, most collected, top genre, favourite decade, oldest, longest, nearly-complete series, one-book authors);
  - charts (genres, top authors, decades, formats; books added per month on 8080 only);
  - with AI, a weekly "fun facts" card on 8080 only.

**Looks**
- A dark theme (deep navy, International Orange highlights), plus a matching **light theme** that follows the device setting.
- Built for phone first, and wide screens use the space (centred, columns).
- No sidebar: a slim top bar with **Books · Stats · Scan · Do I own this?**.

**Data safety**
- **Nightly backups to `/data/backups/`:**
  - a dated SQLite copy (backup API, integrity-checked, rollback journal) plus a CSV;
  - 30 days kept, and the newest is never deleted.
- **A "Download backup" button** gives a zip of the database, CSV and covers.

**Out of scope for v1:** reading status and ratings, user accounts, email or notifications, multiple libraries, other languages, a mobile app.

## 3. Public view guarantees (8081)

- **Routes:** `/`, `/book/{id}`, `/author`, `/stats`, `/api/books`, `/cover/{id}`, `/healthz`. GET and HEAD only.
- **Fields:** only public fields are sent, via a single serialiser: title, authors, year, format, publisher, ISBN, cover, genre, series, pages. Notes, room, loans and dates are never sent.
- **Covers:** only those referenced by a book, and never fetched on a visitor's behalf.
- **Links:** nothing links to 8080.
- **Headers:** `noindex`, a strict CSP (scripts from self only), `frame-ancestors 'none'`, and short (60 s) caching, since the data is public.
- **Tests:**
  - enumerate every route of the public app and assert that none mutates;
  - POST, PUT, PATCH and DELETE on every path are refused;
  - no private field appears in any response.

## 4. Architecture

```
exlibris/
  core/            no web code; unit-tested
    db.py            schema, migrations (versioned, run once at start), FTS
    books.py         add/update/delete, editions, validation, CSV import/export
    openlibrary.py   search, edition, work, author lookups; pacing + cache
    covers.py        cover finding (Google Books + Open Library), Pillow resize/checks
    series.py        series parsing + gaps
    stats.py         stats + highlight cards (public/private variants)
    ai.py            optional genre + fun-facts via OpenAI-compatible API
    backup.py        nightly snapshot + CSV + prune; zip download
    tasks.py         in-process scheduler (covers, genres, backups) — no cron needed
  web/
    library.py       FastAPI app on :8080 (all routes)
    public.py        FastAPI app on :8081 (read-only routes only)
    templates/       Jinja; shared partials for browse + stats
    static/          CSS, JS (browse, scanner, edit panel), vendored ZXing + ECharts
  __main__.py      starts both apps (uvicorn, one process, two servers) + tasks
tests/
Dockerfile, compose.yaml, README.md, LICENSE, CHANGELOG.md, docs/
```

- **Runtime:** Python 3.12-slim. Dependencies: fastapi, uvicorn, jinja2, httpx, pillow, python-multipart. No database server.
- **Image:** a multi-arch build (linux/amd64, linux/arm64) via GitHub Actions to `ghcr.io/christopherjohndillon/ex-libris`, tagged `vX.Y.Z` and `latest`. It runs as a non-root user and has a `HEALTHCHECK` on `/healthz`.
- **Data (`/data`):**
  - `library.db`
  - `covers/`
  - `cache/`: Open Library editions, works and authors
  - `backups/`
- **Open Library:**
  - an identified User-Agent (`ex-libris/<version> (+repo URL)`, plus the contact if set);
  - paced at 1 request/s, or 3/s with a contact;
  - editions and works cached indefinitely, authors for 7 days;
  - an attribution link on every page.
- **Vendored front-end libraries** (ZXing, ECharts), so it works offline on a LAN and the CSP can stay `script-src 'self'`. Fonts are bundled (Source Sans 3, SIL OFL).

## 5. Security notes (README + first-run page)

- **8080 has no login by design.** Recommended: Cloudflare Tunnel + Access (free, gives https so the camera works); alternatively Tailscale or a VPN; at the very least, home network only.
- **8081 is safe to share:** read-only, with public fields only.
- **Writes on 8080:** JSON or an `HX-Request` header plus a same-origin check, so a hostile website can't forge changes from the user's browser.
- **Stored text is escaped everywhere.** Chart labels go through `encodeHTML` too, since Open Library data is editable by anyone.
- **Camera:** it needs https or localhost. The README explains the options.

## 6. Privacy of the release (hard rule)

- **Written fresh:** nothing is copied from the author's private repository history, which is never pushed.
- **A `scripts/check_clean.py` check runs in CI and as a pre-commit step.** It fails on:
  - the owner's names, emails, domains and hostnames, personal paths, or household terms (a denylist kept **outside the repo**, passed to CI as a secret);
  - plus generic patterns: email addresses other than the project's no-reply, and IPs.
- **Commit author:** "Ex Libris contributors" with a no-reply email.
- **Samples and screenshots:**
  - the sample dataset uses public-domain classics;
  - screenshots may use the owner's catalogue, showing only book pages and covers (no rooms, notes or loans);
  - the owner reviews them before publishing.

## 7. Testing

- **pytest:** unit tests for `core/`, route tests for both apps, and the public-view guarantees from section 3.
- **Container smoke test in CI:** start the image, add a book through the API with Open Library mocked, check 8081 shows it, and check a write on 8081 is refused.
- **Screenshot check:** headless browser screenshots of the main pages at phone and desktop widths, reviewed by eye before release.

## 8. Release

1. Build and test locally.
2. Create the GitHub repo as **private**.
3. Push, and let CI go green.
4. The owner reviews the README and screenshots.
5. Make the repo public and tag `v1.0.0`; the image is published.

## Decisions

- **No built-in auth:** an unprotected 8080 is the user's call, and the docs are explicit about it.
- **Two ports** rather than host routing: simplest to explain and hardest to misconfigure.
- **Front-end libraries vendored**, not from a CDN.
- **AI off by default.**
- **Reading status excluded.**
