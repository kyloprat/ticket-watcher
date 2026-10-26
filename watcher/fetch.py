"""Page fetching: real headless browser (Playwright) with a plain-HTTP fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


@dataclass
class Page:
    url: str
    status: int = 0
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)   # (text, absolute href)
    actions: list[str] = field(default_factory=list)              # short button/link labels
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class _Extractor(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.actions: list[str] = []
        self._skip = 0
        self._stack: list[tuple[str, str | None, list[str]]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in ("a", "button") or a.get("role") == "button":
            href = urljoin(self.base, a["href"]) if tag == "a" and a.get("href") else None
            self._stack.append((tag, href, [a.get("aria-label", "") or ""]))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif self._stack and self._stack[-1][0] == tag:
            _, href, parts = self._stack.pop()
            label = " ".join(" ".join(parts).split())
            if href:
                self.links.append((label, href))
            if label and len(label) < 40:
                self.actions.append(label)
            if self._stack:
                self._stack[-1][2].append(label)

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._stack:
            self._stack[-1][2].append(data)


def parse_html(url: str, html: str, status: int = 200) -> Page:
    ex = _Extractor(url)
    ex.feed(html)
    return Page(url=url, status=status, text=" ".join(" ".join(ex.text).split()),
                links=ex.links, actions=ex.actions)


class Fetcher:
    """Use as a context manager. One browser is shared across all checks in a run."""

    def __init__(self, mode: str = "auto", wait_seconds: float = 4, timezone: str = "Asia/Kolkata",
                 block_markers: list[str] | None = None):
        self.mode = mode
        self.wait = wait_seconds
        self.tz = timezone
        self.block_markers = [m.lower() for m in (block_markers or [])]
        self._pw = self._browser = self._ctx = None
        self._cache: dict[str, Page] = {}

    # -- lifecycle -------------------------------------------------------
    def __enter__(self):
        if self.mode in ("auto", "always"):
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
                self._ctx = self._browser.new_context(
                    user_agent=UA, locale="en-IN", timezone_id=self.tz,
                    viewport={"width": 1366, "height": 900})
                log.info("Using headless browser")
            except Exception as e:  # noqa: BLE001
                if self.mode == "always":
                    raise
                log.warning("Browser unavailable (%s); falling back to plain HTTP", e)
                self._close()
        return self

    def __exit__(self, *exc):
        self._close()

    def _close(self):
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._ctx = None

    # -- fetching --------------------------------------------------------
    def get(self, url: str) -> Page:
        if url in self._cache:
            return self._cache[url]
        try:
            page = self._get_browser(url) if self._ctx else self._get_http(url)
        except Exception as e:  # noqa: BLE001
            page = Page(url=url, error=f"{type(e).__name__}: {e}"[:200])
        if page.ok:
            page.error = self._blocked_reason(page)
        self._cache[url] = page
        return page

    def _blocked_reason(self, page: Page) -> str | None:
        if page.status in (401, 403, 404, 410, 429) or page.status >= 500:
            return f"HTTP {page.status}"
        head = page.text[:3000].lower()
        for m in self.block_markers:
            if m in head and len(page.text) < 5000:
                return f"blocked ('{m}')"
        if not page.text.strip():
            return "empty page"
        return None

    def _get_http(self, url: str) -> Page:
        import requests
        r = requests.get(url, timeout=30, headers={
            "User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        return parse_html(r.url, r.text, r.status_code)

    def _get_browser(self, url: str) -> Page:
        p = self._ctx.new_page()
        try:
            resp = p.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                p.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            for _ in range(3):                      # trigger lazy-loaded cards
                p.mouse.wheel(0, 3000)
                p.wait_for_timeout(500)
            p.wait_for_timeout(int(self.wait * 1000))
            text = p.inner_text("body")
            links = p.eval_on_selector_all(
                "a[href]", "els => els.map(e => [(e.innerText||e.getAttribute('aria-label')||'').trim(), e.href])")
            actions = p.eval_on_selector_all(
                "a, button, [role=button]",
                "els => els.map(e => (e.innerText||e.getAttribute('aria-label')||'').trim())"
                ".filter(t => t && t.length < 40)")
            return Page(url=p.url, status=resp.status if resp else 0,
                        text=" ".join(text.split()), links=[tuple(l) for l in links], actions=actions)
        finally:
            p.close()
