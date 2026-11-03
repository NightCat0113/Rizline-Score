"""The /help command: what this bot can do and how to use it."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


_INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1562086860988223568"
_COMMANDS_URL = "https://github.com/NightCat0113/Rizline-Score/blob/main/COMMANDS.md"
_PRIVACY_URL = "https://github.com/NightCat0113/Rizline-Score/blob/main/PRIVACY.md"
_TERMS_URL = "https://github.com/NightCat0113/Rizline-Score/blob/main/TERMS.md"


def _mention(name: str, command_ids: dict[str, int]) -> str:
    command_id = command_ids.get(name)
    return f"</{name}:{command_id}>" if command_id else f"`/{name}`"


def help_parts(command_ids: dict[str, int]) -> tuple[str, list[tuple[str, str]], str]:
    """Title description, labeled sections, and footer for /help."""

    def mention(name: str) -> str:
        return _mention(name, command_ids)

    description = "\n".join(
        [
            "An unofficial fan Discord bot for Rizline, run by one person. "
            "It is not affiliated with Pigeon Games or with Discord. "
            "Game songs, art, and names stay with their copyright holders.",
            "",
            "**How to start**",
            f"1. Add the bot: {_INVITE_URL}",
            "2. Commands work in a server, a DM, or a group chat.",
            f"3. Song lookups need no account. For your scores, run {mention('bind')} once.",
            f"4. After you play, run {mention('refresh')} so the saved scores update.",
        ]
    )
    sections = [
        (
            "Who can see a reply",
            "\n".join(
                [
                    "The reply shows in the channel where you ran the command.",
                    "Set `private` when only you should see that reply.",
                    f"{mention('bind')}, {mention('unbind')}, and {mention('help')} stay hidden.",
                    f"{mention('share')} and {mention('language')} confirm in the channel.",
                    f"Another person can open your {mention('profile')} only after you turn sharing on. People reading the channel can still see a reply that is not private.",
                ]
            ),
        ),
        (
            "Songs — no account",
            "\n".join(
                [
                    f"{mention('song')} `title` — Song and charts. Your scores appear on the card after you bind",
                    f"{mention('arts')} `title` — Jacket images, including Special arts",
                    f"{mention('series')} `name` — One track series",
                    f"{mention('random')} — A random chart. Optional difficulty and level range",
                    f"{mention('charts')} `min` `max` — Charts between two constants. Optional difficulty",
                    f"{mention('collection')} — Bios, layouts, and arts. Owned and Missing need {mention('bind')}",
                ]
            ),
        ),
        (
            "Your scores — bind first",
            "\n".join(
                [
                    f"{mention('bind')} — Sign in with your Rizline email. Use your password, or type `code` for an email code. The form stays hidden",
                    f"{mention('refresh')} — Download your scores again",
                    f"{mention('profile')} — Your RKS and top charts. Name someone else only after they use {mention('share')} on",
                    f"{mention('b40')} — Your AH5 and B35 as one image",
                    f"{mention('recommend')} — Score targets that raise your RKS",
                    f"{mention('achievements')} — Your achievement list. Filter: All, Unlocked, or Locked",
                ]
            ),
        ),
        (
            "Live data — saved login",
            "\n".join(
                [
                    f"{mention('asyncombat')} — Your current Asyncombat ranks",
                    f"{mention('weekly')} — Your weekly tasks",
                    (
                        f"These use the login from {mention('bind')}. "
                        f"It lasts 14 days after a successful {mention('bind')}, {mention('refresh')}, "
                        f"{mention('asyncombat')}, or {mention('weekly')}. "
                        "It is stored encrypted and survives a restart. "
                        "Your password and email code are not saved."
                    ),
                ]
            ),
        ),
        (
            "Account",
            "\n".join(
                [
                    f"{mention('share')} `on` / `off` — Let other bot users open your {mention('profile')}, or stop that. Off is the default. They only see a cache that is still valid",
                    f"{mention('language')} — Words on card images: English, 简体中文, 繁體中文, or 日本語",
                    f"{mention('unbind')} — Delete your binding, cached scores, and saved login. Your language choice stays until you ask for it to be removed",
                ]
            ),
        ),
        (
            "Policies",
            "\n".join(
                [
                    "Using this bot means you agree to the privacy policy and the terms of service.",
                    "The operator does not own the game assets. The bot's code is AI-generated.",
                    f"How to use it: {_COMMANDS_URL}",
                    f"Privacy: {_PRIVACY_URL}",
                    f"Terms: {_TERMS_URL}",
                ]
            ),
        ),
    ]
    footer = "Email: nightwind0112@gmail.com · Discord: @nightwind.nightcat"
    return description, sections, footer


def help_embed(command_ids: dict[str, int]) -> discord.Embed:
    description, sections, footer = help_parts(command_ids)
    embed = discord.Embed(title="Rizline Lookup", description=description)
    for name, value in sections:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=footer)
    return embed


def help_text(command_ids: dict[str, int]) -> str:
    """Flat copy of the help embed, for tests and anywhere an embed cannot be read."""
    description, sections, footer = help_parts(command_ids)
    parts = ["**Rizline Lookup**", description]
    for name, value in sections:
        parts.extend(["", f"**{name}**", value])
    parts.extend(["", footer])
    return "\n".join(parts)


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show what this bot can do and how to use it")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def help(self, interaction: discord.Interaction) -> None:
        command_ids = getattr(interaction.client, "command_ids", {}) or {}
        await interaction.response.send_message(embed=help_embed(command_ids), ephemeral=True)
