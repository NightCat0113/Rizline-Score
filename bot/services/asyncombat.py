"""Map a GetWeeklyRankInfo payload into the Asyncombat card."""

from __future__ import annotations

from dataclasses import dataclass


# WeeklyRankData.segment is a 0-based enum in this order.
_SEGMENTS = ("Do", "Re", "Mi", "Fa", "Sol", "La", "Si", "Do△")
# Rail spelling from the rank-journey sheet. Sol/Si stay as the API names.
RAIL_LABELS = ("Do", "Re", "Mi", "Fa", "So", "La", "Ti", "Do△")

_RAIL_INDEX = {name.casefold(): index for index, name in enumerate(_SEGMENTS)}
_RAIL_INDEX.update({name.casefold(): index for index, name in enumerate(RAIL_LABELS)})
_RAIL_INDEX["dol"] = 7
_RAIL_INDEX["doδ"] = 7


@dataclass(frozen=True)
class RankBadge:
    label: str
    segment: str = ""
    stars: int | None = None
    is_plus: bool = False


@dataclass(frozen=True)
class SideStats:
    matches: int
    wins: int
    streak: int


@dataclass(frozen=True)
class AsyncombatView:
    initial: RankBadge
    current: RankBadge
    peak: RankBadge
    challenge: SideStats
    engage: SideStats


def _unwrap(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("result", "data", "info"):
        child = payload.get(key)
        if isinstance(child, dict) and any(
            name in child for name in ("currentRank", "currentSeasonStats", "lifetimeStats")
        ):
            return child
    return payload


def _first_int(source: dict, *keys: str) -> int:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    return 0


def _segment_text(value: dict) -> str:
    for key in ("segmentName", "name"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    raw = value.get("segment")
    if isinstance(raw, str):
        text = raw.strip()
        if text and not text.lstrip("-").isdigit():
            return text
        if text.lstrip("-").isdigit():
            raw = int(text)
        else:
            return ""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return ""
    index = int(raw)
    if index in range(len(_SEGMENTS)):
        return _SEGMENTS[index]
    return ""


def _star_count(value: dict) -> int | None:
    raw = value.get("stars")
    if raw is None:
        raw = value.get("absStars")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def _badge(value: object) -> RankBadge:
    if not isinstance(value, dict):
        text = str(value).strip() if value not in (None, "") else "—"
        return RankBadge(text or "—")
    segment = _segment_text(value)
    stars = _star_count(value)
    is_plus = value.get("isPlus") is True
    star_text = "" if stars is None else f"{stars}{'+' if is_plus else ''}"
    label = f"{segment} {star_text}".strip()
    return RankBadge(label or "—", segment=segment, stars=stars, is_plus=is_plus)


def _side(group: object, name: str) -> SideStats:
    side: dict = {}
    if isinstance(group, dict):
        found = group.get(name)
        if isinstance(found, dict):
            side = found
        elif name == "active" and not any(isinstance(group.get(key), dict) for key in ("active", "passive")):
            side = group
    matches = _first_int(side, "playCount", "matchCount", "matches", "total")
    wins = _first_int(side, "winCount", "wins", "totalWin")
    streak = _first_int(side, "bestWinStreak", "currentWinStreak", "winStreakCount", "streak")
    return SideStats(matches, wins, streak)


def display_name(payload: dict) -> str:
    body = _unwrap(payload if isinstance(payload, dict) else {})
    for source in (body, payload if isinstance(payload, dict) else {}):
        for key in ("username", "name", "playerName"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        profile = source.get("profile")
        if isinstance(profile, dict):
            for key in ("username", "name"):
                value = profile.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return "Player"


def segment_index(badge: RankBadge) -> int:
    """0–7 for Do…Do△. -1 when the badge has no known tier."""
    return _RAIL_INDEX.get(badge.segment.strip().casefold(), -1)


def win_rate(side: SideStats) -> int:
    if side.matches <= 0:
        return 0
    return max(0, min(100, int(round(100 * side.wins / side.matches))))


def map_weekly_rank(payload: dict) -> AsyncombatView:
    body = _unwrap(payload)
    stats = body.get("currentSeasonStats")
    if not isinstance(stats, dict):
        stats = body.get("lifetimeStats") if isinstance(body.get("lifetimeStats"), dict) else {}
    return AsyncombatView(
        initial=_badge(body.get("currentSeasonStartingRank")),
        current=_badge(body.get("currentRank") if body.get("currentRank") is not None else body.get("rank")),
        peak=_badge(body.get("currentSeasonBestRank")),
        challenge=_side(stats, "active"),
        engage=_side(stats, "passive"),
    )
