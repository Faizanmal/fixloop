"""Safe deterministic cache for Nebius Token Factory / NVIDIA Nemotron LLM inference.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. ONLY deterministic model inference responses may be cached.
2. NEVER cache active probe results (HTTP/TCP live checks) or sandboxed patch verification executions.
3. Thread-safe LRU eviction to prevent unbounded memory growth.
4. Tracks empirical metrics: cache hits, misses, tokens saved, and estimated cost saved.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any


class SafeDeterministicCache:
    """Thread-safe LRU cache for deterministic model inference calls."""

    def __init__(self, max_entries: int = 256):
        self._max_entries = max_entries
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()
        self._hits: int = 0
        self._misses: int = 0
        self._tokens_saved: int = 0
        self._calls_avoided: int = 0

    @staticmethod
    def compute_key(model: str, system_prompt: str, user_prompt: str) -> str:
        """Computes a collision-resistant SHA256 cache key."""
        payload = f"{model.strip()}::{system_prompt.strip()}::{user_prompt.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, model: str, system_prompt: str, user_prompt: str) -> str | None:
        """Retrieves cached response if present. Updates LRU order and metrics."""
        key = self.compute_key(model, system_prompt, user_prompt)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                self._calls_avoided += 1
                cached_val = self._cache[key]
                # Estimate tokens saved (~4 chars per token for prompt + completion)
                estimated_tokens = max(1, (len(user_prompt) + len(cached_val)) // 4)
                self._tokens_saved += estimated_tokens
                return cached_val
            self._misses += 1
            return None

    def set(
        self, model: str, system_prompt: str, user_prompt: str, response: str
    ) -> None:
        """Stores a verified model response. Evicts oldest entry if capacity reached."""
        if not response or not response.strip():
            return
        key = self.compute_key(model, system_prompt, user_prompt)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = response
            if len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    def get_metrics(self) -> dict[str, Any]:
        """Returns empirical cache statistics."""
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_rate = (self._hits / total_lookups) if total_lookups > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_lookups": total_lookups,
                "hit_rate": round(hit_rate, 3),
                "calls_avoided": self._calls_avoided,
                "tokens_saved": self._tokens_saved,
                "estimated_cost_saved_usd": round(self._tokens_saved * 0.00000035, 6),
                "current_size": len(self._cache),
                "max_entries": self._max_entries,
            }

    def clear(self) -> None:
        """Resets the cache and all metrics."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._tokens_saved = 0
            self._calls_avoided = 0


# Global singleton cache instance for the application lifecycle
llm_cache = SafeDeterministicCache()
