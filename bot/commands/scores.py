"""Personal score, profile, and B40 commands."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.songs import _DIFFICULTIES, autocomplete_songs
from bot.security.authz import Decision, decide_view, dm_only, personal_denial_message
from bot.services.rks import build_records, select_top40
from bot.services.songdata import attachment_name, illustration_path
from bot.store.crypto import TamperError
from bot.ui.b40_image import render_b40
from bot.ui.embeds import COLOR, ambiguous_embed, profile_embed, score_embed


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
    @app_commands.describe(query="Song title", difficulty="Optional chart difficulty", user="Another person who turned sharing on")
    @app_commands.autocomplete(query=autocomplete_songs)
    @app_commands.choices(difficulty=_DIFFICULTIES)
    @dm_only()
    async def score(
        self,
        interaction: discord.Interaction,
        query: str,
        difficulty: app_commands.Choice[str] | None = None,
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
            embed = ambiguous_embed(candidates) if candidates else discord.Embed(title="No song matched")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        diff = difficulty.value if difficulty else None
        image = illustration_path(
            song,
            interaction.client.settings.illust_hires_dir,
            interaction.client.settings.illust_dir,
        )
        filename = attachment_name(song) if image else None
        kwargs: dict = {
            "embed": score_embed(song, cache, diff, image_name=filename),
            "ephemeral": True,
        }
        if image and filename:
            kwargs["file"] = discord.File(image, filename=filename)
        await interaction.response.send_message(**kwargs)

    @app_commands.command(name="profile", description="Show RKS and top charts")
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
            embed=profile_embed(cache, interaction.client.songs),
            ephemeral=True,
        )

    @app_commands.command(name="b40", description="Show your AH5 and B35 charts")
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
        await interaction.response.defer(ephemeral=True)
        records, _missing = build_records(cache, interaction.client.songs)
        special, ordinary, overflow = select_top40(records)
        username = str(cache.get("username") or "Player")
        total = float(cache.get("totalRks") or 0)
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
            )
        except Exception as exc:
            logger.error("b40 image failed type=%s", type(exc).__name__)
            await interaction.followup.send(
                "Something went wrong. The details were not included here.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=username, description=f"RKS {total:.2f}", color=COLOR)
        embed.set_image(url="attachment://b40.png")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(io.BytesIO(png), filename="b40.png"),
            ephemeral=True,
        )
