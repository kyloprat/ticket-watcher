"""Watch any URL for text appearing or disappearing – concerts, matches, restocks…

Tracker fields:
  url            page to watch
  open_phrases   alert when ANY of these appears        (e.g. ["book now"])
  closed_phrases alert when ALL of these are gone       (e.g. ["sold out"])
Give one or both.
"""
from __future__ import annotations

from ..matching import contains_phrase
from .base import Provider, Result, Status


class PageProvider(Provider):
    key = "page"
    name = "Web page"

    def check(self, tracker: dict, fetcher) -> Result:
        page = fetcher.get(tracker["url"])
        if not page.ok:
            return Result(self.key, Status.ERROR, url=tracker["url"], detail=page.error)
        hay = [page.text] + page.actions
        open_p, closed_p = tracker.get("open_phrases") or [], tracker.get("closed_phrases") or []
        opened = contains_phrase(hay, open_p) if open_p else None
        closed = contains_phrase(hay, closed_p) if closed_p else None
        if open_p and opened and not closed:
            return Result(self.key, Status.OPEN, page.url, f"page shows '{opened}'")
        if not open_p and closed_p and not closed:
            return Result(self.key, Status.OPEN, page.url, f"'{closed_p[0]}' no longer on page")
        if opened and closed:
            return Result(self.key, Status.POSSIBLE, page.url, f"shows '{opened}' and '{closed}'")
        return Result(self.key, Status.NOT_YET, page.url, f"still shows '{closed}'" if closed else "no change")
