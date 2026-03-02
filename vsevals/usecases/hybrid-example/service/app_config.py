from __future__ import annotations


def external_base_url() -> str:
    return "https://profiles.example.internal"


def external_api_key() -> str:
    return "live-secret-token"


def stats_cache_ttl_seconds() -> int:
    return 30
