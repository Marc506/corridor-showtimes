# Instructions for AI assistants working in this folder

This folder is **Corridor Showtimes**: a program that collects showtimes from cinema websites and shows
them on one web page (`site/index.html`). Most people who open it in an AI assistant are **not
programmers**. They downloaded it from GitHub because they want to see *their* cinemas, and were told to
send you: *"Please read AGENTS.md in this folder and help me add a cinema."*

Part 1 is the conversation to have with them. Part 2 is reference for the code.

---

## Part 1 — Helping someone add a cinema

### How to talk

- Reply in the language the person writes in (Chinese or English, usually).
- Plain words, short messages. No stack traces, no jargon; if you must mention a file, say what it is.
- Before running a command for the first time, say in one sentence what it does. Commands are safe to
  run; nothing here needs an account, a password or payment.
- Never ask them to edit code. You do all of it.

### Step 1 — Ask for the cinema

Send one message asking for:

1. the cinema's **name**;
2. the **web page that lists its showtimes** (the "Calendar" / "Showtimes" / "Now playing" page, not
   just the home page — if they only have the home page, that's fine, try it);
3. the **city** it is in (used for the time zone).

If they want several cinemas, do them one at a time.

### Step 2 — Set up (first time only, a few minutes)

The program needs Python 3.12 or newer and a few packages, installed into a private `.venv` folder
inside this project (nothing system-wide changes except the Python installer, if needed).

1. Check for Python: `python3 --version` (Windows: `py --version`).
2. If it's missing or older than 3.12, the easiest route is **uv**, which downloads the right Python by
   itself. Ask first ("I need to install a small tool called uv that sets up Python — OK?"), then:
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
3. Create the environment and install:
   - with uv: `uv venv --python 3.12 .venv` then `uv pip install --python .venv -e ".[dev]"`
   - with Python 3.12+: `python3 -m venv .venv` then `.venv/bin/pip install -e ".[dev]"`
4. From now on use the project's Python: `.venv/bin/python` (Windows: `.venv\Scripts\python`).
   Check the install with `.venv/bin/python -m pytest -q` — every test should pass.

You do **not** need to install a browser (Playwright / Chromium). The few sites that need one fall back
to another source automatically.

### Step 3 — Run the setup wizard

Turn the city into an IANA time zone yourself (New York → `America/New_York`, Chicago →
`America/Chicago`, Denver → `America/Denver`, Phoenix → `America/Phoenix`, Los Angeles / San Francisco /
Seattle / Portland → `America/Los_Angeles`, …) and run, in the person's language (`zh` or `en`):

```
.venv/bin/python -m scraper.add "<cinema name>" "<showtimes URL>" --tz <time zone> --lang <zh|en>
```

It takes about half a minute (it waits 2 seconds between requests to be polite to the site). Its last
lines say which of four things happened:

| The wizard says | What it means | What you do |
|---|---|---|
| **Done / 成功** … read through '<adapter>' | The site runs on a ticketing system the program knows. The cinema is added and scraped once. | Go to Step 4. |
| **needs a recipe / 需要写配方** (and `handoff/<id>/BRIEF.md` was written) | The page shows showtimes but in the cinema's own format. | Tell them: "This cinema's website has its own layout, so I need to write a small reading rule for it. This takes a few minutes." Then follow `handoff/<id>/BRIEF.md` exactly — it is the full specification. Write `scraper/recipes/<id>.yaml` first; only if the recipe format cannot express the page, write `scraper/sources/<id>.py`. Run every acceptance command in the brief; when they pass, delete `handoff/<id>/` and go to Step 4. |
| **blocks automated access / 挡住了程序访问** | A firewall (Cloudflare, Sucuri …) refuses programs. | Explain that this cinema can't be read automatically and that this project never works around such protection. For New York and San Francisco cinemas, offer the screenslate fallback (see "Blocked cinemas" below). Do not try other tricks. |
| **No showtimes found / 没有找到任何场次时间** | That page has no showtimes (often the home page). | Ask for the page that lists showtimes, or look at the site's own links for "Calendar" / "Showtimes" and suggest one, then run the wizard again. |

Answers to questions the wizard may print:
- *"Which time zone…?"* — you passed `--tz`, so it shouldn't ask; if it does, answer with the zone.
- *"venues.yaml already has id …"* — the cinema is already there; ask whether they meant a different branch.

### Step 4 — Show the result

1. Find the cinema's street address yourself (its website's footer or "Visit" / "Contact" page) and
   add it to the cinema's entry in `config/venues.yaml`: `location: {address: "123 Main St, City, ST 12345"}`
   (copy the shape of an existing entry; `geo: [latitude, longitude]` is optional and pins the exact
   spot). The page's "Add to Calendar" button puts this address in the event, so the calendar can open
   it in Maps. Don't ask them for it unless the site doesn't show one.
