"""B40 / RKS selection, ported from rizb40_tool.js."""

from __future__ import annotations

import math
import struct

from bot.services.songdata import SongIndex, normalize


EPS = 1e-6


def strip_track_prefix(track_id: str) -> str:
    return track_id[6:] if track_id.startswith("track.") else track_id


def asset_title(track_id: str) -> str:
    text = strip_track_prefix(track_id)
    if text and text[-1].isdigit():
        text = text.rsplit(".", 1)[0]
    parts = text.split(".")
    return parts[0] if parts else text


def js_round(value: float) -> int:
    if math.isnan(value) or math.isinf(value):
        return 0
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", float(value)))[0]


def rks_float32_matches(left: float, right: float) -> bool:
    return _f32(left) == _f32(right)


def chart_const(track_id: str, difficulty: str, fallback: float, overrides: dict[str, float]) -> float:
    keys = (f"{track_id}|{difficulty}", f"{strip_track_prefix(track_id)}|{difficulty}")
    for key in keys:
        if key in overrides:
            return float(overrides[key])
    return fallback


def compute_h(max_hit: int, difficulty: str) -> int:
    if max_hit <= 0:
        return 0
    factor = 0.98
    if difficulty == "EZ":
        factor = 0.5
    elif difficulty == "HD":
        factor = 0.9
    if (1 - factor) * max_hit > 5:
        return math.ceil(factor * max_hit - 1e-12)
    return max_hit - 5


def get_acc_rks(complete_rate: float) -> float:
    if complete_rate >= 119.9999:
        return 10.5
    if complete_rate >= 118:
        return 10.2
    if complete_rate >= 116:
        return 9.9
    if complete_rate >= 114:
        return 9.6
    if complete_rate >= 112:
        return 9.3
    if complete_rate >= 110:
        return 9.0
    if complete_rate >= 105:
        return 8.25
    if complete_rate >= 100:
        return 7.5
    if complete_rate >= 95:
        return 6.75
    if complete_rate >= 90:
        return 6.0
    if complete_rate >= 80:
        return 4.5
    if complete_rate >= 70:
        return 3.0
    if complete_rate >= 60:
        return 1.5
    return 0.0


def integrality(constant: float, hits: int, rks: float, accuracy: float) -> tuple[float, bool]:
    if constant <= 0 or hits <= 0:
        return 0.0, False
    value = hits * (11 * constant + accuracy - rks) / constant
    nearest = js_round(value)
    ok = abs(value - nearest) <= EPS and value >= -EPS and value <= hits + EPS
    return value, ok


def score_riz_perfect(score: int) -> float:
    perfect = js_round((score - 1_000_000) / 100)
    return 0.0 if perfect < 0 else float(perfect)


def expected_rks_if_hit_full(
    constant: float,
    hits: int,
    score: int,
    accuracy: float,
    observed: float,
) -> tuple[float, bool, bool]:
    if constant <= 0 or hits <= 0 or score <= 0:
        return 0.0, False, False
    perfect = score_riz_perfect(score)
    quotient = min(perfect, hits)
    expected = 10 * constant + accuracy + constant * quotient / hits
    return expected, True, rks_float32_matches(expected, observed)


def build_records(
    cache: dict,
    index: SongIndex,
    overrides: dict[str, float] | None = None,
) -> tuple[list[dict], list[str]]:
    overrides = overrides or {}
    best_by_key = {
        (str(item.get("trackAssetId") or ""), str(item.get("difficultyClassName") or "")): item
        for item in cache.get("myBest") or []
        if isinstance(item, dict)
    }
    records: list[dict] = []
    missing: list[str] = []
    for index_number, level in enumerate(cache.get("levelsRks") or []):
        if not isinstance(level, dict):
            continue
        track_id = str(level.get("trackId") or "")
        difficulty = str(level.get("difficultyClassName") or "")
        best = best_by_key.get((track_id, difficulty))
        if not track_id or best is None:
            missing.append(f"#{index_number + 1} {track_id} {difficulty} missing myBest")
            continue
        asset_id = strip_track_prefix(track_id)
        song = index.by_asset.get(asset_id) or index.by_norm.get(normalize(asset_title(track_id)))
        if song is None:
            missing.append(f"#{index_number + 1} {track_id}")
            continue
        chart = song.charts.get(difficulty)
        if chart is None:
            missing.append(f"#{index_number + 1} {track_id} {difficulty}")
            continue
        constant = chart_const(track_id, difficulty, chart.level, overrides)
        riz_hit = chart.riz_hit
        if riz_hit == 0 and chart.score >= 1_000_000:
            riz_hit = js_round((chart.score - 1_000_000) / 100)
        hits = compute_h(riz_hit, difficulty)
        accuracy = get_acc_rks(float(best.get("completeRate") or 0))
        observed = float(level.get("rks") or 0)
        _value, integral_ok = integrality(constant, hits, observed, accuracy)
        _expected, expected_known, expected_matches = expected_rks_if_hit_full(
            constant,
            hits,
            int(best.get("score") or 0),
            accuracy,
            observed,
        )
        confirmed = chart.hit > 0 and riz_hit == chart.hit
        hit_full = integral_ok or (expected_known and expected_matches)
        if confirmed:
            ah_status = 1
        elif hit_full:
            ah_status = 2
        else:
            ah_status = 0
        records.append(
            {
                "sourceRank": index_number + 1,
                "trackId": track_id,
                "title": song.title,
                "artist": song.artist,
                "diff": difficulty,
                "rks": observed,
                "score": int(best.get("score") or 0),
                "completeRate": float(best.get("completeRate") or 0),
                "isFullCombo": bool(best.get("isFullCombo")),
                "isClear": bool(best.get("isClear")),
                "const": constant,
                "ahStatus": ah_status,
            }
        )
    return records, missing


