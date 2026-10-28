"""Account bind, unbind, share, and refresh."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from bot.models import Session
from bot.security.authz import ALLOWLIST_DENIED, dm_only
from bot.security.redaction import log_safe
from bot.services import rizline_api
from bot.ui.views import (
    BIND_CODE_AFTER_PASSCODE,
    BIND_CODE_LABEL,
    BIND_CODE_READY,
    BIND_CODE_TITLE,
    BIND_ENTER_CODE,
    BIND_CONTINUE,
    BIND_EMAIL_LABEL,
    BIND_MODAL_TITLE,
    BIND_PASSCODE_HINT,
    BIND_PASSCODE_LABEL,
    BIND_PUBLIC_REPLY,
    SHARE_OFF,
    SHARE_ON,
    UNBIND_EMPTY,
    UNBIND_REMOVED,
)
from rizline.client import RizlineAPIError, RizlineError, scrub


logger = logging.getLogger("rizline.bot")
_BIND_TTL_SECONDS = 300
_INTRO_DELETE_SECONDS = 60
_RESULT_DELETE_SECONDS = 15
_BIND_FAILED = "The bind could not be completed. Run /bind to try again."
_LOGIN_FAILED = "That login did not work. Run /bind to try again."
_CODE_FAILED = "The verification email could not be requested. Run /bind to try again."


async def _delete_original_later(interaction: discord.Interaction, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException) as exc:
        logger.error("ephemeral delete failed type=%s", type(exc).__name__)


class _CredentialsModal(discord.ui.Modal):
    def __init__(self, cog: AccountCog) -> None:
        super().__init__(title=BIND_MODAL_TITLE, timeout=_BIND_TTL_SECONDS)
        self.cog = cog
        self.email_input = discord.ui.TextInput(required=True, max_length=254)
        self.secret_input = discord.ui.TextInput(
            required=True,
            max_length=200,
            placeholder=BIND_PASSCODE_HINT,
        )
        self.add_item(discord.ui.Label(text=BIND_EMAIL_LABEL, component=self.email_input))
        self.add_item(
            discord.ui.Label(
                text=BIND_PASSCODE_LABEL,
                description=BIND_PASSCODE_HINT,
                component=self.secret_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        secret = str(self.secret_input.value)
        try:
            await self.cog._submit_credentials(interaction, str(self.email_input.value), secret)
        finally:
            secret = ""


class _CodeModal(discord.ui.Modal):
    def __init__(self, cog: AccountCog, email: str, device_id: str, expires: float) -> None:
        super().__init__(title=BIND_CODE_TITLE, timeout=_BIND_TTL_SECONDS)
        self.cog = cog
        self.email = email
        self.device_id = device_id
        self.expires = expires
        self.code_input = discord.ui.TextInput(required=True, max_length=32)
        self.add_item(discord.ui.Label(text=BIND_CODE_LABEL, component=self.code_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        secret = str(self.code_input.value)
        try:
            await self.cog._submit_code(interaction, self.email, self.device_id, secret, self.expires)
        finally:
            secret = ""


class _EnterCode(discord.ui.View):
    def __init__(self, cog: AccountCog, email: str, device_id: str, expires: float) -> None:
        super().__init__(timeout=_BIND_TTL_SECONDS)
        self.cog = cog
        self.email = email
        self.device_id = device_id
        self.expires = expires

    @discord.ui.button(label=BIND_ENTER_CODE, style=discord.ButtonStyle.primary)
    async def open_code(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not self.cog._user_allowed(interaction.user.id):
            await self.cog._reply(interaction, ALLOWLIST_DENIED, _RESULT_DELETE_SECONDS)
            return
        if time.monotonic() > self.expires:
            await self.cog._reply(interaction, "That bind expired. Run /bind again.", _RESULT_DELETE_SECONDS)
            return
        await interaction.response.send_modal(_CodeModal(self.cog, self.email, self.device_id, self.expires))


class _BindIntro(discord.ui.View):
    def __init__(self, cog: AccountCog) -> None:
        super().__init__(timeout=_BIND_TTL_SECONDS)
        self.cog = cog

    @discord.ui.button(label=BIND_CONTINUE, style=discord.ButtonStyle.primary)
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not self.cog._user_allowed(interaction.user.id):
            await self.cog._reply(interaction, ALLOWLIST_DENIED, _RESULT_DELETE_SECONDS)
            return
        await interaction.response.send_modal(_CredentialsModal(self.cog))


class AccountCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._delete_tasks: set[asyncio.Task[None]] = set()

    def _schedule_delete(self, interaction: discord.Interaction, delay: float) -> None:
        task = asyncio.create_task(_delete_original_later(interaction, delay))
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    async def _reply(
        self,
        interaction: discord.Interaction,
        content: str,
        delay: float,
        *,
        view: discord.ui.View | None = None,
    ) -> None:
        payload: dict[str, object] = {"content": content}
        if view is not None:
            payload["view"] = view
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(**payload)
            except (discord.NotFound, discord.HTTPException) as exc:
                logger.error("bind edit failed type=%s", type(exc).__name__)
                await interaction.followup.send(ephemeral=True, **payload)
        else:
            await interaction.response.send_message(ephemeral=True, **payload)
        self._schedule_delete(interaction, delay)

    async def _defer(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

    @app_commands.command(name="bind", description="Bind your Rizline account")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def bind(self, interaction: discord.Interaction) -> None:
        if not interaction.client.limiter.allow(f"bind-start:{interaction.user.id}", 3, 600):
            await self._reply(
                interaction,
                "Too many bind attempts. Wait a few minutes and try again.",
                _RESULT_DELETE_SECONDS,
            )
            return
        await interaction.response.send_message(
            BIND_PUBLIC_REPLY,
            ephemeral=True,
            view=_BindIntro(self),
        )
        self._schedule_delete(interaction, _INTRO_DELETE_SECONDS)

    @app_commands.command(name="unbind", description="Delete your binding, cache, and in-memory session")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @dm_only()
    async def unbind(self, interaction: discord.Interaction) -> None:
        removed = interaction.client.db.unbind(interaction.user.id)
        interaction.client.sessions.pop(interaction.user.id)
        await self._reply(
            interaction,
            UNBIND_REMOVED if removed else UNBIND_EMPTY,
            _RESULT_DELETE_SECONDS,
        )

    @app_commands.command(name="share", description="Allow or block other people looking up your scores")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
        )

    @app_commands.command(name="refresh", description="Fetch your scores again with the in-memory session")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
        await interaction.response.defer(ephemeral=False)
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
        )

    def _user_allowed(self, user_id: int) -> bool:
        allowed = self.bot.settings.allowed_user_ids
        return not allowed or user_id in allowed

    async def _submit_credentials(self, interaction: discord.Interaction, email: str, secret: str) -> None:
        try:
            if not self._user_allowed(interaction.user.id):
                await self._reply(interaction, ALLOWLIST_DENIED, _RESULT_DELETE_SECONDS)
                return
            cleaned = email.strip()
            if "@" not in cleaned or len(cleaned) > 254:
                await self._reply(interaction, "Enter the account email. Nothing was saved.", _RESULT_DELETE_SECONDS)
                return
            if secret.strip().lower() == "code":
                await self._request_code(interaction, cleaned)
                return
            await self._finish_login(interaction, cleaned, secret, str(uuid.uuid4()), using_code=False)
        except Exception as exc:
            logger.error("DM bind failed type=%s", type(exc).__name__)
            await self._reply(interaction, _BIND_FAILED, _RESULT_DELETE_SECONDS)
        finally:
            secret = ""

    async def _request_code(
        self,
        interaction: discord.Interaction,
        email: str,
        *,
        after_passcode: bool = False,
    ) -> None:
        await self._defer(interaction)
        device_id = str(uuid.uuid4())
        try:
            device_id = await rizline_api.send_email_code(email, device_id)
        except RizlineError as exc:
            log_safe(
                logging.WARNING,
                "send code failed type=%s detail=%s",
                type(exc).__name__,
                scrub(str(exc), (email,)),
            )
            await self._reply(interaction, _CODE_FAILED, _RESULT_DELETE_SECONDS)
            return
        expires = time.monotonic() + _BIND_TTL_SECONDS
        message = BIND_CODE_AFTER_PASSCODE if after_passcode else BIND_CODE_READY
        await self._reply(
            interaction,
            message,
            _BIND_TTL_SECONDS,
            view=_EnterCode(self, email, device_id, expires),
        )

    async def _submit_code(
        self,
        interaction: discord.Interaction,
        email: str,
        device_id: str,
        secret: str,
        expires: float,
    ) -> None:
        try:
            if not self._user_allowed(interaction.user.id):
                await self._reply(interaction, ALLOWLIST_DENIED, _RESULT_DELETE_SECONDS)
                return
            if time.monotonic() > expires:
                await self._reply(interaction, "That bind expired. Run /bind again.", _RESULT_DELETE_SECONDS)
                return
            await self._finish_login(interaction, email, secret, device_id, using_code=True)
        except Exception as exc:
            logger.error("DM bind failed type=%s", type(exc).__name__)
            await self._reply(interaction, _BIND_FAILED, _RESULT_DELETE_SECONDS)
        finally:
            secret = ""

    async def _finish_login(
        self,
        interaction: discord.Interaction,
        email: str,
        secret: str,
        device_id: str,
        *,
        using_code: bool,
    ) -> None:
        secrets = (email, secret)
        try:
            await self._defer(interaction)
            if using_code:
                result = await rizline_api.login_code(email, secret, device_id)
            else:
                try:
                    result = await rizline_api.login_passcode(email, secret, device_id)
                except RizlineAPIError as exc:
                    # Server often rejects password when email verification is required.
                    log_safe(
                        logging.INFO,
                        "passcode login rejected type=%s detail=%s; requesting email code",
                        type(exc).__name__,
                        scrub(str(exc), secrets),
                    )
                    secret = ""
                    await self._request_code(interaction, email, after_passcode=True)
                    return
            cache = await rizline_api.fetch_cache(email, result.token, result.device_id)
        except RizlineError as exc:
            log_safe(
                logging.WARNING,
                "bind login failed type=%s detail=%s",
                type(exc).__name__,
                scrub(str(exc), secrets),
            )
            await self._reply(interaction, _LOGIN_FAILED, _RESULT_DELETE_SECONDS)
            return
        finally:
            secret = ""
        self.bot.db.put_cache(interaction.user.id, cache, self.bot.settings.cache_ttl)
        self.bot.sessions.put(
            interaction.user.id,
            Session(email=email, token=result.token, device_id=result.device_id),
        )
        username = cache.get("username") or "your account"
        await self._reply(
            interaction,
            f"Bound as {username}. The session token stays in memory until /unbind or a restart. "
            "Use /unbind to delete the cache.",
            _RESULT_DELETE_SECONDS,
        )
