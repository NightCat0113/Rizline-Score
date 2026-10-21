"""Rizline global-server client.

The bot and the CLI both use this module. The API host for the bot is pinned.
Redirects are refused. Environment proxies are ignored. TLS verification stays on.
"""

from __future__ import annotations

import json
import re
import ssl
import uuid
from dataclasses import dataclass
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None  # type: ignore[assignment]


DEFAULT_BASE_URL = "https://service.rhyths.net"
PINNED_HOST = "service.rhyths.net"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 8_000_000
AES_KEY = bytes.fromhex("537640482c2b53562d552a56456a43572c6e3757412d406e7d6a333b553b5846")
AES_IV = bytes.fromhex("31255b4f422e3c5953773f296f3a7251")
CN_AES_KEY = bytes.fromhex("5866617b714f2e397354477076346963533a405d5848456a727a5567715d7c51")
SENSITIVE_FIELDS = {
    "email",
    "phone",
    "password",
    "code",
    "device_id",
    "key",
    "token",
    "set_token",
    "authorization",
}
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class RizlineError(Exception):
    """Base error. Messages are scrubbed before they are raised."""


class RizlineNetworkError(RizlineError):
    pass


class RizlineAPIError(RizlineError):
    pass


class RizlineDataError(RizlineError):
    pass


def _require_crypto() -> None:
    if AES is None:
        raise SystemExit(
            "Missing dependency: PyCryptodome. Install it with "
            "`py -m pip install -r requirements.txt`."
        )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if str(key).lower() in SENSITIVE_FIELDS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _EMAIL_RE.sub("<redacted-email>", value)
    return value


def scrub(text: str, secrets: tuple[str, ...] = ()) -> str:
    cleaned = _EMAIL_RE.sub("<redacted-email>", text)
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "<redacted>")
    return cleaned


def debug_log(enabled: bool, message: str, secrets: tuple[str, ...] = ()) -> None:
    if not enabled:
        return
    import sys

    print(f"[debug] {scrub(message, secrets)}", file=sys.stderr)


def _validate_base_url(
    base_url: str,
    *,
    require_pinned_host: bool,
    allow_http_localhost: bool,
) -> str:
    parts = urlsplit(base_url.strip())
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        raise RizlineError("URL userinfo is not allowed")
    if parts.query or parts.fragment:
        raise RizlineError("base URL must not include a query or fragment")
    if allow_http_localhost:
        if parts.scheme != "http" or host not in {"127.0.0.1", "localhost"}:
            raise RizlineError("Test mode only allows http://127.0.0.1")
        return base_url.rstrip("/")
    if parts.scheme != "https" or not host:
        raise RizlineError("base URL must be an https URL")
    if require_pinned_host and (host != PINNED_HOST or parts.port not in (None, 443)):
        raise RizlineError("host is not the pinned API host")
    return base_url.rstrip("/")


