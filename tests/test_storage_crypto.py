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


def test_expired_cache_is_removed(tmp_path):
    database = Database(tmp_path / "bot.db", _box())
    database.put_cache(7, _cache(), timedelta(seconds=-1))
    assert database.get_cache(7) is None
    assert database.access_flags(7) == (False, False)
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
