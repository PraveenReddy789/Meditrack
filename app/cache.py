"""Small thread-safe TTL cache with write-invalidation.

Dashboard queries aggregate the whole appointments table, so repeated views are
served from memory for a short TTL. Any write invalidates everything, which
keeps the dashboard consistent: staff never see numbers that ignore an
appointment they just reconciled.

A generation counter prevents a race where a slow computation that started
before a write stores its (now stale) result after the invalidation.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 128, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._generation = 0
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> tuple[Any, bool]:
        """Return (value, was_cache_hit)."""
        if self.ttl > 0:
            with self._lock:
                entry = self._data.get(key)
                if entry and entry[0] > self._clock():
                    self._data.move_to_end(key)
                    self.hits += 1
                    return entry[1], True
                self.misses += 1
                generation = self._generation
        else:
            with self._lock:
                self.misses += 1
            return compute(), False

        value = compute()
        with self._lock:
            if generation == self._generation:  # no write happened while computing
                self._data[key] = (self._clock() + self.ttl, value)
                self._data.move_to_end(key)
                while len(self._data) > self.max_entries:
                    self._data.popitem(last=False)
        return value, False

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
