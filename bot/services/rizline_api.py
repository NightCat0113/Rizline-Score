"""Async wrapper around the pinned Rizline client. urllib calls run in a thread."""

from __future__ import annotations

import asyncio
from typing import Any

from rizline.client import (
    DEFAULT_BASE_URL,
    fetch_equipped_rizcard,
    fetch_minimal_cache,
    fetch_own_rizcard,
    fetch_weekly_rank_info,
    fetch_weekly_tasks,
    login_with_code,
    login_with_passcode,
    request_email_code,
)


def _pinned(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        **kwargs,
        "base_url": DEFAULT_BASE_URL,
        "require_pinned_host": True,
    }


async def login_passcode(email: str, passcode: str, device_id: str):
    return await asyncio.to_thread(
        login_with_passcode,
        email,
        passcode,
        device_id=device_id,
        **_pinned({}),
    )


async def send_email_code(email: str, device_id: str) -> str:
    return await asyncio.to_thread(
        request_email_code,
        email,
        device_id=device_id,
        **_pinned({}),
    )


async def login_code(email: str, code: str, device_id: str):
    return await asyncio.to_thread(
        login_with_code,
        email,
        code,
        device_id=device_id,
        **_pinned({}),
    )


async def fetch_cache(email: str, token: str, device_id: str) -> dict:
    return await asyncio.to_thread(
        fetch_minimal_cache,
        email,
        token,
        device_id,
        **_pinned({}),
    )


async def weekly_rank(email: str, token: str, device_id: str) -> dict:
    return await asyncio.to_thread(fetch_weekly_rank_info, email, token, device_id, **_pinned({}))


async def weekly_tasks(email: str, token: str, device_id: str) -> dict:
    return await asyncio.to_thread(fetch_weekly_tasks, email, token, device_id, **_pinned({}))


async def equipped_rizcard(email: str, token: str, device_id: str) -> dict:
    return await asyncio.to_thread(
        fetch_equipped_rizcard,
        email,
        token,
        device_id,
        **_pinned({}),
    )


async def own_rizcard(email: str, token: str, device_id: str) -> dict:
    return await asyncio.to_thread(fetch_own_rizcard, email, token, device_id, **_pinned({}))
