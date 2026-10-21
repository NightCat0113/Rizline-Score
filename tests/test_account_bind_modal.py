import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest

from bot.commands import account as account_module
from bot.commands.account import AccountCog, _BindIntro, _CodeModal, _CredentialsModal
from bot.security.authz import ALLOWLIST_DENIED
from bot.services.sessions import SessionStore
from bot.ui.views import BIND_PUBLIC_REPLY, UNBIND_REMOVED
from rizline_client import LoginResult, RizlineError


EMAIL = "player@example.com"
PASSCODE = "s3cret-pass"
CODE = "998877"


class _Response:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.modals: list[object] = []
        self.deferred = False
        self.defer_ephemeral = False
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str, *, ephemeral: bool = False, view: object = None) -> None:
        self._done = True
        self.messages.append({"content": content, "ephemeral": ephemeral, "view": view})

    async def send_modal(self, modal: object) -> None:
        self._done = True
        self.modals.append(modal)

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        del thinking
        self._done = True
        self.deferred = True
        self.defer_ephemeral = ephemeral


class _Channel:
    async def send(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("credentials must not be posted in the DM")


class _Interaction:
    def __init__(self, bot: object, user_id: int = 7) -> None:
        self.client = bot
        self.user = SimpleNamespace(id=user_id)
        self.response = _Response()
        self.channel = _Channel()
        self.guild = None
        self.edits: list[dict] = []
        self.deleted = 0

    async def edit_original_response(self, **kwargs: object) -> None:
        self.edits.append(kwargs)

    async def delete_original_response(self) -> None:
        self.deleted += 1

    def visible_text(self) -> str:
        parts = [item["content"] for item in self.response.messages]
        parts.extend(str(item.get("content", "")) for item in self.edits)
        return "\n".join(parts)


class _Limiter:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def allow(self, key: str, limit: int, window: int) -> bool:
        del key, limit, window
        return self.allowed


class _Database:
    def __init__(self, removed: bool = True) -> None:
        self.caches: list[tuple] = []
        self.removed = removed
        self.unbound: list[int] = []

    def put_cache(self, user_id: int, cache: dict, ttl: object) -> None:
        self.caches.append((user_id, cache, ttl))

    def unbind(self, user_id: int) -> bool:
        self.unbound.append(user_id)
        return self.removed


class _Settings:
    allowed_user_ids: frozenset[int] = frozenset()
    cache_ttl = timedelta(hours=1)


class _Bot:
    def __init__(self, *, allow_bind: bool = True, removed: bool = True) -> None:
        self.limiter = _Limiter(allow_bind)
        self.db = _Database(removed)
        self.sessions = SessionStore()
        self.settings = _Settings()


async def _instant_sleep(_delay: float) -> None:
    return None


def _install_api(monkeypatch: pytest.MonkeyPatch, **handlers: object) -> dict[str, list]:
    calls: dict[str, list] = {"login": [], "fetch": [], "send": [], "login_code": []}

    async def login_passcode(email: str, secret: str, device_id: str) -> LoginResult:
        calls["login"].append((email, secret, device_id))
        handler = handlers.get("login_passcode")
        if handler is not None:
            return await handler(email, secret, device_id)  # type: ignore[misc]
        return LoginResult(token="token-value", device_id="dev-1")

    async def fetch_cache(email: str, token: str, device_id: str) -> dict:
        calls["fetch"].append((email, token, device_id))
        return {"username": "NightXWind"}

    async def send_email_code(email: str, device_id: str) -> str:
        calls["send"].append((email, device_id))
        handler = handlers.get("send_email_code")
        if handler is not None:
            return await handler(email, device_id)  # type: ignore[misc]
        return "device-from-api"

    async def login_code(email: str, secret: str, device_id: str) -> LoginResult:
        calls["login_code"].append((email, secret, device_id))
        handler = handlers.get("login_code")
        if handler is not None:
            return await handler(email, secret, device_id)  # type: ignore[misc]
        return LoginResult(token="code-token", device_id=device_id)

    monkeypatch.setattr(account_module.rizline_api, "login_passcode", login_passcode)
    monkeypatch.setattr(account_module.rizline_api, "fetch_cache", fetch_cache)
    monkeypatch.setattr(account_module.rizline_api, "send_email_code", send_email_code)
    monkeypatch.setattr(account_module.rizline_api, "login_code", login_code)
    return calls


async def _drain(cog: AccountCog) -> None:
    tasks = list(cog._delete_tasks)
    if tasks:
        await asyncio.gather(*tasks)


def test_bind_intro_is_private_and_opens_a_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)

    async def scenario() -> None:
        bot = _Bot()
        cog = AccountCog(bot)
        interaction = _Interaction(bot)
        await AccountCog.bind.callback(cog, interaction)
        sent = interaction.response.messages[0]
        assert sent["ephemeral"] is True
        assert sent["content"] == BIND_PUBLIC_REPLY
        assert "Reply with your account email" not in sent["content"]
        assert isinstance(sent["view"], _BindIntro)
        assert not hasattr(cog, "_pending")
        button = _Interaction(bot)
        await sent["view"].children[0].callback(button)
        assert isinstance(button.response.modals[0], _CredentialsModal)
        await _drain(cog)

    asyncio.run(scenario())


