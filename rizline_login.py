#!/usr/bin/env python3
"""Fetch a Rizline global-server save using passcode or email verification."""

import argparse
import base64
import binascii
import json
import os
import re
import sys
import uuid
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    from Crypto.Cipher import AES
except ImportError:
    print(
        "Missing dependency: PyCryptodome. Install it with "
        "`py -m pip install -r requirements.txt`.",
        file=sys.stderr,
    )
    raise SystemExit(1)


DEFAULT_BASE_URL = "https://service.rhyths.net"
TIMEOUT_SECONDS = 20
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


def redact(value):
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key.lower() in SENSITIVE_FIELDS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "<redacted-email>",
            value,
        )
    return value


def debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}", file=sys.stderr)


def masked_input(prompt: str) -> str:
    print(prompt, end="", flush=True)
    characters = []

    if os.name == "nt":
        import msvcrt

        while True:
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                print()
                return "".join(characters)
            if char == "\003":
                raise KeyboardInterrupt
            if char == "\b":
                if characters:
                    characters.pop()
                    print("\b \b", end="", flush=True)
                continue
            if char in ("\000", "\xe0"):
                msvcrt.getwch()
                continue
            characters.append(char)
            print("*", end="", flush=True)

    import termios
    import tty

    if not sys.stdin.isatty():
        raise RuntimeError("Masked input requires an interactive terminal.")
    file_descriptor = sys.stdin.fileno()
    original_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        while True:
            char = sys.stdin.read(1)
            if char in ("\r", "\n"):
                print()
                return "".join(characters)
            if char in ("\x03", "\x04"):
                raise KeyboardInterrupt
            if char in ("\x7f", "\b"):
                if characters:
                    characters.pop()
                    print("\b \b", end="", flush=True)
                continue
            characters.append(char)
            print("*", end="", flush=True)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)


def response_message(body: bytes) -> str:
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if isinstance(result, dict):
        message = result.get("msg") or result.get("message") or result.get("error")
        if isinstance(message, str):
            return message
    return ""


