"""Offline tests: fake web pages + fake Telegram. Run: python -m pytest -q"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from watcher.fetch import Fetcher, Page, parse_html
from watcher.notifiers import ConsoleNotifier
from watcher.runner import Watcher
from watcher.store import load_config

ROOT = Path(__file__).resolve().parent.parent

BMS_LIST = "https://in.bookmyshow.com/explore/movies-bengaluru"
BMS_UPCOMING = "https://in.bookmyshow.com/explore/upcoming-movies-bengaluru"
DIST_LIST = "https://www.district.in/movies/bengaluru-movie-tickets"
DIST_UPCOMING = "https://www.district.in/movies/upcoming-movies-in-bengaluru"
MOVIE = "https://in.bookmyshow.com/movies/bengaluru/avengers-doomsday/ET00999999"
DIST_MOVIE = "https://www.district.in/movies/avengers-doomsday-movie-tickets-in-bengaluru-MV1"

LISTING = """<html><body><h1>Movies in Bengaluru</h1>
<a href="/movies/bengaluru/avengers-endgame-encore/ET00111">Avengers: Endgame Encore</a>
<a href="/movies/bengaluru/avengers-doomsday/ET00999999"><img alt=""><div>Avengers: Doomsday</div></a>
</body></html>"""
EMPTY_LISTING = "<html><body><a href='/movies/bengaluru/other/ET1'>Some Other Film</a></body></html>"
COMING = "<html><body><h1>Avengers: Doomsday</h1><button>I'm interested</button><p>Releasing on 18 Dec</p></body></html>"
OPEN = "<html><body><h1>Avengers: Doomsday</h1><a href='/buytickets/x'>Book tickets</a></body></html>"
# District's movie page lists showtimes instead of a "Book tickets" button; its footer
# and FAQ text mention "book tickets" and "coming soon" on every movie page.
DIST_LISTING = """<html><body>
<a href="/movies/avengers-doomsday-movie-tickets-in-bengaluru-MV1">Avengers: Doomsday December 18, 2026</a>
<a href="/movies/avengers-doomsday-movie-tickets-in-mumbai-MV1">Avengers: Doomsday (Mumbai)</a>
</body></html>"""
DIST_COMING = """<html><body><h1>Avengers: Doomsday</h1><button>Watch Trailer</button>
<p>How to book tickets? Coming soon to cinemas near you.</p></body></html>"""
DIST_OPEN = """<html><body><h1>Avengers: Doomsday</h1><button>Watch Trailer</button>
<div role="button">10:35 PM IMAX</div><div role="button">11:05 AM</div>
<p>How to book tickets? Coming soon to cinemas near you.</p></body></html>"""
DOOMSDAY = {"id": "avengers-doomsday-bengaluru", "type": "movie", "movie": "Avengers: Doomsday",
            "city": "Bangalore", "providers": ["bookmyshow", "district"], "urls": {},
            "stop_after_found": True, "enabled": True}


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
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    # tests own their tracker, so pinning live URLs in the real trackers.json can't break them
    (tmp_path / "trackers.json").write_text(json.dumps([DOOMSDAY]))
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
    trackers[0]["urls"] = {"district": DIST_MOVIE}
    (base / "trackers.json").write_text(json.dumps(trackers))
    pages = {BMS_LIST: LISTING, BMS_UPCOMING: LISTING, MOVIE: COMING, DIST_MOVIE: DIST_OPEN}
    w, tg = make(base, pages)
    s = statuses(w.run_once())
    assert s == {"bookmyshow": "not_yet", "district": "open"}


def test_district_open_means_showtimes_for_the_city(base):
    pages = {BMS_LIST: EMPTY_LISTING, BMS_UPCOMING: EMPTY_LISTING,
             DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: DIST_LISTING, DIST_MOVIE: DIST_COMING}
    w, tg = make(base, pages)
    assert statuses(w.run_once())["district"] == "not_yet"     # footer "book tickets" text is ignored
    assert tg.sent == []

    pages[DIST_MOVIE] = DIST_OPEN
    w, tg = make(base, pages)
    results = w.run_once()
    assert statuses(results)["district"] == "open"
    assert any("BOOKING OPEN" in m and DIST_MOVIE in m for m in tg.sent)


def test_bms_cityless_listing_link_is_checked_on_the_city_page(base):
    # Plain-HTTP BookMyShow listings link to /movies/<slug>/ET…, a page with no city and so
    # never a "Book tickets" button; the city page is /movies/<city>/<slug>/ET….
    listing = '<a href="/movies/avengers-doomsday/ET00999999">Avengers: Doomsday</a>'
    cityless = "https://in.bookmyshow.com/movies/avengers-doomsday/ET00999999"
    pages = {BMS_LIST: listing, BMS_UPCOMING: EMPTY_LISTING, cityless: COMING, MOVIE: OPEN,
             DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: EMPTY_LISTING}
    w, tg = make(base, pages)
    assert statuses(w.run_once())["bookmyshow"] == "open"
    assert any(MOVIE in m for m in tg.sent)


def test_404_listing_is_an_error_not_an_empty_listing(base):
    gone = Page(url=DIST_UPCOMING, status=404, text="Sorry, something went wrong This page doesnt exist.")
    pages = {BMS_LIST: EMPTY_LISTING, BMS_UPCOMING: EMPTY_LISTING, DIST_LIST: gone, DIST_UPCOMING: gone}
    w, _ = make(base, pages)
    w.fetcher_factory = lambda: _BlockCheckingFetcher(pages)
    assert statuses(w.run_once())["district"] == "error"


def test_cloudflare_block_page_is_an_error(base):
    block = Page(url=BMS_LIST, status=200, text="Sorry, you have been blocked You are unable to access bookmyshow.com")
    pages = {BMS_LIST: block, BMS_UPCOMING: block, DIST_LIST: EMPTY_LISTING, DIST_UPCOMING: EMPTY_LISTING}
    w, _ = make(base, pages)
    w.fetcher_factory = lambda: _BlockCheckingFetcher(pages)
    assert statuses(w.run_once())["bookmyshow"] == "error"


class _BlockCheckingFetcher(FakeFetcher):
    """FakeFetcher that runs the real Fetcher's blocked-page rules on each page."""

    def get(self, url):
        page = super().get(url)
        if page.ok:
            page.error = Fetcher(mode="never", block_markers=load_config(ROOT / "config.yaml")
                                 .get("block_markers"))._blocked_reason(page)
        return page


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
