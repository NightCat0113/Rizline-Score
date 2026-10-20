"""Fernet encryption for the score cache. The key comes from the environment."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class MissingKeyError(Exception):
    pass


class TamperError(Exception):
    pass


class CryptoBox:
    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or not key.strip():
            raise MissingKeyError("BOT_ENCRYPTION_KEY is missing")
        try:
            self._fernet = Fernet(key.strip().encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise MissingKeyError("BOT_ENCRYPTION_KEY is not a valid Fernet key") from exc

    def encrypt_json(self, payload: dict) -> bytes:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw)

    def decrypt_json(self, blob: bytes) -> dict:
        try:
            raw = self._fernet.decrypt(blob)
            parsed = json.loads(raw.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TamperError("Cached score data could not be decrypted") from exc
        if not isinstance(parsed, dict):
            raise TamperError("Cached score data could not be decrypted")
        return parsed


def rotate_ciphertext(blob: bytes, old_key: str, new_key: str) -> bytes:
    payload = CryptoBox(old_key).decrypt_json(blob)
    return CryptoBox(new_key).encrypt_json(payload)
