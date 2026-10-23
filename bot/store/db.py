"""SQLite storage for bindings and the encrypted minimal score cache.

Session tokens are not stored here.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.store.crypto import CryptoBox, TamperError


class StorageError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: Path, crypto: CryptoBox) -> None:
        self.path = Path(path)
        self.crypto = crypto
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bindings (
                    discord_id INTEGER PRIMARY KEY,
                    sharing_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS score_cache (
                    discord_id INTEGER PRIMARY KEY,
                    ciphertext BLOB NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (discord_id) REFERENCES bindings(discord_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS user_prefs (
                    discord_id INTEGER PRIMARY KEY,
                    language TEXT NOT NULL DEFAULT 'en'
                );
                """
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError("Could not open the score database") from exc

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert_binding(self, discord_id: int, sharing_enabled: bool | None = None) -> None:
        now = _utcnow().isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT sharing_enabled FROM bindings WHERE discord_id = ?",
                (discord_id,),
            ).fetchone()
            if row is None:
                flag = 1 if sharing_enabled else 0
                self._conn.execute(
                    "INSERT INTO bindings (discord_id, sharing_enabled, updated_at) VALUES (?, ?, ?)",
                    (discord_id, flag, now),
                )
            else:
                flag = row[0] if sharing_enabled is None else int(bool(sharing_enabled))
                self._conn.execute(
                    "UPDATE bindings SET sharing_enabled = ?, updated_at = ? WHERE discord_id = ?",
                    (flag, now, discord_id),
                )
            self._conn.commit()

    def get_language(self, discord_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT language FROM user_prefs WHERE discord_id = ?",
                (discord_id,),
            ).fetchone()
        return str(row[0]) if row else "en"

    def set_language(self, discord_id: int, language: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO user_prefs (discord_id, language) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET language = excluded.language
                """,
                (discord_id, str(language)),
            )
            self._conn.commit()

    def get_binding(self, discord_id: int) -> tuple[bool, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT sharing_enabled, updated_at FROM bindings WHERE discord_id = ?",
                (discord_id,),
            ).fetchone()
        if row is None:
            return None
        return bool(row[0]), str(row[1])

    def set_sharing(self, discord_id: int, enabled: bool) -> bool:
        now = _utcnow().isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE bindings SET sharing_enabled = ?, updated_at = ? WHERE discord_id = ?",
                (int(enabled), now, discord_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def put_cache(self, discord_id: int, payload: dict, ttl: timedelta) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("myBest"), list):
            raise StorageError("Refusing to store a score cache with an unexpected shape")
        now = _utcnow()
        blob = self.crypto.encrypt_json(payload)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bindings (discord_id, sharing_enabled, updated_at)
                VALUES (?, 0, ?)
                ON CONFLICT(discord_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (discord_id, now.isoformat()),
            )
            self._conn.execute(
                """
                INSERT INTO score_cache (discord_id, ciphertext, fetched_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (discord_id, blob, now.isoformat(), (now + ttl).isoformat()),
            )
            self._conn.commit()

    def get_cache(self, discord_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT ciphertext, expires_at FROM score_cache WHERE discord_id = ?",
                (discord_id,),
            ).fetchone()
            if row is None:
                return None
            expires = datetime.fromisoformat(row[1])
            if expires <= _utcnow():
                self._conn.execute("DELETE FROM score_cache WHERE discord_id = ?", (discord_id,))
                self._conn.commit()
                return None
            try:
                payload = self.crypto.decrypt_json(row[0])
            except TamperError:
                self._conn.execute("DELETE FROM score_cache WHERE discord_id = ?", (discord_id,))
                self._conn.commit()
                raise
        if not isinstance(payload.get("myBest"), list) or not isinstance(payload.get("levelsRks"), list):
            raise TamperError("Cached score data could not be decrypted")
        return payload

    def access_flags(self, discord_id: int) -> tuple[bool, bool]:
        """Return (sharing_enabled, cache_available). Missing users are (False, False)."""
        binding = self.get_binding(discord_id)
        if binding is None:
            return False, False
        try:
            cache = self.get_cache(discord_id)
        except TamperError:
            cache = None
        return binding[0], cache is not None

    def unbind(self, discord_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM bindings WHERE discord_id = ?", (discord_id,))
            self._conn.commit()
            removed = cursor.rowcount > 0
            try:
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                pass
            return removed

    def reencrypt_all(self, new_box: CryptoBox) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT discord_id, ciphertext FROM score_cache"
            ).fetchall()
            count = 0
            for discord_id, blob in rows:
                payload = self.crypto.decrypt_json(blob)
                updated = new_box.encrypt_json(payload)
                self._conn.execute(
                    "UPDATE score_cache SET ciphertext = ? WHERE discord_id = ?",
                    (updated, discord_id),
                )
                count += 1
            self._conn.commit()
            self.crypto = new_box
            return count
