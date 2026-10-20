from pathlib import Path

from bot.security.authz import (
    DM_REQUIRED,
    NOT_AVAILABLE,
    Decision,
    decide_view,
    dm_rejection,
    personal_denial_message,
)
from bot.security.ratelimit import RateLimiter
from bot.ui.views import UNBIND_REMOVED


ROOT = Path(__file__).resolve().parents[1]


def test_cross_user_denial_is_identical():
    unbound = decide_view(caller_id=1, target_id=2, target_has_cache=False, target_sharing=False)
    private = decide_view(caller_id=1, target_id=2, target_has_cache=True, target_sharing=False)
    expired = decide_view(caller_id=1, target_id=2, target_has_cache=False, target_sharing=True)
    assert unbound is private is expired is Decision.DENIED
    assert personal_denial_message(unbound) == personal_denial_message(private) == NOT_AVAILABLE
    assert "bind" not in NOT_AVAILABLE.lower()
    assert "share" not in NOT_AVAILABLE.lower()


def test_self_and_shared_access():
    assert decide_view(caller_id=1, target_id=1, target_has_cache=False, target_sharing=False) is Decision.SELF_MISSING
    assert decide_view(caller_id=1, target_id=1, target_has_cache=True, target_sharing=False) is Decision.ALLOW
    assert decide_view(caller_id=1, target_id=2, target_has_cache=True, target_sharing=True) is Decision.ALLOW


def test_dm_and_allowlist():
    assert dm_rejection(frozenset(), in_guild=True, user_id=1) == DM_REQUIRED
    assert dm_rejection(frozenset({2}), in_guild=False, user_id=1)
    assert dm_rejection(frozenset({1}), in_guild=False, user_id=1) is None
    assert dm_rejection(frozenset(), in_guild=False, user_id=1) is None


def test_rate_limiter():
    limiter = RateLimiter()
    assert limiter.allow("user", 1, 30, now=100)
    assert limiter.allow("user", 1, 30, now=110) is False
    assert limiter.allow("user", 1, 30, now=140)


def test_unbind_mentions_backup_limits():
    assert "VACUUM" in UNBIND_REMOVED
    assert "backups" in UNBIND_REMOVED


def test_bot_modules_import():
    import bot.app  # noqa: F401
    import bot.commands.account  # noqa: F401
    import bot.commands.scores  # noqa: F401


def test_slash_commands_register_without_network(tmp_path):
    import asyncio

    from cryptography.fernet import Fernet

    from bot.app import RizlineBot
    from bot.commands.account import AccountCog
    from bot.commands.admin import AdminCog
    from bot.commands.scores import ScoresCog
    from bot.commands.songs import SongsCog
    from bot.config import Settings
    from bot.services.songdata import SongIndex
    from bot.store.crypto import CryptoBox
    from bot.store.db import Database

    async def registered() -> set[str]:
        settings = Settings.from_mapping(
            {
                "DISCORD_TOKEN": "test-token",
                "BOT_ENCRYPTION_KEY": Fernet.generate_key().decode("utf-8"),
            },
            repo_root=ROOT,
        )
        database = Database(tmp_path / "bot.db", CryptoBox(settings.encryption_key))
        bot = RizlineBot(settings, SongIndex.load(ROOT / "bot" / "static" / "songs_index.json"), database)
        await bot.add_cog(AccountCog(bot))
        await bot.add_cog(SongsCog(bot))
        await bot.add_cog(ScoresCog(bot))
        await bot.add_cog(AdminCog(bot))
        names = {command.name for command in bot.tree.get_commands()}
        database.close()
        return names

    assert asyncio.run(registered()) == {
        "bind",
        "unbind",
        "share",
        "refresh",
        "song",
        "score",
        "profile",
        "b40",
        "reload-data",
    }
