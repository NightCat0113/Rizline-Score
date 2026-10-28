"""Personal score, profile, and B40 commands."""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import Decision, decide_view, dm_only, personal_denial_message
from bot.services.achievements import achievement_rows, unlocked_achievement_ids
from bot.services.language import user_language
from bot.services.profile import local_profile
from bot.services.recommendation import recommend_score_targets, resolve_song_filter
from bot.services.rks import build_records, select_top40
from bot.store.crypto import TamperError
from bot.ui.achievement_view import AchievementChecklistView
from bot.ui.b40_image import render_b40
from bot.ui.recommendation_view import RecommendationPlanView
from bot.ui.texts import profile_text


logger = logging.getLogger("rizline.bot")


async def autocomplete_recommend_songs(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    parts = current.split(";")
    prefix = "; ".join(part.strip() for part in parts[:-1] if part.strip())
    fragment = parts[-1].strip()
    try:
        songs = interaction.client.songs.search(fragment, limit=25)
    except Exception:
        return []
    choices = []
    for song in songs:
        value = f"{prefix}; {song.title}" if prefix else song.title
        if len(value) <= 100:
            label = f"{song.title} — {song.artist}" if song.artist else song.title
            choices.append(app_commands.Choice(name=label[:100], value=value))
    return choices


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
        )

    @app_commands.command(name="recommend", description="Find score targets to raise your RKS")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        increase="Overall RKS increase (score-only; accuracy held fixed). Leave empty for the max.",
        songs="Optional song titles separated by semicolons",
    )
    @app_commands.autocomplete(songs=autocomplete_recommend_songs)
    @dm_only()
    async def recommend(
        self,
        interaction: discord.Interaction,
        increase: app_commands.Range[float, 0.01, 10.0] | None = None,
        songs: str | None = None,
    ) -> None:
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.", ephemeral=True
            )
            return
        decision, cache = self._load_view(interaction, interaction.user.id)
        if decision is not Decision.ALLOW or cache is None:
            await interaction.response.send_message(personal_denial_message(decision), ephemeral=True)
            return
        if not cache.get("myBest"):
            await interaction.response.send_message(
                "No saved song scores were found. Run /refresh after playing and try again.",
                ephemeral=True,
            )
            return
        song_ids, filter_errors = resolve_song_filter(interaction.client.songs, songs)
        if filter_errors:
            await interaction.response.send_message("\n".join(filter_errors), ephemeral=True)
            return
        requested = None if increase is None else float(increase)
        recommendations, max_available = recommend_score_targets(
            cache, interaction.client.songs, increase=requested, song_ids=song_ids
        )
        target = "the max score-only gain" if requested is None else f"+{requested:.2f} RKS"
        if not recommendations:
            if song_ids:
                message = (
                    f"The selected songs with saved scores cannot reach {target} by score improvement "
                    f"(estimated maximum: +{max_available:.3f}). "
                    "Try selecting more scored songs or removing the filter."
                )
            else:
                message = (
                    f"Saved scores cannot reach {target} through score improvements alone "
                    f"(estimated score-only maximum: +{max_available:.3f}). "
                    "Improving accuracy or adding songs may increase RKS."
                )
            await interaction.response.send_message(message, ephemeral=True)
            return

        view = RecommendationPlanView(
            owner_id=interaction.user.id,
            increase=requested,
            rows=recommendations,
            max_available=max_available,
        )
        await interaction.response.send_message(view.render(), view=view)

    @app_commands.command(name="achievements", description="Browse your Rizline achievement checklist")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(status="Show all, unlocked, or locked achievements")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Unlocked", value="unlocked"),
            app_commands.Choice(name="Locked", value="locked"),
        ]
    )
    @dm_only()
    async def achievements(
        self,
        interaction: discord.Interaction,
        status: str = "all",
    ) -> None:
        if self._too_fast(interaction):
            await interaction.response.send_message(
                "Too many lookups. Wait a moment and try again.", ephemeral=True
            )
            return
        decision, cache = self._load_view(interaction, interaction.user.id)
        if decision is not Decision.ALLOW or cache is None:
            await interaction.response.send_message(personal_denial_message(decision), ephemeral=True)
            return
        unlocked = unlocked_achievement_ids(cache)
        if unlocked is None:
            await interaction.response.send_message(
                "Your cached scores predate achievement tracking. Run /refresh and try again.",
                ephemeral=True,
            )
            return
        language = user_language(interaction.client.db, interaction.user.id)
        all_rows = achievement_rows(interaction.client.settings.repo_root, language)
        unlocked.intersection_update(row["id"] for row in all_rows)
        mode = status
        if mode == "unlocked":
            rows = [row for row in all_rows if row["id"] in unlocked]
        elif mode == "locked":
            rows = [row for row in all_rows if row["id"] not in unlocked]
        else:
            rows = all_rows
        if not all_rows:
            await interaction.response.send_message(
                "Achievement definitions are unavailable in the local data files.", ephemeral=True
            )
            return
        view = AchievementChecklistView(
            owner_id=interaction.user.id,
            rows=rows,
            unlocked=unlocked,
            total=len(all_rows),
            language=language,
        )
        await interaction.response.send_message(view.render(), view=view)

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
                font_path=interaction.client.settings.font_path,
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

    def _with_local_card(self, interaction: discord.Interaction, cache: dict, username: str) -> dict:
        card = dict(cache)
        found = local_profile(interaction.client.settings.repo_root, username)
        if not found:
            return card
        changed = False
        for key, value in found.items():
            if not card.get(key):
                card[key] = value
                changed = True
        if changed:
            try:
                interaction.client.db.put_cache(
                    interaction.user.id,
                    card,
                    interaction.client.settings.cache_ttl,
                )
            except Exception as exc:
                logger.error("profile cache update failed type=%s", type(exc).__name__)
        return card
