"""Telegram chat commands to manage trackers without touching files."""
from __future__ import annotations

import html

from .providers import enabled_site_keys
from .store import State, Trackers

HELP = """<b>Ticket Watcher</b>
/track <i>Movie</i> | <i>City</i> [| bookmyshow,district]
   e.g. <code>/track Avengers: Doomsday | Bangalore</code>
/watch <i>URL</i> | <i>appear text</i> [| <i>gone text</i>]
   e.g. <code>/watch https://site/event | book now | sold out</code>
   (leave appear text empty to alert when "gone text" disappears)
/seturl <i>id</i> <i>site</i> <i>URL</i> – pin the exact movie page for a site
/list – all trackers and last status
/pause <i>id</i> · /resume <i>id</i> · /untrack <i>id</i>
/sites – available sites
/help"""


def _e(s) -> str:
    return html.escape(str(s))


def _split(arg: str) -> list[str]:
    return [p.strip() for p in arg.split("|")]


def describe(t: dict, state: State) -> str:
    what = (f"{_e(t['movie'])} — {_e(t['city'])}" if t.get("type", "movie") == "movie"
            else _e(t.get("label") or t.get("url")))
    flag = "" if t.get("enabled", True) else " ⏸"
    sts = state.data["trackers"].get(t["id"], {})
    status = ", ".join(f"{k}: {v.get('status') or '–'}" for k, v in sts.items()) or "not checked yet"
    return f"• <code>{_e(t['id'])}</code>{flag}\n  {what}\n  <i>{_e(status)}</i>"


def handle(text: str, trackers: Trackers, state: State, config: dict) -> str | None:
    text = text.strip()
    if not text.startswith("/"):
        return None
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    sites = enabled_site_keys(config)

    if cmd in ("/start", "/help"):
        return HELP

    if cmd == "/sites":
        allp = config.get("providers") or {}
        return "\n".join(f"• <code>{k}</code> {'✅' if k in sites else '⛔ disabled in config'}"
                         for k in allp) or "No sites configured."

    if cmd == "/track":
        parts = _split(arg)
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return "Usage: /track Movie name | City [| site1,site2]"
        chosen = [s.strip().lower() for s in parts[2].split(",")] if len(parts) > 2 and parts[2] else sites
        unknown = [s for s in chosen if s not in (config.get("providers") or {})]
        if unknown:
            return f"Unknown site(s): {_e(', '.join(unknown))}. See /sites"
        t = trackers.add({"type": "movie", "movie": parts[0], "city": parts[1],
                          "providers": chosen, "urls": {}})
        return f"👀 Tracking added:\n{describe(t, state)}\nI'll message you when booking opens."

    if cmd == "/watch":
        parts = _split(arg)
        if not parts or not parts[0].startswith("http"):
            return "Usage: /watch URL | text that appears [| text that disappears]"
        open_p = [parts[1]] if len(parts) > 1 and parts[1] else []
        closed_p = [parts[2]] if len(parts) > 2 and parts[2] else []
        if not open_p and not closed_p:
            return "Give at least one phrase to look for."
        t = trackers.add({"type": "page", "url": parts[0], "label": parts[0][:60],
                          "open_phrases": open_p, "closed_phrases": closed_p})
        return f"👀 Watching page:\n{describe(t, state)}"

    if cmd == "/seturl":
        bits = arg.split()
        if len(bits) != 3:
            return "Usage: /seturl tracker-id site URL"
        t = trackers.get(bits[0])
        if not t or t.get("type", "movie") != "movie":
            return "No movie tracker with that id. See /list"
        t.setdefault("urls", {})[bits[1].lower()] = bits[2]
        return f"📌 Pinned {_e(bits[1])} page for <code>{_e(t['id'])}</code>."

    if cmd == "/list":
        if not trackers.items:
            return "No trackers yet. Try /track"
        return "\n\n".join(describe(t, state) for t in trackers.items)

    if cmd in ("/pause", "/resume", "/untrack"):
        t = trackers.get(arg)
        if not t:
            return "No tracker with that id. See /list"
        if cmd == "/untrack":
            trackers.remove(arg)
            state.forget(arg)
            return f"🗑 Removed <code>{_e(arg)}</code>."
        t["enabled"] = cmd == "/resume"
        if t["enabled"]:
            state.forget(arg)   # fresh start: alert again if it's open
        return f"{'▶️ Resumed' if t['enabled'] else '⏸ Paused'} <code>{_e(arg)}</code>."

    return "Unknown command. /help"


def process_updates(notifier, trackers: Trackers, state: State, config: dict, timeout: int = 0) -> int:
    """Pull pending chat commands, apply them, reply. Returns number handled."""
    if hasattr(notifier, "offset"):
        notifier.offset = state.data.get("telegram_offset", notifier.offset)
    updates = notifier.get_updates(timeout=timeout)
    if hasattr(notifier, "offset"):
        state.data["telegram_offset"] = notifier.offset
    for _, text in updates:
        reply = handle(text, trackers, state, config)
        if reply:
            notifier.send(reply)
    if updates:
        trackers.save()
        state.save()
    return len(updates)
