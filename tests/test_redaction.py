import json

from rizline_client import debug_log, derive_minimal_cache, redact, scrub


def test_redact_structured_secrets():
    payload = {
        "email": "person@example.com",
        "password": "s3cret-pass",
        "code": "999111",
        "token": "session-token-value",
        "device_id": "device-id-value",
        "note": "mail person@example.com please",
    }
    rendered = json.dumps(redact(payload))
    for secret in ("person@example.com", "s3cret-pass", "999111", "session-token-value", "device-id-value"):
        assert secret not in rendered
    assert "<redacted>" in rendered
    assert "<redacted-email>" in rendered


def test_debug_log_scrubs_free_text(capsys):
    debug_log(True, "password=s3cret-pass email=person@example.com", ("s3cret-pass", "person@example.com"))
    captured = capsys.readouterr().err
    assert "s3cret-pass" not in captured
    assert "person@example.com" not in captured
    assert "<redacted>" in captured


def test_session_repr_hides_secrets():
    from bot.models import Session

    session = Session(email="person@example.com", token="session-token-value", device_id="device-id-value")
    rendered = repr(session)
    assert "person@example.com" not in rendered
    assert "session-token-value" not in rendered


def test_scrub_keeps_short_unrelated_text():
    assert "abc" in scrub("abc", ("ab",))


def test_derive_drops_personal_save_fields():
    save = {
        "username": "Player",
        "totalRks": 10,
        "userId": "user-id-value",
        "mails": [{"body": "secret-mail-body"}],
        "getProducts": ["sku"],
        "myBest": [
            {
                "trackAssetId": "track.Song.0",
                "difficultyClassName": "IN",
                "score": 1001000,
                "completeRate": 100,
                "isFullCombo": False,
                "isClear": True,
            }
        ],
        "levelsRks": [{"trackId": "track.Song.0", "difficultyClassName": "IN", "rks": 12.5}],
        "rizcard": {
            "avatarId": "illustration.Song.0",
            "avatarPos": {"x": 0.2, "y": 0.4, "z": 1.5},
            "bioId1": "bio.exbio00007.1",
            "bioId2": "bio.exbio00007.2",
            "backgroundId": "illustration.Other.0",
            "createTime": "secret-created-at",
            "layoutId": "layout.00056",
        },
    }
    cache = derive_minimal_cache(save)
    rendered = json.dumps(cache)
    assert cache["v"] == 1
    assert cache["avatarId"] == "illustration.Song.0"
    assert cache["bioId1"] == "bio.exbio00007.1"
    assert cache["backgroundId"] == "illustration.Other.0"
    assert cache["layoutId"] == "layout.00056"
    assert cache["avatarPos"]["z"] == 1.5
    assert "secret-mail-body" not in rendered
    assert "user-id-value" not in rendered
    assert "secret-created-at" not in rendered
    assert "mails" not in cache
    assert save["mails"]
