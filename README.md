# 🎟️ Ticket Watcher

A small, self-hosted bot that watches ticketing sites and messages you on
**Telegram** the moment booking opens. Runs for free on **GitHub Actions**
(or on any computer you leave on). No Claude, no paid service.

- Any movie, any city, several at once
- Sites: **BookMyShow**, **District** (on), **PVR INOX** (template, off) – add more in `config.yaml`
- Also watches **any web page** for text appearing/disappearing (concerts, matches, restocks)
- Manage everything from Telegram: `/track`, `/list`, `/pause`, …
- Alerts once per change, stops a tracker after it fires, warns you if a site starts blocking it, daily "still alive" ping

---

## 1. Create your Telegram bot (2 min)

1. In Telegram, open **@BotFather** → `/newbot` → pick a name → copy the **token**
   (looks like `7123456789:AAH...`).
2. Open your new bot and send it any message (e.g. `hi`).
3. In a browser, open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   and find `"chat":{"id": 123456789` – that number is your **chat ID**.

## 2. Run it free on GitHub Actions

1. Create a new GitHub repo and upload all files from this folder
   (keep the `.github/workflows/watch.yml` path as is).
   **Public repo = unlimited free minutes.** Your token stays secret either way
   (it's stored as a secret, not in the code). If you make it private, change the
   cron in `watch.yml` to `*/30 * * * *` or slower to stay inside the free quota.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = your token
   - `TELEGRAM_CHAT_ID` = your chat ID
3. Repo → **Actions** tab → enable workflows → **ticket-watch → Run workflow**.
   Within a couple of minutes you'll get a "Still watching…" message (sent once a
   day after 10:00).

It now checks every ~15 minutes. Avengers: Doomsday in Bangalore is already in
`trackers.json`.

> GitHub pauses scheduled workflows in repos with no activity for 60 days. The
> bot commits its `state.json` after each run, which keeps the repo active.

## 3. Use it from Telegram

| Command | What it does |
|---|---|
| `/track Avengers: Doomsday \| Bangalore` | watch a movie on all enabled sites |
| `/track Dune: Part Three \| Mumbai \| bookmyshow` | only on specific sites |
| `/watch https://site/event \| book now` | alert when "book now" appears |
| `/watch https://site/event \|  \| sold out` | alert when "sold out" disappears |
| `/seturl <id> bookmyshow <url>` | pin the exact movie page (most reliable) |
| `/list` | trackers + last status per site |
| `/pause <id>` · `/resume <id>` · `/untrack <id>` | manage |
| `/sites` · `/help` | |

On GitHub Actions, commands are picked up on the next run (≤ ~15 min). In local
mode (below) they're answered within seconds.

**Tip:** as soon as the movie appears on BookMyShow/District (usually as
"I'm interested" / "Coming soon"), copy that page's URL from your browser and
`/seturl` it. The bot then checks that exact page for a "Book tickets" button.

## 4. Or run it on your own computer / Raspberry Pi

Useful if a site blocks GitHub's servers (you'll get a ⚠️ message if that happens).

```bash
pip install -r requirements.txt
python -m playwright install chromium
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m watcher test-telegram       # sends a test message
python -m watcher loop --minutes 5    # checks every 5 min, answers commands instantly
```

Windows PowerShell: `$env:TELEGRAM_BOT_TOKEN="..."` instead of `export`.
No browser available (e.g. Termux on Android)? Set `use_browser: never` in
`config.yaml` – it'll use plain HTTP, which works on fewer sites.

Other CLI commands: `python -m watcher run --dry-run` (one pass, print instead of
send), `add-movie "Name" --city X [--sites a,b]`, `add-page URL --appear "..." --gone "..."`,
`list`, `remove ID`.

## How a check works

For each movie tracker and each site:

1. Open the site's listing pages for the city (`listing_urls` in `config.yaml`),
   find a link whose text or URL contains every word of the movie name
   (so "Avengers: Endgame" never matches "Avengers: Doomsday").
2. Open that movie page and read its buttons:
   - "Book tickets" and no "Coming soon/I'm interested" → **🎟️ BOOKING OPEN** (tracker stops)
   - both → **👀 may be open** (keeps watching)
   - otherwise → not yet (silent)
3. A site that fails 6 times in a row → one ⚠️ warning; it tells you when it recovers.

## Adding / fixing a site

Everything site-specific is in `config.yaml`. To add a site, copy the
`bookmyshow:` block, change `listing_urls` (use `{city}`), the link filter, and the
button phrases. If a site changes its layout, that file is usually the only thing
to edit. `city_aliases` maps "Bangalore" → `bengaluru` etc.; `city_slugs` handles
per-site oddities (BookMyShow uses `national-capital-region-ncr` for Delhi).

For a new *kind* of check (e.g. an API), add a `Provider` subclass in
`watcher/providers/` and register it in `providers/__init__.py`.

## Honest limits

- Ticketing sites don't offer public APIs and use bot protection; a site may
  block cloud servers or change its page layout. The ⚠️ warning tells you when a
  check stops working; running locally, `/seturl`, or tweaking `config.yaml`
  phrases usually fixes it.
- The default District and PVR URLs could not be verified live while building
  this – open them in a browser once, and adjust `listing_urls` if they don't
  show your city's movies.
- Checks are every ~15 min on GitHub (scheduled runs can lag a little). For
  minute-level speed, use local `loop` mode.
- Also tap "I'm interested"/"Notify me" on BookMyShow and District themselves as a backup.

## Project layout

```
config.yaml            sites, phrases, city aliases, settings
trackers.json          what to watch (edited by you or by Telegram commands)
state.json             last status per tracker/site (auto-created)
watcher/
  runner.py            one check pass, alert-on-change logic
  commands.py          Telegram commands
  fetch.py             headless browser / HTTP fetch + HTML parsing
  matching.py          name & phrase matching
  providers/           listing.py (ticket sites), page.py (any URL)
  notifiers/           telegram.py, console
tests/test_watcher.py  offline tests (python -m pytest -q)
.github/workflows/watch.yml
```
