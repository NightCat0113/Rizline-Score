"""Track series catalog stored beside the songs in songs_index.json."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from bot.services.profile import player_title


_BIO_LINE = re.compile(
    r"(?im)^series(?:bio|tag)?\.(\d+)\b[^=\n]*=\s*(?:bio\.)?((?:sp|ex)bio\d+)\s*$"
)


def preorder_date(deadline: object) -> str:
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        return ""
    if deadline <= 0:
        return ""
    return datetime.fromtimestamp(int(deadline), timezone.utc).strftime("%Y-%m-%d")


def bio_ids_from_locale(script: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for line in script.splitlines():
        match = _BIO_LINE.match(line.strip())
        if match:
            found[int(match.group(1))] = match.group(2)
    return found


def series_tag(bio_id: str, repo_root: Path, language: str = "en") -> str:
    cleaned = bio_id.strip()
    if cleaned.startswith("bio."):
        cleaned = cleaned[4:]
    cleaned = cleaned.split(".", 1)[0]
    if not cleaned:
        return ""
    return player_title(f"bio.{cleaned}.1", f"bio.{cleaned}.2", repo_root, language)


def series_mark(index: int) -> str:
    """Number printed on the banner. Phigros is SP, so every later series is one lower than seriesIndex."""
    if index == 12:
        return "SP"
    if 12 < index < 10000:
        return str(index - 1)
    return str(index)


def series_art_name(kind: str, index: int) -> str:
    number = str(index) if index >= 10000 else f"{index:05d}"
    return f"series{kind}.{number}"


def build_series_records(
    configs: list,
    songs: list[dict],
    names: dict[int, str],
    bio_ids: dict[int, str] | None = None,
) -> list[dict]:
    tags = bio_ids or {}
    known = {str(song.get("assetId") or "") for song in songs if song.get("assetId")}
    seen: set[int] = set()
    records: list[dict] = []
    for config in configs:
        if not isinstance(config, dict):
            continue
        index = config.get("seriesIndex")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            continue
        volumes = _config_volumes(config, known)
        if not volumes:
            continue
        seen.add(index)
        records.append(_record(index, names.get(index) or f"Track Series {index}", volumes, tags.get(index, "")))

    extras: dict[int, list[str]] = {}
    extra_names: dict[int, str] = {}
    for song in songs:
        index = song.get("seriesIndex")
        asset_id = str(song.get("assetId") or "")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in seen or not asset_id:
            continue
        bucket = extras.setdefault(index, [])
        if asset_id not in bucket:
            bucket.append(asset_id)
        name = str(song.get("seriesName") or "")
        if name and index not in extra_names:
            extra_names[index] = name
    for index, song_ids in extras.items():
        records.append(
            _record(
                index,
                names.get(index) or extra_names.get(index) or f"Track Series {index}",
                [{"label": "", "songs": song_ids}],
                tags.get(index, ""),
            )
        )
    records.sort(key=lambda row: int(row["seriesIndex"]))
    return records


def _config_volumes(config: dict, known: set[str]) -> list[dict]:
    volumes: list[dict] = []
    for group in config.get("volGroups") or []:
        if not isinstance(group, dict):
            continue
        song_ids: list[str] = []
        for level_id in group.get("levelIds") or []:
            song_id = str(level_id or "")
            if song_id and song_id in known and song_id not in song_ids:
                song_ids.append(song_id)
        if not song_ids:
            continue
        volume: dict = {"label": str(group.get("volLabel") or ""), "songs": song_ids}
        timing = group.get("preOrderTimeConfig") if isinstance(group.get("preOrderTimeConfig"), dict) else {}
        date = preorder_date(timing.get("deadline"))
        if date:
            volume["preorderEnds"] = date
        volumes.append(volume)
    return volumes


def _record(index: int, name: str, volumes: list[dict], bio_id: str) -> dict:
    record: dict = {"seriesIndex": index, "name": name, "volumes": volumes}
    if bio_id:
        record["bioId"] = bio_id
    return record
