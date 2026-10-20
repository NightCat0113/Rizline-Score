"""Owner-only maintenance commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import caller_is_owner, dm_only
from bot.services.songdata import SongIndex


logger = logging.getLogger("rizline.bot")


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="reload-data", description="Reload the local song index")
    @dm_only()
    async def reload_data(self, interaction: discord.Interaction) -> None:
        if not caller_is_owner(interaction.client, interaction.user.id):
            await interaction.response.send_message("That command is limited to the bot owner.", ephemeral=True)
            return
        path = interaction.client.settings.songs_index_path
        if not path.is_file():
            await interaction.response.send_message(
                "The song index file is missing. Run tools/build_songs_index.py first.",
                ephemeral=True,
            )
            return
        interaction.client.songs = SongIndex.load(path)
        logger.info("Reloaded song index count=%s", len(interaction.client.songs.songs))
        await interaction.response.send_message(
            f"Reloaded {len(interaction.client.songs.songs)} songs.",
            ephemeral=True,
        )
