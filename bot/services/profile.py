"""Player-card title text from the local bio and achievement JSON files."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rizline_client import derive_minimal_cache


_BIO_ID = re.compile(r"^bio\.([^.]+)\.(1|2)$")
_ACH_ID = re.compile(r"^ach\.\[([^\]]+)\]\.(title1|title2)$")


_CARD_KEYS = ("avatarId", "avatarPos", "bioId1", "bioId2", "backgroundId", "layoutId")


def local_profile(repo_root: Path, username: str) -> dict:
    """Profile card from a local *_gameData.json whose username matches."""
    wanted = username.strip().casefold()
    if not wanted:
        return {}
    for path in sorted(repo_root.glob("*gameData*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("username")
        if not isinstance(name, str) or name.strip().casefold() != wanted:
            continue
        try:
            derived = derive_minimal_cache(payload)
        except Exception:
            continue
        return {key: derived[key] for key in _CARD_KEYS}
    return {}


def layout_colors(layout_id: str, repo_root: Path) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Bottom-bar colors from layout.json. Falls back to the page's white bar."""
    white = (255, 255, 255)
    ink = (51, 51, 51)
    payload = _load_json(repo_root / "layout.json")
    rows = payload.get("layoutColors") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("id") == layout_id:
                return (
                    _hex_color(row.get("bgColor1"), white),
                    _hex_color(row.get("bgColor2"), white),
                    _hex_color(row.get("fgColor"), ink),
                )
    return white, white, ink


def _hex_color(value: object, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(value, str):
        return default
    text = value.strip().lstrip("#")
    if len(text) not in (6, 8):
        return default
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return default


def player_title(bio_id1: str, bio_id2: str, repo_root: Path) -> str:
    parts = []
    for bio_id in (bio_id1, bio_id2):
        text = _title_for(bio_id, repo_root)
        if text:
            parts.append(text)
    return " ".join(parts)


def _title_for(bio_id: str, repo_root: Path) -> str:
    cleaned = bio_id.strip()
    if not cleaned:
        return ""
    english = _lookup(cleaned, _load_json(repo_root / "bio_en.json"), _load_json(repo_root / "achievement_en.json"))
    if english:
        return english
    return _lookup(cleaned, _load_json(repo_root / "bio.json"), _load_json(repo_root / "achievement.json"))


def _lookup(bio_id: str, bios: dict, achievements: dict) -> str:
    direct = bios.get(bio_id)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    normalized = bio_id.replace("[", "").replace("]", "")
    direct = bios.get(normalized)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    bio_match = _BIO_ID.match(bio_id)
    if bio_match:
        entry = bios.get(bio_match.group(1))
        if isinstance(entry, dict):
            key = "title1" if bio_match.group(2) == "1" else "title2"
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    achievement_match = _ACH_ID.match(bio_id)
    if achievement_match:
        entry = achievements.get(achievement_match.group(1))
        if isinstance(entry, dict):
            value = entry.get(achievement_match.group(2))
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


@lru_cache(maxsize=8)
def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
