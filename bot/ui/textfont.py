"""Pick a Hangul font when the main face has no Korean glyphs."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageDraw, ImageFont


_HANGUL_FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "malgunbd.ttf"


def one_line(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def hangul_face(primary: ImageFont.ImageFont, fallback: ImageFont.ImageFont | None, text: str) -> ImageFont.ImageFont:
    if fallback is not None and any("\uac00" <= character <= "\ud7a3" or "\u1100" <= character <= "\u11ff" for character in text):
        return fallback
    return primary


def load_face(path: Path, size: int) -> ImageFont.ImageFont:
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def load_hangul(size: int) -> ImageFont.ImageFont | None:
    if not _HANGUL_FONT.is_file():
        return None
    return ImageFont.truetype(str(_HANGUL_FONT), size)


def clip(
    text: str,
    font: ImageFont.ImageFont,
    width: int,
    draw: ImageDraw.ImageDraw,
    fallback: ImageFont.ImageFont | None = None,
) -> tuple[str, ImageFont.ImageFont]:
    text = one_line(text)
    chosen = hangul_face(font, fallback, text)
    if width <= 0 or not text or draw.textlength(text, font=chosen) <= width:
        return text, chosen
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=chosen) > width:
        trimmed = trimmed[:-1]
    return (f"{trimmed}…" if trimmed else "…"), chosen
