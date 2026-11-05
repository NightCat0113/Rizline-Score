"""Live commands: /asyncombat, /weekly, and /rizcard."""

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
from bot.services.rizcard import has_card_art
from bot.services.weekly_tasks import map_weekly_tasks
from bot.services.sessions import is_auth_failure
from bot.ui.asyncombat_image import render_asyncombat
from bot.ui.rizcard_image import render_live_rizcard
from bot.ui.views import SESSION_EXPIRED
from bot.ui.weekly_view import WeeklyTaskView
from rizline.client import RizlineError


logger = logging.getLogger("rizline.bot")
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
            await interaction.response.send_message(SESSION_EXPIRED, ephemeral=True)
            return None
        return session

    async def _live_error(self, interaction: discord.Interaction, exc: RizlineError) -> None:
        if is_auth_failure(exc):
            interaction.client.sessions.pop(interaction.user.id)
            await interaction.followup.send(SESSION_EXPIRED, ephemeral=True)
            return
        await interaction.followup.send(_FETCH_FAILED, ephemeral=True)

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
    @app_commands.describe(private="Only you can see this reply")
    @dm_only()
    async def asyncombat(self, interaction: discord.Interaction, private: bool = False) -> None:
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=private)
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
            await self._live_error(interaction, exc)
            return
        except Exception as exc:
            logger.error("asyncombat image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                "Something went wrong. The details were not included here.",
                ephemeral=True,
            )
            return
        interaction.client.sessions.touch(interaction.user.id)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(png), filename="asyncombat.png"),
            ephemeral=private,
        )

    @app_commands.command(name="weekly", description="Show your weekly task progress")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(private="Only you can see this reply")
    @dm_only()
    async def weekly(self, interaction: discord.Interaction, private: bool = False) -> None:
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=private)
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
            await self._live_error(interaction, exc)
            return
        interaction.client.sessions.touch(interaction.user.id)
        view = WeeklyTaskView(
            owner_id=interaction.user.id,
            board=board,
            language=language,
        )
        await interaction.followup.send(view.render(), view=view, ephemeral=private)

    @app_commands.command(name="rizcard", description="Show your live Rizcard")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(private="Only you can see this reply")
    @dm_only()
    async def rizcard(self, interaction: discord.Interaction, private: bool = False) -> None:
        session = await self._session(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=private)
        secrets = (session.email, session.token, session.device_id)
        try:
            # Equipped card from a fresh rn_login — not SyncOwnRizcards (exchange inbox).
            payload = await rizline_api.equipped_rizcard(session.email, session.token, session.device_id)
            if not has_card_art(payload):
                await interaction.followup.send(_FETCH_FAILED, ephemeral=True)
                return
            username, card = self._profile(interaction)
            try:
                live_rks = float(payload["totalRks"]) if payload.get("totalRks") is not None else float(card.get("totalRks") or 0)
            except (TypeError, ValueError, KeyError):
                live_rks = float(card.get("totalRks") or 0)
            settings = interaction.client.settings
            png = await asyncio.to_thread(
                render_live_rizcard,
                payload,
                username=str(payload.get("username") or username),
                total_rks=live_rks,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                font_path=settings.font_path,
                repo_root=settings.repo_root,
                language=user_language(interaction.client.db, interaction.user.id),
            )
        except RizlineError as exc:
            log_safe(logging.WARNING, "rizcard failed type=%s detail=%s", type(exc).__name__, str(exc), secrets=secrets)
            await self._live_error(interaction, exc)
            return
        except Exception as exc:
            logger.error("rizcard image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                "Something went wrong. The details were not included here.",
                ephemeral=True,
            )
            return
        interaction.client.sessions.touch(interaction.user.id)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(png), filename="rizcard.png"),
            ephemeral=private,
        )
