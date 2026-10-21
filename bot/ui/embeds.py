"""Embeds for song, score, profile, and B40 pages."""

from __future__ import annotations

import discord

from bot.models import Song
from bot.services.rks import bests_for_song, chart_track_ids, score_counts, top_levels
from bot.services.songdata import SongIndex


COLOR = 0x61D8FF
_ORDER = ("EZ", "HD", "IN", "AT", "SP")


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


def _chart_value(song: Song, difficulty: str, personal: dict | None) -> str:
    chart = song.charts[difficulty]
    designer = chart.designer or "—"
    lines = [
        f"Level {chart.level_text or f'{chart.level:g}'} · Designer {designer}",
        f"Hit {chart.hit:,} · Combo {chart.combo:,} · Max {_fmt_score(chart.score)}",
    ]
    if personal:
        lines.append(f"Your best: {_personal_line(personal)}")
    return "\n".join(lines)


def song_embed(
    song: Song,
    *,
    cache: dict | None = None,
    difficulty: str | None = None,
    image_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=song.title,
        description=song.artist or None,
        color=COLOR,
    )
    if song.disc_name:
        embed.add_field(name="Disc", value=song.disc_name, inline=True)
    personal = bests_for_song(cache, song.asset_id, chart_track_ids(song)) if cache else {}
    difficulties = [difficulty] if difficulty else [name for name in _ORDER if name in song.charts]
    if difficulty and difficulty not in song.charts:
        embed.add_field(name=difficulty, value="This song has no chart at that difficulty.", inline=False)
    for name in difficulties:
        if name not in song.charts:
            continue
        embed.add_field(
            name=name,
            value=_chart_value(song, name, personal.get(name))[:1024],
            inline=False,
        )
    if not difficulties:
        embed.add_field(name="Charts", value="No chart details are in the local song index.", inline=False)
    if image_name:
        embed.set_image(url=f"attachment://{image_name}")
    return embed


def score_embed(
    song: Song,
    cache: dict,
    difficulty: str | None = None,
    image_name: str | None = None,
) -> discord.Embed:
    embed = song_embed(song, cache=cache, difficulty=difficulty, image_name=image_name)
    username = cache.get("username") or "Your scores"
    embed.set_footer(text=str(username))
    return embed


def profile_embed(cache: dict, index: SongIndex) -> discord.Embed:
    counts = score_counts(cache)
    username = str(cache.get("username") or "Player")
    total = float(cache.get("totalRks") or 0)
    embed = discord.Embed(
        title=username,
        description=f"RKS {total:.2f}",
        color=COLOR,
    )
    embed.add_field(
        name="Records",
        value=f"{counts['records']} records · {counts['clears']} clears · {counts['full_combos']} full combos",
        inline=False,
    )
    lines = []
    for number, row in enumerate(top_levels(cache, index, limit=5), start=1):
        lines.append(f"**{number}.** {row['title']} `{row['diff']}` · RKS {row['rks']:.2f}")
    embed.add_field(name="Top charts", value="\n".join(lines) or "No ranked charts yet.", inline=False)
    return embed


def ambiguous_embed(candidates: list[Song]) -> discord.Embed:
    lines = [f"• {song.title} — {song.artist}".rstrip(" —") for song in candidates[:5]]
    return discord.Embed(
        title="Several songs match",
        description="\n".join(lines) or "Try a more specific title.",
        color=COLOR,
    )
