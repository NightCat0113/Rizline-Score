"""Owner-only maintenance commands."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import caller_is_owner, dm_only
from bot.services.songdata import SongIndex


logger = logging.getLogger("rizline.bot")


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._refreshing = False

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

    @app_commands.command(
        name="refresh-game-data",
        description="Download latest game resources, rebuild songs index, and reload (Owner only)",
    )
    @dm_only()
    async def refresh_game_data(self, interaction: discord.Interaction) -> None:
        if not caller_is_owner(interaction.client, interaction.user.id):
            await interaction.response.send_message("That command is limited to the bot owner.", ephemeral=True)
            return

        if self._refreshing:
            await interaction.response.send_message("A game data update is already running.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        self._refreshing = True

        repo_root = interaction.client.settings.repo_root
        py_exe = sys.executable

        try:
            # 1. Run Riz_bundle.py to fetch catalog and export assets
            proc_bundle = await asyncio.create_subprocess_exec(
                py_exe,
                str(repo_root / "Riz_bundle.py"),
                cwd=str(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out_bundle, err_bundle = await proc_bundle.communicate()
            if proc_bundle.returncode != 0:
                err_text = err_bundle.decode("utf-8", errors="replace")[-500:]
                logger.error("Riz_bundle.py failed code=%s: %s", proc_bundle.returncode, err_text)
                await interaction.followup.send(
                    f"Failed running `Riz_bundle.py` (exit code {proc_bundle.returncode}).\n```{err_text}```",
                    ephemeral=True,
                )
                return

            # 2. Run tools/build_songs_index.py to rebuild bot/static/songs_index.json
            proc_index = await asyncio.create_subprocess_exec(
                py_exe,
                str(repo_root / "tools" / "build_songs_index.py"),
                cwd=str(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out_index, err_index = await proc_index.communicate()
            if proc_index.returncode != 0:
                err_text = err_index.decode("utf-8", errors="replace")[-500:]
                logger.error("build_songs_index.py failed code=%s: %s", proc_index.returncode, err_text)
                await interaction.followup.send(
                    f"Failed running `build_songs_index.py` (exit code {proc_index.returncode}).\n```{err_text}```",
                    ephemeral=True,
                )
                return

            # 3. Reload in-memory SongIndex
            path = interaction.client.settings.songs_index_path
            if path.is_file():
                interaction.client.songs = SongIndex.load(path)
                count = len(interaction.client.songs.songs)
                logger.info("Successfully updated game data and reloaded %s songs.", count)
                await interaction.followup.send(
                    f"Successfully updated game data and reloaded {count} songs!",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Game data update completed, but songs_index.json was not found.",
                    ephemeral=True,
                )
        except Exception as exc:
            logger.exception("refresh_game_data error: %s", exc)
            await interaction.followup.send(f"An unexpected error occurred: {exc}", ephemeral=True)
        finally:
            self._refreshing = False