def api_request(
    base_url: str,
    path: str,
    payload: dict,
    headers: dict[str, str],
    debug: bool,
    log_json_response: bool = True,
    log_binary_prefix: bool = False,
) -> tuple[bytes, Message]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request_headers = {
        "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
        "game_id": "pigeongames.rizline",
        "channel_id": "11",
        "i18n": "en-US",
        "device_id": headers["device_id"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    request_headers.update(
        {key: value for key, value in headers.items() if key != "device_id"}
    )
    debug_log(
        debug,
        f"POST {url}; JSON fields: "
        f"{json.dumps(redact(payload), ensure_ascii=False)}",
    )
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read()
            response_headers = response.headers
    except HTTPError as exc:
        status = exc.code
        body = exc.read()
        response_headers = exc.headers
    except URLError as exc:
        debug_log(debug, f"Transport error: {exc.reason}")
        raise ConnectionError(
            f"Could not contact the global server: {exc.reason}"
        ) from None
    except TimeoutError:
        debug_log(debug, f"Request timed out after {TIMEOUT_SECONDS} seconds")
        raise ConnectionError("The request timed out.") from None

    debug_log(
        debug,
        f"HTTP {status}; response bytes={len(body)}; "
        f"content-type={response_headers.get('Content-Type', 'unknown')}",
    )
    if debug and log_binary_prefix:
        debug_log(debug, f"Response first 32 bytes (hex): {body[:32].hex()}")
    if log_json_response:
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = None
        if parsed is not None:
            debug_log(
                debug,
                "Response JSON: " + json.dumps(redact(parsed), ensure_ascii=False),
            )

    if status >= 400:
        detail = response_message(body)
        message = f"HTTP {status}" + (f": {detail}" if detail else "")
        if status >= 500:
            raise ConnectionError(message)
        raise RuntimeError(message)
    return body, response_headers


def decrypt_save(body: bytes):
    try:
        text = body.decode("utf-8").strip()
    except UnicodeDecodeError:
        text = ""

    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    candidates = [body]
    encoded = b"".join(body.split())
    try:
        base64_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        base64_data = None
    if base64_data:
        candidates.append(base64_data)

    for ciphertext in candidates:
        for key in dict.fromkeys((AES_KEY, CN_AES_KEY)):
            if len(ciphertext) >= 12 + 16:
                try:
                    nonce, encrypted_and_tag = ciphertext[:12], ciphertext[12:]
                    plaintext = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(
                        encrypted_and_tag[:-16], encrypted_and_tag[-16:]
                    )
                    return json.loads(plaintext.decode("utf-8"))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    pass

        if ciphertext and len(ciphertext) % AES.block_size == 0:
            try:
                plaintext = AES.new(key=AES_KEY, mode=AES.MODE_CBC, iv=AES_IV).decrypt(
                    ciphertext
                )
                padding_length = plaintext[-1]
                if not 1 <= padding_length <= AES.block_size:
                    continue
                if plaintext[-padding_length:] != bytes([padding_length]) * padding_length:
                    continue
                return json.loads(plaintext[:-padding_length].decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass

    raise RuntimeError(
        "Save response was received, but none of the known AES formats produced "
        "valid JSON."
    )


def default_save_path(username: object) -> Path:
    player_name = username.strip() if isinstance(username, str) else ""
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", player_name).rstrip(" .")
    if not safe_name:
        safe_name = "player"
    if safe_name.upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }:
        safe_name = f"_{safe_name}"
    return Path(f"{safe_name}_gameData.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and decrypt your Rizline global-server player save."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"global server base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="path for the decrypted save JSON (default: <player name>_gameData.json)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print request diagnostics; credentials and player data are redacted",
    )
    args = parser.parse_args()

    parsed_url = urlsplit(args.base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        parser.error("--base-url must be an HTTPS URL")

    email = input("Account email: ").strip()
    if not email:
        parser.error("account email cannot be empty")

    device_id = str(uuid.uuid4())
    public_headers = {"device_id": device_id}
    token = None
    try:
        passcode = masked_input("Passcode (press Enter to use verification code): ")
        if passcode:
            login_body, login_headers = api_request(
                args.base_url,
                "account/login",
                {"email": email, "password": passcode},
                public_headers,
                args.debug,
            )
            token = (
                login_headers.get("set_token")
                or login_headers.get("set-token")
                or login_headers.get("token")
            )
            if not token:
                reason = response_message(login_body) or "The server did not return a session token."
                raise RuntimeError(reason)
    except RuntimeError as exc:
        print(f"Passcode login failed: {exc}", file=sys.stderr)
        print("Falling back to email verification code.")
    except (ConnectionError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nLogin cancelled.", file=sys.stderr)
        else:
            print(f"Login request failed: {exc}", file=sys.stderr)
        return 1

    if not token:
        try:
            api_request(
                args.base_url,
                "account/send_email",
                {"email": email, "transaction": "login"},
                public_headers,
                args.debug,
            )
            code = masked_input("Email verification code: ").strip()
            if not code:
                print("Verification code cannot be empty.", file=sys.stderr)
                return 1
            login_body, login_headers = api_request(
                args.base_url,
                "account/login",
                {"email": email, "code": code},
                public_headers,
                args.debug,
            )
            token = (
                login_headers.get("set_token")
                or login_headers.get("set-token")
                or login_headers.get("token")
            )
            if not token:
                reason = response_message(login_body) or "The server did not return a session token."
                raise RuntimeError(reason)
        except (RuntimeError, ConnectionError) as exc:
            print(f"Verification-code login failed: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nLogin cancelled.", file=sys.stderr)
            return 1

    debug_log(args.debug, "Login response included a session token (value hidden).")

    authenticated_headers = {
        "device_id": device_id,
        "email": email,
        "token": token,
    }
    try:
        encrypted_save, _ = api_request(
            args.base_url,
            "game/rn_login",
            {},
            authenticated_headers,
            args.debug,
            log_json_response=False,
            log_binary_prefix=True,
        )
        save = decrypt_save(encrypted_save)
        if not isinstance(save, dict):
            raise RuntimeError("Decrypted player save was not a JSON object.")
        save["_id"] = ""
        save["userId"] = ""
        save["mailSyncId"] = ""
        output_path = args.output or default_save_path(save.get("username"))
        output_path.write_text(
            json.dumps(save, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (RuntimeError, OSError) as exc:
        print(f"Could not fetch or save player data: {exc}", file=sys.stderr)
        return 1

    username = save.get("username")
    print(f"Player data fetched{': ' + username if isinstance(username, str) else ''}.")
    print(f"Saved decrypted player data to {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