2. The first time, fetch the rest of the default cinemas too: `.venv/bin/python -m scraper.run`
   (a few minutes; one of them, MoMA, falls back to another source — that's expected). Otherwise run
   `.venv/bin/python -m scraper.export` so the address reaches the page.
3. Open the page: `open site/index.html` (macOS), `start site\index.html` (Windows),
   `xdg-open site/index.html` (Linux).
4. Tell them in two or three sentences: how many showtimes were found and for which dates, that the new
   cinema has its own button at the top, and that they can switch view (timeline / list / week).
5. Tell them three things they should know:
   - Everything lives on **their computer**; it doesn't change the public website.
   - Showtimes update **by themselves twice a day** once Step 5 is done (only while the computer is on).
   - To hide the author's default cinemas, click a cinema's button at the top of the page (it remembers),
     or ask you to switch them off.

### Step 5 — Turn on daily updates

Do this the first time, right after Step 4, unless they already said no. Say it in one sentence and
ask: *"I'll set it to update the showtimes automatically every day at 1:00 and 13:00 (while this computer
is on) — OK?"* On yes:

```
.venv/bin/python -m scraper.schedule on            # macOS / Linux
.venv\Scripts\python -m scraper.schedule on        # Windows
```

- It schedules this folder with the OS's own scheduler (macOS launchd, Windows Task Scheduler, Linux
  systemd or cron) and never publishes anything. Missed runs (computer asleep) catch up afterwards.
- **macOS, exit code 2 with "Downloads / Documents / Desktop / iCloud Drive"**: background jobs may not
  read those folders. Offer to move the whole project folder into their home folder (e.g.
  `~/corridor-showtimes`), reopen it there, reinstall with the setup command from Step 1 (the `.venv` has
  absolute paths inside), and run `schedule on` again.
- They want other times → `schedule on --times 08:00 20:00` (24-hour, this computer's clock).
- Later cinemas need nothing extra: every enabled cinema in `config/venues.yaml` is included.
- The wizard's last line (and `"auto_update"` in `--json` output) says whether it is on.

### Other requests you may get

- **"Update the showtimes" (right now)** → `.venv/bin/python -m scraper.update`, then reopen the page.
- **"Remove a cinema" / "hide the default cinemas"** → in `config/venues.yaml` set `enabled: false` on
  those entries, then `.venv/bin/python -m scraper.export`.
- **"Update every day by itself" / "stop updating" / "is it updating?"** →
  `.venv/bin/python -m scraper.schedule on` / `off` / `status` (see Step 5).
- **"Add to Calendar" has no address / the map opens the wrong place** → set or fix that cinema's
  `location:` in `config/venues.yaml` (see Step 4), then `.venv/bin/python -m scraper.export`. A cinema
  with several buildings lists them under `location.places` (see `filmadelphia` / `filmlinc`).
- **"The page says it hasn't updated in days"** → `.venv/bin/python -m scraper.schedule status`; if it
  isn't on, do Step 5; if it is, show them the last lines of `logs/refresh.log`.

### Blocked cinemas

New York and San Francisco cinemas may be listed on screenslate.com. Look up the cinema's id:

```
curl -s 'https://www.screenslate.com/jsonapi/node/venue?filter[title]=<cinema name>'
```

If it's there, add the venue with only that source: `source: {adapter: screenslate, nid: <id>}` in
`config/venues.yaml` (copy the shape of an existing entry), then `.venv/bin/python -m scraper.run --venue <id>`.
Tell them this data may be less complete than the cinema's own site.

### When you can't solve it

If a cinema still doesn't work after an honest attempt (the brief's acceptance commands keep failing,
or the site needs something the rules below forbid), stop, and help them open an issue:

1. Explain in one or two sentences what went wrong.
2. Give them this link: <https://github.com/Marc506/corridor-showtimes/issues/new?template=help-add-cinema.yml>
   (they need a free GitHub account).
3. Prepare the text for them to paste: cinema name, URL, which assistant they used, the wizard's last
   lines, and what you tried.

---

## Part 2 — Working on the code

Design: `ARCHITECTURE.md`. Per-cinema notes: `SOURCES.md`. Per-platform notes: `PLATFORMS.md`.

A cinema's data source is chosen in `config/venues.yaml` (`source:`), in this order of preference:
platform adapter (`scraper/adapters/<name>.py`, parameters only) → recipe (`adapter: recipe`,
`scraper/recipes/<id>.yaml`) → custom module (`scraper/sources/<id>.py`, `adapter: custom`).

```
pytest -q                                                   # offline; must stay green
pytest tests/test_contract.py -k <id>                       # the Screening contract for one venue
python -m scraper.run --venue <id> --parse-fixture <file>   # parse a saved page, no network
python -m scraper.run --venue <id> --dry-run                # fetch live, print, write nothing
python -m scraper.add --verify <id>                         # fetch once, save fixture, run the contract
```

Rules:

- `parse()` is a pure function of saved pages; every source has fixtures under `tests/fixtures/`.
- Times are ISO 8601 with the venue's offset: use `iso(dt, self.tz)` / `to_local(dt, self.tz)`, never a
  hard-coded New York zone.
- Never work around Cloudflare, Sucuri, Incapsula, CAPTCHAs or rate limits. A 403 / 429 / challenge page
  means stop and report; do not retry or change the user agent.
- Respect `max_requests_per_run` and `rate_limit_s`; keep request counts per run small.
- Do not run `scripts/refresh.sh`, `scripts/publish.sh` or `scraper.update --publish`, and never pass
  `--publish` to `scraper.schedule on` — those publish to the author's website.
- Don't edit other venues' fixtures or tests when adding one.
