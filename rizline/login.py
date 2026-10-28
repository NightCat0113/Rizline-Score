#!/usr/bin/env python3
"""Fetch a Rizline global-server save using passcode or email verification."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from rizline.client import (
    DEFAULT_BASE_URL,
    RizlineAPIError,
    RizlineError,
    RizlineNetworkError,
    fetch_save,
    login_with_code,
    login_with_passcode,
    request_email_code,
    scrub,
)


def masked_input(prompt: str) -> str:
    print(prompt, end="", flush=True)
    characters: list[str] = []

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
    token = None
    try:
        passcode = masked_input("Passcode (press Enter to use verification code): ")
        if passcode:
            try:
                result = login_with_passcode(
                    email,
                    passcode,
                    base_url=args.base_url,
                    device_id=device_id,
                    debug=args.debug,
                )
                token = result.token
                device_id = result.device_id
            except RizlineAPIError as exc:
                print(f"Passcode login failed: {scrub(str(exc), (email, passcode))}", file=sys.stderr)
                print("Falling back to email verification code.")
            finally:
                passcode = ""
    except (RizlineNetworkError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nLogin cancelled.", file=sys.stderr)
        else:
            print(f"Login request failed: {scrub(str(exc), (email,))}", file=sys.stderr)
        return 1

    if not token:
        code = ""
        try:
            device_id = request_email_code(
                email,
                base_url=args.base_url,
                device_id=device_id,
                debug=args.debug,
            )
            code = masked_input("Email verification code: ").strip()
            if not code:
                print("Verification code cannot be empty.", file=sys.stderr)
                return 1
            result = login_with_code(
                email,
                code,
                base_url=args.base_url,
                device_id=device_id,
                debug=args.debug,
            )
            token = result.token
            device_id = result.device_id
        except (RizlineAPIError, RizlineNetworkError) as exc:
            print(
                f"Verification-code login failed: {scrub(str(exc), (email, code))}",
                file=sys.stderr,
            )
            return 1
        except KeyboardInterrupt:
            print("\nLogin cancelled.", file=sys.stderr)
            return 1
        finally:
            code = ""

    if args.debug:
        print("[debug] Login response included a session token (value hidden).", file=sys.stderr)

    try:
        save = fetch_save(
            email,
            token,
            device_id,
            base_url=args.base_url,
            debug=args.debug,
        )
        save["_id"] = ""
        save["userId"] = ""
        save["mailSyncId"] = ""
        output_path = args.output or default_save_path(save.get("username"))
        output_path.write_text(
            json.dumps(save, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (RizlineError, OSError) as exc:
        print(f"Could not fetch or save player data: {scrub(str(exc), (email, token))}", file=sys.stderr)
        return 1

    username = save.get("username")
    print(f"Player data fetched{': ' + username if isinstance(username, str) else ''}.")
    print(f"Saved decrypted player data to {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
