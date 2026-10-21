"""Public song lookup, plus the caller's own scores when a cache exists."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.services.rks import bests_for_song, chart_track_ids
from bot.services.seriesdata import series_mark, series_tag
from bot.services.songdata import attachment_name, illustration_path
from bot.ui.embeds import COLOR, ambiguous_embed, series_embed, song_embed
from bot.ui.series_image import open_series_art, render_series
from bot.ui.song_image import render_song


logger = logging.getLogger("rizline.bot")

_DIFFICULTIES = [
    app_commands.Choice(name=name, value=name) for name in ("EZ", "HD", "IN", "AT", "SP")
]


async def autocomplete_songs(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        songs = interaction.client.songs.search(current, limit=25)
    except Exception:
        return []
    choices = []
    for song in songs:
        label = f"{song.title} — {song.artist}" if song.artist else song.title
        value = song.asset_id if len(song.asset_id) <= 100 else song.title[:100]
        choices.append(app_commands.Choice(name=label[:100], value=value))
    return choices


async def autocomplete_series(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        found = interaction.client.songs.search_series(current, limit=25)
    except Exception:
        return []
    choices = []
    for item in found:
        label = f"{series_mark(item.series_index)} · {item.name or 'Track Series'}"
        choices.append(app_commands.Choice(name=label[:100], value=f"i{item.series_index}"))
    return choices


class SongsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="song", description="Look up a Rizline song")
    @app_commands.describe(query="Song title", difficulty="Optional chart difficulty")
    @app_commands.autocomplete(query=autocomplete_songs)
    @app_commands.choices(difficulty=_DIFFICULTIES)
    @dm_only()
    async def song(
        self,
        interaction: discord.Interaction,
        query: str,
        difficulty: app_commands.Choice[str] | None = None,
    ) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        song, candidates = interaction.client.songs.resolve(query)
        if song is None:
            embed = ambiguous_embed(candidates) if candidates else discord.Embed(
                title="No song matched",
                description="Try a title from the song list.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        cache = None
        try:
            cache = interaction.client.db.get_cache(interaction.user.id)
        except Exception:
            cache = None
        diff = difficulty.value if difficulty else None
        await interaction.response.defer()
        settings = interaction.client.settings
        try:
            png = await asyncio.to_thread(
                render_song,
                song=song,
                personal=bests_for_song(cache, song.asset_id, chart_track_ids(song)) if cache else {},
                highlight=diff,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                font_path=settings.repo_root / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
            )
        except Exception as exc:
            logger.error("song image failed type=%s", type(exc).__name__)
            await _send_text_song(interaction, song, cache, diff, False)
            return
        embed = discord.Embed(title=song.title, color=COLOR)
        embed.set_image(url="attachment://song.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(io.BytesIO(png), filename="song.png"),
        )

    @app_commands.command(name="series", description="Look up a Rizline track series")
    @app_commands.describe(query="Series name")
    @app_commands.autocomplete(query=autocomplete_series)
    @dm_only()
    async def series(self, interaction: discord.Interaction, query: str) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        series, candidates = interaction.client.songs.resolve_series(query)
        if series is None:
            embed = _series_ambiguous(candidates) if candidates else discord.Embed(
                title="No series matched",
                description="Try a name from the track series list.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer()
        settings = interaction.client.settings
        tag = series_tag(series.bio_id, settings.repo_root) if series.bio_id else ""
        try:
            png = await asyncio.to_thread(
                render_series,
                series=series,
                songs=interaction.client.songs.by_asset,
                tag=tag,
                banner=open_series_art(settings.series_dir, "Banner", series.series_index),
                poster=open_series_art(settings.series_dir, "Poster", series.series_index),
                font_path=settings.repo_root / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
            )
        except Exception as exc:
            logger.error("series image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                embed=series_embed(series, interaction.client.songs.by_asset, tag),
            )
            return
        embed = discord.Embed(title=series.name or f"Track Series {series.series_index}", color=COLOR)
        embed.set_image(url="attachment://series.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(io.BytesIO(png), filename="series.png"),
        )


def _series_ambiguous(candidates) -> discord.Embed:
    lines = [f"• {item.name or item.series_index}" for item in candidates[:5]]
    return discord.Embed(
        title="Several series match",
        description="\n".join(lines) or "Try a more specific name.",
        color=COLOR,
    )


async def _send_text_song(interaction, song, cache, diff: str | None, ephemeral: bool) -> None:
    image = illustration_path(
        song,
        interaction.client.settings.illust_hires_dir,
        interaction.client.settings.illust_dir,
    )
    filename = attachment_name(song) if image else None
    embed = song_embed(song, cache=cache, difficulty=diff, image_name=filename)
    kwargs: dict = {"embed": embed, "ephemeral": ephemeral}
    if image and filename:
        kwargs["file"] = discord.File(image, filename=filename)
    await interaction.followup.send(**kwargs)
