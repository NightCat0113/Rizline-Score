"""Rizline sessions kept in memory and, when a database is attached, encrypted on disk."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from bot.models import Session
from bot.store.db import Database


def is_auth_failure(exc: BaseException) -> bool:
    """True when Rizline rejected the saved login (expired or invalid token)."""
    text = str(exc).lstrip()
    return text.startswith("HTTP 401") or text.startswith("HTTP 403")


class SessionStore:
    def __init__(self, database: Database | None = None) -> None:
        self._items: dict[int, Session] = {}
        self._expires: dict[int, datetime] = {}
        self._lock = threading.Lock()
        self._db = database

    def put(self, user_id: int, session: Session) -> None:
        expires = None
        if self._db is not None:
            expires = self._db.put_session(
                user_id,
                {"email": session.email, "token": session.token, "device_id": session.device_id},
            )
        with self._lock:
            self._items[user_id] = session
            if expires is not None:
                self._expires[user_id] = expires
            else:
                self._expires.pop(user_id, None)

    def get(self, user_id: int) -> Session | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            cached = self._items.get(user_id)
            deadline = self._expires.get(user_id)
        if cached is not None and (deadline is None or deadline > now):
            return cached
        if cached is not None and deadline is not None and deadline <= now:
            self.pop(user_id)
            return None
        if self._db is None:
            return None
        loaded = self._db.get_session(user_id)
        if loaded is None:
            return None
        payload, expires = loaded
        session = Session(
            email=payload["email"],
            token=payload["token"],
            device_id=payload["device_id"],
        )
        with self._lock:
            self._items[user_id] = session
            self._expires[user_id] = expires
        return session

    def touch(self, user_id: int) -> None:
        if self._db is None:
            return
        expires = self._db.touch_session(user_id)
        if expires is None:
            return
        with self._lock:
            self._expires[user_id] = expires

    def pop(self, user_id: int) -> None:
        with self._lock:
            self._items.pop(user_id, None)
            self._expires.pop(user_id, None)
        if self._db is not None:
            self._db.delete_session(user_id)
