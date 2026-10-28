"""Score targets for raising the player's estimated Best 40 RKS."""

from __future__ import annotations

import math

from bot.services.rks import (
    build_records,
    compute_h,
    expected_rks_if_hit_full,
    get_acc_rks,
    score_riz_perfect,
    select_top40,
    strip_track_prefix,
)
from bot.services.songdata import SongIndex


def resolve_song_filter(index: SongIndex, raw: str | None) -> tuple[set[str], list[str]]:
    """Resolve semicolon-separated titles into asset IDs and return any problems."""
    if not raw or not raw.strip():
        return set(), []
    selected: set[str] = set()
    errors: list[str] = []
    for query in (part.strip() for part in raw.split(";")):
        if not query:
            continue
        song, candidates = index.resolve(query)
        if song is None:
            if candidates:
                names = ", ".join(item.title for item in candidates[:4])
                errors.append(f"`{query}` matched multiple songs: {names}")
            else:
                errors.append(f"`{query}` did not match a song")
            continue
        selected.add(song.asset_id)
    return selected, errors


def recommend_score_targets(
    cache: dict,
    index: SongIndex,
    increase: float | None = None,
    song_ids: set[str] | None = None,
) -> tuple[list[dict], float]:
    """Return a combined score-improvement plan and its available overall gain.

    Targets hold the player's current accuracy tier constant and combine score
    improvements across all scored charts that can enter or improve the Best 40.
    ``increase`` is an overall RKS bump. ``None`` plans the full score-only maximum.
    """
    records, _missing = build_records(cache, index)
    special, ordinary, _overflow = select_top40(records)
    top40 = special + ordinary
    if not top40:
        return [], 0.0
    wanted_ids = song_ids or set()
    want_all = increase is None
    target_gain = math.inf if want_all else max(0.01, float(increase)) * 40
    candidates: list[dict] = []

    for row in top40:
        asset_id = strip_track_prefix(str(row.get("trackId") or ""))
        if wanted_ids and asset_id not in wanted_ids:
            continue
        song = index.by_asset.get(asset_id)
        chart = song.charts.get(str(row.get("diff") or "")) if song else None
        if chart is None or chart.score <= 0 or chart.level <= 0:
            continue
        riz_hit = chart.riz_hit
        if riz_hit <= 0 and chart.score >= 1_000_000:
            riz_hit = max(0, math.floor((chart.score - 1_000_000) / 100 + 0.5))
        hits = compute_h(riz_hit, chart.difficulty)
        if hits <= 0:
            continue
        accuracy = get_acc_rks(float(row.get("completeRate") or 0))
        score = int(row.get("score") or 0)
        observed = float(row.get("rks") or 0)
        current_q = min(hits, int(score_riz_perfect(score)))
        max_q = min(hits, int(score_riz_perfect(chart.score)))
        _current_formula, known, matches = expected_rks_if_hit_full(
            chart.level, hits, score, accuracy, observed
        )
        if not known or not matches or max_q <= current_q:
            continue

        steps_available = max_q - current_q
        if steps_available <= 0:
            continue
        per_step = chart.level / hits
        candidates.append(
            {
                "title": row["title"],
                "difficulty": row["diff"],
                "current_score": score,
                "current_q": current_q,
                "max_q": max_q,
                "per_step": per_step,
                "max_score": chart.score,
                "key": (str(row.get("trackId") or ""), str(row.get("diff") or "")),
                "max_rks": 10 * chart.level + accuracy + chart.level * max_q / hits,
            }
        )

    max_gain = sum(
        (item["max_q"] - item["current_q"]) * item["per_step"] for item in candidates
    ) / 40
    remaining = target_gain
    plan: list[dict] = []
    ordered = sorted(
        candidates,
        key=lambda row: (row["max_q"] - row["current_q"], -row["per_step"], row["title"]),
    )
    for item in ordered:
        steps_available = item["max_q"] - item["current_q"]
        if want_all:
            steps = steps_available
        else:
            if remaining <= 1e-9:
                break
            steps = min(steps_available, math.ceil(remaining / item["per_step"]))
        target_score = min(item["max_score"], 1_000_000 + (item["current_q"] + steps) * 100)
        gain = steps * item["per_step"] / 40
        plan.append(
            {
                "title": item["title"],
                "difficulty": item["difficulty"],
                "current_score": item["current_score"],
                "target_score": target_score,
                "rks_gain": gain,
                "in_top40": True,
            }
        )
        if not want_all:
            remaining -= steps * item["per_step"]

    # Raise current Best 40 charts to their score-only maximum before finding
    # the replacement cutoffs for songs currently outside the list.
    maxed_records = [dict(row) for row in records]
    maxed_by_key = {
        (str(row.get("trackId") or ""), str(row.get("diff") or "")): row
        for row in maxed_records
    }
    for item in candidates:
        maxed_row = maxed_by_key.get(item["key"])
        if maxed_row is not None:
            maxed_row["rks"] = item["max_rks"]
    maxed_special, maxed_ordinary, _maxed_overflow = select_top40(maxed_records)
    maxed_top40 = maxed_special + maxed_ordinary
    maxed_keys = {
        (str(row.get("trackId") or ""), str(row.get("diff") or ""))
        for row in maxed_top40
    }
    replacement_values = sorted(float(row["rks"]) for row in maxed_top40)
    replacement_values = [0.0] * max(0, 40 - len(replacement_values)) + replacement_values

    outside_candidates: list[dict] = []
    for row in records:
        key = (str(row.get("trackId") or ""), str(row.get("diff") or ""))
        if key in maxed_keys:
            continue
        asset_id = strip_track_prefix(key[0])
        if wanted_ids and asset_id not in wanted_ids:
            continue
        song = index.by_asset.get(asset_id)
        chart = song.charts.get(key[1]) if song else None
        if chart is None or chart.score <= 0 or chart.level <= 0:
            continue
        riz_hit = chart.riz_hit
        if riz_hit <= 0 and chart.score >= 1_000_000:
            riz_hit = max(0, math.floor((chart.score - 1_000_000) / 100 + 0.5))
        hits = compute_h(riz_hit, chart.difficulty)
        if hits <= 0:
            continue
        accuracy = get_acc_rks(float(row.get("completeRate") or 0))
        score = int(row.get("score") or 0)
        observed = float(row.get("rks") or 0)
        current_q = min(hits, int(score_riz_perfect(score)))
        max_q = min(hits, int(score_riz_perfect(chart.score)))
        _current_formula, known, matches = expected_rks_if_hit_full(
            chart.level, hits, score, accuracy, observed
        )
        if not known or not matches or max_q <= current_q:
            continue
        outside_candidates.append(
            {
                "title": row["title"],
                "difficulty": row["diff"],
                "current_score": score,
                "current_q": current_q,
                "max_q": max_q,
                "per_step": chart.level / hits,
                "max_score": chart.score,
                "base_rks": 10 * chart.level + accuracy,
                "max_rks": 10 * chart.level + accuracy + chart.level * max_q / hits,
            }
        )

    # Pair the strongest outsiders with the lowest Best 40 slots, then prefer
    # the charts that need the smallest score jump to enter.
    ranked = sorted(outside_candidates, key=lambda item: (-item["max_rks"], item["title"]))
    viable: list[dict] = []
    outside_max_raw = 0.0
    for slot, item in enumerate(ranked[:40]):
        threshold = replacement_values[slot]
        if item["max_rks"] <= threshold:
            break
        entry_q = max(
            item["current_q"] + 1,
            math.floor((threshold - item["base_rks"]) / item["per_step"] + 1e-9) + 1,
        )
        if entry_q > item["max_q"]:
            continue
        item = {**item, "threshold": threshold, "target_q": entry_q}
        viable.append(item)
        outside_max_raw += item["max_rks"] - threshold
    viable.sort(key=lambda item: (item["target_q"] - item["current_q"], -item["max_rks"], item["title"]))

    max_available = max_gain + outside_max_raw / 40
    if want_all:
        for item in viable:
            item["target_q"] = item["max_q"]
        _append_outside(plan, viable)
        return plan, max_available
    if remaining <= 1e-9 or not viable:
        return plan, max_available

    selected: list[dict] = []
    available_raw = 0.0
    for item in viable:
        selected.append(item)
        available_raw += item["max_rks"] - item["threshold"]
        if available_raw + 1e-9 >= remaining:
            break

    planned_raw = sum(
        item["base_rks"] + item["target_q"] * item["per_step"] - item["threshold"]
        for item in selected
    )
    extra_needed = max(0.0, remaining - planned_raw)
    for item in sorted(selected, key=lambda row: (-row["per_step"], row["title"])):
        if extra_needed <= 1e-9:
            break
        steps = min(
            item["max_q"] - item["target_q"],
            math.ceil(extra_needed / item["per_step"]),
        )
        item["target_q"] += steps
        extra_needed -= steps * item["per_step"]

    _append_outside(plan, selected)
    return plan, max_available


def _append_outside(plan: list[dict], selected: list[dict]) -> None:
    for item in selected:
        target_score = min(item["max_score"], 1_000_000 + item["target_q"] * 100)
        target_rks = item["base_rks"] + item["target_q"] * item["per_step"]
        plan.append(
            {
                "title": item["title"],
                "difficulty": item["difficulty"],
                "current_score": item["current_score"],
                "target_score": target_score,
                "rks_gain": (target_rks - item["threshold"]) / 40,
                "score_gain": target_score - item["current_score"],
                "in_top40": False,
            }
        )
