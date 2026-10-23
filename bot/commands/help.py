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
            "**Rizline Score Lookup**",
            "All commands work **anywhere** once you add the bot to your account. "
            "Song lookups need no account; score lookups need your Rizline account bound first.",
            "",
            "**Songs (no account needed)**",
            f"{mention('song')} `title` — Look up a song and its charts",
            f"{mention('series')} `name` — Look up a track series",
            "",
            "**Your scores (bind first)**",
            f"{mention('bind')} — Bind your Rizline account",
            f"{mention('score')} `title` — Your score for a song",
            f"{mention('profile')} — Your RKS and top charts",
            f"{mention('b40')} — Your AH5 and B35 charts",
            f"{mention('refresh')} — Fetch your scores again after playing",
            "",
            "**Account and settings**",
            f"{mention('share')} `on/off` — Let other people see your scores",
            f"{mention('unbind')} — Delete your binding and cached scores",
            f"{mention('language')} — Set the language used on your card images",
            "",
            "Tip: type / in any chat to see every command.",
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
