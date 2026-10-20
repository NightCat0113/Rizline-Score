"""Async wrapper around the pinned Rizline client. urllib calls run in a thread."""

from __future__ import annotations

import asyncio
from typing import Any

from rizline_client import (
    DEFAULT_BASE_URL,
    fetch_minimal_cache,
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
