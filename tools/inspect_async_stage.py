"""Inspect Async Battle-related fields in a live Rizline save without saving it."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rizline.client import (  # noqa: E402
    DEFAULT_BASE_URL,
    RizlineAPIError,
    RizlineDataError,
    RizlineError,
    RizlineNetworkError,
    api_request,
    decrypt_save,
    fetch_save,
    login_with_code,
    login_with_passcode,
    request_email_code,
)


KEY_HINT = re.compile(r"async|battle|challenge|tier|rank|stage|season|league|division|grade", re.I)
VALUE_HINT = re.compile(r"rank|tier|stage|season|league|division|grade|progress", re.I)
SECRET_HINT = re.compile(r"email|phone|password|token|device|user.?id|account|mail", re.I)
STAGE_VALUES = {"do", "re", "mi", "fa", "sol", "la", "ti", "dol"}
ASYNC_STATS_HINT = re.compile(r"async|battle|challenge|rank|match|win|streak|engage", re.I)
TUTORIAL_STATS = ("$.challenge:", "$.challengeProgress:")
CANDIDATE_PATHS = (
    "game/challenge",
    "game/weekly",
    "game/weekly_challenge",
    "game/challenge_weekly",
    "game/rn_challenge",
    "game/rn_weekly",
    "game/asyncombat",
    "game/challenge/weekly",
)


def safe_challenge_data(value: object) -> object:
    """Keep challenge values while excluding account/session identifiers."""
    if isinstance(value, dict):
        return {
            str(key): safe_challenge_data(child)
            for key, child in value.items()
            if not SECRET_HINT.search(str(key))
        }
    if isinstance(value, list):
        return [safe_challenge_data(child) for child in value]
    return value


def inspect_async_stats(value: object, path: str = "$") -> list[str]:
    """Print only fields whose names identify Async Battle or its requested stats."""
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if SECRET_HINT.search(key):
                continue
            child_path = f"{path}.{key}"
            if ASYNC_STATS_HINT.search(key):
                safe = safe_challenge_data(child)
                encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
                if len(encoded) > 1600:
                    encoded = encoded[:1600] + "…<truncated>"
                found.append(f"{child_path}: {encoded}")
            found.extend(inspect_async_stats(child, child_path))
    elif isinstance(value, list):
        for number, child in enumerate(value[:100]):
            found.extend(inspect_async_stats(child, f"{path}[{number}]"))
    return found


def inspect(value: object, path: str = "$", async_context: bool = False) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if SECRET_HINT.search(key):
                continue
            hinted = bool(KEY_HINT.search(key))
            context = async_context or bool(re.search(r"async|battle|challenge", key, re.I))
            child_path = f"{path}.{key}"
            if hinted:
                if isinstance(child, dict):
                    keys = (str(k) for k in child if not SECRET_HINT.search(str(k)))
                    found.append(f"{child_path}: object keys={', '.join(keys)}")
                elif isinstance(child, list):
                    found.append(f"{child_path}: list length={len(child)}")
                else:
                    found.append(f"{child_path}: {child!r}")
            elif context and VALUE_HINT.search(key) and not isinstance(child, (dict, list)):
                found.append(f"{child_path}: {child!r}")
            found.extend(inspect(child, child_path, context))
    elif isinstance(value, list):
        for number, child in enumerate(value):
            found.extend(inspect(child, f"{path}[{number}]", async_context))
    elif async_context and isinstance(value, str) and value.casefold() in STAGE_VALUES:
        found.append(f"{path}: {value!r}")
    return found


def meaningful_async_stats(stats: list[str]) -> list[str]:
    """Drop tutorial challenge rows. Those are not Asyncombat rank or match stats."""
    return [line for line in stats if not line.startswith(TUTORIAL_STATS)]


def key_names(value: object, path: str = "$", depth: int = 0) -> list[str]:
    """List JSON key paths only. Values and secret-looking keys are omitted."""
    if depth > 3:
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if SECRET_HINT.search(key):
                continue
            child_path = f"{path}.{key}"
            found.append(child_path)
            if len(found) >= 80:
                return found
            found.extend(key_names(child, child_path, depth + 1))
            if len(found) >= 80:
                return found[:80]
    elif isinstance(value, list) and value:
        found.extend(key_names(value[0], f"{path}[0]", depth + 1))
    return found[:80]


def summarize_body(body: bytes) -> str:
    """Describe a probe response by status shape and key names, never by secrets."""
    parsed: object | None = None
    text = ""
    try:
        text = body.decode("utf-8").strip()
    except UnicodeDecodeError:
        text = ""
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    if parsed is None:
        try:
            parsed = decrypt_save(body)
        except (RizlineDataError, RizlineError):
            return f"HTTP 200, {len(body)} bytes, not a known JSON save"
    names = key_names(parsed)
    if not names:
        return "HTTP 200, no non-secret keys"
    stats = meaningful_async_stats(inspect_async_stats(parsed))
    summary = "HTTP 200, keys=" + ", ".join(names)
    if stats:
        summary += "\n" + "\n".join(stats[:40])
    return summary


def probe_async_endpoints(email: str, token: str, device_id: str) -> None:
    """POST empty bodies to name-hinted paths. Print status and key names only."""
    print("No Asyncombat rank or match fields were in the player save.")
    print("Probing name-hinted read-only paths on the pinned host…")
    secrets = (email, token)
    for path in CANDIDATE_PATHS:
        try:
            body, _headers = api_request(
                DEFAULT_BASE_URL,
                path,
                {},
                {"device_id": device_id, "email": email, "token": token},
                log_json_response=False,
                require_pinned_host=True,
                secrets=secrets,
            )
        except (RizlineAPIError, RizlineNetworkError) as exc:
            print(f"{path}: {exc}")
            continue
        print(f"{path}: {summarize_body(body)}")


def report_save(save: dict) -> list[str]:
    """Print challenge data and Async Battle field hits. Return non-tutorial hits."""
    challenge_data = {
        key: safe_challenge_data(save[key])
        for key in ("challenge", "challengeProgress")
        if key in save
    }
    if challenge_data:
        print("Challenge data (sensitive-looking keys removed):")
        print(json.dumps(challenge_data, ensure_ascii=False, indent=2))
    stats = inspect_async_stats(save)
    extra = meaningful_async_stats(stats)
    if extra:
        print("Async Battle/rank/match-related save fields:")
        print("\n".join(extra[:100]))
    else:
        print("No Async Battle, rank, match, win, or streak fields were found by name in this save.")
    fields = inspect(save)
    if fields:
        print("Matching field paths and stage-related values:")
        print("\n".join(fields))
    else:
        print("No matching Async Battle, tier, rank, or stage fields appeared in this save response.")
    return extra


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Asyncombat fields without writing a save.")
    parser.add_argument(
        "--save",
        type=Path,
        help="Inspect an existing decrypted save JSON instead of signing in. Does not probe the server.",
    )
    args = parser.parse_args()
    if args.save:
        save = json.loads(args.save.read_text(encoding="utf-8"))
        try:
            report_save(save)
            print("Local save only. Server probes run after an interactive sign-in, not from --save.")
        finally:
            save.clear()
        return

    email = input("Rizline account email: ").strip()
    if not email:
        print("No email entered; stopped.")
        return

    device_id = str(uuid.uuid4())
    token = ""
    passcode = getpass.getpass("Passcode (press Enter for email verification): ")
    if passcode:
        try:
            result = login_with_passcode(
                email,
                passcode,
                device_id=device_id,
                base_url=DEFAULT_BASE_URL,
                require_pinned_host=True,
                secrets=(email, passcode),
            )
            token, device_id = result.token, result.device_id
        except RizlineAPIError:
            print("Passcode sign-in failed; switching to email verification.")
        finally:
            passcode = ""

    if not token:
        device_id = request_email_code(
            email,
            device_id=device_id,
            base_url=DEFAULT_BASE_URL,
            require_pinned_host=True,
            secrets=(email,),
        )
        code = getpass.getpass("Email verification code: ").strip()
        result = login_with_code(
            email,
            code,
            device_id=device_id,
            base_url=DEFAULT_BASE_URL,
            require_pinned_host=True,
            secrets=(email, code),
        )
        token, device_id = result.token, result.device_id
        code = ""

    print("Fetching player-save response from the pinned Rizline server…")
    save = fetch_save(
        email,
        token,
        device_id,
        base_url=DEFAULT_BASE_URL,
        require_pinned_host=True,
        secrets=(email, token),
    )
    try:
        extra = report_save(save)
        if not extra:
            probe_async_endpoints(email, token, device_id)
        print("Probing Socket.IO weekly rank, weekly tasks, and own Rizcard…")
        from rizline.socket import probe_transactions

        for line in probe_transactions(email, token, device_id):
            print(line)
        print("No player-save file was written.")
    finally:
        save.clear()
        email = ""
        token = ""


if __name__ == "__main__":
    try:
        main()
    except (RizlineError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nCheck cancelled.")
        else:
            print(f"Could not complete the live check ({type(exc).__name__}).")
