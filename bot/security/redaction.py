"""Logging helpers that reuse the login client's redaction."""

from __future__ import annotations

import logging

from rizline_client import redact, scrub


logger = logging.getLogger("rizline.bot")


def log_safe(level: int, message: str, *args: object, secrets: tuple[str, ...] = ()) -> None:
    text = message % args if args else message
    if not isinstance(text, str):
        text = str(redact(text))
    logger.log(level, "%s", scrub(text, secrets))
