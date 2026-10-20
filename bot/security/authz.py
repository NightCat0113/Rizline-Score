"""Server-side authorization for personal score data."""

from __future__ import annotations

from enum import Enum

import discord
from discord import app_commands


NOT_AVAILABLE = "That result is not available."
SELF_MISSING = "Bind your Rizline account with /bind, then try again."
DM_REQUIRED = "Use this command in a DM with the bot."
ALLOWLIST_DENIED = "This bot only responds to its allow list."


class Decision(Enum):
    ALLOW = "allow"
    SELF_MISSING = "self_missing"
    DENIED = "denied"


def decide_view(
    *,
    caller_id: int,
    target_id: int,
    target_has_cache: bool,
    target_sharing: bool,
) -> Decision:
    if caller_id == target_id:
        if target_has_cache:
            return Decision.ALLOW
        return Decision.SELF_MISSING
    if target_has_cache and target_sharing:
        return Decision.ALLOW
    return Decision.DENIED


def personal_denial_message(decision: Decision) -> str:
    if decision is Decision.DENIED:
        return NOT_AVAILABLE
    if decision is Decision.SELF_MISSING:
        return SELF_MISSING
    return ""


def dm_rejection(
    allowed_user_ids: frozenset[int],
    *,
    in_guild: bool,
    user_id: int,
) -> str | None:
    if in_guild:
        return DM_REQUIRED
    if allowed_user_ids and user_id not in allowed_user_ids:
        return ALLOWLIST_DENIED
    return None


def caller_is_owner(bot: discord.Client, user_id: int) -> bool:
    settings = bot.settings  # type: ignore[attr-defined]
    if settings.owner_id is not None:
        return user_id == settings.owner_id
    application = bot.application
    owner = getattr(application, "owner", None)
    if isinstance(owner, discord.User):
        return owner.id == user_id
    return False


def dm_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        settings = interaction.client.settings  # type: ignore[attr-defined]
        message = dm_rejection(
            settings.allowed_user_ids,
            in_guild=interaction.guild is not None,
            user_id=interaction.user.id,
        )
        if message:
            raise app_commands.CheckFailure(message)
        return True

    return app_commands.check(predicate)