def test_passcode_submit_logs_in_without_posting_to_the_dm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)
    calls = _install_api(monkeypatch)

    async def scenario() -> None:
        bot = _Bot()
        cog = AccountCog(bot)
        modal = _CredentialsModal(cog)
        modal.email_input._value = EMAIL
        modal.secret_input._value = PASSCODE
        interaction = _Interaction(bot)
        await modal.on_submit(interaction)
        await _drain(cog)
        assert calls["login"][0][0] == EMAIL
        assert calls["login"][0][1] == PASSCODE
        assert calls["fetch"] == [(EMAIL, "token-value", "dev-1")]
        assert calls["send"] == []
        session = bot.sessions.get(7)
        assert session is not None
        assert session.token == "token-value"
        assert bot.db.caches[0][0] == 7
        assert interaction.response.defer_ephemeral is True
        text = interaction.visible_text()
        assert "Bound as NightXWind" in text
        assert EMAIL not in text
        assert PASSCODE not in text
        assert interaction.deleted == 1

    asyncio.run(scenario())


def test_code_word_opens_code_modal_then_logs_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)
    calls = _install_api(monkeypatch)

    async def scenario() -> None:
        bot = _Bot()
        cog = AccountCog(bot)
        modal = _CredentialsModal(cog)
        modal.email_input._value = f"  {EMAIL}  "
        modal.secret_input._value = "Code"
        interaction = _Interaction(bot)
        await modal.on_submit(interaction)
        assert interaction.response.modals == []
        prompt = interaction.edits[-1]
        assert "Enter code" in prompt["content"]
        assert EMAIL not in prompt["content"]
        assert calls["send"][0][0] == EMAIL
        assert calls["login"] == []
        assert calls["fetch"] == []
        opener = _Interaction(bot)
        await prompt["view"].children[0].callback(opener)
        code_modal = opener.response.modals[0]
        assert isinstance(code_modal, _CodeModal)
        assert code_modal.email == EMAIL
        assert code_modal.device_id == "device-from-api"
        code_modal.code_input._value = CODE
        follow = _Interaction(bot)
        await code_modal.on_submit(follow)
        await _drain(cog)
        assert calls["login_code"] == [(EMAIL, CODE, "device-from-api")]
        assert calls["fetch"] == [(EMAIL, "code-token", "device-from-api")]
        assert "Bound as NightXWind" in follow.visible_text()
        assert CODE not in follow.visible_text()
        assert EMAIL not in follow.visible_text()

    asyncio.run(scenario())


def test_login_failure_scrubs_email_and_passcode(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)

    async def explode(email: str, secret: str, device_id: str) -> LoginResult:
        del device_id
        raise RizlineError(f"rejected {email} {secret}")

    _install_api(monkeypatch, login_passcode=explode)

    async def scenario() -> None:
        bot = _Bot()
        cog = AccountCog(bot)
        modal = _CredentialsModal(cog)
        modal.email_input._value = EMAIL
        modal.secret_input._value = PASSCODE
        interaction = _Interaction(bot)
        with caplog.at_level(logging.WARNING, logger="rizline.bot"):
            await modal.on_submit(interaction)
        await _drain(cog)
        text = interaction.visible_text()
        assert "Run /bind to try again" in text
        assert EMAIL not in text
        assert PASSCODE not in text
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert EMAIL not in logged
        assert PASSCODE not in logged
        assert "<redacted>" in logged

    asyncio.run(scenario())


def test_unbind_reply_is_private_and_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)

    async def scenario() -> None:
        bot = _Bot()
        cog = AccountCog(bot)
        interaction = _Interaction(bot)
        await AccountCog.unbind.callback(cog, interaction)
        await _drain(cog)
        sent = interaction.response.messages[0]
        assert sent["ephemeral"] is True
        assert sent["content"] == UNBIND_REMOVED
        assert interaction.deleted == 1
        assert bot.db.unbound == [7]
        assert bot.sessions.get(7) is None

    asyncio.run(scenario())


def test_disallowed_modal_submit_does_not_call_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module.asyncio, "sleep", _instant_sleep)
    calls = _install_api(monkeypatch)

    async def scenario() -> None:
        bot = _Bot()
        bot.settings.allowed_user_ids = frozenset({1})
        cog = AccountCog(bot)
        modal = _CredentialsModal(cog)
        modal.email_input._value = EMAIL
        modal.secret_input._value = PASSCODE
        interaction = _Interaction(bot, user_id=7)
        await modal.on_submit(interaction)
        await _drain(cog)
        assert calls["login"] == []
        assert calls["send"] == []
        assert interaction.visible_text() == ALLOWLIST_DENIED

    asyncio.run(scenario())
