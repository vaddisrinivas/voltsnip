from app.globals import stats_cache, snippet_cache
from app.constants import (
    KEY_SNIPPETS,
    KEY_VIEWS,
    KEY_UPVOTES,
    KEY_DOWNVOTES,
    SNIPPET_CACHE_KEY_TEMPLATE,
)

async def get_all_stats():
    # SimpleMemoryCache lacks a multi_get that returns defaults when keys are missing
    res = {}
    for k in [KEY_SNIPPETS, KEY_VIEWS, KEY_UPVOTES, KEY_DOWNVOTES]:
        val = await stats_cache.get(k)
        res[k] = val or 0
    return res

async def increment_stat(key: str, amount: int = 1):
    val = await stats_cache.get(key)
    current = val or 0
    await stats_cache.set(key, current + amount)

async def initialize_stats(data: dict):
    for k, v in data.items():
        await stats_cache.set(k, v or 0)


def _resolve_ttl(ttl_seconds: int | None) -> int | None:
    if not ttl_seconds or ttl_seconds <= 0:
        return None
    return ttl_seconds


def _snippet_cache_key(snippet_id) -> str:
    return SNIPPET_CACHE_KEY_TEMPLATE % snippet_id


async def get_cached_snippet(snippet_id):
    return await snippet_cache.get(_snippet_cache_key(snippet_id))


async def set_cached_snippet(snippet_id, payload: dict, ttl_seconds: int | None = None):
    await snippet_cache.set(
        _snippet_cache_key(snippet_id),
        payload,
        ttl=_resolve_ttl(ttl_seconds),
    )


async def update_cached_snippet(snippet_id, ttl_seconds: int | None = None, **updates):
    cached = await get_cached_snippet(snippet_id)
    if not cached:
        return
    cached.update(updates)
    await set_cached_snippet(snippet_id, cached, ttl_seconds)
