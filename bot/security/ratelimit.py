"""In-process per-user rate limits. Counts reset when the process exits."""

from __future__ import annotations

import time


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window_seconds: float, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        recent = [stamp for stamp in self._events.get(key, []) if current - stamp < window_seconds]
        if len(recent) >= limit:
            self._events[key] = recent
            return False
        recent.append(current)
        self._events[key] = recent
        return True
