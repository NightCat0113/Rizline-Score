"""Song and chart card rendered as one PNG."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.models import ChartInfo, Song
from bot.services.songdata import illustration_path


MAX_PNG_BYTES = 8_000_000
_SCALES = (2.0, 1.5, 1.0)
_ORDER = ("EZ", "HD", "IN", "AT", "SP")
_DIFF_COLORS = {
    "EZ": (87, 228, 196),
    "HD": (253, 186, 97),
    "IN": (254, 134, 97),
    "AT": (76, 54, 75),
    "SP": (0, 0, 0),
}
_GOLD = (214, 164, 38)
_INK = (28, 28, 32)
_MUTED = (90, 90, 98)
_WIDTH = 980
_PAD = 28
_HEADER_H = 188
_ROW_H = 116
_ROW_CIRCLE = 92
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
        "meta": _load_font(font_path, _px(scale, 13)),
        "pill": _load_font(font_path, _px(scale, 22)),
        "body": _load_font(font_path, _px(scale, 15)),
        "level": _load_font(font_path, _px(scale, 20)),
        "score": _load_font(font_path, _px(scale, 30)),
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
    title = _clip(song.title or "—", fonts["title"], text_w, draw)
    artist = _clip(song.artist or "—", fonts["artist"], text_w, draw)
    details = [(_clip(line, fonts["meta"], text_w, draw), fonts["meta"]) for line in _meta_lines(song)]
    title_box = fonts["title"].getbbox(title)
    artist_box = fonts["artist"].getbbox(artist)
    pair_gap = _px(scale, 1)
    section_gap = _px(scale, 10)
    detail_gap = _px(scale, 3)
    title_h = title_box[3] - title_box[1]
    artist_h = artist_box[3] - artist_box[1]
    detail_h = sum(getattr(font, "size", detail_gap) for _, font in details)
    if details:
        detail_h += detail_gap * (len(details) - 1)
    block_h = title_h + pair_gap + artist_h + (section_gap + detail_h if details else 0)
    ink_y = top + max(_px(scale, 8), (height - block_h) // 2)
    draw.text((text_x, ink_y - title_box[1]), title, font=fonts["title"], fill=(*_INK, 255), anchor="lt")
    artist_ink = ink_y + title_h + pair_gap
    draw.text((text_x, artist_ink - artist_box[1]), artist, font=fonts["artist"], fill=(*_MUTED, 255), anchor="lt")
    line_y = artist_ink + artist_h + section_gap
    for text, font in details:
        draw.text((text_x, line_y), text, font=font, fill=(*_INK, 255), anchor="lt")
        line_y += getattr(font, "size", detail_gap) + detail_gap
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
    inset = max(_px(scale, 8), (height - circle) // 2)
    color = _DIFF_COLORS.get(difficulty, (107, 70, 193))
    _difficulty_circle(
        draw,
        left + inset,
        top + (height - circle) // 2,
        circle,
        difficulty,
        chart.level_text or f"{chart.level:.1f}",
        color,
        (255, 255, 255),
        fonts,
    )
    text_x = left + inset + circle + _px(scale, 16)
    text_right = right - _px(scale, 22)
    split = text_x + int((text_right - text_x) * 0.56)
    draw.line(
        [(split, top + _px(scale, 18)), (split, top + height - _px(scale, 18))],
        fill=(170, 170, 176, 255),
        width=max(2, _px(scale, 2)),
    )

    max_rks = None if chart.level <= 0 else 11 * chart.level + 10.5
    player = _player_score(best)
    shown = f"{player:,}" if player is not None else "—"
    chart_score = f"{chart.score:,}" if chart.score > 0 else "—"
    score_text = f"Score {shown} / {chart_score}"
    full = player is not None and chart.score > 0 and player >= chart.score - 1
    rks_text, rks_full = _rks_line(best, max_rks)
    column_right = split - _px(scale, 14)
    column_w = column_right - text_x
    lines = (
        (
            _clip(score_text, fonts["score"], column_w, draw),
            fonts["score"],
            (*_GOLD, 255) if full else (196, 154, 106, 255),
        ),
        (
            _clip(_result_line(best), fonts["small"], column_w, draw),
            fonts["small"],
            (*_MUTED, 255),
        ),
        (
            _clip(rks_text, fonts["small"], column_w, draw),
            fonts["small"],
            (*_GOLD, 255) if rks_full else (196, 154, 106, 255),
        ),
    )
    gap = _px(scale, 6)
    block_w = max(draw.textlength(text, font=font) for text, font, _ in lines)
    block_h = sum(getattr(font, "size", _px(scale, 14)) for _, font, _ in lines) + gap * (len(lines) - 1)
    line_x = text_x + max(0, (column_w - block_w) / 2)
    line_y = top + max(_px(scale, 8), (height - block_h) // 2)
    for text, font, fill in lines:
        draw.text((line_x, line_y), text, font=font, fill=fill, anchor="lt")
        line_y += getattr(font, "size", _px(scale, 14)) + gap

    facts = [
        f"Hit {chart.hit:,}",
        f"RizHit {chart.riz_hit:,}",
        f"Combo {chart.combo:,}",
        f"Charter {chart.designer or '—'}",
    ]
    line_x = split + _px(scale, 16)
    line_top = top + _px(scale, 12)
    step = _px(scale, 24)
    for index, fact in enumerate(facts):
        limit = text_right - line_x
        draw.text(
            (line_x, line_top + index * step),
            _clip(fact, fonts["small"], limit, draw),
            font=fonts["small"],
            fill=(*_INK, 255),
        )
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


def _result_line(best: dict | None) -> str:
    if best is None or _player_score(best) is None:
        return "No record"
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
    return f"Accuracy {accuracy}  ·  {status}"


def _rks_line(best: dict | None, max_rks: float | None) -> tuple[str, bool]:
    rks = best.get("rks") if best else None
    has_rks = isinstance(rks, (int, float))
    if max_rks is None:
        return (f"RKS {float(rks):.3f}" if has_rks else "RKS —"), False
    cap = f"{max_rks:.3f}"
    if not has_rks:
        return f"RKS — / {cap}", False
    return f"RKS {float(rks):.3f} / {cap}", float(rks) >= max_rks - 1e-3


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
    lines = ["   ·   ".join(parts)] if parts else []
    if song.illustrator:
        lines.append(f"Illustrator {song.illustrator}")
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
    level: str,
    color: tuple[int, int, int],
    ink: tuple[int, int, int],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    box = (left, top, left + size - 1, top + size - 1)
    draw.ellipse(box, fill=(*color, 255))
    draw.ellipse(box, outline=(255, 255, 255, 255), width=max(2, size // 28))
    center_x = left + size // 2
    center_y = top + size // 2
    draw.text((center_x, center_y - size // 7), difficulty, font=fonts["pill"], fill=(*ink, 255), anchor="mm")
    draw.text((center_x, center_y + size // 6), level, font=fonts["level"], fill=(*ink, 255), anchor="mm")


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
