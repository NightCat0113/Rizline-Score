"""Socket client contract. No network."""

from rizline.client import fetch_own_rizcard, fetch_weekly_rank_info, fetch_weekly_tasks
from rizline.socket import (
    SOCKET_PATH,
    SOCKET_PATHS,
    SOCKET_URL,
    RizlineSocketError,
    _EngineSession,
    _as_dict,
    _describe_message,
    _event_payload,
    _match_response,
    _payload,
    _socketio_body,
    urlsplit_host_mismatch,
)


class _FakeEio:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.sent: list = []
        self.connected = False
        self.connect_kwargs: dict = {}
        self.connect_url = ""

    def on(self, event, handler=None):
        if handler is None:
            def decorator(fn):
                self.handlers[event] = fn
                return fn
            return decorator
        self.handlers[event] = handler
        return handler

    def connect(self, url: str, **kwargs) -> None:
        assert url.startswith(SOCKET_URL)
        assert "token=" in url
        self.connect_url = url
        self.connect_kwargs = kwargs
        self.connected = True

    def send(self, data) -> None:
        self.sent.append(data)
        handler = self.handlers.get("message")
        if not handler:
            return
        text = data if isinstance(data, str) else ""
        # CONNECT uses Socket.IO type 0 (Engine.IO will add 4 on the wire).
        if text.startswith("0"):
            handler('0{"sid":"abc"}')
            return
        # Must not double-wrap as 42/40 at this layer.
        assert not text.startswith("40"), text
        assert not text.startswith("42"), text
        if text.startswith("2") and (
            "GetWeeklyTasks" in text
            or "GetWeeklyRankInfo" in text
            or "FetchStaticRizcardProgress" in text
            or "FetchOwnRizcard" in text
        ):
            name = "GetWeeklyTasks"
            for candidate in (
                "GetWeeklyRankInfo",
                "GetWeeklyTasks",
                "FetchStaticRizcardProgress",
                "FetchOwnRizcard",
                "EnsureWeeklyPlayerInfo",
                "RefreshWeeklyPlayerInfo",
                "SyncOwnRizcards",
            ):
                if candidate in text:
                    name = candidate
                    break
            if name == "FetchOwnRizcard":
                handler(
                    '3[{"messageName":"FetchOwnRizcard","ok":true,'
                    '"avatarId":"illustration.live","layoutId":"layout.1"}]'
                )
                return
            if name in {"EnsureWeeklyPlayerInfo", "RefreshWeeklyPlayerInfo", "SyncOwnRizcards"}:
                return
            handler(f'3[{{"messageName":"{name}","ok":true}}]')

    def disconnect(self) -> None:
        self.connected = False


def test_payload_uses_transaction_names():
    from rizline.socket import _handshake_url, _session_fields

    body = _payload("GetWeeklyTasks", "a@b.c", "secret-token", "device")
    assert body["messageName"] == "GetWeeklyTasks"
    assert body["transactionName"] == "GetWeeklyTasks"
    assert body["requestId"]
    assert body["deviceId"] == "device"
    fields = _session_fields("a@b.c", "secret-token", "device-123")
    assert fields["device_id"] == fields["deviceId"] == "device-123"
    url = _handshake_url("a@b.c", "secret-token", "device-123")
    assert "device_id=device-123" in url
    assert "deviceId=device-123" in url
    assert "device-id=device-123" in url
    assert urlsplit_host_mismatch("https://service.rhyths.net/websocket/pigeongames.rizline") is False
    assert urlsplit_host_mismatch("https://evil.example/websocket") is True
    assert _as_dict(["x", {"rank": 1}]) == {"rank": 1}


def test_fetches_use_socketio_type_digits_not_engineio(monkeypatch):
    fake = _FakeEio()
    monkeypatch.setattr("engineio.Client", lambda **_kwargs: fake)
    monkeypatch.setattr("rizline.client._first_game_json", lambda *_args, **_kwargs: None)

    tasks = fetch_weekly_tasks("a@b.c", "secret-token", "device")
    assert tasks == {"messageName": "GetWeeklyTasks", "ok": True}
    assert fake.connect_kwargs["transports"] == ["websocket"]
    assert fake.connect_kwargs["engineio_path"] in SOCKET_PATHS
    assert fake.connected is False
    assert any(isinstance(item, str) and item.startswith("0") for item in fake.sent)
    assert any(isinstance(item, str) and item.startswith("2") and "GetWeeklyTasks" in item for item in fake.sent)
    assert not any(isinstance(item, str) and item.startswith("42") for item in fake.sent)

    rank = fetch_weekly_rank_info("a@b.c", "secret-token", "device")
    assert rank["messageName"] == "GetWeeklyRankInfo"

    card = fetch_own_rizcard("a@b.c", "secret-token", "device")
    assert card["messageName"] in {"FetchStaticRizcardProgress", "FetchOwnRizcard"}
    assert not any("ClaimWeeklyTaskReward" in item for item in fake.sent if isinstance(item, str))


