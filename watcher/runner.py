"""One check pass: process chat commands, check every enabled tracker, alert on changes."""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .commands import process_updates
from .fetch import Fetcher
from .providers import Status, build_providers, enabled_site_keys
from .store import State, Trackers, load_config

log = logging.getLogger(__name__)


class Watcher:
    def __init__(self, base: Path, notifier, fetcher_factory=None, now=None):
        self.base = Path(base)
        self.config = load_config(self.base / "config.yaml")
        self.settings = self.config.get("settings") or {}
        self.trackers = Trackers(self.base / "trackers.json")
        self.state = State(self.base / "state.json")
        self.notifier = notifier
        self.providers = build_providers(self.config)
        self.tz = ZoneInfo(self.settings.get("timezone", "Asia/Kolkata"))
        self._now = now
        self.fetcher_factory = fetcher_factory or (lambda: Fetcher(
            mode=self.settings.get("use_browser", "auto"),
            wait_seconds=self.settings.get("page_wait_seconds", 4),
            timezone=self.settings.get("timezone", "Asia/Kolkata"),
            block_markers=self.config.get("block_markers")))

    def now(self) -> datetime:
        return self._now() if self._now else datetime.now(self.tz)

    # ------------------------------------------------------------------
    def poll_commands(self, timeout: int = 0) -> int:
        return process_updates(self.notifier, self.trackers, self.state, self.config, timeout)

    def run_once(self) -> list[tuple[dict, object]]:
        self.poll_commands()
        out = []
        with self.fetcher_factory() as fetcher:
            for t in self.trackers.enabled():
                out += [(t, r) for r in self.check_tracker(t, fetcher)]
        self.heartbeat()
        self.trackers.save()
        self.state.save()
        return out

    def _site_keys(self, t: dict) -> list[str]:
        if t.get("type", "movie") == "page":
            return ["page"]
        enabled = enabled_site_keys(self.config)
        wanted = t.get("providers") or enabled
        # a site disabled in config is skipped unless the tracker pinned a URL for it
        return [k for k in wanted if k in self.providers and (k in enabled or k in (t.get("urls") or {}))]

    def check_tracker(self, t: dict, fetcher) -> list:
        results = []
        for key in self._site_keys(t):
            try:
                r = self.providers[key].check(t, fetcher)
            except Exception as e:  # noqa: BLE001  – one broken site never kills the run
                log.exception("check failed")
                from .providers import Result
                r = Result(key, Status.ERROR, detail=f"{type(e).__name__}: {e}")
            log.info("%s / %s -> %s (%s)", t["id"], key, r.status.value, r.detail)
            self._apply(t, r)
            results.append(r)

        if t.get("stop_after_found", True) and any(r.status == Status.OPEN for r in results):
            t["enabled"] = False
            self.notifier.send(f"✅ Stopped watching <code>{html.escape(t['id'])}</code>. "
                               f"Send /resume {html.escape(t['id'])} to keep watching.")
        return results

    def _apply(self, t: dict, r) -> None:
        slot = self.state.slot(t["id"], r.provider)
        slot["last_checked"] = self.now().isoformat(timespec="minutes")
        site = self.providers[r.provider].name

        if r.status == Status.ERROR:
            slot["fails"] += 1
            slot["last_error"] = r.detail
            limit = int(self.settings.get("error_alert_after", 6))
            if slot["fails"] >= limit and not slot["error_alerted"]:
                slot["error_alerted"] = True
                self.notifier.send(
                    f"⚠️ Can't check <b>{html.escape(site)}</b> for <code>{html.escape(t['id'])}</code> "
                    f"({slot['fails']} failures in a row).\n<i>{html.escape(r.detail[:250])}</i>\n"
                    "The site may be blocking the bot – check manually, or run the watcher "
                    "from your own computer/phone (see README).")
            return

        if slot["error_alerted"]:
            self.notifier.send(f"🔄 {html.escape(site)} is reachable again for "
                               f"<code>{html.escape(t['id'])}</code>.")
        slot["fails"], slot["error_alerted"] = 0, False
        prev = slot.get("status")
        slot["status"] = r.status.value
        if r.url:
            slot["url"] = r.url

        became_open = r.status == Status.OPEN and prev != Status.OPEN.value
        became_possible = r.status == Status.POSSIBLE and prev not in (Status.OPEN.value, Status.POSSIBLE.value)
        if became_open or became_possible:
            self.notifier.send(self._alert_text(t, r, site))
        elif r.status == Status.NOT_YET and prev in (None, Status.NOT_LISTED.value) \
                and t.get("type", "movie") == "movie":
            slot["listed_at"] = slot["last_checked"]   # quiet milestone, shown in /list

    def _alert_text(self, t: dict, r, site: str) -> str:
        e = html.escape
        if t.get("type", "movie") == "movie":
            what = f"<b>{e(t['movie'])}</b> in <b>{e(t['city'])}</b>"
        else:
            what = f"<b>{e(t.get('label') or t['url'])}</b>"
        link = f'\n👉 <a href="{e(r.url)}">{e(r.url)}</a>' if r.url else ""
        if r.status == Status.OPEN:
            return f"🎟️ BOOKING OPEN — {what} on {e(site)}!{link}\n<i>{e(r.detail)}</i>"
        return f"👀 Booking may be open — {what} on {e(site)}. Go check.{link}\n<i>{e(r.detail)}</i>"

    def heartbeat(self) -> None:
        hour = self.settings.get("heartbeat_hour")
        if hour is None:
            return
        now = self.now()
        today = now.date().isoformat()
        if now.hour >= int(hour) and self.state.data.get("last_heartbeat") != today:
            self.state.data["last_heartbeat"] = today
            active = self.trackers.enabled()
            if active:
                names = ", ".join(t.get("movie") or t.get("label") or t["id"] for t in active)
                self.notifier.send(f"🫡 Still watching {len(active)} tracker(s): {html.escape(names)}. /list for details.")
