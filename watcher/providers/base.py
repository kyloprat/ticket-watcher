"""Provider interface + registry. A provider answers: is <thing> bookable on <site>?"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    OPEN = "open"              # clearly bookable
    POSSIBLE = "possible"      # booking button seen, but mixed signals – go look
    NOT_YET = "not_yet"        # page exists, not bookable yet
    NOT_LISTED = "not_listed"  # site doesn't list it yet
    ERROR = "error"            # couldn't check (blocked, timeout, …)

    @property
    def rank(self) -> int:
        return ["error", "not_listed", "not_yet", "possible", "open"].index(self.value)


@dataclass
class Result:
    provider: str
    status: Status
    url: str | None = None
    detail: str = ""


class Provider(ABC):
    key: str = ""
    name: str = ""

    @abstractmethod
    def check(self, tracker: dict, fetcher) -> Result: ...
