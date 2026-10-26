"""Offline tests: fake web pages + fake Telegram. Run: python -m pytest -q"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from watcher.fetch import Page, parse_html
from watcher.notifiers import ConsoleNotifier
from watcher.runner import Watcher

ROOT = Path(__file__).resolve().parent.parent

BMS_LIST = "https://in.bookmyshow.com/explore/movies-bengaluru"
BMS_UPCOMING = "https://in.bookmyshow.com/explore/upcoming-movies-bengaluru"
DIST_LIST = "https://www.district.in/movies/"
DIST_UPCOMING = "https://www.district.in/movies/upcoming"
MOVIE = "https://in.bookmyshow.com/bengaluru/movies/avengers-doomsday/ET00999999"

LISTING = """<html><body><h1>Movies in Bengaluru</h1>
<a href="/bengaluru/movies/avengers-endgame-encore/ET00111">Avengers: Endgame Encore</a>
<a href="/bengaluru/movies/avengers-doomsday/ET00999999"><img alt=""><div>Avengers: Doomsday</div></a>
</body></html>"""
EMPTY_LISTING = "<html><body><a href='/bengaluru/movies/other/ET1'>Some Other Film</a></body></html>"
COMING = "<html><body><h1>Avengers: Doomsday</h1><button>I'm interested</button><p>Releasing on 18 Dec</p></body></html>"
OPEN = "<html><body><h1>Avengers: Doomsday</h1><a href='/buytickets/x'>Book tickets</a></body></html>"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def get(self, url):
        v = self.pages.get(url)
        if v is None:
            return Page(url=url, error="HTTP 404")
        if isinstance(v, Page):
            return v
        return parse_html(url, v)


class FakeTelegram(ConsoleNotifier):
    def __init__(self, inbox=None):
        super().__init__()
        self.inbox = inbox or []

    def send(self, text):
        self.sent.append(text)

    def get_updates(self, timeout=0):
        msgs, self.inbox = self.inbox, []
        return [("1", m) for m in msgs]


@pytest.fixture
def base(tmp_path):
    for f in ("config.yaml", "trackers.json"):
        shutil.copy(ROOT / f, tmp_path / f)
    return tmp_path


def make(base, pages, inbox=None, hour=8):
    tg = FakeTelegram(inbox)
    w = Watcher(base, tg, fetcher_factory=lambda: FakeFetcher(pages),
                now=lambda: datetime(2026, 10, 26, hour, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    return w, tg


def statuses(results):
    return {r.provider: r.status.value for _, r in results}


def test_not_listed_is_quiet(base):
    pages = {BMS_LIST: EMPTY_LISTING, BMS_UPCOMING: EMPTY_LISTING, DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: EMPTY_LISTING}
    w, tg = make(base, pages)
    assert statuses(w.run_once()) == {"bookmyshow": "not_listed", "district": "not_listed"}
    assert tg.sent == []


def test_coming_soon_then_open_alerts_once_and_stops(base):
    pages = {BMS_LIST: LISTING, BMS_UPCOMING: LISTING, DIST_LIST: EMPTY_LISTING,
             DIST_UPCOMING: EMPTY_LISTING, MOVIE: COMING}
    w, tg = make(base, pages)
    assert statuses(w.run_once())["bookmyshow"] == "not_yet"
    assert tg.sent == []

    pages[MOVIE] = OPEN
    w, tg = make(base, pages)
    assert statuses(w.run_once())["bookmyshow"] == "open"
    assert any("BOOKING OPEN" in m and MOVIE in m and "Bangalore" in m for m in tg.sent)
    assert any("Stopped watching" in m for m in tg.sent)
    assert json.loads((base / "trackers.json").read_text())[0]["enabled"] is False

    w, tg = make(base, pages)            # disabled now → nothing checked, nothing sent
    assert w.run_once() == [] and tg.sent == []


def test_endgame_not_mistaken_for_doomsday(base):
    listing = '<a href="/bengaluru/movies/avengers-endgame-encore/ET00111">Avengers: Endgame Encore</a>'
    pages = {BMS_LIST: listing, BMS_UPCOMING: listing, DIST_LIST: listing, DIST_UPCOMING: listing}
    w, _ = make(base, pages)
    assert set(statuses(w.run_once()).values()) == {"not_listed"}


def test_mixed_signals_is_possible_and_keeps_watching(base):
    both = "<html><body><button>Book tickets</button><button>I'm interested</button></body></html>"
    pages = {BMS_LIST: LISTING, BMS_UPCOMING: LISTING, DIST_LIST: EMPTY_LISTING,
             DIST_UPCOMING: EMPTY_LISTING, MOVIE: both}
    w, tg = make(base, pages)
    assert statuses(w.run_once())["bookmyshow"] == "possible"
    assert any("may be open" in m for m in tg.sent)
    assert json.loads((base / "trackers.json").read_text())[0]["enabled"] is True


def test_blocked_site_warns_once_after_threshold(base):
    blocked = Page(url=BMS_LIST, status=403, text="Access denied", error="HTTP 403")
    pages = {BMS_LIST: blocked, BMS_UPCOMING: blocked, DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: EMPTY_LISTING}
    warnings = 0
    for _ in range(8):
        w, tg = make(base, pages)
        w.run_once()
        warnings += sum("Can't check" in m for m in tg.sent)
    assert warnings == 1


def test_telegram_commands(base):
    inbox = ["/track Oppenheimer | Mumbai | bookmyshow",
             "/watch https://example.com/concert | book now",
             "/list", "/pause oppenheimer-mumbai", "/bogus"]
    w, tg = make(base, {}, inbox)
    w.poll_commands()
    ids = [t["id"] for t in w.trackers.items]
    assert "oppenheimer-mumbai" in ids and len(ids) == 3
    assert w.trackers.get("oppenheimer-mumbai")["enabled"] is False
    assert w.trackers.get("oppenheimer-mumbai")["providers"] == ["bookmyshow"]
    assert any("Unknown command" in m for m in tg.sent)


def test_city_alias_and_pinned_url(base):
    trackers = json.loads((base / "trackers.json").read_text())
    trackers[0]["urls"] = {"district": "https://www.district.in/movies/doomsday-in-bengaluru-MV1"}
    (base / "trackers.json").write_text(json.dumps(trackers))
    pages = {BMS_LIST: LISTING, BMS_UPCOMING: LISTING, MOVIE: COMING,
             "https://www.district.in/movies/doomsday-in-bengaluru-MV1": OPEN}
    w, tg = make(base, pages)
    s = statuses(w.run_once())
    assert s == {"bookmyshow": "not_yet", "district": "open"}


def test_page_tracker_disappear_mode(base):
    (base / "trackers.json").write_text(json.dumps([{
        "id": "gig", "type": "page", "url": "https://x.test/gig", "label": "Gig",
        "open_phrases": [], "closed_phrases": ["sold out"]}]))
    pages = {"https://x.test/gig": "<p>SOLD OUT</p>"}
    w, tg = make(base, pages)
    assert statuses(w.run_once()) == {"page": "not_yet"}
    pages["https://x.test/gig"] = "<p>Tickets available</p>"
    w, tg = make(base, pages)
    assert statuses(w.run_once()) == {"page": "open"}
    assert any("BOOKING OPEN" in m for m in tg.sent)


def test_heartbeat_once_per_day(base):
    pages = {BMS_LIST: EMPTY_LISTING, BMS_UPCOMING: EMPTY_LISTING, DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: EMPTY_LISTING}
    w, tg = make(base, pages, hour=11)
    w.run_once()
    assert sum("Still watching" in m for m in tg.sent) == 1
    w, tg = make(base, pages, hour=15)
    w.run_once()
    assert not any("Still watching" in m for m in tg.sent)
