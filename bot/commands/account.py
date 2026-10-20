"""Account bind, unbind, share, and refresh."""

from __future__ import annotations

import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from bot.models import Session
from bot.security.authz import dm_only
from bot.security.redaction import log_safe
from bot.services import rizline_api
from bot.ui.views import (
    BIND_ASK_CODE,
    BIND_ASK_SECRET,
    BIND_PUBLIC_REPLY,
    SHARE_OFF,
    SHARE_ON,
    UNBIND_EMPTY,
    UNBIND_REMOVED,
)
from rizline_client import RizlineError, scrub


logger = logging.getLogger("rizline.bot")
_BIND_TTL_SECONDS = 300


class AccountCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._pending: dict[int, dict] = {}

    @app_commands.command(name="bind", description="Bind your Rizline account in a DM")
    @dm_only()
    async def bind(self, interaction: discord.Interaction) -> None:
        if not interaction.client.limiter.allow(f"bind-start:{interaction.user.id}", 3, 600):
            await interaction.response.send_message(
                "Too many bind attempts. Wait a few minutes and try again.",
                ephemeral=True,
            )
            return
        self._pending[interaction.user.id] = {
            "step": "email",
            "email": "",
            "device_id": str(uuid.uuid4()),
            "expires": time.monotonic() + _BIND_TTL_SECONDS,
        }
        await interaction.response.send_message(BIND_PUBLIC_REPLY)

    @app_commands.command(name="unbind", description="Delete your binding, cache, and in-memory session")
    @dm_only()
    async def unbind(self, interaction: discord.Interaction) -> None:
        removed = interaction.client.db.unbind(interaction.user.id)
        interaction.client.sessions.pop(interaction.user.id)
        self._pending.pop(interaction.user.id, None)
        await interaction.response.send_message(
            UNBIND_REMOVED if removed else UNBIND_EMPTY,
            ephemeral=True,
        )

    @app_commands.command(name="share", description="Allow or block other people looking up your scores")
    @app_commands.describe(state="on lets other people who use this bot see your scores")
    @app_commands.choices(
        state=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
    @dm_only()
    async def share(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        updated = interaction.client.db.set_sharing(interaction.user.id, state.value == "on")
        if not updated:
            await interaction.response.send_message(
                "Bind your Rizline account with /bind, then try again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            SHARE_ON if state.value == "on" else SHARE_OFF,
            ephemeral=True,
        )

    @app_commands.command(name="refresh", description="Fetch your scores again with the in-memory session")
    @dm_only()
    async def refresh(self, interaction: discord.Interaction) -> None:
        if not interaction.client.limiter.allow(f"refresh:{interaction.user.id}", 1, 30):
            await interaction.response.send_message(
                "Wait a moment before refreshing again.",
                ephemeral=True,
            )
            return
        session = interaction.client.sessions.get(interaction.user.id)
        if session is None:
            await interaction.response.send_message(
                "The in-memory session is gone. Run /bind again.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        secrets = (session.email, session.token)
        try:
            cache = await rizline_api.fetch_cache(session.email, session.token, session.device_id)
            interaction.client.db.put_cache(
                interaction.user.id,
                cache,
                interaction.client.settings.cache_ttl,
            )
        except RizlineError as exc:
            log_safe(logging.WARNING, "refresh failed type=%s detail=%s", type(exc).__name__, scrub(str(exc), secrets))
            await interaction.followup.send(
                "The Rizline server did not return a save. Run /bind again if the session expired.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Updated scores for {cache.get('username') or 'your account'}.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is not None:
            return
        pending = self._pending.get(message.author.id)
        if pending is None:
            return
        if not self.bot.limiter.allow(f"bind-msg:{message.author.id}", 8, 60):
            await message.channel.send("Too many replies. Wait a moment, or send `cancel`.")
            return
        if time.monotonic() > pending["expires"]:
            self._pending.pop(message.author.id, None)
            await message.channel.send("That bind expired. Run /bind again.")
            return
        if not self._user_allowed(message.author.id):
            self._pending.pop(message.author.id, None)
            await message.channel.send("This bot only responds to its allow list.")
            return
        text = (message.content or "").strip()
        if not text:
            await message.channel.send("Reply with text, or send `cancel`.")
            return
        if len(text) > 500:
            await message.channel.send("That reply is too long. Send `cancel` to stop.")
            return
        if text.lower() == "cancel":
            self._pending.pop(message.author.id, None)
            await message.channel.send("Bind cancelled. Nothing from this attempt was saved.")
            return
        try:
            if pending["step"] == "email":
                await self._accept_email(message, pending, text)
            elif pending["step"] == "secret":
                await self._accept_secret(message, pending, text)
            elif pending["step"] == "code":
                await self._accept_code(message, pending, text)
        except Exception:
            logger.error("DM bind failed type=unexpected")
            await message.channel.send("The bind could not be completed. Run /bind to try again.")
            self._pending.pop(message.author.id, None)

    def _user_allowed(self, user_id: int) -> bool:
        allowed = self.bot.settings.allowed_user_ids
        return not allowed or user_id in allowed

    async def _accept_email(self, message: discord.Message, pending: dict, text: str) -> None:
        if "@" not in text or len(text) > 254:
            await message.channel.send("Reply with the account email, or send `cancel`.")
            return
        pending["email"] = text
        pending["step"] = "secret"
        await message.channel.send(BIND_ASK_SECRET)

    async def _accept_secret(self, message: discord.Message, pending: dict, text: str) -> None:
        if text.lower() == "code":
            try:
                pending["device_id"] = await rizline_api.send_email_code(pending["email"], pending["device_id"])
            except RizlineError as exc:
                log_safe(
                    logging.WARNING,
                    "send code failed type=%s detail=%s",
                    type(exc).__name__,
                    scrub(str(exc), (pending["email"],)),
                )
                await message.channel.send("The verification email could not be requested. Send `cancel` or try the passcode.")
                return
            pending["step"] = "code"
            await message.channel.send(BIND_ASK_CODE)
            return
        await self._finish_login(message, pending, text, using_code=False)

    async def _accept_code(self, message: discord.Message, pending: dict, text: str) -> None:
        await self._finish_login(message, pending, text, using_code=True)

    async def _finish_login(
        self,
        message: discord.Message,
        pending: dict,
        secret: str,
        *,
        using_code: bool,
    ) -> None:
        email = pending["email"]
        device_id = pending["device_id"]
        secrets = (email, secret)
        try:
            if using_code:
                result = await rizline_api.login_code(email, secret, device_id)
            else:
                result = await rizline_api.login_passcode(email, secret, device_id)
            cache = await rizline_api.fetch_cache(email, result.token, result.device_id)
        except RizlineError as exc:
            log_safe(
                logging.WARNING,
                "bind login failed type=%s detail=%s",
                type(exc).__name__,
                scrub(str(exc), secrets),
            )
            retry = "Reply with the code again, or send `cancel`." if using_code else (
                "Reply with the passcode again, send `code`, or send `cancel`."
            )
            await message.channel.send(f"That login did not work. {retry}")
            return
        finally:
            secret = ""
        self.bot.db.put_cache(message.author.id, cache, self.bot.settings.cache_ttl)
        self.bot.sessions.put(
            message.author.id,
            Session(email=email, token=result.token, device_id=result.device_id),
        )
        self._pending.pop(message.author.id, None)
        username = cache.get("username") or "your account"
        await message.channel.send(
            f"Bound as {username}. The session token stays in memory until /unbind or a restart. "
            "Use /unbind to delete the cache. You can delete the messages you sent in this DM."
        )
