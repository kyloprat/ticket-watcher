"""Command line.

  python -m watcher run              one check pass (what GitHub Actions runs)
  python -m watcher run --dry-run    print alerts instead of sending
  python -m watcher loop             run forever on your own machine
  python -m watcher add-movie "Avengers: Doomsday" --city Bangalore [--sites bookmyshow,district]
  python -m watcher add-page URL --appear "book now" [--gone "sold out"]
  python -m watcher list | remove ID
  python -m watcher test-telegram    send a test message
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .commands import describe
from .notifiers import ConsoleNotifier, notifier_from_env
from .providers import enabled_site_keys
from .runner import Watcher
from .store import State, Trackers, load_config

BASE = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="watcher")
    ap.add_argument("--dir", default=str(BASE), help="folder with config.yaml / trackers.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    lp = sub.add_parser("loop")
    lp.add_argument("--minutes", type=float, default=10, help="minutes between checks")
    lp.add_argument("--dry-run", action="store_true")

    am = sub.add_parser("add-movie")
    am.add_argument("movie")
    am.add_argument("--city", required=True)
    am.add_argument("--sites", default="")
    am.add_argument("--keep-watching", action="store_true", help="don't stop after the first alert")
    apg = sub.add_parser("add-page")
    apg.add_argument("url")
    apg.add_argument("--appear", action="append", default=[])
    apg.add_argument("--gone", action="append", default=[])
    apg.add_argument("--label", default="")
    sub.add_parser("list")
    rm = sub.add_parser("remove")
    rm.add_argument("id")
    sub.add_parser("test-telegram")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    base = Path(a.dir)

    if a.cmd in ("add-movie", "add-page", "list", "remove"):
        trackers, state = Trackers(base / "trackers.json"), State(base / "state.json")
        if a.cmd == "add-movie":
            sites = [s.strip() for s in a.sites.split(",") if s.strip()] or \
                enabled_site_keys(load_config(base / "config.yaml"))
            t = trackers.add({"type": "movie", "movie": a.movie, "city": a.city, "providers": sites,
                              "urls": {}, "stop_after_found": not a.keep_watching})
            print("Added", t["id"])
        elif a.cmd == "add-page":
            if not a.appear and not a.gone:
                ap.error("give --appear and/or --gone")
            t = trackers.add({"type": "page", "url": a.url, "label": a.label or a.url[:60],
                              "open_phrases": a.appear, "closed_phrases": a.gone})
            print("Added", t["id"])
        elif a.cmd == "remove":
            print("Removed" if trackers.remove(a.id) else "Not found", a.id)
            state.forget(a.id)
            state.save()
        else:
            import html, re
            for t in trackers.items:
                print(html.unescape(re.sub(r"<[^>]+>", "", describe(t, state))))
            return 0
        trackers.save()
        return 0

    notifier = notifier_from_env(getattr(a, "dry_run", False))
    if a.cmd == "test-telegram":
        if isinstance(notifier, ConsoleNotifier):
            print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")
            return 1
        notifier.send("✅ Ticket Watcher is connected. Send /help to see commands.")
        print("Sent.")
        return 0

    if a.cmd == "run":
        Watcher(base, notifier).run_once()
        return 0

    # loop: check every N minutes; answer chat commands within seconds in between
    print(f"Watching every {a.minutes:g} min. Ctrl+C to stop.")
    while True:
        w = Watcher(base, notifier)
        try:
            w.run_once()
        except Exception:  # noqa: BLE001
            logging.exception("check pass failed")
        deadline = time.time() + a.minutes * 60
        while time.time() < deadline:
            w = Watcher(base, notifier)
            if isinstance(notifier, ConsoleNotifier):
                time.sleep(min(30, max(1, deadline - time.time())))
            elif w.poll_commands(timeout=25):
                w.trackers.save()


if __name__ == "__main__":
    sys.exit(main())
