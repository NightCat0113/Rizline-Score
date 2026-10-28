"""Live commands: /asyncombat and /weekly. /rizcard is disabled."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.security.redaction import log_safe
from bot.services import rizline_api
from bot.services.asyncombat import map_weekly_rank
from bot.services.language import user_language
from bot.services.profile import local_profile
from bot.services.weekly_tasks import map_weekly_tasks
from bot.ui.asyncombat_image import render_asyncombat
from bot.ui.weekly_view import WeeklyTaskView
from rizline.client import RizlineError


logger = logging.getLogger("rizline.bot")
_SESSION_GONE = "The in-memory session is gone. Run /bind again."
_FETCH_FAILED = "Rizline did not return this. Run /bind again if the session expired."


class LiveCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _too_fast(self, interaction: discord.Interaction) -> bool:
        return not interaction.client.limiter.allow(f"live:{interaction.user.id}", 4, 30)

    async def _session(self, interaction: discord.Interaction):
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many live lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return None
        session = interaction.client.sessions.get(interaction.user.id)
        if session is None:
            await interaction.response.send_message(_SESSION_GONE, ephemeral=True)
            return None
        return session

    def _profile(self, interaction: discord.Interaction) -> tuple[str, dict]:
        cache: dict = {}
        try:
            loaded = interaction.client.db.get_cache(interaction.user.id)
            if isinstance(loaded, dict):
                cache = loaded
        except Exception:
            cache = {}
        username = str(cache.get("username") or "").strip() or "Player"
        card = dict(cache)
        for key, value in local_profile(interaction.client.settings.repo_root, username).items():
            if not card.get(key):
                card[key] = value
        return username, card

    @app_commands.command(name="asyncombat", description="Show your live Asyncombat ranks")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def asyncombat(self, interaction: discord.Interaction) -> None:
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=False)
        secrets = (session.email, session.token, session.device_id)
        try:
            payload = await rizline_api.weekly_rank(session.email, session.token, session.device_id)
            view = map_weekly_rank(payload)
            username, card = self._profile(interaction)
            settings = interaction.client.settings
            png = await asyncio.to_thread(
                render_asyncombat,
                view,
                username=username,
                font_path=settings.font_path,
                card=card,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                repo_root=settings.repo_root,
                language=user_language(interaction.client.db, interaction.user.id),
                total_rks=float(card.get("totalRks") or 0),
            )
        except RizlineError as exc:
            log_safe(logging.WARNING, "asyncombat failed type=%s detail=%s", type(exc).__name__, str(exc), secrets=secrets)
            await interaction.followup.send(_FETCH_FAILED)
            return
        except Exception as exc:
            logger.error("asyncombat image failed type=%s", type(exc).__name__)
            await interaction.followup.send("Something went wrong. The details were not included here.")
            return
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="asyncombat.png"))

    @app_commands.command(name="weekly", description="Show your weekly task progress")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=False)
        secrets = (session.email, session.token, session.device_id)
        try:
            payload = await rizline_api.weekly_tasks(session.email, session.token, session.device_id)
            language = user_language(interaction.client.db, interaction.user.id)
            board = map_weekly_tasks(
                payload,
                language=language,
                repo_root=interaction.client.settings.repo_root,
            )
        except RizlineError as exc:
            log_safe(logging.WARNING, "weekly failed type=%s detail=%s", type(exc).__name__, str(exc), secrets=secrets)
            await interaction.followup.send(_FETCH_FAILED)
            return
        view = WeeklyTaskView(
            owner_id=interaction.user.id,
            board=board,
            language=language,
        )
        await interaction.followup.send(view.render(), view=view)
