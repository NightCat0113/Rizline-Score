"""The /help command: what this bot can do and how to use it."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


def _mention(name: str, command_ids: dict[str, int]) -> str:
    command_id = command_ids.get(name)
    return f"</{name}:{command_id}>" if command_id else f"`/{name}`"


def help_text(command_ids: dict[str, int]) -> str:
    def mention(name: str) -> str:
        return _mention(name, command_ids)

    return "\n".join(
        [
            "**Rizline Lookup**",
            "An unofficial fan Discord bot for Rizline. "
            "It looks up songs, series, scores, Best 40, recommendations, achievements, Asyncombat, and weekly tasks. "
            "It is not affiliated with the Rizline publisher or Discord.",
            "",
            "Commands work **anywhere** after you add the bot. "
            "Song lookups need no account. Score lookups need `/bind` first. "
            "Replies are public unless you set `private`. "
            "`/bind`, `/unbind`, and `/help` stay private to you. "
            "Sessions are stored encrypted, survive restarts, and last 14 days after a successful live call.",
            "",
            "**Songs (no account needed)**",
            f"{mention('song')} `title` — Look up a song and its charts",
            f"{mention('series')} `name` — Look up a track series",
            f"{mention('random')} — Random chart",
            f"{mention('charts')} `min` `max` — Charts in a constant range",
            "",
            "**Your scores (bind first)**",
            f"{mention('bind')} — Bind your Rizline email",
            f"{mention('profile')} — Your RKS and top charts",
            f"{mention('recommend')} — Score targets that raise RKS",
            f"{mention('achievements')} — Browse your achievement checklist",
            f"{mention('b40')} — Your AH5 and B35 charts",
            f"{mention('asyncombat')} — Live Asyncombat ranks",
            f"{mention('weekly')} — Weekly task progress",
            f"{mention('refresh')} — Fetch your scores again after playing",
            "",
            "**Account and settings**",
            f"{mention('share')} `on/off` — Let other people see your scores",
            f"{mention('unbind')} — Delete your binding and cached scores",
            f"{mention('language')} — Set the language used on your card images",
            "",
            "**Policies**",
            "Using this bot means you agree to:",
            "Privacy Policy: https://github.com/NightCat0113/Rizline-Score/blob/main/PRIVACY.md",
            "ToS: https://github.com/NightCat0113/Rizline-Score/blob/main/TERMS.md",
            "",
            "**Contact**",
            "Email: nightwind0112@gmail.com",
            "Discord: @nightwind.nightcat",
        ]
    )



class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show what this bot can do and how to use it")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def help(self, interaction: discord.Interaction) -> None:
        command_ids = getattr(interaction.client, "command_ids", {}) or {}
        await interaction.response.send_message(help_text(command_ids), ephemeral=True)
