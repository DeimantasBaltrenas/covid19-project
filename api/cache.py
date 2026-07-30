"""cache.py — In-memory TTL cache for frequently requested API data.

Uses cachetools.TTLCache instead of an external cache (Redis, Memcached),
because this API runs as a single process and the data behind it only
changes on COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES' own refresh
schedule (Task 7, TARGET_LAG = '1 hour'). A per-process in-memory cache
whose entries expire on the same 1-hour cycle matches how often the
underlying data can actually change, without needing a separate cache
service to run and configure.
"""

import functools

from cachetools import TTLCache

# One shared cache for every cached endpoint. maxsize is generous relative
# to the number of distinct (endpoint, parameter) combinations this API
# can realistically be called with (a few hundred countries times a
# handful of case types and date-range presets), so eviction by size
# should not happen in normal use, only expiry by ttl.
_cache = TTLCache(maxsize=2048, ttl=3600)

# Counters exposed through GET /cache/stats, so caching can be demonstrated
# and verified without needing to read server logs.
_stats = {"hits": 0, "misses": 0}


def cached(func):
    """Caches a function's return value, keyed by its arguments.

    Applied to the endpoint functions that either query Snowflake or fit a
    model (Holt-Winters, KMeans) on every call, since those are the
    "frequently requested" and comparatively expensive operations named in
    the Task 8 requirement. MongoDB-backed endpoints are left uncached on
    purpose: an annotation added through POST /annotations is expected to
    show up immediately in the dashboard's list, and caching GET
    /annotations would delay that.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = (func.__qualname__, args, tuple(sorted(kwargs.items())))
        if key in _cache:
            _stats["hits"] += 1
            return _cache[key]
        _stats["misses"] += 1
        result = func(*args, **kwargs)
        _cache[key] = result
        return result

    return wrapper


def get_cache_stats() -> dict:
    """Returns hit/miss counts and current cache size, for GET /cache/stats."""
    return {
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "current_size": len(_cache),
        "max_size": _cache.maxsize,
        "ttl_seconds": _cache.ttl,
    }


def clear_cache() -> None:
    """Empties the cache, used by POST /cache/clear."""
    _cache.clear()