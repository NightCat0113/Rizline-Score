"""Public song lookup, plus the caller's own scores when a cache exists."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.services.rks import bests_for_song
from bot.services.songdata import attachment_name, illustration_path
from bot.ui.embeds import COLOR, ambiguous_embed, song_embed
from bot.ui.song_image import render_song


logger = logging.getLogger("rizline.bot")

_DIFFICULTIES = [
    app_commands.Choice(name=name, value=name) for name in ("EZ", "HD", "IN", "AT")
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
        ephemeral = cache is not None
        await interaction.response.defer(ephemeral=ephemeral)
        settings = interaction.client.settings
        try:
            png = await asyncio.to_thread(
                render_song,
                song=song,
                personal=bests_for_song(cache, song.asset_id) if cache else {},
                highlight=diff,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                font_path=settings.repo_root / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
            )
        except Exception as exc:
            logger.error("song image failed type=%s", type(exc).__name__)
            await _send_text_song(interaction, song, cache, diff, ephemeral)
            return
        embed = discord.Embed(title=song.title, color=COLOR)
        embed.set_image(url="attachment://song.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(io.BytesIO(png), filename="song.png"),
            ephemeral=ephemeral,
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
