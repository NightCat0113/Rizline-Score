"""Public song lookup, plus the caller's own scores when a cache exists."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.services.language import user_language
from bot.services.rks import bests_for_song, chart_track_ids
from bot.services.seriesdata import series_mark, series_tag
from bot.services.songdata import attachment_name, illustration_path
from bot.ui.chart_list_view import ChartListView
from bot.ui.series_image import open_series_art, render_series
from bot.ui.texts import ambiguous_text, series_text, song_text
from bot.ui.song_image import render_song


logger = logging.getLogger("rizline.bot")
_DIFFICULTIES = [
    app_commands.Choice(name=name, value=name) for name in ("EZ", "HD", "IN", "AT", "SP")
]
_NO_CHARTS = "No charts match that filter."


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
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(query="Song title", private="Only you can see this reply")
    @app_commands.autocomplete(query=autocomplete_songs)
    @dm_only()
    async def song(
        self,
        interaction: discord.Interaction,
        query: str,
        private: bool = False,
    ) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        song, candidates = interaction.client.songs.resolve(query)
        if song is None:
            message = ambiguous_text(candidates) if candidates else "No song matched\nTry a title from the song list."
            await interaction.response.send_message(message, ephemeral=True)
            return
        await self._reply_song(interaction, song, private=private, highlight=None)

    @app_commands.command(name="random", description="Show a random chart from the catalog")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        difficulty="Chart difficulty",
        min_level="Lowest chart constant",
        max_level="Highest chart constant",
        private="Only you can see this reply",
    )
    @app_commands.choices(difficulty=_DIFFICULTIES)
    @dm_only()
    async def random_song(
        self,
        interaction: discord.Interaction,
        difficulty: str | None = None,
        min_level: app_commands.Range[float, 1.0, 20.0] | None = None,
        max_level: app_commands.Range[float, 1.0, 20.0] | None = None,
        private: bool = False,
    ) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        picked = interaction.client.songs.random_chart(
            min_level=None if min_level is None else float(min_level),
            max_level=None if max_level is None else float(max_level),
            difficulty=difficulty,
        )
        if picked is None:
            await interaction.response.send_message(_NO_CHARTS, ephemeral=True)
            return
        song, chart = picked
        await self._reply_song(interaction, song, private=private, highlight=chart.difficulty)

    @app_commands.command(name="charts", description="List charts in a constant range")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        min_level="Lowest chart constant",
        max_level="Highest chart constant",
        difficulty="Chart difficulty",
        private="Only you can see this reply",
    )
    @app_commands.choices(difficulty=_DIFFICULTIES)
    @dm_only()
    async def charts(
        self,
        interaction: discord.Interaction,
        min_level: app_commands.Range[float, 1.0, 20.0],
        max_level: app_commands.Range[float, 1.0, 20.0],
        difficulty: str | None = None,
        private: bool = False,
    ) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        rows = interaction.client.songs.charts_in_range(float(min_level), float(max_level), difficulty)
        if not rows:
            await interaction.response.send_message(_NO_CHARTS, ephemeral=True)
            return
        low, high = sorted((float(min_level), float(max_level)))
        heading = f"{low:g}–{high:g}"
        if difficulty:
            heading = f"{heading} · {difficulty}"
        view = ChartListView(owner_id=interaction.user.id, rows=rows, heading=heading)
        await interaction.response.send_message(view.render(), view=view, ephemeral=private)

    async def _reply_song(
        self,
        interaction: discord.Interaction,
        song,
        *,
        private: bool,
        highlight: str | None,
    ) -> None:
        cache = None
        try:
            cache = interaction.client.db.get_cache(interaction.user.id)
        except Exception:
            cache = None
        await interaction.response.defer(ephemeral=private)
        settings = interaction.client.settings
        try:
            png = await asyncio.to_thread(
                render_song,
                song=song,
                personal=bests_for_song(cache, song.asset_id, chart_track_ids(song)) if cache else {},
                highlight=highlight,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                font_path=settings.font_path,
                language=user_language(interaction.client.db, interaction.user.id),
            )
        except Exception as exc:
            logger.error("song image failed type=%s", type(exc).__name__)
            await _send_text_song(interaction, song, cache, private, highlight)
            return
        await interaction.followup.send(
            f"**{song.title}**",
            file=discord.File(io.BytesIO(png), filename="song.png"),
            ephemeral=private,
        )

    @app_commands.command(name="series", description="Look up a Rizline track series")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(query="Series name", private="Only you can see this reply")
    @app_commands.autocomplete(query=autocomplete_series)
    @dm_only()
    async def series(self, interaction: discord.Interaction, query: str, private: bool = False) -> None:
        if not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        series, candidates = interaction.client.songs.resolve_series(query)
        if series is None:
            message = _series_ambiguous(candidates) if candidates else "No series matched\nTry a name from the track series list."
            await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=private)
        settings = interaction.client.settings
        language = user_language(interaction.client.db, interaction.user.id)
        tag = series_tag(series.bio_id, settings.repo_root, language) if series.bio_id else ""
        try:
            png = await asyncio.to_thread(
                render_series,
                series=series,
                songs=interaction.client.songs.by_asset,
                tag=tag,
                banner=open_series_art(settings.series_dir, "Banner", series.series_index, language),
                poster=open_series_art(settings.series_dir, "Poster", series.series_index, language),
                font_path=settings.font_path,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                language=language,
            )
        except Exception as exc:
            logger.error("series image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                series_text(series, interaction.client.songs.by_asset, tag),
                ephemeral=private,
            )
            return
        await interaction.followup.send(
            f"**{series.name or f'Track Series {series.series_index}'}**",
            file=discord.File(io.BytesIO(png), filename="series.png"),
            ephemeral=private,
        )


def _series_ambiguous(candidates) -> str:
    lines = [f"• {item.name or item.series_index}" for item in candidates[:5]]
    body = "\n".join(lines) or "Try a more specific name."
    return f"Several series match\n{body}"


async def _send_text_song(interaction, song, cache, ephemeral: bool, difficulty: str | None = None) -> None:
    image = illustration_path(
        song,
        interaction.client.settings.illust_hires_dir,
        interaction.client.settings.illust_dir,
    )
    filename = attachment_name(song) if image else None
    kwargs: dict = {"ephemeral": ephemeral}
    if image and filename:
        kwargs["file"] = discord.File(image, filename=filename)
    await interaction.followup.send(song_text(song, cache=cache, difficulty=difficulty), **kwargs)
