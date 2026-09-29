"""Small thread-safe LRU caches with explicit keys (no global mutable diagram state besides these caches)."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable

from .constants import PARSER_VERSION, RENDER_CACHE_SIZE


class LRU:
    def __init__(self, size: int = RENDER_CACHE_SIZE) -> None:
        self.size, self._d, self._lock = size, OrderedDict(), Lock()
        self.hits = self.misses = 0

    def get_or_compute(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                self.hits += 1
                return self._d[key]
            self.misses += 1
        value = fn()   # computed outside the lock; duplicate work is harmless (deterministic)
        with self._lock:
            self._d[key] = value
            while len(self._d) > self.size:
                self._d.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


def key(*parts: Any) -> str:
    h = hashlib.sha256(PARSER_VERSION.encode())
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
        h.update(b"\x00")
    return h.hexdigest()


RENDER = LRU()
PREPROCESS = LRU(64)
SIGNATURE = LRU(64)
OCR = LRU(128)
