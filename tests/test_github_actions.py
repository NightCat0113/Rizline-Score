from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from bot.config import Settings
from bot.services.github_actions import GitHubActionsError, dispatch_workflow


ROOT = Path(__file__).resolve().parents[1]


def test_settings_github_dispatch_flag():
    base = {
        "DISCORD_TOKEN": "test-token",
        "BOT_ENCRYPTION_KEY": Fernet.generate_key().decode("utf-8"),
    }
    empty = Settings.from_mapping(base, repo_root=ROOT)
    assert empty.github_dispatch_configured is False
    ready = Settings.from_mapping(
        {
            **base,
            "GITHUB_TOKEN": "ghp_test",
            "GITHUB_REPOSITORY": "NightCat0113/Rizline-Score",
        },
        repo_root=ROOT,
    )
    assert ready.github_dispatch_configured is True
    assert ready.github_ref == "main"
    assert ready.github_workflow == "refresh-game-data.yml"


def test_dispatch_workflow_posts_expected_request(monkeypatch: pytest.MonkeyPatch):
    calls: list[object] = []

    class _Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=30):
        calls.append((request.full_url, request.method, request.data, dict(request.header_items())))
        return _Response()

    monkeypatch.setattr("bot.services.github_actions.urllib.request.urlopen", fake_urlopen)
    dispatch_workflow(
        token="secret-token",
        repository="NightCat0113/Rizline-Score",
        workflow="refresh-game-data.yml",
        ref="main",
    )
    assert len(calls) == 1
    url, method, data, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/actions/workflows/refresh-game-data.yml/dispatches")
    assert b'"ref": "main"' in data
    assert headers["Authorization"] == "Bearer secret-token"


def test_dispatch_rejects_bad_repository():
    with pytest.raises(GitHubActionsError):
        dispatch_workflow(token="x", repository="noslash", workflow="refresh-game-data.yml")