def select_top40(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    by_rks = sorted(records, key=lambda record: record["rks"], reverse=True)
    confirmed = [record for record in by_rks if record["ahStatus"] == 1]
    possible = [record for record in by_rks if record["ahStatus"] == 2]
    candidates: list[dict] = []
    selected: set[tuple[str, str]] = set()
    for group in (confirmed, possible):
        for record in group:
            if len(candidates) >= 5:
                break
            key = (record["trackId"], record["diff"])
            if key not in selected:
                candidates.append(record)
                selected.add(key)
    candidates.sort(key=lambda record: record["rks"], reverse=True)
    ordinary: list[dict] = []
    overflow: list[dict] = []
    for record in by_rks:
        if (record["trackId"], record["diff"]) in selected:
            continue
        if len(ordinary) < 35:
            ordinary.append(record)
        elif len(overflow) < 10:
            overflow.append(record)
        else:
            break
    return candidates, ordinary, overflow


def chart_track_ids(song: object) -> tuple[str, ...]:
    asset_id = str(getattr(song, "asset_id", "") or "")
    charts = getattr(song, "charts", {}) or {}
    return tuple(
        chart.track_id
        for chart in charts.values()
        if getattr(chart, "track_id", "") and chart.track_id != asset_id
    )


def bests_for_song(cache: dict, asset_id: str, track_ids: tuple[str, ...] = ()) -> dict[str, dict]:
    wanted = {asset_id, f"track.{asset_id}"}
    for track_id in track_ids:
        if track_id and track_id != asset_id:
            wanted.add(track_id)
            wanted.add(f"track.{track_id}")
    rks_by: dict[str, float] = {}
    for level in cache.get("levelsRks") or []:
        if not isinstance(level, dict):
            continue
        track_id = str(level.get("trackId") or "")
        if track_id in wanted or strip_track_prefix(track_id) == asset_id:
            rks_by[str(level.get("difficultyClassName") or "")] = float(level.get("rks") or 0)
    found: dict[str, dict] = {}
    for best in cache.get("myBest") or []:
        if not isinstance(best, dict):
            continue
        asset = str(best.get("trackAssetId") or "")
        if asset not in wanted and strip_track_prefix(asset) != asset_id:
            continue
        difficulty = str(best.get("difficultyClassName") or "")
        found[difficulty] = {**best, "rks": rks_by.get(difficulty)}
    return found


def score_counts(cache: dict) -> dict[str, int]:
    bests = [item for item in cache.get("myBest") or [] if isinstance(item, dict)]
    return {
        "records": len(bests),
        "clears": sum(1 for item in bests if item.get("isClear")),
        "full_combos": sum(1 for item in bests if item.get("isFullCombo")),
    }


def top_levels(cache: dict, index: SongIndex, limit: int = 5) -> list[dict]:
    levels = [item for item in cache.get("levelsRks") or [] if isinstance(item, dict)]
    levels.sort(key=lambda item: float(item.get("rks") or 0), reverse=True)
    rows = []
    for level in levels[:limit]:
        track_id = str(level.get("trackId") or "")
        asset_id = strip_track_prefix(track_id)
        song = index.by_asset.get(asset_id)
        rows.append(
            {
                "title": song.title if song else asset_title(track_id),
                "diff": str(level.get("difficultyClassName") or ""),
                "rks": float(level.get("rks") or 0),
            }
        )
    return rows
