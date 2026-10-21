#!/usr/bin/env python3
"""Build bot/static/songs_index.json from portable song files plus optional local chart metadata.

songs.json is the canonical source for levels, hits, combos, and max scores.
output/default.json (or Database.txt) adds the chart designer, disc name, and illustration id.
all_cache.json is not merged: its cargo query includes extra SP columns.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.songdata import normalize  # noqa: E402


DIFFICULTIES = ("EZ", "HD", "IN", "AT")
# Names are the titles on the official track-series banners. The banner file
# number matches seriesIndex; the # printed on some later banners does not.
SERIES_NAMES = {
    1: "Juggernaut",
    2: "Diverse System",
    3: "Sobrem",
    4: "Tone Sphere",
    5: "BlackY",
    6: "Cytus & Muse Dash",
    7: "KALPA",
    8: "Rotaeno",
    9: "宇宙ラジヲ 2024",
    10: "HARDCORE TANO*C",
    11: "DEEMO",
    12: "Phigros",
    13: "kuro",
    14: "Cosmos Panorama",
    15: "Tanchiky",
    16: "ルゼ & LisicA",
    17: "Diachronic Resonance",
    18: "ASTRAL",
    10001: "Paradigm: Reboot",
    10002: "去远方",
}
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


_BPM_RE = re.compile(r'"bPM"\s*:\s*([0-9]+(?:\.[0-9]+)?)')
_TIME_RE = re.compile(br'"time"\s*:\s*([0-9]+(?:\.[0-9]+)?)')


def load_default(path: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
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
    series: dict[str, int] = {}
    for level in payload.get("levels") or []:
        music_id = str(level.get("musicId") or level.get("id") or "")
        if not music_id:
            continue
        discs[music_id] = str(level.get("discName") or "")
        illustrations[music_id] = str(level.get("illustrationId") or "")
        raw_series = level.get("seriesIndex")
        if isinstance(raw_series, int):
            series[music_id] = raw_series
    illustrators: dict[str, str] = {}
    for item in payload.get("illustrations") or []:
        illustration_id = str(item.get("id") or "")
        artist = str(item.get("artist") or "").strip()
        if illustration_id and artist:
            illustrators[illustration_id] = artist
    sp_charts: dict[str, dict] = {}
    for level in payload.get("discOLevels") or []:
        if str(level.get("difficultyName") or "") != "SP":
            continue
        music_id = str(level.get("musicId") or "")
        chart_ids = [str(chart_id) for chart_id in level.get("chartIds") or [] if chart_id]
        if not music_id or not chart_ids:
            continue
        sp_charts[music_id] = {
            "trackId": str(level.get("id") or ""),
            "levelText": str(level.get("difficultyText") or ""),
            "chartId": chart_ids[0],
            "designerKey": str(level.get("designerInfoKey") or ""),
        }
    return designers, discs, illustrations, illustrators, series, sp_charts


def read_bpm(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            head = handle.read(8192)
    except OSError:
        return None
    match = _BPM_RE.search(head)
    if match is None:
        return None
    value = round(float(match.group(1)), 2)
    return value if value > 0 else None


def song_bpm(charts_dir: Path, asset_id: str) -> float | None:
    for difficulty in DIFFICULTIES:
        path = charts_dir / f"chart.{asset_id}.{difficulty}.json"
        if not path.is_file():
            continue
        bpm = read_bpm(path)
        if bpm is not None:
            return bpm
    return None


def chart_end_beats(path: Path) -> float:
    best = 0.0
    try:
        handle = path.open("rb")
    except OSError:
        return 0.0
    with handle:
        previous = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            data = previous + chunk
            for match in _TIME_RE.finditer(data):
                best = max(best, float(match.group(1)))
            previous = data[-48:]
    return best


def song_length(charts_dir: Path, asset_id: str, bpm: float | None) -> float | None:
    if not bpm:
        return None
    charts = [
        path
        for difficulty in DIFFICULTIES
        if (path := charts_dir / f"chart.{asset_id}.{difficulty}.json").is_file()
    ]
    if not charts:
        return None
    beats = chart_end_beats(min(charts, key=lambda item: item.stat().st_size))
    if beats <= 0:
        return None
    return round(beats * 60.0 / bpm, 1)


def disco_display_names(root: Path) -> dict[str, str]:
    file_list = root / "download" / "fileList.json"
    bundle_name = "dfc26ebdd285d9dc61f6ee898b722aa9.bundle"
    if file_list.is_file():
        try:
            pairs = json.loads(file_list.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pairs = []
        for pair in pairs:
            if isinstance(pair, list) and len(pair) >= 2 and pair[0] == "local.en" and isinstance(pair[1], str):
                bundle_name = pair[1]
                break
    path = root / "download" / "bundles" / bundle_name
    if not path.is_file():
        return {}
    try:
        import UnityPy
    except ImportError:
        return {}
    names: dict[str, str] = {}
    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name != "TextAsset":
            continue
        for line in str(obj.read().m_Script).splitlines():
            if not line.startswith("discoDisplay."):
                continue
            key, separator, value = line.partition("=")
            if separator and value:
                names[key] = value
    return names


def sp_chart_record(charts_dir: Path, spec: dict | None, designers: dict[str, str] | None = None) -> dict | None:
    if not spec:
        return None
    chart_id = str(spec.get("chartId") or "")
    path = charts_dir / f"{chart_id}.json"
    hit = combo = score = riz_hit = 0
    if path.is_file():
        from Riz_bundle import (
            apply_rizcol_ranges_to_notes,
            compute_hit_combo_score,
            extract_notes_from_chart_obj,
            extract_rizcol_from_chart_obj,
        )

        chart = json.loads(path.read_text(encoding="utf-8"))
        notes = extract_notes_from_chart_obj(chart)
        rizcol = extract_rizcol_from_chart_obj(chart)
        if rizcol and notes:
            notes = apply_rizcol_ranges_to_notes(rizcol, notes)
        hit, combo, score = compute_hit_combo_score(notes)
        riz_hit = max(0, (score - 1_000_000) // 100)
    return {
        "level": 0,
        "levelText": str(spec.get("levelText") or ""),
        "trackId": str(spec.get("trackId") or ""),
        "hit": hit,
        "combo": combo,
        "score": score,
        "rizHit": riz_hit,
        "designer": (designers or {}).get(str(spec.get("designerKey") or ""), ""),
    }


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
    charts_dir = ROOT / "output" / "charts"
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
    illustrators: dict[str, str] = {}
    series: dict[str, int] = {}
    sp_charts: dict[str, dict] = {}
    sources = ["songs.json", "mapping.json"]
    if database_path.is_file():
        designers, discs = load_database(database_path)
        sources.append("Database.txt")
    if default_path.is_file():
        default_designers, default_discs, illustrations, illustrators, series, sp_charts = load_default(default_path)
        designers.update(default_designers)
        discs.update(default_discs)
        sources.append("output/default.json")
    if charts_dir.is_dir():
        sources.append("output/charts")
    sp_designers = disco_display_names(ROOT) if sp_charts else {}

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
        illustration_id = illustrations.get(str(asset_id)) or f"illustration.{asset_id}"
        # No local file records an "original" flag. Add it here if a source appears.
        item = {
            "assetId": str(asset_id),
            "title": str(row.get("Title") or title),
            "artist": str(row.get("Artist") or ""),
            "discName": discs.get(str(asset_id)) or str(row.get("discName") or ""),
            "illustrationId": illustration_id,
            "aliases": [],
            "charts": charts,
        }
        bpm = song_bpm(charts_dir, str(asset_id))
        if bpm is not None:
            item["bpm"] = bpm
        length = song_length(charts_dir, str(asset_id), bpm)
        if length is not None:
            item["length"] = length
        illustrator = illustrators.get(illustration_id, "")
        if illustrator:
            item["illustrator"] = illustrator
        series_index = series.get(str(asset_id))
        if isinstance(series_index, int) and series_index != -1:
            item["seriesIndex"] = series_index
            name = SERIES_NAMES.get(series_index, "")
            if name:
                item["seriesName"] = name
        sp_chart = sp_chart_record(charts_dir, sp_charts.get(str(asset_id)), sp_designers)
        if sp_chart is not None:
            charts["SP"] = sp_chart
        built.append(item)

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
