"""Builds provider objects from config. To add a new kind of provider, write a
Provider subclass and register it in `build_providers`; to add another
ticketing site, just add a block to config.yaml."""
from .base import Provider, Result, Status
from .listing import ListingProvider
from .page import PageProvider


def build_providers(config: dict) -> dict[str, Provider]:
    out: dict[str, Provider] = {}
    aliases = config.get("city_aliases") or {}
    for key, cfg in (config.get("providers") or {}).items():
        out[key] = ListingProvider(key, cfg or {}, aliases)
    out["page"] = PageProvider()
    return out


def enabled_site_keys(config: dict) -> list[str]:
    return [k for k, v in (config.get("providers") or {}).items() if (v or {}).get("enabled", True)]


__all__ = ["Provider", "Result", "Status", "build_providers", "enabled_site_keys"]
