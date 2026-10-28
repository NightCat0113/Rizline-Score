"""RhythNet live socket calls for Asyncombat, weekly tasks, and Rizcard.

Engine.IO is websocket-only on ``websocket/pigeongames.rizline`` (and the
``/socket.io`` variant). ``engineio.Client.send`` already prefixes Engine.IO
MESSAGE (``4``), so Socket.IO payloads must be sent as ``0`` / ``2...`` — not
``40`` / ``42...`` (that double-wraps into invalid ``440`` / ``442``).
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any
from urllib.parse import urlencode

from rizline.client import (
    PINNED_HOST,
    RizlineError,
    RizlineNetworkError,
    scrub,
)


SOCKET_URL = "https://service.rhyths.net"
SOCKET_PATHS = (
    "websocket/pigeongames.rizline",
    "websocket/pigeongames.rizline/socket.io",
)
SOCKET_PATH = SOCKET_PATHS[0]
RANK_TRANSACTION = "GetWeeklyRankInfo"
RANK_PREP = ("EnsureWeeklyPlayerInfo", "RefreshWeeklyPlayerInfo")
TASKS_TRANSACTION = "GetWeeklyTasks"
RIZCARD_TRANSACTIONS = (
    "SyncOwnRizcards",
    "FetchOwnRizcard",
    "FetchStaticRizcardProgress",
    "OnGetStaticCard",
)


class RizlineSocketError(RizlineError):
    pass


def _require_device_id(device_id: str) -> str:
    value = str(device_id or "").strip()
    if not value:
        raise RizlineSocketError("Session has no device_id. Run /bind again.")
    return value


def _session_fields(email: str, token: str, device_id: str) -> dict[str, str]:
    device_id = _require_device_id(device_id)
    # HTTP login uses device_id. The socket gateway often drops underscore headers,
    # and the kick message "no device id" matches a missing device-id header.
    return {
        "game_id": "pigeongames.rizline",
        "channel_id": "11",
        "i18n": "en-US",
        "device_id": device_id,
        "deviceId": device_id,
        "device-id": device_id,
        "device": device_id,
        "email": email,
        "token": token,
    }


def _headers(email: str, token: str, device_id: str) -> dict[str, str]:
    fields = _session_fields(email, token, device_id)
    return {
        "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
        **fields,
    }


def _handshake_url(email: str, token: str, device_id: str) -> str:
    query = urlencode(_session_fields(email, token, device_id))
    return f"{SOCKET_URL}?{query}"


def _payload(transaction: str, email: str, token: str, device_id: str) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    return {
        "messageName": transaction,
        "transactionName": transaction,
        "requestId": str(uuid.uuid4()),
        "email": email,
        "token": token,
        "device_id": device_id,
        "deviceId": device_id,
    }


def _as_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _as_dict(item)
            if found is not None:
                return found
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return _as_dict(json.loads(text))
            except json.JSONDecodeError:
                return None
    return None


def _socketio_body(text: str) -> str:
    """Strip Socket.IO type digits and optional ``/namespace,`` prefix."""
    if not text:
        return text
    idx = 0
    while idx < len(text) and text[idx].isdigit():
        idx += 1
    rest = text[idx:]
    if rest.startswith("/"):
        comma = rest.find(",")
        if comma >= 0:
            rest = rest[comma + 1 :]
    return rest


def _event_payload(value: Any) -> dict | None:
    """Accept common BestHTTP / Socket.IO event shapes as a dict result."""
    found = _as_dict(value)
    if found is not None:
        return found
    if isinstance(value, (list, tuple)) and value:
        name = value[0] if isinstance(value[0], str) else ""
        if len(value) == 1 and name:
            return {"event": name}
        if len(value) >= 2:
            data = value[1]
            nested = _as_dict(data)
            if nested is not None:
                if name and "event" not in nested:
                    return {**nested, "event": name}
                return nested
            if isinstance(data, str):
                return {"event": name or "message", "message": data}
            if data is not None:
                return {"event": name or "message", "data": data}
    if isinstance(value, str) and value.strip():
        return {"message": value.strip()}
    return None


def _match_response(transaction: str, request_id: str, payload: dict | None) -> dict | None:
    """Accept only payloads that belong to this RPC (or raise on explicit errors)."""
    if not isinstance(payload, dict) or not payload:
        return None

    event = str(payload.get("event") or "").strip()
    message_name = str(
        payload.get("messageName") or payload.get("transactionName") or event or ""
    ).strip()
    error_text = payload.get("error") or payload.get("errorMessage") or payload.get("msg")
    if event.lower() in {"error", "connect_error", "exception", "disconnect"}:
        detail = error_text or payload.get("message") or event
        raise RizlineSocketError(f"{transaction} rejected ({detail}).")
    if error_text and not any(
        key in payload for key in ("currentRank", "tasks", "weeklyTasks", "rizcard", "avatarId")
    ):
        raise RizlineSocketError(f"{transaction} rejected ({error_text}).")

    for nest in ("result", "data", "resp", "Resp", "body"):
        child = payload.get(nest)
        if isinstance(child, dict):
            matched = _match_response(transaction, request_id, child)
            if matched is not None:
                return matched

    if request_id and str(payload.get("requestId") or "") == request_id:
        return payload

    aliases = {
        transaction,
        f"{transaction}Result",
        f"On{transaction}",
        f"Complete{transaction}",
        "Resp",
    }
    if message_name in aliases:
        return payload

    keys = set(payload)
    # Ignore bare event wrappers like {"event":"message","message":"..."}.
    if keys <= {"event", "message", "data"}:
        return None

    if transaction == RANK_TRANSACTION and {
        "currentRank",
        "currentSeasonBestRank",
        "currentSeasonStartingRank",
        "currentSeasonStats",
    } & keys:
        return payload
    if transaction == TASKS_TRANSACTION and {
        "tasks",
        "weeklyTasks",
        "weekIndex",
        "nextRefreshAt",
        "items",
        "list",
    } & keys:
        return payload
    if transaction in RIZCARD_TRANSACTIONS and {
        "rizcard",
        "rizcards",
        "avatarId",
        "layoutId",
        "staticCard",
        "ownRizcards",
        "card",
    } & keys:
        return payload
    if transaction in RANK_PREP and (message_name == transaction or payload.get("ok") is True):
        return payload
    return None


def _describe_message(message: Any, secrets: tuple[str, ...] = ()) -> str:
    if isinstance(message, (bytes, bytearray)):
        return f"bin:{len(message)}"
    if isinstance(message, dict):
        return _describe_dict(message, secrets)
    if not isinstance(message, str):
        return type(message).__name__
    text = scrub(message, secrets)
    if len(text) > 180:
        text = text[:180] + "…"
    body = _socketio_body(message)
    parsed = None
    if body.startswith("[") or body.startswith("{"):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
    if isinstance(parsed, dict):
        return _describe_dict(parsed, secrets)
    if isinstance(parsed, list) and parsed:
        head = parsed[0] if isinstance(parsed[0], str) else type(parsed[0]).__name__
        extra = ""
        if len(parsed) > 1:
            if isinstance(parsed[1], dict):
                extra = " " + _describe_dict(parsed[1], secrets)
            elif isinstance(parsed[1], str):
                extra = " message=" + scrub(parsed[1], secrets)[:80]
        return f"event={head}{extra}"
    return f"raw={text}"


def _describe_dict(message: dict, secrets: tuple[str, ...] = ()) -> str:
    parts: list[str] = []
    for key in ("event", "message", "error", "errorMessage", "reason", "code", "messageName"):
        value = message.get(key)
        if value in (None, ""):
            continue
        text = scrub(str(value), secrets)
        if len(text) > 80:
            text = text[:80] + "…"
        parts.append(f"{key}={text}")
    if parts:
        return " ".join(parts)
    keys = [
        str(key)
        for key in message
        if not any(part in str(key).lower() for part in ("email", "token", "device", "password"))
    ]
    return "dict keys=" + ",".join(keys[:20])


def urlsplit_host_mismatch(url: str) -> bool:
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and host != PINNED_HOST


def _packet_prefix(message: Any) -> str:
    if isinstance(message, (bytes, bytearray)):
        return f"bin:{len(message)}"
    if not isinstance(message, str):
        return type(message).__name__
    if not message:
        return "empty"
    # Socket.IO types arrive here without the Engine.IO '4' prefix.
    idx = 0
    while idx < len(message) and message[idx].isdigit():
        idx += 1
        if idx >= 3:
            break
    return message[: max(idx, 1)]


class _EngineSession:
    """One Engine.IO connection with correctly framed Socket.IO packets."""

    def __init__(self, email: str, token: str, device_id: str) -> None:
        self.email = email
        self.token = token
        self.device_id = device_id
        self.secrets = (email, token, device_id)
        self.path = SOCKET_PATH
        self._eio = None
        self._messages: list[Any] = []
        self._seen: list[str] = []
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._ack_id = 0
        self._sio_ready = False
        self._last_unmatched = ""
        self._disconnected = False

    def connect(self) -> None:
        try:
            import engineio
        except ImportError as exc:
            raise RizlineSocketError(
                "Missing dependency: python-engineio (via python-socketio). Install bot requirements."
            ) from exc
        last_error = "no path worked"
        # Plain CONNECT first: CONNECT auth appears to get accepted then kicked.
        for path in SOCKET_PATHS:
            for mode in ("plain", "auth"):
                try:
                    self._open(engineio, path, mode=mode)
                    self.path = path
                    return
                except RizlineError as exc:
                    last_error = scrub(str(exc), self.secrets) or type(exc).__name__
                    self.close()
        raise RizlineNetworkError(f"Could not open the Rizline socket ({last_error}).")

    def _open(self, engineio: Any, path: str, *, mode: str = "plain") -> None:
        device_id = _require_device_id(self.device_id)
        header_map = _headers(self.email, self.token, device_id)
        client = engineio.Client(handle_sigint=False, ssl_verify=True)
        self._eio = client
        self._messages.clear()
        self._seen.clear()
        self._event.clear()
        self._sio_ready = False
        self._disconnected = False

        @client.on("message")
        def _on_message(data: Any) -> None:
            with self._lock:
                self._messages.append(data)
                self._seen.append(_packet_prefix(data))
            self._event.set()

        url = _handshake_url(self.email, self.token, device_id)
        try:
            client.connect(
                url,
                headers=header_map,
                transports=["websocket"],
                engineio_path=path,
            )
        except Exception as exc:
            message = scrub(str(exc), self.secrets) or type(exc).__name__
            raise RizlineNetworkError(f"Engine.IO connect failed on {path} ({message}).") from None
        if urlsplit_host_mismatch(url):
            raise RizlineNetworkError("Socket host is not the pinned API host.")
        raw_base = str(getattr(client, "base_url", "") or "")
        self._handshake_meta = (
            f"device_len={len(device_id)}; has_device_query="
            f"{('device_id=' in raw_base) or ('deviceId=' in raw_base)}; path={path}"
        )
        # Drain any server-first packets, then join '/'.
        self._wait_message(timeout=0.8)
        self._handshake_socketio(mode=mode)

    def _handshake_socketio(self, *, mode: str = "plain") -> None:
        auth = _session_fields(self.email, self.token, self.device_id)
        # Socket.IO CONNECT payloads (Engine.IO adds the leading 4).
        packet = "0" if mode == "plain" else "0" + json.dumps(auth, separators=(",", ":"))
        self._send_raw(packet)
        message = self._wait_message(timeout=4.0)
        if message is None:
            raise RizlineSocketError(f"Socket.IO CONNECT ({mode}) timed out.")
        text = message if isinstance(message, str) else ""
        if text.startswith("4") and (len(text) == 1 or not text[1].isdigit()):
            raise RizlineSocketError(
                f"Socket.IO CONNECT ({mode}) rejected ({_describe_message(message, self.secrets)})."
            )
        if text.startswith("0") and (len(text) == 1 or text[1] in "{/"):
            self._sio_ready = True
            self._reject_if_kicked(mode=mode)
            return
        raise RizlineSocketError(
            f"Socket.IO CONNECT ({mode}) got unexpected packet ({_describe_message(message, self.secrets)})."
        )

    def _reject_if_kicked(self, *, mode: str = "plain") -> None:
        """Some rejections arrive as EVENT + DISCONNECT immediately after CONNECT."""
        meta = getattr(self, "_handshake_meta", "")
        first = self._wait_message(timeout=0.7)
        if first is None:
            return
        text = first if isinstance(first, str) else ""
        described = _describe_message(first, self.secrets)
        if text.startswith("1") and (len(text) == 1 or not text[1].isdigit()):
            raise RizlineSocketError(
                f"Socket disconnected right after connect mode={mode} ({described}; {meta})."
            )
        parsed = self._parse_response(first, "")
        second = self._wait_message(timeout=0.5)
        if second is not None:
            second_text = second if isinstance(second, str) else ""
            if second_text.startswith("1") and (len(second_text) == 1 or not second_text[1].isdigit()):
                detail = described
                if isinstance(parsed, dict):
                    detail = _describe_message(parsed, self.secrets)
                raise RizlineSocketError(
                    f"Socket disconnected right after connect mode={mode} ({detail}; {meta})."
                )
            with self._lock:
                self._messages.insert(0, second)
            self._event.set()
        # Not a kick — keep the first packet for the caller.
        with self._lock:
            self._messages.insert(0, first)
        self._event.set()

    def _send_raw(self, data: str) -> None:
        if self._eio is None:
            raise RizlineSocketError("Socket is not connected.")
        self._eio.send(data)

    def _wait_message(self, timeout: float) -> Any | None:
        deadline = timeout
        while deadline > 0:
            self._event.clear()
            with self._lock:
                if self._messages:
                    return self._messages.pop(0)
            remaining = min(0.4, deadline)
            if not self._event.wait(remaining):
                deadline -= remaining
                continue
            with self._lock:
                if self._messages:
                    return self._messages.pop(0)
            deadline -= remaining
        return None

    def call(self, transaction: str, timeout: float = 8.0) -> dict:
        body = _payload(transaction, self.email, self.token, self.device_id)
        frames = self._frames(transaction, body)
        last_error = "no response"
        self._last_unmatched = ""
        self._disconnected = False
        for index, frame in enumerate(frames):
            if self._disconnected:
                break
            with self._lock:
                self._messages.clear()
            self._event.clear()
            try:
                self._send_raw(frame)
            except Exception as exc:
                last_error = type(exc).__name__
                continue
            deadline = min(2.0, timeout)
            while deadline > 0:
                if self._disconnected:
                    break
                slice_wait = min(0.4, deadline)
                message = self._wait_message(timeout=slice_wait)
                if message is None:
                    deadline -= slice_wait
                    continue
                parsed = self._parse_response(message, transaction)
                if self._disconnected:
                    last_error = "server disconnect"
                    if not self._last_unmatched:
                        self._last_unmatched = _describe_message(message, self.secrets)
                    break
                if parsed is not None:
                    try:
                        matched = _match_response(transaction, str(body.get("requestId") or ""), parsed)
                    except RizlineSocketError as exc:
                        self._last_unmatched = _describe_message(message, self.secrets)
                        raise RizlineSocketError(
                            f"{exc}; last={self._last_unmatched}"
                        ) from None
                    if matched is not None:
                        return matched
                self._last_unmatched = _describe_message(message, self.secrets)
                last_error = "unmatched response"
            else:
                last_error = "timeout"
                continue
            break
        seen = ",".join(self._seen[-12:]) or "none"
        detail = (
            f"{last_error}; path={self.path}; sio_ready={self._sio_ready}; "
            f"recv={seen}; frames={len(frames)}"
        )
        if self._last_unmatched:
            detail += f"; last={self._last_unmatched}"
        raise RizlineSocketError(f"{transaction} was not acknowledged ({detail}).")

    def _frames(self, transaction: str, body: dict) -> list[str]:
        """Socket.IO packet bodies. send() adds the Engine.IO MESSAGE prefix."""
        encoded = json.dumps(body, separators=(",", ":"))
        # SendRequestToServerWithJson passes the body as a JSON string argument.
        as_string = json.dumps([transaction, encoded], separators=(",", ":"))
        as_object = json.dumps([transaction, body], separators=(",", ":"))
        with_json = json.dumps(
            ["SendRequestToServerWithJson", transaction, encoded],
            separators=(",", ":"),
        )
        send_request = json.dumps(["SendRequestToServer", body], separators=(",", ":"))
        message_payload = json.dumps(["message", body], separators=(",", ":"))
        self._ack_id += 1
        ack = self._ack_id
        return [
            f"2{ack}{as_string}",
            "2" + as_string,
            f"2{ack}{as_object}",
            "2" + as_object,
            "2" + with_json,
            "2" + send_request,
            "2" + message_payload,
        ]

    def _parse_response(self, message: Any, transaction: str) -> dict | None:
        del transaction
        if isinstance(message, dict):
            return message
        if not isinstance(message, str):
            return _event_payload(message)
        text = message.strip()
        if not text:
            return None
        packet_type = text[0]
        body = _socketio_body(text)
        # CONNECT
        if packet_type == "0":
            self._sio_ready = True
            return None
        # DISCONNECT
        if packet_type == "1" and (len(text) == 1 or not text[1].isdigit()):
            self._disconnected = True
            self._last_unmatched = _describe_message(message, self.secrets)
            return None
        # CONNECT_ERROR
        if packet_type == "4" and (len(text) == 1 or not text[1].isdigit()):
            self._last_unmatched = _describe_message(message, self.secrets)
            return None
        # ACK / EVENT / BINARY_EVENT-ish JSON payloads
        if packet_type in {"2", "3", "5", "6"}:
            if not body:
                return None
            try:
                decoded = json.loads(body)
            except json.JSONDecodeError:
                return _event_payload(body)
            return _event_payload(decoded)
        return _event_payload(text)

    def close(self) -> None:
        client = self._eio
        self._eio = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            pass


def _with_session(email: str, token: str, device_id: str) -> _EngineSession:
    session = _EngineSession(email, token, device_id)
    session.connect()
    return session


def call_transaction(
    email: str,
    token: str,
    device_id: str,
    transaction: str,
    *,
    timeout: float = 8.0,
) -> dict:
    session = _with_session(email, token, device_id)
    try:
        return session.call(transaction, timeout=timeout)
    finally:
        session.close()


def fetch_weekly_rank_info(email: str, token: str, device_id: str) -> dict:
    session = _with_session(email, token, device_id)
    try:
        for transaction in RANK_PREP:
            try:
                session.call(transaction, timeout=2.0)
            except RizlineError:
                if session._disconnected:
                    raise
                continue
        if session._disconnected:
            raise RizlineSocketError("Socket disconnected during weekly rank prep.")
        return session.call(RANK_TRANSACTION, timeout=8.0)
    finally:
        session.close()


def fetch_weekly_tasks(email: str, token: str, device_id: str) -> dict:
    return call_transaction(email, token, device_id, TASKS_TRANSACTION)


def fetch_own_rizcard(email: str, token: str, device_id: str) -> dict:
    from rizline.payload import has_card_art

    session = _with_session(email, token, device_id)
    errors: list[str] = []
    try:
        for transaction in RIZCARD_TRANSACTIONS:
            try:
                payload = session.call(transaction, timeout=8.0)
            except RizlineError as exc:
                errors.append(f"{transaction}: {type(exc).__name__}")
                continue
            if has_card_art(payload):
                return payload
            errors.append(f"{transaction}: no card art")
        raise RizlineSocketError("Own Rizcard socket calls failed (" + "; ".join(errors) + ").")
    finally:
        session.close()


def _key_names(value: Any, path: str = "$", depth: int = 0) -> list[str]:
    if depth > 3 or not isinstance(value, dict):
        return []
    found: list[str] = []
    secret = ("email", "token", "password", "device", "userid", "user_id")
    for raw_key, child in value.items():
        key = str(raw_key)
        if any(part in key.lower() for part in secret):
            continue
        child_path = f"{path}.{key}"
        found.append(child_path)
        if len(found) >= 60:
            return found
        found.extend(_key_names(child, child_path, depth + 1))
    return found[:60]


def probe_transactions(email: str, token: str, device_id: str) -> list[str]:
    names = (*RANK_PREP, RANK_TRANSACTION, TASKS_TRANSACTION, *RIZCARD_TRANSACTIONS)
    lines: list[str] = []
    session = None
    try:
        session = _with_session(email, token, device_id)
        lines.append(
            f"connected path={session.path} transport=websocket sio_ready={session._sio_ready}"
        )
    except RizlineError as exc:
        return [f"connect: {exc}"]
    try:
        for transaction in names:
            try:
                payload = session.call(transaction, timeout=8.0)
            except RizlineError as exc:
                lines.append(f"{transaction}: {exc}")
                continue
            lines.append(f"{transaction}: keys=" + ", ".join(_key_names(payload)))
    finally:
        if session is not None:
            session.close()
    return lines
