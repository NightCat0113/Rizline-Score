"""Saved display language for card images."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.security.authz import dm_only
from bot.services.language import LANGUAGE_NAMES, normalize_language


_CHOICES = [
    app_commands.Choice(name=name, value=code) for code, name in LANGUAGE_NAMES.items()
]


class PreferencesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="language", description="Set the language used on your card images")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(language="Card image language")
    @app_commands.choices(language=_CHOICES)
    @dm_only()
    async def language(self, interaction: discord.Interaction, language: app_commands.Choice[str]) -> None:
        code = normalize_language(language.value)
        try:
            interaction.client.db.set_language(interaction.user.id, code)
        except Exception:
            await interaction.response.send_message(
                "Something went wrong. The details were not included here.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Card image language set to {LANGUAGE_NAMES[code]}. "
            "This changes the series poster and banner, and the words drawn on /series, /song, and /b40 cards.",
            ephemeral=True,
        )
