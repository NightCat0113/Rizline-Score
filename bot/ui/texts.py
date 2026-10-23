"""Plain-text messages for song, score, profile, and series pages.

These are the text fallbacks used when an image card cannot be rendered,
plus the ambiguous-match and profile replies. They are ordinary message
content, not embeds.
"""

from __future__ import annotations

from bot.models import Song, TrackSeries
from bot.services.rks import bests_for_song, chart_track_ids, score_counts, top_levels
from bot.services.songdata import SongIndex
from bot.services.seriesdata import series_mark
from bot.ui.series_image import chart_levels


_ORDER = ("EZ", "HD", "IN", "AT", "SP")
_MAX_MESSAGE = 2000


def _limit(text: str) -> str:
    if len(text) <= _MAX_MESSAGE:
        return text
    return text[: _MAX_MESSAGE - 1].rstrip() + "…"


def _fmt_score(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_rate(value: object) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "—"


def _personal_line(best: dict) -> str:
    tags = []
    if best.get("isFullCombo"):
        tags.append("FC")
    elif best.get("isClear"):
        tags.append("Clear")
    else:
        tags.append("Not cleared")
    rks = best.get("rks")
    rks_text = f" · RKS {float(rks):.2f}" if isinstance(rks, (int, float)) else ""
    return f"{_fmt_score(best.get('score'))} · {_fmt_rate(best.get('completeRate'))} · {' · '.join(tags)}{rks_text}"


def _chart_lines(song: Song, difficulty: str, personal: dict | None) -> list[str]:
    chart = song.charts[difficulty]
    designer = chart.designer or "—"
    lines = [
        f"**{difficulty}** Level {chart.level_text or f'{chart.level:g}'} · Designer {designer}",
        f"Hit {chart.hit:,} · Combo {chart.combo:,} · Max {_fmt_score(chart.score)}",
    ]
    if personal:
        lines.append(f"Your best: {_personal_line(personal)}")
    return lines


def song_text(
    song: Song,
    *,
    cache: dict | None = None,
    difficulty: str | None = None,
) -> str:
    lines = [f"**{song.title}**"]
    if song.artist:
        lines.append(song.artist)
    if song.disc_name:
        lines.append(song.disc_name if song.disc_name.lower().startswith("disc") else f"Disc {song.disc_name}")
    personal = bests_for_song(cache, song.asset_id, chart_track_ids(song)) if cache else {}
    difficulties = [difficulty] if difficulty else [name for name in _ORDER if name in song.charts]
    if difficulty and difficulty not in song.charts:
        lines.append(f"\nThis song has no chart at {difficulty}.")
    shown = [name for name in difficulties if name in song.charts]
    for name in shown:
        lines.append("")
        lines.extend(_chart_lines(song, name, personal.get(name)))
    if not shown and not difficulty:
        lines.append("\nNo chart details are in the local song index.")
    return _limit("\n".join(lines))


def score_text(song: Song, cache: dict) -> str:
    username = cache.get("username") or "Your scores"
    return _limit(f"{username}\n\n{song_text(song, cache=cache)}")


def profile_text(cache: dict, index: SongIndex) -> str:
    counts = score_counts(cache)
    username = str(cache.get("username") or "Player")
    total = float(cache.get("totalRks") or 0)
    lines = [
        f"**{username}**",
        f"RKS {total:.2f}",
        f"{counts['records']} records · {counts['clears']} clears · {counts['full_combos']} full combos",
        "",
        "**Top charts**",
    ]
    rows = top_levels(cache, index, limit=5)
    if rows:
        lines.extend(
            f"{number}. {row['title']} `{row['diff']}` · RKS {row['rks']:.2f}"
            for number, row in enumerate(rows, start=1)
        )
    else:
        lines.append("No ranked charts yet.")
    return _limit("\n".join(lines))


def series_text(series: TrackSeries, songs: dict[str, Song], tag: str) -> str:
    mark = f"Track Series {series_mark(series.series_index)}"
    lines = [f"**{series.name or mark}**", mark]
    if tag:
        lines.append(tag)
    for index, volume in enumerate(series.volumes, start=1):
        label = volume.label or ("Songs" if len(series.volumes) == 1 else f"Volume {index}")
        lines.append("")
        lines.append(f"**{label}**")
        if volume.preorder_ends:
            lines.append(f"Preorder ends {volume.preorder_ends}")
        for song_id in volume.song_ids:
            song = songs.get(song_id)
            if song is None:
                lines.append(song_id)
                continue
            artist = f" — {song.artist}" if song.artist else ""
            levels = chart_levels(song)
            lines.append(f"{song.title}{artist}" + (f"\n{levels}" if levels else ""))
    return _limit("\n".join(lines))


def ambiguous_text(candidates: list[Song]) -> str:
    lines = [f"• {song.title} — {song.artist}".rstrip(" —") for song in candidates[:5]]
    body = "\n".join(lines) or "Try a more specific title."
    return _limit(f"Several songs match\n{body}")
