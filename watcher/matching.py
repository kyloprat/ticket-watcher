"""Text normalisation and fuzzy-ish name matching."""
import re
from urllib.parse import urlparse

_STOP = {"the", "a", "an", "of", "and", "part", "movie", "film"}


def normalize(text: str) -> str:
    text = (text or "").lower().replace("’", "'")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(name: str) -> list[str]:
    toks = [t for t in normalize(name).split() if t not in _STOP]
    return toks or normalize(name).split()


def matches_name(name: str, text: str) -> bool:
    """True if every significant word of `name` appears as a word in `text`."""
    words = set(normalize(text).split())
    toks = name_tokens(name)
    return bool(toks) and all(t in words for t in toks)


def href_slug_text(href: str) -> str:
    """Turn a URL path like /bengaluru/movies/avengers-doomsday/ET123 into words."""
    try:
        path = urlparse(href).path
    except ValueError:
        path = href
    return normalize(path.replace("-", " ").replace("/", " "))


def matches_pattern(haystacks: list[str], patterns: list[str]) -> str | None:
    """Return the first text matched by any regex (case-insensitive) in any haystack."""
    for p in patterns:
        rx = re.compile(p, re.I)
        for h in haystacks:
            m = rx.search(h or "")
            if m:
                return m.group(0)
    return None


def contains_phrase(haystacks: list[str], phrases: list[str]) -> str | None:
    """Return the first phrase found (normalised, word-boundary) in any haystack."""
    norm_h = [" " + normalize(h) + " " for h in haystacks]
    for p in phrases:
        np = " " + normalize(p) + " "
        if np.strip() and any(np in h for h in norm_h):
            return p
    return None
