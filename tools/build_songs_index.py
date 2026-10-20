#!/usr/bin/env python3
"""Build bot/static/songs_index.json from portable song files plus optional local chart metadata.

songs.json is the canonical source for levels, hits, combos, and max scores.
output/default.json (or Database.txt) adds the chart designer, disc name, and illustration id.
all_cache.json is not merged: its cargo query includes extra SP columns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.songdata import normalize  # noqa: E402


DIFFICULTIES = ("EZ", "HD", "IN", "AT")
ALIASES = {
    "houkagooverdrive": "Houkago OVERDRIVE!!!!! (Game ver.)",
    "linklins": "LINK x LIN＃S",
    "swingsweettweedance": "Swing Sweet Twee Dance feat. ななきなな",
    "bamboo": "竹",
}


def parse_float(value: object) -> float:
    text = str(value or "").strip().replace(",", "")
    if text.endswith("+"):
        text = text[:-1]
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_int(value: object) -> int:
    return int(round(parse_float(value)))


def load_default(path: Path) -> tuple[dict, dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    designers: dict[tuple[str, str], str] = {}
    for chart in payload.get("charts") or []:
        chart_id = str(chart.get("id") or "")
        level = str(chart.get("level") or "")
        prefix = "chart."
        suffix = f".{level}"
        if not chart_id.startswith(prefix) or not level or not chart_id.endswith(suffix):
            continue
        music_id = chart_id[len(prefix) : -len(suffix)]
        designers[(music_id, level)] = str(chart.get("designer") or "")
    discs: dict[str, str] = {}
    illustrations: dict[str, str] = {}
    for level in payload.get("levels") or []:
        music_id = str(level.get("musicId") or level.get("id") or "")
        if not music_id:
            continue
        discs[music_id] = str(level.get("discName") or "")
        illustrations[music_id] = str(level.get("illustrationId") or "")
    return designers, discs, illustrations


def load_database(path: Path) -> tuple[dict, dict]:
    designers: dict[tuple[str, str], str] = {}
    discs: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) < 10:
            continue
        asset_id, _name, _artist, difficulty, _constant, disc, _hit, _combo, _score, designer = columns[:10]
        designers[(asset_id, difficulty)] = designer
        discs[asset_id] = disc
    return designers, discs


def song_row(asset_id: str, title: str, songs_by_norm: dict[str, dict]) -> dict | None:
    return songs_by_norm.get(normalize(title))


def main() -> int:
    songs_path = ROOT / "songs.json"
    mapping_path = ROOT / "mapping.json"
    default_path = ROOT / "output" / "default.json"
    database_path = ROOT / "Database.txt"
    output_path = ROOT / "bot" / "static" / "songs_index.json"

    songs = json.loads(songs_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(songs, list) or not isinstance(mapping, dict):
        print("songs.json must be a list and mapping.json must be an object", file=sys.stderr)
        return 1

    songs_by_norm: dict[str, dict] = {}
    for row in songs:
        for key in (row.get("Page") or "", row.get("Title") or ""):
            normalized = normalize(str(key))
            if normalized:
                songs_by_norm.setdefault(normalized, row)

    designers: dict[tuple[str, str], str] = {}
    discs: dict[str, str] = {}
    illustrations: dict[str, str] = {}
    sources = ["songs.json", "mapping.json"]
    if database_path.is_file():
        designers, discs = load_database(database_path)
        sources.append("Database.txt")
    if default_path.is_file():
        default_designers, default_discs, illustrations = load_default(default_path)
        designers.update(default_designers)
        discs.update(default_discs)
        sources.append("output/default.json")

    built: list[dict] = []
    missing_rows = 0
    for asset_id, title in mapping.items():
        if not isinstance(title, str):
            continue
        row = song_row(str(asset_id), title, songs_by_norm)
        if row is None:
            missing_rows += 1
            row = {}
        charts = {}
        for difficulty in DIFFICULTIES:
            raw_level = row.get(f"{difficulty} Lv") if row else None
            if raw_level is None or str(raw_level).strip() == "":
                continue
            charts[difficulty] = {
                "level": parse_float(raw_level),
                "hit": parse_int(row.get(f"{difficulty} Hit")),
                "combo": parse_int(row.get(f"{difficulty} Combo")),
                "score": parse_int(row.get(f"{difficulty} Score")),
                "rizHit": parse_int(row.get(f"{difficulty} RizHit")),
                "designer": designers.get((str(asset_id), difficulty), ""),
            }
        built.append(
            {
                "assetId": str(asset_id),
                "title": str(row.get("Title") or title),
                "artist": str(row.get("Artist") or ""),
                "discName": discs.get(str(asset_id)) or str(row.get("discName") or ""),
                "illustrationId": illustrations.get(str(asset_id)) or f"illustration.{asset_id}",
                "aliases": [],
                "charts": charts,
            }
        )

    by_title = {normalize(item["title"]): item for item in built}
    for alias, target in ALIASES.items():
        item = by_title.get(normalize(target))
        if item is None:
            print(f"alias not matched: {alias}", file=sys.stderr)
            continue
        if alias not in item["aliases"]:
            item["aliases"].append(alias)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": " + ".join(sources) + "; songs.json is canonical for chart constants",
        "songs": built,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(built)} songs to {output_path.name}. Unmatched mapping rows: {missing_rows}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
