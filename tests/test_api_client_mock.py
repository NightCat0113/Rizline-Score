import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rizline.client import (
    AES_KEY,
    RizlineAPIError,
    RizlineDataError,
    RizlineError,
    RizlineNetworkError,
    api_request,
    decrypt_save,
    login_with_passcode,
)


def _server():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if self.path == "/account/login":
                mode = getattr(self.server, "mode", "redirect")
                if mode == "redirect":
                    self.send_response(302)
                    host, port = self.server.server_address[:2]
                    self.send_header("Location", f"http://{host}:{port}/evil")
                    self.end_headers()
                    return
                if mode == "token":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("set_token", "fake-session-token")
                    self.end_headers()
                    self.wfile.write(b'{"msg":"ok"}')
                    return
                if mode == "garbage":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"this is not json {{{")
                    return
                if mode == "oversized":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok":true,' + b"x" * 200 + b"}")
                    return
            if self.path == "/evil":
                self.server.evil_hit = True
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.evil_hit = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _base(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def test_redirect_is_not_followed():
    server = _server()
    try:
        server.mode = "redirect"
        with pytest.raises(RizlineNetworkError, match="redirect"):
            api_request(
                _base(server),
                "account/login",
                {"email": "person@example.com", "password": "s3cret-pass"},
                {"device_id": "device-id-value"},
                allow_http_localhost=True,
                secrets=("s3cret-pass", "person@example.com"),
            )
        assert server.evil_hit is False
    finally:
        server.shutdown()


def test_login_reads_token_header_only():
    server = _server()
    try:
        server.mode = "token"
        result = login_with_passcode(
            "person@example.com",
            "s3cret-pass",
            base_url=_base(server),
            device_id="device-id-value",
            allow_http_localhost=True,
        )
        assert result.token == "fake-session-token"
        assert "fake-session-token" not in repr(result)
    finally:
        server.shutdown()


def test_malformed_json_does_not_echo_secret():
    server = _server()
    try:
        server.mode = "garbage"
        with pytest.raises(RizlineAPIError) as caught:
            login_with_passcode(
                "person@example.com",
                "s3cret-pass",
                base_url=_base(server),
                device_id="device-id-value",
                allow_http_localhost=True,
            )
        assert "s3cret-pass" not in str(caught.value)
    finally:
        server.shutdown()


def test_oversized_response_is_rejected():
    server = _server()
    try:
        server.mode = "oversized"
        with pytest.raises(RizlineNetworkError, match="size"):
            api_request(
                _base(server),
                "account/login",
                {"email": "a@b.co", "password": "s3cret-pass"},
                {"device_id": "device-id-value"},
                allow_http_localhost=True,
                max_bytes=32,
            )
    finally:
        server.shutdown()


def test_non_json_save_is_rejected():
    with pytest.raises(RizlineDataError):
        decrypt_save(b"not-a-save")


def test_gcm_round_trip():
    from Crypto.Cipher import AES

    payload = {"username": "Player", "myBest": [], "levelsRks": []}
    nonce = b"0123456789ab"
    cipher = AES.new(AES_KEY, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(json.dumps(payload).encode())
    decoded = decrypt_save(nonce + ciphertext + tag)
    assert decoded["username"] == "Player"


def test_pinned_host_rejects_other_https_origin():
    with pytest.raises(RizlineError):
        api_request(
            "https://example.invalid",
            "account/login",
            {},
            {"device_id": "device-id-value"},
            require_pinned_host=True,
        )


def test_tls_verification_is_not_disabled():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    needles = ("verify=" + "False", "CERT_" + "NONE", "_create_unverified_" + "context")
    for path in root.rglob("*.py"):
        if any(part in {".venv", "venv", "site-packages"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text


def test_bot_does_not_opt_into_localhost_or_save_dumps():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    api = (root / "bot" / "services" / "rizline_api.py").read_text(encoding="utf-8")
    assert "require_pinned_host" in api
    for path in (root / "bot").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "allow_http_localhost" not in text
        if "gameData" not in text:
            continue
        # Optional local dump reads for card enrichment are limited to profile.py.
        # The Discord bot must not write decrypted save dumps.
        assert path.name == "profile.py"
        assert "write_text" not in text
        assert "json.dump" not in text
        assert ".write(" not in text
