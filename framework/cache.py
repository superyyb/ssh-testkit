import os
import time
from abc import ABC, abstractmethod


class CacheBackend(ABC):
    """Strategy interface for TTL-gated deduplication (check-then-set with expiry)."""

    @abstractmethod
    def set_if_absent(self, key: str, ttl: int) -> bool:
        """Set key with TTL only if not already present.

        Returns True if the key was newly set (first occurrence within the window),
        False if the key already existed and has not expired yet.
        """
        ...


class DictCacheBackend(CacheBackend):
    """In-process dict — default for single-instance deployments."""

    def __init__(self):
        self._store = {}  # key -> expires_at (epoch float)

    def set_if_absent(self, key: str, ttl: int) -> bool:
        now = time.time()
        if self._store.get(key, 0) > now:
            return False
        self._store[key] = now + ttl
        return True


class RedisCacheBackend(CacheBackend):
    """Redis-backed — correct for multi-instance deployments.

    Uses SET NX EX for atomic check-then-set, eliminating the TOCTOU race
    that a read-check-write pattern has under concurrent writers.
    """

    def __init__(self, host="localhost", port=6379, db=0, key_prefix="ltaf:"):
        import redis
        self._r = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self._prefix = key_prefix

    def set_if_absent(self, key: str, ttl: int) -> bool:
        result = self._r.set(f"{self._prefix}{key}", "1", nx=True, ex=ttl)
        return result is True  # True if newly set, None if already existed


def build_cache_backend() -> CacheBackend:
    """Return RedisCacheBackend if REDIS_HOST env var is set, otherwise DictCacheBackend."""
    redis_host = os.getenv("REDIS_HOST")
    if redis_host:
        return RedisCacheBackend(
            host=redis_host,
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
        )
    return DictCacheBackend()
