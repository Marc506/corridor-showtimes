# Corridor Showtimes

**Every repertory screening from New York to Philadelphia, on one timeline.**

**Live site → https://marc506.github.io/corridor-showtimes/** · [中文说明](README.zh-CN.md)

Corridor Showtimes aggregates the calendars of nine art-house and repertory cinemas along the
Northeast Corridor: Metrograph, Film Forum, Film at Lincoln Center, Anthology Film Archives, BAM,
MoMA, Japan Society, L'Alliance New York, and the Philadelphia Film Society. It refreshes twice a
day and shows the day as a timeline, so you can answer *"what can I see tonight, and when?"* at a
glance. It was built as a faster, customizable alternative to existing listings sites, which
often lag behind the cinemas' own schedules.

![Timeline view](docs/timeline.png)

| | |
|---|---|
| ![Mobile list view, filtered to subtitled films](docs/mobile-list.png) | **Views.** Timeline (a lane per screen, block width = runtime), list, and week grid.<br><br>**Filters.** Cinemas, *on film* (16/35/70mm), *non-English / subtitled*, *hide started*, and title/director search. All state lives in the URL, so every view is shareable.<br><br>**Mobile.** On narrow screens the timeline flips vertical. The page is also an installable home-screen app.<br><br>**Honest data.** Each cinema shows whether its data is fresh, stale (last good copy kept), or came from the fallback source. |

## How it works

```
 launchd (01:00, 13:00 ET)
        │
        ▼
 scraper.run ── per venue: fetch → parse → validate ──┐   failure? keep last good data,
        │          (JSON API / HTML / browser / feed)  │   or fall back to screenslate
        │                                              ▼
        │                               language enrichment (site text → TMDB → default)
        ▼
   SQLite ──► export ──► site/data.js ──► publish.sh ──► gh-pages ──► GitHub Pages
```

* **Python 3.12 scrapers**, one file per cinema behind a small registry. Every source separates
  `fetch()` (network) from `parse()` (pure), so all parsers are tested offline against real captured pages.
* **SQLite** keeps history. A successful scrape replaces only that venue's future rows; a failed one
  leaves them alone and marks the venue *stale*.
* **Static frontend**: vanilla JS, no framework or build step. It reads a generated `data.js`, so
  it works from `file://` as well as GitHub Pages.
* **Publishing**: after each run, the page and fresh data are force-pushed to `gh-pages` as a single
  orphan commit, so twice-daily updates never grow the repository.

## Sources, and the problems each one posed

| Cinema | Source | Notes |
|---|---|---|
| BAM | Undocumented calendar JSON API | Director, runtime, and language enriched from film pages (cached 7 days) |
| Film at Lincoln Center | The API behind their site | The website is behind Cloudflare; the API isn't. NYFF / Met Opera series inferred from presale metadata |
| Japan Society | WordPress custom endpoint | Series containers vs. single screenings |
| Anthology Film Archives | Server-rendered HTML, month by month | One listing can hold several showtimes; loosely formatted metadata lines |
| Film Forum | Server-rendered HTML, 7 day tabs | **Times have no am/pm**, so they are inferred by house rules; month roll-over inferred from fetch date |
| Metrograph | One HTML page, ~4 weeks | **Rate-limits by IP**: exactly one request per run, stop on 429/403, cooldown before retrying |
| L'Alliance New York | Event cards + detail pages | Cards carry no times; per-film notes are scoped to the date they mention |
| MoMA | Headless browser (Playwright) | Cloudflare managed challenge. When it doesn't pass, the fallback source is used; the site's protection is never circumvented |
| Philadelphia Film Society | **Agile Ticketing public event feed** | The website blocks all automated clients; their ticketing provider publishes an official JSON feed covering all three theaters |

**Fallback.** [screenslate](https://www.screenslate.com)'s open JSON:API covers the NYC venues and
is used automatically when a primary source fails. A per-venue cooldown avoids hammering a site
that just blocked us. Its WAF rejects Python's TLS handshake, so that one source goes through the
system `curl`.

**Subtitled-film filter.** Language comes from the cinema's own text when it has any ("In Wolof
with English subtitles", "silent"), otherwise from [TMDB](https://www.themoviedb.org/), then
from a per-venue default. Matching favors *unknown* over *wrong*:
* check year and director when known;
* borrow a missing year from another venue that lists the same title;
* for undated festival titles, prefer this year's premiere, or accept any answer when every
  candidate shares one language;
* never look up talks, shorts programs, or double bills;
* route opera broadcasts to "subtitled" instead of a same-name movie.

## Run it yourself

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium        # only needed for MoMA's browser path
echo "<TMDB API Read Access Token>" > config/tmdb_token.txt   # optional: language data
.venv/bin/python -m scraper.run                        # scrape all cinemas and export site/data.js
open site/index.html
```

```bash
.venv/bin/python -m scraper.run --venue metrograph --dry-run   # print parsed screenings only
.venv/bin/python -m scraper.run --venue moma --source screenslate
.venv/bin/pytest -q                                           # offline tests on captured pages
```

Scheduling (macOS `launchd`), adding a cinema (one YAML entry plus one parser file), and
troubleshooting are covered in [README.zh-CN.md](README.zh-CN.md). Design notes are in
[ARCHITECTURE.md](ARCHITECTURE.md), and per-site reverse-engineering notes in [SOURCES.md](SOURCES.md).

## Notes

Showtimes belong to the cinemas; every screening links back to the cinema's own page and ticketing.
Scrapers make one to a few requests per cinema twice a day, and respect rate limits and blocks.
This product uses the TMDB API but is not endorsed or certified by TMDB.
