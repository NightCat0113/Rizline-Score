"""Discord client setup."""

from __future__ import annotations

import logging
import sys

import discord
from discord import app_commands
from discord.ext import commands

from bot.commands.account import AccountCog
from bot.commands.admin import AdminCog
from bot.commands.help import HelpCog
from bot.commands.live import LiveCog
from bot.commands.preferences import PreferencesCog
from bot.commands.scores import ScoresCog
from bot.commands.songs import SongsCog
from bot.config import ConfigError, Settings
from bot.security.ratelimit import RateLimiter
from bot.services.sessions import SessionStore
from bot.services.songdata import SongIndex
from bot.store.crypto import CryptoBox, MissingKeyError
from bot.store.db import Database, StorageError


logger = logging.getLogger("rizline.bot")


class RizlineBot(commands.Bot):
    def __init__(self, settings: Settings, songs: SongIndex, database: Database) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            activity=discord.Activity(type=discord.ActivityType.listening, name="/help in a DM"),
        )
        self.settings = settings
        self.songs = songs
        self.db = database
        self.sessions = SessionStore()
        self.limiter = RateLimiter()
        self.command_ids: dict[str, int] = {}

    async def setup_hook(self) -> None:
        await self.add_cog(AccountCog(self))
        await self.add_cog(PreferencesCog(self))
        await self.add_cog(SongsCog(self))
        await self.add_cog(ScoresCog(self))
        await self.add_cog(LiveCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(HelpCog(self))
        synced = await self.tree.sync()
        self.command_ids = {command.name: command.id for command in synced}
        logger.info(
            "Synced global commands. They can take up to an hour to appear in DMs the first time."
        )

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def on_error(self, event_method: str, /, *args, **kwargs) -> None:
        logger.error("event %s failed", event_method)


async def _on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    cause = getattr(error, "original", error)
    if isinstance(error, app_commands.CheckFailure):
        message = str(error) or "That command is not available."
    else:
        logger.error("command error type=%s", type(cause).__name__)
        message = "Something went wrong. The details were not included here."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def build_bot(settings: Settings) -> RizlineBot:
    if not settings.songs_index_path.is_file():
        raise StorageError("Song index is missing. Run tools/build_songs_index.py first.")
    try:
        crypto = CryptoBox(settings.encryption_key)
    except MissingKeyError as exc:
        raise StorageError(str(exc)) from exc
    database = Database(settings.db_path, crypto)
    songs = SongIndex.load(settings.songs_index_path)
    bot = RizlineBot(settings, songs, database)
    bot.tree.on_error = _on_app_command_error
    return bot


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    try:
        settings = Settings.load()
        bot = build_bot(settings)
    except (ConfigError, StorageError, MissingKeyError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
    logger.info("Starting bot. Commands are DM-only and need the Message Content intent.")
    bot.run(settings.discord_token, log_handler=None)
