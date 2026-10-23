"""Personal score, profile, and B40 commands."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.songs import autocomplete_songs
from bot.security.authz import Decision, decide_view, dm_only, personal_denial_message
from bot.services.language import user_language
from bot.services.profile import local_profile
from bot.services.rks import bests_for_song, build_records, chart_track_ids, select_top40
from bot.services.songdata import attachment_name, illustration_path
from bot.store.crypto import TamperError
from bot.ui.b40_image import render_b40
from bot.ui.song_image import render_song
from bot.ui.texts import ambiguous_text, profile_text, score_text


logger = logging.getLogger("rizline.bot")


class ScoresCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _too_fast(self, interaction: discord.Interaction) -> bool:
        return not interaction.client.limiter.allow(f"lookup:{interaction.user.id}", 10, 30)

    def _load_view(self, interaction: discord.Interaction, target_id: int) -> tuple[Decision, dict | None]:
        sharing, has_cache = interaction.client.db.access_flags(target_id)
        decision = decide_view(
            caller_id=interaction.user.id,
            target_id=target_id,
            target_has_cache=has_cache,
            target_sharing=sharing,
        )
        if decision is not Decision.ALLOW:
            return decision, None
        try:
            cache = interaction.client.db.get_cache(target_id)
        except TamperError:
            return Decision.DENIED if target_id != interaction.user.id else Decision.SELF_MISSING, None
        if cache is None:
            if target_id == interaction.user.id:
                return Decision.SELF_MISSING, None
            return Decision.DENIED, None
        return Decision.ALLOW, cache

    @app_commands.command(name="score", description="Show your score for a song")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(query="Song title", user="Another person who turned sharing on")
    @app_commands.autocomplete(query=autocomplete_songs)
    @dm_only()
    async def score(
        self,
        interaction: discord.Interaction,
        query: str,
        user: discord.User | None = None,
    ) -> None:
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        target = user or interaction.user
        decision, cache = self._load_view(interaction, target.id)
        if decision is not Decision.ALLOW or cache is None:
            await interaction.response.send_message(personal_denial_message(decision), ephemeral=True)
            return
        song, candidates = interaction.client.songs.resolve(query)
        if song is None:
            message = ambiguous_text(candidates) if candidates else "No song matched"
            await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        settings = interaction.client.settings
        try:
            png = await asyncio.to_thread(
                render_song,
                song=song,
                personal=bests_for_song(cache, song.asset_id, chart_track_ids(song)),
                highlight=None,
                illust_hires_dir=settings.illust_hires_dir,
                illust_dir=settings.illust_dir,
                font_path=settings.repo_root / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
                language=user_language(interaction.client.db, interaction.user.id),
            )
        except Exception as exc:
            logger.error("song image failed type=%s", type(exc).__name__)
            image = illustration_path(song, settings.illust_hires_dir, settings.illust_dir)
            filename = attachment_name(song) if image else None
            kwargs: dict = {"ephemeral": True}
            if image and filename:
                kwargs["file"] = discord.File(image, filename=filename)
            await interaction.followup.send(score_text(song, cache), **kwargs)
            return
        username = cache.get("username") or "Your scores"
        await interaction.followup.send(
            f"**{song.title}**\n{username}",
            file=discord.File(io.BytesIO(png), filename="song.png"),
            ephemeral=True,
        )

    @app_commands.command(name="profile", description="Show RKS and top charts")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(user="Another person who turned sharing on")
    @dm_only()
    async def profile(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
    ) -> None:
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        target = user or interaction.user
        decision, cache = self._load_view(interaction, target.id)
        if decision is not Decision.ALLOW or cache is None:
            await interaction.response.send_message(personal_denial_message(decision), ephemeral=True)
            return
        await interaction.response.send_message(
            profile_text(cache, interaction.client.songs),
            ephemeral=True,
        )

    @app_commands.command(name="b40", description="Show your AH5 and B35 charts")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def b40(self, interaction: discord.Interaction) -> None:
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.",
                ephemeral=True,
            )
            return
        decision, cache = self._load_view(interaction, interaction.user.id)
        if decision is not Decision.ALLOW or cache is None:
            await interaction.response.send_message(personal_denial_message(decision), ephemeral=True)
            return
        await interaction.response.defer()
        records, _missing = build_records(cache, interaction.client.songs)
        special, ordinary, overflow = select_top40(records)
        username = str(cache.get("username") or "Player")
        total = float(cache.get("totalRks") or 0)
        card = self._with_local_card(interaction, cache, username)
        try:
            png = await asyncio.to_thread(
                render_b40,
                username=username,
                total_rks=total,
                special=special,
                ordinary=ordinary,
                overflow=overflow,
                index=interaction.client.songs,
                illust_hires_dir=interaction.client.settings.illust_hires_dir,
                illust_dir=interaction.client.settings.illust_dir,
                font_path=interaction.client.settings.repo_root
                / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
                repo_root=interaction.client.settings.repo_root,
                card=card,
                language=user_language(interaction.client.db, interaction.user.id),
            )
        except Exception as exc:
            logger.error("b40 image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                "Something went wrong. The details were not included here.",
            )
            return
        await interaction.followup.send(
            f"**{username}**\nRKS {total:.2f}",
            file=discord.File(io.BytesIO(png), filename="b40.png"),
        )

    @app_commands.command(name="rizcard", description="Show your Rizcard")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def rizcard(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Rizcard is turned off.", ephemeral=True)

    def _with_local_card(self, interaction: discord.Interaction, cache: dict, username: str) -> dict:
        card = dict(cache)
        if card.get("layoutId") and card.get("avatarId"):
            return card
        found = local_profile(interaction.client.settings.repo_root, username)
        if not found:
            return card
        for key, value in found.items():
            if not card.get(key):
                card[key] = value
        try:
            interaction.client.db.put_cache(
                interaction.user.id,
                card,
                interaction.client.settings.cache_ttl,
            )
        except Exception as exc:
            logger.error("profile cache update failed type=%s", type(exc).__name__)
        return card
