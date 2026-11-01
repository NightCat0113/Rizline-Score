from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from bot.store.crypto import CryptoBox, MissingKeyError, TamperError, rotate_ciphertext
from bot.store.db import Database, StorageError


def _box() -> CryptoBox:
    return CryptoBox(Fernet.generate_key().decode("utf-8"))


def _cache() -> dict:
    return {
        "v": 1,
        "username": "CANARY_USER_NAME_XYZ",
        "totalRks": 1.5,
        "myBest": [],
        "levelsRks": [],
    }


def test_round_trip_and_canary_absent_from_database(tmp_path):
    box = _box()
    database = Database(tmp_path / "bot.db", box)
    database.put_cache(42, _cache(), timedelta(hours=1))
    loaded = database.get_cache(42)
    assert loaded["username"] == "CANARY_USER_NAME_XYZ"
    raw = (tmp_path / "bot.db").read_bytes()
    assert b"CANARY_USER_NAME_XYZ" not in raw
    assert b"canary-token-should-not-be-stored" not in raw
    database.close()


def test_tamper_and_wrong_key(tmp_path):
    box = _box()
    blob = box.encrypt_json(_cache())
    broken = bytearray(blob)
    broken[-2] ^= 0xFF
    with pytest.raises(TamperError):
        box.decrypt_json(bytes(broken))
    other = _box()
    with pytest.raises(TamperError):
        other.decrypt_json(blob)


def test_missing_and_invalid_key():
    with pytest.raises(MissingKeyError):
        CryptoBox("")
    with pytest.raises(MissingKeyError):
        CryptoBox("not-a-fernet-key")


def test_corrupt_database_file(tmp_path):
    path = tmp_path / "bot.db"
    path.write_bytes(b"this is not a sqlite database")
    with pytest.raises(StorageError):
        Database(path, _box())


def test_cache_refresh_keeps_sharing_off_by_default_and_preserves_opt_in(tmp_path):
    database = Database(tmp_path / "bot.db", _box())
    database.put_cache(3, _cache(), timedelta(hours=1))
    assert database.get_binding(3) == (False, database.get_binding(3)[1])
    database.set_sharing(3, True)
    database.put_cache(3, _cache(), timedelta(hours=1))
    assert database.access_flags(3) == (True, True)
    database.close()


def test_cache_age_reads_fetched_at(tmp_path):
    database = Database(tmp_path / "bot.db", _box())
    assert database.cache_age(1) is None
    database.put_cache(1, _cache(), timedelta(hours=2))
    age = database.cache_age(1)
    assert age is not None
    assert age < timedelta(minutes=1)
    database.put_cache(1, _cache(), timedelta(seconds=-1))
    assert database.cache_age(1) is None
    database.close()


def test_expired_cache_is_removed(tmp_path):
    database = Database(tmp_path / "bot.db", _box())
    database.put_cache(7, _cache(), timedelta(seconds=-1))
    assert database.get_cache(7) is None
    assert database.access_flags(7) == (False, False)
    database.close()


def test_encrypted_session_round_trip_hides_plaintext(tmp_path):
    from datetime import datetime, timedelta, timezone

    from bot.models import Session
    from bot.services.sessions import SessionStore, is_auth_failure
    from rizline.client import RizlineAPIError

    token = "canary-session-token-XYZ"
    email = "canary-session@example.com"
    device = "device-canary-99"
    database = Database(tmp_path / "bot.db", _box())
    store = SessionStore(database)
    store.put(4, Session(email=email, token=token, device_id=device))
    raw = (tmp_path / "bot.db").read_bytes()
    assert token.encode() not in raw
    assert email.encode() not in raw
    assert device.encode() not in raw

    restarted = SessionStore(database)
    loaded = restarted.get(4)
    assert loaded is not None
    assert loaded.token == token
    assert loaded.email == email
    assert loaded.device_id == device

    database._conn.execute(
        "UPDATE sessions SET expires_at = ?",
        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),),
    )
    database._conn.commit()
    assert SessionStore(database).get(4) is None
    assert database.get_session(4) is None

    store.put(4, Session(email=email, token=token, device_id=device))
    assert database.unbind(4) is True
    assert database.get_session(4) is None
    assert SessionStore(database).get(4) is None

    assert is_auth_failure(RizlineAPIError("HTTP 401"))
    assert is_auth_failure(RizlineAPIError("HTTP 403: denied"))
    assert is_auth_failure(RizlineAPIError("HTTP 404")) is False
    database.close()


def test_rotation_and_unbind(tmp_path):
    old_key = Fernet.generate_key().decode("utf-8")
    new_key = Fernet.generate_key().decode("utf-8")
    database = Database(tmp_path / "bot.db", CryptoBox(old_key))
    database.put_cache(9, _cache(), timedelta(hours=1))
    blob = database._conn.execute("SELECT ciphertext FROM score_cache").fetchone()[0]
    rotated = rotate_ciphertext(blob, old_key, new_key)
    assert CryptoBox(new_key).decrypt_json(rotated)["username"] == "CANARY_USER_NAME_XYZ"
    count = database.reencrypt_all(CryptoBox(new_key))
    assert count == 1
    assert database.get_cache(9)["username"] == "CANARY_USER_NAME_XYZ"
    assert database.unbind(9) is True
    assert database.get_binding(9) is None
    assert database.get_cache(9) is None
    database.close()
