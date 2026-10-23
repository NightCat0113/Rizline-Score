from bot.commands.help import HelpCog, dm_prompt_text, dm_view, help_text


def test_help_text_lists_the_main_commands():
    text = help_text({})
    for name in ("song", "series", "bind", "score", "profile", "b40", "refresh", "share", "unbind", "language"):
        assert f"`/{name}`" in text
    assert "rizcard" not in text
    assert "reload-data" not in text


def test_help_text_uses_clickable_mentions_when_ids_are_known():
    text = help_text({"song": 123456789})
    assert "</song:123456789>" in text
    assert "</series:" not in text


def test_help_command_has_no_dm_check():
    checks = [getattr(check, "__qualname__", "") for check in HelpCog.help.checks]
    assert not any("dm_only" in name for name in checks)


def test_dm_prompt_points_at_the_bot_dm():
    text = dm_prompt_text({"song": 42})
    assert "DM" in text
    assert "</song:42>" in text
    view = dm_view(987654321)
    button = view.children[0]
    assert button.url == "https://discord.com/users/987654321"
