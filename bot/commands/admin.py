"""Owner-only maintenance commands."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import caller_is_owner, dm_only
from bot.services.github_actions import GitHubActionsError, dispatch_workflow
from bot.services.songdata import SongIndex


logger = logging.getLogger("rizline.bot")

_PIPELINE_HOST_HINT = (
    "This host cannot run the Unity download pipeline locally.\n"
    "Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` in `.env` so `/refresh-game-data` "
    "can start the GitHub Actions refresh workflow, or run the pipeline on your PC "
    "and push. New jackets still need a full art pack upload."
)


def _refresh_blocked_reason(repo_root: Path, pipeline: Path, index_builder: Path) -> str | None:
    if not pipeline.is_file():
        return (
            "Cannot download game data: `tools/pipelines/Riz_bundle.py` is not on this host.\n"
            + _PIPELINE_HOST_HINT
        )
    if not index_builder.is_file():
        return "Cannot rebuild the song index: `tools/build_songs_index.py` is missing."
    missing = [name for name in ("UnityPy", "requests") if importlib.util.find_spec(name) is None]
    if missing:
        return (
            "Cannot download game data on this host: missing "
            + ", ".join(f"`{name}`" for name in missing)
            + ".\n"
            + _PIPELINE_HOST_HINT
        )
    return None


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
        description="Refresh the song catalog (local pipeline or GitHub Actions)",
    )
    @dm_only()
    async def refresh_game_data(self, interaction: discord.Interaction) -> None:
        if not caller_is_owner(interaction.client, interaction.user.id):
            await interaction.response.send_message("That command is limited to the bot owner.", ephemeral=True)
            return

        if self._refreshing:
            await interaction.response.send_message("A game data update is already running.", ephemeral=True)
            return

        settings = interaction.client.settings
        repo_root = settings.repo_root
        pipeline = Path(settings.pipeline_script)
        index_builder = repo_root / "tools" / "build_songs_index.py"
        blocked = _refresh_blocked_reason(repo_root, pipeline, index_builder)
        if blocked is not None:
            if settings.github_dispatch_configured:
                await self._dispatch_github_refresh(interaction)
                return
            await interaction.response.send_message(blocked, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        self._refreshing = True
        py_exe = sys.executable

        try:
            proc_bundle = await asyncio.create_subprocess_exec(
                py_exe,
                str(pipeline),
                cwd=str(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _out_bundle, err_bundle = await proc_bundle.communicate()
            if proc_bundle.returncode != 0:
                err_text = err_bundle.decode("utf-8", errors="replace")[-500:]
                logger.error("Riz_bundle.py failed code=%s: %s", proc_bundle.returncode, err_text)
                await interaction.followup.send(
                    f"Failed running `Riz_bundle.py` (exit code {proc_bundle.returncode}).\n```{err_text}```",
                    ephemeral=True,
                )
                return

            proc_index = await asyncio.create_subprocess_exec(
                py_exe,
                str(index_builder),
                cwd=str(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _out_index, err_index = await proc_index.communicate()
            if proc_index.returncode != 0:
                err_text = err_index.decode("utf-8", errors="replace")[-500:]
                logger.error("build_songs_index.py failed code=%s: %s", proc_index.returncode, err_text)
                await interaction.followup.send(
                    f"Failed running `build_songs_index.py` (exit code {proc_index.returncode}).\n```{err_text}```",
                    ephemeral=True,
                )
                return

            path = settings.songs_index_path
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

    async def _dispatch_github_refresh(self, interaction: discord.Interaction) -> None:
        settings = interaction.client.settings
        await interaction.response.defer(ephemeral=True)
        self._refreshing = True
        try:
            await asyncio.to_thread(
                dispatch_workflow,
                token=settings.github_token,
                repository=settings.github_repository,
                workflow=settings.github_workflow,
                ref=settings.github_ref,
            )
        except GitHubActionsError as exc:
            logger.warning("github refresh dispatch failed: %s", exc)
            await interaction.followup.send(
                f"Could not start the GitHub refresh workflow.\n{exc}",
                ephemeral=True,
            )
            return
        finally:
            self._refreshing = False

        repo = settings.github_repository
        await interaction.followup.send(
            "Started the **Refresh game data** GitHub Action for "
            f"`{repo}` on `{settings.github_ref}`.\n"
            "When it finishes it commits the catalog and Deploy Altare restarts the bot "
            "with the new song index. Watch Actions on GitHub; jackets for brand-new songs "
            "still need a full art pack if the cover is missing.",
            ephemeral=True,
        )
