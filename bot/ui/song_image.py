"""Song and chart card rendered as one PNG."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.models import ChartInfo, Song
from bot.services.songdata import illustration_path


MAX_PNG_BYTES = 8_000_000
_SCALES = (2.0, 1.5, 1.0)
_ORDER = ("EZ", "HD", "IN", "AT")
_DIFF_COLORS = {
    "EZ": (87, 228, 196),
    "HD": (253, 186, 97),
    "IN": (254, 134, 97),
    "AT": (76, 54, 75),
}
_LIGHT_DIFFS = {"EZ", "HD"}
_GOLD = (214, 164, 38)
_INK = (28, 28, 32)
_MUTED = (90, 90, 98)
_WIDTH = 980
_PAD = 28
_HEADER_H = 188
_ROW_H = 100
_ROW_CIRCLE = 64
_GAP = 12


def render_song(
    *,
    song: Song,
    personal: dict[str, dict] | None,
    highlight: str | None,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    max_bytes: int = MAX_PNG_BYTES,
) -> bytes:
    artwork = _open_art(song, illust_hires_dir, illust_dir)
    last = b""
    for scale in _SCALES:
        image = _draw(
            song=song,
            personal=personal or {},
            highlight=highlight if highlight in _ORDER else None,
            artwork=artwork,
            font_path=font_path,
            scale=scale,
        )
        last = _encode(image)
        if len(last) <= max_bytes:
            return last
    return last


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw(
    *,
    song: Song,
    personal: dict[str, dict],
    highlight: str | None,
    artwork: Image.Image | None,
    font_path: Path,
    scale: float,
) -> Image.Image:
    charts = [(name, song.charts[name]) for name in _ORDER if name in song.charts]
    width = _px(scale, _WIDTH)
    pad = _px(scale, _PAD)
    gap = _px(scale, _GAP)
    header_h = _px(scale, _HEADER_H)
    row_h = _px(scale, _ROW_H)
    rows = max(1, len(charts))
    height = pad + header_h + gap + rows * row_h + max(0, rows - 1) * gap + pad
    image = _background(width, height, artwork).convert("RGBA")
    fonts = {
        "title": _load_font(font_path, _px(scale, 30)),
        "artist": _load_font(font_path, _px(scale, 18)),
        "meta": _load_font(font_path, _px(scale, 16)),
        "pill": _load_font(font_path, _px(scale, 14)),
        "body": _load_font(font_path, _px(scale, 15)),
        "score": _load_font(font_path, _px(scale, 22)),
        "small": _load_font(font_path, _px(scale, 14)),
    }
    draw = ImageDraw.Draw(image)
    _header(image, draw, song, artwork, fonts, scale, pad, width - pad, pad, header_h)
    top = pad + header_h + gap
    if not charts:
        _empty_row(image, draw, fonts, scale, pad, width - pad, top, row_h)
        return image
    for index, (name, chart) in enumerate(charts):
        y = top + index * (row_h + gap)
        _chart_row(
            image,
            draw,
            name,
            chart,
            personal.get(name),
            highlighted=name == highlight,
            fonts=fonts,
            scale=scale,
            left=pad,
            right=width - pad,
            top=y,
            height=row_h,
        )
    return image


def _header(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    song: Song,
    artwork: Image.Image | None,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
) -> None:
    _paste_panel(image, left, top, right - left, height, height // 2)
    circle = _px(scale, _HEADER_H - 10)
    inset = (height - circle) // 2
    image.alpha_composite(_circle_art(artwork, circle, _px(scale, 6)), (left + inset, top + inset))
    text_x = left + inset + circle + _px(scale, 18)
    text_w = right - height // 3 - text_x
    title_y = top + _px(scale, 18)
    draw.text((text_x, title_y), _clip(song.title or "—", fonts["title"], text_w, draw), font=fonts["title"], fill=(*_INK, 255))
    draw.text(
        (text_x, title_y + _px(scale, 36)),
        _clip(song.artist or "—", fonts["artist"], text_w, draw),
        font=fonts["artist"],
        fill=(*_MUTED, 255),
    )
    for index, line in enumerate(_meta_lines(song)):
        draw.text(
            (text_x, title_y + _px(scale, 66 + index * 24)),
            _clip(line, fonts["meta"], text_w, draw),
            font=fonts["meta"],
            fill=(*_INK, 255),
        )
    _outline(draw, left, top, right, top + height, (0, 178, 236, 255), _px(scale, 4))


def _chart_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    difficulty: str,
    chart: ChartInfo,
    best: dict | None,
    *,
    highlighted: bool,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
) -> None:
    _paste_panel(image, left, top, right - left, height, height // 2)
    circle = _px(scale, _ROW_CIRCLE)
    inset = _px(scale, 10)
    color = _DIFF_COLORS.get(difficulty, (107, 70, 193))
    ink = _INK if difficulty in _LIGHT_DIFFS else (255, 255, 255)
    _difficulty_circle(draw, left + inset, top + (height - circle) // 2, circle, difficulty, chart.level, color, ink, fonts)
    text_x = left + inset + circle + _px(scale, 14)
    text_right = right - _px(scale, 24)
    max_rks = 11 * chart.level + 10.5
    max_label = f"Max RKS {max_rks:.1f}"
    max_w = int(draw.textlength(max_label, font=fonts["body"]))
    draw.text((text_right - max_w, top + _px(scale, 12)), max_label, font=fonts["body"], fill=(*_INK, 255))
    charter = f"Charter {chart.designer or '—'}"
    charter_w = text_right - max_w - _px(scale, 12) - text_x
    draw.text((text_x, top + _px(scale, 12)), _clip(charter, fonts["body"], charter_w, draw), font=fonts["body"], fill=(*_INK, 255))

    stats = f"Hit {chart.hit:,}  ·  Combo {chart.combo:,}  ·  RizHit {chart.riz_hit:,}"
    draw.text((text_x, top + _px(scale, 34)), _clip(stats, fonts["small"], text_right - text_x, draw), font=fonts["small"], fill=(*_MUTED, 255))

    player = _player_score(best)
    shown = f"{player:,}" if player is not None else "—"
    chart_score = f"{chart.score:,}" if chart.score > 0 else "—"
    score_text = f"{shown} / {chart_score}"
    full = player is not None and chart.score > 0 and player >= chart.score - 1
    score_y = top + _px(scale, 56)
    draw.text((text_x, score_y), score_text, font=fonts["score"], fill=(*_GOLD, 255) if full else (196, 154, 106, 255))
    detail = _personal_line(best) if best else "No record"
    detail_x = text_x + int(draw.textlength(score_text, font=fonts["score"])) + _px(scale, 14)
    draw.text((detail_x, score_y + _px(scale, 6)), _clip(detail, fonts["small"], text_right - detail_x, draw), font=fonts["small"], fill=(*_MUTED, 255))
    if highlighted:
        _outline(draw, left, top, right, top + height, (0, 178, 236, 255), _px(scale, 4))


def _empty_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
) -> None:
    _paste_panel(image, left, top, right - left, height, height // 2)
    draw.text(
        (left + height // 2, top + height // 2 - _px(scale, 10)),
        "No chart details are in the local song index.",
        font=fonts["body"],
        fill=(*_MUTED, 255),
    )


def _personal_line(best: dict) -> str:
    if best.get("isFullCombo"):
        status = "FC"
    elif best.get("isClear"):
        status = "Clear"
    else:
        status = "Not cleared"
    try:
        accuracy = f"{float(best.get('completeRate')):.2f}%"
    except (TypeError, ValueError):
        accuracy = "—"
    parts = [f"Accuracy {accuracy}", status]
    rks = best.get("rks")
    if isinstance(rks, (int, float)):
        parts.append(f"RKS {float(rks):.3f}")
    return "  ·  ".join(parts)


def _player_score(best: dict | None) -> int | None:
    if not best or best.get("score") is None:
        return None
    try:
        return int(best["score"])
    except (TypeError, ValueError):
        return None


def _meta_lines(song: Song) -> list[str]:
    parts: list[str] = []
    if song.bpm:
        parts.append(f"BPM {_fmt_bpm(song.bpm)}")
    if song.length_seconds:
        parts.append(f"Length {_fmt_length(song.length_seconds)}")
    if song.illustrator:
        parts.append(f"Illustrator {song.illustrator}")
    lines = ["   ·   ".join(parts)] if parts else []
    if song.disc_name:
        disc = song.disc_name if song.disc_name.lower().startswith("disc") else f"Disc {song.disc_name}"
        lines.append(disc)
    if song.series_index is not None:
        series = f"Track Series {song.series_index}"
        if song.series_name:
            series = f"{series} - {song.series_name}"
        lines.append(series)
    return lines


def _fmt_bpm(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _fmt_length(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60}:{total % 60:02d}"


def _outline(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int, color: tuple[int, int, int, int], width: int) -> None:
    radius = max(1, (bottom - top) // 2)
    draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=radius, outline=color, width=width)


def _difficulty_circle(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    size: int,
    difficulty: str,
    level: float,
    color: tuple[int, int, int],
    ink: tuple[int, int, int],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    box = (left, top, left + size - 1, top + size - 1)
    draw.ellipse(box, fill=(*color, 255))
    draw.ellipse(box, outline=(255, 255, 255, 255), width=max(2, size // 28))
    center_x = left + size // 2
    center_y = top + size // 2
    draw.text((center_x, center_y - size // 8), difficulty, font=fonts["pill"], fill=(*ink, 255), anchor="mm")
    draw.text((center_x, center_y + size // 7), f"{level:.1f}", font=fonts["body"], fill=(*ink, 255), anchor="mm")


def _paste_panel(image: Image.Image, left: int, top: int, width: int, height: int, radius: int) -> None:
    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(255, 255, 255, 214))
    image.alpha_composite(panel, (left, top))


def _circle_art(artwork: Image.Image | None, size: int, ring: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).ellipse((0, 0, size - 1, size - 1), fill=(255, 255, 255, 255))
    inner = max(1, size - ring * 2)
    if artwork is None:
        photo = Image.new("RGBA", (inner, inner), (208, 208, 208, 255))
    else:
        photo = _cover(artwork, inner, inner).convert("RGBA")
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    photo.putalpha(mask)
    canvas.alpha_composite(photo, (ring, ring))
    return canvas


def _open_art(song: Song, hires_dir: Path, low_dir: Path) -> Image.Image | None:
    path = illustration_path(song, hires_dir, low_dir, prefer_low=False)
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB")
    except (OSError, ValueError):
        return None


def _background(width: int, height: int, artwork: Image.Image | None) -> Image.Image:
    if artwork is None:
        return Image.new("RGB", (width, height), (24, 26, 34))
    long_side = max(width, height, 1)
    work = min(long_side, 1800)
    ratio = work / long_side
    blur_w = max(8, int(width * ratio))
    blur_h = max(8, int(height * ratio))
    blurred = _cover(artwork, blur_w, blur_h).filter(ImageFilter.GaussianBlur(radius=max(2, int(15 * ratio))))
    background = blurred.resize((width, height), Image.Resampling.LANCZOS)
    shade = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.blend(background, shade, 0.5)


def _cover(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _load_font(path: Path, size: int) -> ImageFont.ImageFont:
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _px(scale: float, value: int) -> int:
    return max(1, int(round(value * scale)))


def _clip(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw) -> str:
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
