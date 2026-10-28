from bot.commands.help import HelpCog, help_text


def test_help_text_lists_the_main_commands():
    text = help_text({})
    for name in ("song", "series", "bind", "score", "profile", "b40", "refresh", "share", "unbind", "language"):
        assert f"`/{name}`" in text
    for name in ("recommend", "achievements", "asyncombat", "weekly"):
        assert f"`/{name}`" in text
    assert "`/rizcard`" not in text
    assert "reload-data" not in text


def test_help_text_uses_clickable_mentions_when_ids_are_known():
    text = help_text({"song": 123456789})
    assert "</song:123456789>" in text
    assert "</series:" not in text


def test_help_command_has_no_dm_check():
    checks = [getattr(check, "__qualname__", "") for check in HelpCog.help.checks]
    assert not any("dm_only" in name for name in checks)

