"""Generic "ticketing site" provider, fully driven by config.yaml.

1. Open each listing URL for the city, find links whose text or URL matches
   the movie name (or use a URL you pinned in the tracker's "urls").
2. Open the movie page and look at its buttons/links:
   open phrase only        -> OPEN
   open + closed phrases   -> POSSIBLE (alert, but don't stop tracking)
   otherwise               -> NOT_YET
"""
from __future__ import annotations

import re

from ..matching import contains_phrase, href_slug_text, matches_name, matches_pattern, normalize
from .base import Provider, Result, Status


def city_slug(city: str, aliases: dict, overrides: dict) -> str:
    c = normalize(city).replace(" ", "-")
    c = aliases.get(c, c)
    return overrides.get(c, c)


class ListingProvider(Provider):
    MAX_CANDIDATES = 3

    def __init__(self, key: str, cfg: dict, city_aliases: dict):
        self.key = key
        self.name = cfg.get("name", key)
        self.cfg = cfg
        self.aliases = {normalize(k).replace(" ", "-"): v for k, v in (city_aliases or {}).items()}

    def _rewrite(self, href: str, slug: str) -> str:
        """Apply the site's optional link_rewrite [regex, replacement] (replacement may use {city})."""
        rule = self.cfg.get("link_rewrite")
        if not rule:
            return href
        return re.sub(rule[0], rule[1].replace("{city}", slug), href)

    def _find_candidates(self, movie: str, slug: str, fetcher) -> tuple[list[str], list[str], int]:
        must = [m.format(city=slug) for m in self.cfg.get("link_must_contain", [])]
        found, errors, loaded = [], [], 0
        for tmpl in self.cfg.get("listing_urls", []):
            page = fetcher.get(tmpl.format(city=slug))
            if not page.ok:
                errors.append(f"{page.url}: {page.error}")
                continue
            loaded += 1
            for text, href in page.links:
                if must and not all(m in href for m in must):
                    continue
                if matches_name(movie, text) or matches_name(movie, href_slug_text(href)):
                    href = self._rewrite(href, slug)
                    if href not in found:
                        found.append(href)
        # Prefer URLs that mention the city (e.g. /bengaluru/movies/... or ...-in-bengaluru-...)
        found.sort(key=lambda h: slug not in h.lower())
        return found[: self.MAX_CANDIDATES], errors, loaded

    def classify(self, page) -> tuple[Status, str]:
        hay = page.actions or [page.text]
        opened = contains_phrase(hay, self.cfg.get("open_phrases", [])) or \
            matches_pattern(hay, self.cfg.get("open_patterns", []))
        closed = contains_phrase(hay, self.cfg.get("closed_phrases", []))
        if opened and not closed:
            return Status.OPEN, f"page shows '{opened}'"
        if opened and closed:
            return Status.POSSIBLE, f"page shows both '{opened}' and '{closed}'"
        return Status.NOT_YET, f"page shows '{closed}'" if closed else "no booking button yet"

    def check(self, tracker: dict, fetcher) -> Result:
        movie, city = tracker["movie"], tracker["city"]
        slug = city_slug(city, self.aliases, self.cfg.get("city_slugs") or {})
        pinned = (tracker.get("urls") or {}).get(self.key)
        if pinned:
            candidates, errors, loaded = [pinned], [], 1
        else:
            candidates, errors, loaded = self._find_candidates(movie, slug, fetcher)
        if not loaded:
            return Result(self.key, Status.ERROR, detail="; ".join(errors)[:300] or "no listing URLs")
        if not candidates:
            return Result(self.key, Status.NOT_LISTED, detail=f"'{movie}' not listed for {slug}")

        best = Result(self.key, Status.ERROR, detail="could not open movie page")
        for url in candidates:
            page = fetcher.get(url)
            if not page.ok:
                if best.status == Status.ERROR:
                    best.detail = f"{url}: {page.error}"
                continue
            status, detail = self.classify(page)
            if status.rank > best.status.rank:
                best = Result(self.key, status, url=page.url or url, detail=detail)
            if status == Status.OPEN:
                break
        return best
