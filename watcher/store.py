"""Loading/saving config, trackers.json and state.json."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .matching import normalize


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_json(path: Path, default):
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def make_id(*parts: str) -> str:
    return "-".join(normalize(p).replace(" ", "-") for p in parts if p)[:60] or "tracker"


class Trackers:
    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict] = _read_json(path, [])

    def save(self):
        _write_json(self.path, self.items)

    def get(self, tid: str) -> dict | None:
        return next((t for t in self.items if t["id"] == tid), None)

    def enabled(self) -> list[dict]:
        return [t for t in self.items if t.get("enabled", True)]

    def add(self, tracker: dict) -> dict:
        base = tracker.get("id") or make_id(tracker.get("movie") or tracker.get("label") or "page",
                                            tracker.get("city", ""))
        tid, n = base, 2
        while self.get(tid):
            tid, n = f"{base}-{n}", n + 1
        tracker = {"id": tid, "enabled": True, "stop_after_found": True, **tracker, "id": tid}
        self.items.append(tracker)
        return tracker

    def remove(self, tid: str) -> bool:
        before = len(self.items)
        self.items = [t for t in self.items if t["id"] != tid]
        return len(self.items) < before


class State:
    """Remembers last status per (tracker, site) so we alert on changes only."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = _read_json(path, {})
        self.data.setdefault("trackers", {})

    def save(self):
        _write_json(self.path, self.data)

    def slot(self, tid: str, provider: str) -> dict:
        return self.data["trackers"].setdefault(tid, {}).setdefault(
            provider, {"status": None, "fails": 0, "error_alerted": False})

    def forget(self, tid: str):
        self.data["trackers"].pop(tid, None)
