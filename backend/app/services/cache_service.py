"""
Yatra AI - High-Performance In-Memory Cache Service
Thread-safe TTL caching for trip itineraries, packing lists, and budget reports.
"""
import time
import logging
import threading
from typing import Any, Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe in-memory cache with Time-To-Live (TTL) eviction."""

    def __init__(self, default_ttl_seconds: int = 3600, max_entries: int = 500):
        self.default_ttl = default_ttl_seconds
        self.max_entries = max_entries
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            if key in self._cache:
                expires_at, value = self._cache[key]
                if now <= expires_at:
                    self._hits += 1
                    logger.debug(f"[CACHE HIT] Key: {key}")
                    return value
                else:
                    # Expired entry
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = time.time() + ttl
        with self._lock:
            # Simple eviction when exceeding max_entries
            if len(self._cache) >= self.max_entries:
                self._evict_expired_or_oldest()
            self._cache[key] = (expires_at, value)
            logger.debug(f"[CACHE SET] Key: {key} (TTL: {ttl}s)")

    def _evict_expired_or_oldest(self) -> None:
        now = time.time()
        expired_keys = [k for k, (exp, _) in self._cache.items() if exp < now]
        for k in expired_keys:
            del self._cache[k]
        if len(self._cache) >= self.max_entries:
            # Evict earliest expiring 10%
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])
            for k in sorted_keys[: max(1, self.max_entries // 10)]:
                del self._cache[k]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = (self._hits / total * 100) if total > 0 else 0.0
            return {
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": round(hit_ratio, 2),
            }


# Global cache instance
cache = TTLCache(default_ttl_seconds=3600, max_entries=500)


def make_trip_cache_key(
    destination: str,
    origin: str = "",
    num_days: int = 3,
    budget: float = 0,
    num_travelers: int = 1,
    interests: Optional[list[str]] = None,
    accommodation: str = "mid_range",
    food_preference: str = "any",
    language: str = "english",
) -> str:
    """Generate a normalized cache key for trip itinerary generation."""
    dest_norm = (destination or "").strip().lower()
    orig_norm = (origin or "").strip().lower()
    interests_norm = ",".join(sorted(i.strip().lower() for i in (interests or [])))
    accom_norm = (accommodation or "").strip().lower()
    food_norm = (food_preference or "").strip().lower()
    lang_norm = (language or "english").strip().lower()
    # Bucket budget into ₹1,000 buckets to increase cache hit rates for similar budgets
    budget_bucket = round(float(budget) / 1000.0) * 1000 if budget else 0
    return f"trip:{dest_norm}:{orig_norm}:{num_days}:{budget_bucket}:{num_travelers}:{interests_norm}:{accom_norm}:{food_norm}:{lang_norm}"


def make_packing_cache_key(
    destination: str,
    num_days: int,
    interests: Optional[list[str]] = None,
    language: str = "english",
) -> str:
    """Generate a normalized cache key for packing lists."""
    dest_norm = (destination or "").strip().lower()
    interests_norm = ",".join(sorted(i.strip().lower() for i in (interests or [])))
    lang_norm = (language or "english").strip().lower()
    return f"packing:{dest_norm}:{num_days}:{interests_norm}:{lang_norm}"


def make_budget_cache_key(
    destination: str,
    num_days: int,
    budget: float,
    num_travelers: int,
    language: str = "english",
) -> str:
    """Generate a normalized cache key for budget optimizations."""
    dest_norm = (destination or "").strip().lower()
    budget_bucket = round(float(budget) / 1000.0) * 1000 if budget else 0
    lang_norm = (language or "english").strip().lower()
    return f"budget:{dest_norm}:{num_days}:{budget_bucket}:{num_travelers}:{lang_norm}"