def _redirect_handler_class():
    from urllib.request import HTTPRedirectHandler

    class _Handler(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            raise RizlineNetworkError(f"Refusing HTTP {code} redirect")

    return _Handler


RejectRedirects = _redirect_handler_class()


def _opener(ssl_context: ssl.SSLContext | None):
    context = ssl_context or ssl.create_default_context()
    return build_opener(
        ProxyHandler({}),
        RejectRedirects(),
        HTTPSHandler(context=context),
    )


def _read_limited(response: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = response.read(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > max_bytes:
        raise RizlineNetworkError("Response exceeded the size limit")
    return body


def _server_message(body: bytes) -> str:
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if isinstance(result, dict):
        message = result.get("msg") or result.get("message") or result.get("error")
        if isinstance(message, str):
            return message[:200]
    return ""


def _token_from_headers(headers: Message) -> str:
    for key in ("set_token", "set-token", "token"):
        value = headers.get(key)
        if isinstance(value, str) and value.strip():
            token = value.strip()
            if len(token) > 4096:
                raise RizlineAPIError("The server did not return a usable session token.")
            return token
    return ""


def api_request(
    base_url: str,
    path: str,
    payload: dict,
    headers: dict[str, str],
    *,
    debug: bool = False,
    log_json_response: bool = False,
    secrets: tuple[str, ...] = (),
    require_pinned_host: bool = False,
    allow_http_localhost: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
    timeout: int = TIMEOUT_SECONDS,
) -> tuple[bytes, Message]:
    if any(char in path for char in "\r\n "):
        raise RizlineError("Invalid request path")
    root = _validate_base_url(
        base_url,
        require_pinned_host=require_pinned_host,
        allow_http_localhost=allow_http_localhost,
    )
    url = f"{root}/{path.lstrip('/')}"
    request_headers = {
        "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
        "game_id": "pigeongames.rizline",
        "channel_id": "11",
        "i18n": "en-US",
        "device_id": headers["device_id"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    request_headers.update({key: value for key, value in headers.items() if key != "device_id"})
    encoded = json.dumps(redact(payload), ensure_ascii=False)
    if len(encoded) > 500:
        encoded = encoded[:500] + "...<truncated>"
    debug_log(debug, f"POST {url}; JSON fields: {encoded}", secrets)
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with _opener(ssl_context).open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            body = _read_limited(response, max_bytes)
            response_headers = response.headers
    except RizlineError:
        raise
    except HTTPError as exc:
        status = exc.code
        try:
            body = _read_limited(exc, max_bytes)
        except RizlineError:
            raise
        response_headers = exc.headers
    except URLError as exc:
        if isinstance(exc.reason, RizlineError):
            raise exc.reason from None
        debug_log(debug, f"Transport error: {scrub(str(exc.reason), secrets)}", secrets)
        raise RizlineNetworkError("Could not contact the Rizline server.") from None
    except TimeoutError:
        raise RizlineNetworkError("The request timed out.") from None

    debug_log(
        debug,
        f"HTTP {status}; response bytes={len(body)}; "
        f"content-type={response_headers.get('Content-Type', 'unknown')}",
        secrets,
    )
    if log_json_response:
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = None
        if parsed is not None:
            debug_log(debug, "Response JSON: " + encoded_preview(parsed), secrets)

    if status >= 400:
        detail = scrub(_server_message(body), secrets)
        message = f"HTTP {status}" + (f": {detail}" if detail else "")
        if status >= 500:
            raise RizlineNetworkError(message)
        raise RizlineAPIError(message)
    return body, response_headers


def encoded_preview(parsed: Any) -> str:
    text = json.dumps(redact(parsed), ensure_ascii=False)
    if len(text) > 500:
        return text[:500] + "...<truncated>"
    return text


def decrypt_save(body: bytes) -> dict:
    _require_crypto()
    try:
        text = body.decode("utf-8").strip()
    except UnicodeDecodeError:
        text = ""

    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    candidates = [body]
    import base64
    import binascii

    encoded = b"".join(body.split())
    try:
        base64_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        base64_data = None
    if base64_data:
        candidates.append(base64_data)

    for ciphertext in candidates:
        for key in (AES_KEY, CN_AES_KEY):
            if len(ciphertext) >= 12 + 16:
                try:
                    nonce, encrypted_and_tag = ciphertext[:12], ciphertext[12:]
                    plaintext = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(
                        encrypted_and_tag[:-16], encrypted_and_tag[-16:]
                    )
                    parsed = json.loads(plaintext.decode("utf-8"))
                    if isinstance(parsed, dict):
                        return parsed
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    pass
        if ciphertext and len(ciphertext) % AES.block_size == 0:
            try:
                plaintext = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV).decrypt(ciphertext)
                padding_length = plaintext[-1]
                if not 1 <= padding_length <= AES.block_size:
                    continue
                if plaintext[-padding_length:] != bytes([padding_length]) * padding_length:
                    continue
                parsed = json.loads(plaintext[:-padding_length].decode("utf-8"))
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass

    raise RizlineDataError(
        "Save response was received, but none of the known AES formats produced valid JSON."
    )


def derive_minimal_cache(save: dict) -> dict:
    if not isinstance(save, dict):
        raise RizlineDataError("Decrypted player save was not a JSON object.")

    def as_int(value: Any) -> int:
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return 0

    def as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    bests = []
    for item in save.get("myBest") or []:
        if not isinstance(item, dict):
            continue
        bests.append(
            {
                "trackAssetId": str(item.get("trackAssetId") or ""),
                "difficultyClassName": str(item.get("difficultyClassName") or ""),
                "score": as_int(item.get("score") or 0),
                "completeRate": as_float(item.get("completeRate") or 0),
                "isFullCombo": bool(item.get("isFullCombo")),
                "isClear": bool(item.get("isClear")),
            }
        )
    levels = []
    for item in save.get("levelsRks") or []:
        if not isinstance(item, dict):
            continue
        levels.append(
            {
                "trackId": str(item.get("trackId") or ""),
                "difficultyClassName": str(item.get("difficultyClassName") or ""),
                "rks": as_float(item.get("rks") or 0),
            }
        )
    username = save.get("username")
    try:
        total = as_float(save.get("totalRks") or 0)
    except (TypeError, ValueError):
        total = 0.0
    card = save.get("rizcard") if isinstance(save.get("rizcard"), dict) else {}

    def card_text(*names: str) -> str:
        for source in (card, save):
            for name in names:
                value = source.get(name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    pos_raw = card.get("avatarPos") if isinstance(card.get("avatarPos"), dict) else save.get("avatarPos")
    pos = pos_raw if isinstance(pos_raw, dict) else {}

    def pos_num(name: str, default: float) -> float:
        try:
            return float(pos.get(name))
        except (TypeError, ValueError):
            return default

    return {
        "v": 1,
        "username": username if isinstance(username, str) else "",
        "totalRks": total,
        "myBest": bests,
        "levelsRks": levels,
        "avatarId": card_text("avatarId"),
        "avatarPos": {"x": pos_num("x", 0.0), "y": pos_num("y", 0.0), "z": pos_num("z", 1.0)},
        "bioId1": card_text("bioId1"),
        "bioId2": card_text("bioId2"),
        "backgroundId": card_text("backgroundId"),
    }


@dataclass
class LoginResult:
    token: str
    device_id: str

    def __repr__(self) -> str:
        return "LoginResult(token='<redacted>', device_id='<redacted>')"


def _request_kwargs(kwargs: dict) -> dict:
    return {
        "debug": kwargs.get("debug", False),
        "secrets": kwargs.get("secrets", ()),
        "require_pinned_host": kwargs.get("require_pinned_host", False),
        "allow_http_localhost": kwargs.get("allow_http_localhost", False),
        "ssl_context": kwargs.get("ssl_context"),
        "max_bytes": kwargs.get("max_bytes", MAX_RESPONSE_BYTES),
    }


def login_with_passcode(
    email: str,
    passcode: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    device_id: str | None = None,
    **kwargs: Any,
) -> LoginResult:
    device = device_id or str(uuid.uuid4())
    secrets = tuple(dict.fromkeys((*kwargs.get("secrets", ()), email, passcode)))
    body, headers = api_request(
        base_url,
        "account/login",
        {"email": email, "password": passcode},
        {"device_id": device},
        log_json_response=True,
        **{**_request_kwargs(kwargs), "secrets": secrets},
    )
    token = _token_from_headers(headers)
    if not token:
        reason = scrub(_server_message(body), secrets) or "The server did not return a session token."
        raise RizlineAPIError(reason)
    return LoginResult(token=token, device_id=device)


def request_email_code(
    email: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    device_id: str | None = None,
    **kwargs: Any,
) -> str:
    device = device_id or str(uuid.uuid4())
    secrets = tuple(dict.fromkeys((*kwargs.get("secrets", ()), email)))
    api_request(
        base_url,
        "account/send_email",
        {"email": email, "transaction": "login"},
        {"device_id": device},
        log_json_response=True,
        **{**_request_kwargs(kwargs), "secrets": secrets},
    )
    return device


def login_with_code(
    email: str,
    code: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    device_id: str | None = None,
    **kwargs: Any,
) -> LoginResult:
    device = device_id or str(uuid.uuid4())
    secrets = tuple(dict.fromkeys((*kwargs.get("secrets", ()), email, code)))
    body, headers = api_request(
        base_url,
        "account/login",
        {"email": email, "code": code},
        {"device_id": device},
        log_json_response=True,
        **{**_request_kwargs(kwargs), "secrets": secrets},
    )
    token = _token_from_headers(headers)
    if not token:
        reason = scrub(_server_message(body), secrets) or "The server did not return a session token."
        raise RizlineAPIError(reason)
    return LoginResult(token=token, device_id=device)


def fetch_save(
    email: str,
    token: str,
    device_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    **kwargs: Any,
) -> dict:
    secrets = tuple(dict.fromkeys((*kwargs.get("secrets", ()), email, token)))
    body, _headers = api_request(
        base_url,
        "game/rn_login",
        {},
        {"device_id": device_id, "email": email, "token": token},
        log_json_response=False,
        **{**_request_kwargs(kwargs), "secrets": secrets},
    )
    return decrypt_save(body)


def fetch_minimal_cache(
    email: str,
    token: str,
    device_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    **kwargs: Any,
) -> dict:
    save = fetch_save(email, token, device_id, base_url=base_url, **kwargs)
    try:
        return derive_minimal_cache(save)
    finally:
        save.clear()
