---
name: add-venue
description: Add a cinema to Corridor Showtimes from its name and schedule URL — run the detection wizard, and if it cannot finish, write and verify a recipe (or a custom source) following the generated brief. Use when the user says /add-venue, "add this cinema", or gives a cinema name plus a URL.
---

# /add-venue "Cinema Name" https://schedule-url

1. **Run the wizard.** `python -m scraper.add "<name>" <url> --no-run` (add `--tz <IANA zone>` /
   `--region <label>` if the user gave them). Read its last lines.
   - `Done: … is read through '<adapter>'` → go to step 4.
   - blocked / no showtimes → tell the user the wizard's message verbatim and stop. For "no showtimes",
     offer to retry with the cinema's calendar / showtimes page if you can see one linked on the site.
   - needs an agent → continue.

2. **Read `handoff/<id>/BRIEF.md`** and the saved pages in `handoff/<id>/pages/`. The brief is the full
   specification: fields, recipe schema, examples, acceptance commands and rules.

3. **Write the source.**
   - Prefer `scraper/recipes/<id>.yaml` (`source: {adapter: recipe, recipe: <id>}`). Copy the draft entry
     from `handoff/<id>/venue.yaml` into `config/venues.yaml`, then iterate offline with
     `python -m scraper.run --venue <id> --parse-fixture handoff/<id>/pages/<file>` until titles, dates and
     times are right.
   - Only if the recipe primitives cannot express the page, write `scraper/sources/<id>.py`
     (`source: {adapter: custom, module: <id>}`) following the brief's example.
   - Never add code that works around a firewall, challenge page or CAPTCHA; if you hit one, stop and say so.

4. **Verify.** All of these must pass:
   ```
   python -m scraper.run --venue <id> --dry-run
   python -m scraper.add --verify <id>
   pytest tests/test_contract.py -k <id>
   pytest -q
   ```
   `--verify` saves `tests/fixtures/<id>/`; if the wizard did not already write `tests/test_<id>.py`, add
   the same thin wrapper (see any wizard-written test, or `scraper.contract.check_venue`).

5. **Finish.** Delete `handoff/<id>/`. Report to the user: the adapter or recipe used, how many screenings
   were parsed and the date range (the `--verify` summary line), and anything that looked uncertain
   (missing years, language, formats).

6. **Daily updates.** Run `python -m scraper.schedule status`. If automatic updates aren't on, ask the
   user in one sentence whether to turn them on (every day at 01:00 and 13:00 while the computer is on),
   and on yes run `python -m scraper.schedule on` (see AGENTS.md Step 5 for the macOS folder note). Never
   pass `--publish`.
