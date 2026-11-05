from bot.commands.help import HelpCog, help_embed, help_text


def _flat(command_ids: dict[str, int]) -> str:
    return help_text(command_ids)


def test_help_text_lists_the_main_commands():
    text = _flat({})
    assert "**Rizline Lookup**" in text
    assert "unofficial fan Discord bot" in text
    assert "copyright holders" in text
    assert "AI-generated" in text
    assert "**How to start**" in text
    assert "**Who can see a reply**" in text
    assert "Set `private`" in text
    assert "`/bind`, `/unbind`, and `/help` stay hidden" in text
    assert "only after you turn sharing on" in text
    assert "https://discord.com/oauth2/authorize?client_id=1562086860988223568" in text
    assert "https://github.com/NightCat0113/Rizline-Score/blob/main/docs/COMMANDS.md" in text
    assert "https://github.com/NightCat0113/Rizline-Score/blob/main/docs/PRIVACY.md" in text
    assert "https://github.com/NightCat0113/Rizline-Score/blob/main/docs/TERMS.md" in text
    assert "nightwind0112@gmail.com" in text
    assert "@nightwind.nightcat" in text
    for name in (
        "song",
        "arts",
        "series",
        "random",
        "charts",
        "collection",
        "bind",
        "profile",
        "b40",
        "refresh",
        "share",
        "unbind",
        "language",
    ):
        assert f"`/{name}`" in text
    for name in ("recommend", "achievements", "asyncombat", "weekly", "rizcard"):
        assert f"`/{name}`" in text
    assert "encrypted" in text
    assert "password and email code are not saved" in text
    assert "`/score`" not in text
    assert "`/whatif`" not in text
    assert "reload-data" not in text


def test_help_embed_fits_discord_even_with_command_mentions():
    ids = {
        name: 10**18
        for name in (
            "song",
            "arts",
            "series",
            "random",
            "charts",
            "collection",
            "bind",
            "profile",
            "recommend",
            "achievements",
            "b40",
            "asyncombat",
            "weekly",
            "rizcard",
            "refresh",
            "share",
            "unbind",
            "language",
            "help",
        )
    }
    embed = help_embed(ids)
    assert len(embed.title or "") <= 256
    assert len(embed.description or "") <= 4096
    assert len(embed.footer.text or "") <= 2048
    assert len(embed.fields) <= 25
    for field in embed.fields:
        assert len(field.name) <= 256
        assert len(field.value) <= 1024
    assert len(embed) <= 6000


def test_help_text_uses_clickable_mentions_when_ids_are_known():
    text = _flat({"song": 123456789})
    assert "</song:123456789>" in text
    assert "</series:" not in text


def test_help_command_has_no_dm_check():
    checks = [getattr(check, "__qualname__", "") for check in HelpCog.help.checks]
    assert not any("dm_only" in name for name in checks)


def test_help_command_replies_with_the_embed():
    import inspect

    source = inspect.getsource(HelpCog.help.callback)
    assert "embed=help_embed" in source
    assert "ephemeral=True" in source
