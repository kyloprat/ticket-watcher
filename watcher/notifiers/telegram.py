"""Telegram Bot API over plain HTTPS (no extra library needed)."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str | int):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.offset: int | None = None   # set from saved state by the runner

    def send(self, text: str) -> None:
        r = requests.post(f"{self.base}/sendMessage", timeout=30, json={
            "chat_id": self.chat_id, "text": text[:4000], "parse_mode": "HTML",
            "disable_web_page_preview": True})
        if not r.ok:
            log.error("Telegram send failed: %s %s", r.status_code, r.text[:200])

    def get_updates(self, timeout: int = 0) -> list[tuple[str, str]]:
        """New messages since last call. Only messages from the configured chat
        are returned, so strangers can't control your bot."""
        params = {"timeout": timeout, "allowed_updates": '["message"]'}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            r = requests.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 15)
            data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram getUpdates failed: %s", e)
            return []
        out = []
        for upd in data.get("result", []):
            self.offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            if chat == self.chat_id and msg.get("text"):
                out.append((chat, msg["text"]))
        return out