def test_session_prefers_game_path(monkeypatch):
    fake = _FakeEio()
    monkeypatch.setattr("engineio.Client", lambda **_kwargs: fake)
    session = _EngineSession("a@b.c", "secret-token", "device")
    session.connect()
    assert session.path == SOCKET_PATH
    assert fake.connect_kwargs["engineio_path"] == SOCKET_PATH
    assert session._sio_ready is True
    session.close()


def test_parses_namespaced_events_and_string_payloads():
    assert _socketio_body('2/nsp,["GetWeeklyRankInfo",{"currentRank":1}]') == (
        '["GetWeeklyRankInfo",{"currentRank":1}]'
    )
    session = _EngineSession("a@b.c", "secret-token", "device")
    parsed = session._parse_response(
        '2/nsp,["GetWeeklyRankInfo",{"currentRank":{"segmentName":"Do"}}]',
        "GetWeeklyRankInfo",
    )
    assert parsed is not None
    assert parsed["currentRank"]["segmentName"] == "Do"
    assert _event_payload(["error", "nope"]) == {"event": "error", "message": "nope"}
    matched = _match_response(
        "GetWeeklyRankInfo",
        "req",
        {"messageName": "GetWeeklyRankInfo", "currentRank": {"segmentName": "Do"}},
    )
    assert matched is not None
    assert _match_response("GetWeeklyTasks", "req", {"event": "message", "message": "hi"}) is None
    try:
        _match_response("GetWeeklyTasks", "req", {"event": "error", "message": "denied"})
        assert False, "expected reject"
    except RizlineSocketError as exc:
        assert "denied" in str(exc)
    assert "message=denied" in _describe_message({"event": "error", "message": "denied"})


def test_http_game_path_is_used_before_socket(monkeypatch):
    def _api(_base, path, _payload, _headers, **_kwargs):
        assert path == "game/get_weekly_tasks"
        return b'{"weekIndex": 3, "tasks": []}', None

    monkeypatch.setattr("rizline.client.api_request", _api)
    monkeypatch.setattr(
        "rizline.socket.fetch_weekly_tasks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("socket")),
    )
    result = fetch_weekly_tasks("a@b.c", "tok", "device-123")
    assert result["weekIndex"] == 3
    assert result["tasks"] == []


def test_http_error_does_not_open_the_socket(monkeypatch):
    import pytest
    from rizline.client import RizlineAPIError

    def _api(*_args, **_kwargs):
        raise RizlineAPIError("HTTP 401")

    monkeypatch.setattr("rizline.client.api_request", _api)
    monkeypatch.setattr(
        "rizline.socket.fetch_weekly_tasks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("socket")),
    )
    with pytest.raises(RizlineAPIError, match="HTTP 401"):
        fetch_weekly_tasks("a@b.c", "tok", "device-123")


def test_progress_only_rizcard_does_not_win(monkeypatch):
    def _api(_base, path, _payload, _headers, **_kwargs):
        if path == "game/fetch_own_rizcard":
            return b'{"staticRizcardProgresses":[{"cardId":"x"}]}', None
        if path == "game/fetch_static_rizcard_progress":
            return (
                b'{"cards":[{"rizcard":{"avatarId":"illustration.live","layoutId":"layout.1","backgroundId":"illustration.bg"}}]}',
                None,
            )
        from rizline.client import RizlineAPIError

        raise RizlineAPIError("HTTP 404")

    monkeypatch.setattr("rizline.client.api_request", _api)
    result = fetch_own_rizcard("a@b.c", "tok", "device-123")
    assert result["cards"][0]["rizcard"]["avatarId"] == "illustration.live"


def test_disconnect_stops_call(monkeypatch):
    import pytest
    from rizline.client import RizlineError

    class _DisconnectEio(_FakeEio):
        def send(self, data) -> None:
            self.sent.append(data)
            handler = self.handlers.get("message")
            if not handler:
                return
            text = data if isinstance(data, str) else ""
            if text.startswith("0"):
                handler('0{"sid":"abc"}')
                return
            # Kick only on real RPC frames, not the post-CONNECT auth announce.
            if text.startswith("2") and "GetWeeklyTasks" in text:
                handler("2[]")
                handler("1")

    fake = _DisconnectEio()
    monkeypatch.setattr("engineio.Client", lambda **_kwargs: fake)
    monkeypatch.setattr("rizline.client._first_game_json", lambda *_args, **_kwargs: None)
    with pytest.raises(RizlineError) as raised:
        fetch_weekly_tasks("a@b.c", "secret-token", "device-12345")
    text = str(raised.value)
    assert "disconnect" in text
    assert "recv=" in text


def test_live_clients_do_not_import_the_bot():
    from pathlib import Path

    import rizline.client as client
    import rizline.payload as payload
    import rizline.socket as socket_client

    for module in (client, payload, socket_client):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "bot.services" not in source
        assert "import bot" not in source
