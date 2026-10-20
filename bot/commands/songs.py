"""Public song lookup, plus the caller's own scores when a cache exists."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.services.songdata import attachment_name, illustration_path
from bot.ui.embeds import ambiguous_embed, song_embed


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
        image = illustration_path(
            song,
            interaction.client.settings.illust_hires_dir,
            interaction.client.settings.illust_dir,
        )
        filename = attachment_name(song) if image else None
        embed = song_embed(song, cache=cache, difficulty=diff, image_name=filename)
        kwargs: dict = {"embed": embed, "ephemeral": cache is not None}
        if image and filename:
            kwargs["file"] = discord.File(image, filename=filename)
        await interaction.response.send_message(**kwargs)
