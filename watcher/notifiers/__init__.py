"""Notifiers send messages and (optionally) receive commands.

Interface:
  send(text: str) -> None          text may use Telegram-style HTML (<b>, <a>)
  get_updates() -> list[(chat_id, text)]   new incoming commands, may be []
"""
import html
import os
import re

from .telegram import TelegramNotifier


class ConsoleNotifier:
    """Prints instead of sending – for --dry-run and local testing."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print("\n[notify]\n" + html.unescape(re.sub(r"<[^>]+>", "", text)) + "\n")

    def get_updates(self, timeout: int = 0):
        return []


def notifier_from_env(dry_run: bool = False):
    if dry_run:
        return ConsoleNotifier()
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        return TelegramNotifier(token, chat)
    print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set – printing alerts to console.")
    return ConsoleNotifier()


__all__ = ["ConsoleNotifier", "TelegramNotifier", "notifier_from_env"]
