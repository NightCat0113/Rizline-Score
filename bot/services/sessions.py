"""In-memory Rizline sessions. Nothing here is written to disk."""

from __future__ import annotations

import threading

from bot.models import Session


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[int, Session] = {}
        self._lock = threading.Lock()

    def put(self, user_id: int, session: Session) -> None:
        with self._lock:
            self._items[user_id] = session

    def get(self, user_id: int) -> Session | None:
        with self._lock:
            return self._items.get(user_id)

    def pop(self, user_id: int) -> None:
        with self._lock:
            self._items.pop(user_id, None)
