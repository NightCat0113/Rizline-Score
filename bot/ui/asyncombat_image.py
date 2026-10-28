"""Asyncombat rank sheet: profile pill, rank journey, Challenge/Engage cards."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bot.services.asyncombat import RAIL_LABELS, AsyncombatView, segment_index, win_rate
from bot.services.profile import layout_colors, player_title
from bot.ui.b40_image import _load_font, _open_art, _player_header, _px


_INK = (28, 32, 40)
_MUTED = (120, 132, 146)
_BLUE = (0, 163, 224)
_BLUE_DEEP = (0, 132, 186)
_PALE = (232, 246, 252)
_WHITE = (255, 255, 255)
_WIDTH = 1080
_PAD = 40
_HEADER_SCALE = 0.92
# Two-row rail: Do…Fa+ on top, So…Do△ below.
_RAIL_RADIUS = 36
_RAIL_ROW1 = 8
_RAIL_ROW1_Y = 148
_RAIL_ROW_GAP = 30
_RAIL_ROW2_Y = _RAIL_ROW1_Y + 2 * _RAIL_RADIUS + _RAIL_ROW_GAP
_JOURNEY_H = _RAIL_ROW2_Y + _RAIL_RADIUS + 64
_STAT_BUBBLE = 58
_STAT_CY = 112
_STAT_H = _STAT_CY + _STAT_BUBBLE // 2 + 54
_RAIL_STROKE = 2

# x, y, and diameter are fractions of the canvas so the dots follow the height.
_DOTS = (
    (-0.10, -0.12, 0.46, 96),
    (0.72, -0.08, 0.38, 84),
    (0.86, 0.12, 0.24, 78),
    (-0.08, 0.18, 0.22, 72),
    (0.38, -0.06, 0.16, 64),
    (0.06, 0.36, 0.12, 88),
    (0.84, 0.42, 0.18, 70),
    (-0.06, 0.55, 0.16, 80),
    (0.82, 0.64, 0.22, 90),
    (0.58, 0.74, 0.14, 76),
    (-0.12, 0.78, 0.32, 100),
    (0.12, 0.88, 0.20, 68),
    (0.42, 0.90, 0.26, 86),
    (0.78, 0.82, 0.28, 92),
    (0.22, 0.02, 0.10, 74),
    (0.54, 0.22, 0.11, 60),
)


def _font(path: Path, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _round_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, **kwargs) -> None:
    draw.rounded_rectangle(box, radius=radius, **kwargs)


def _profile_header(
    *,
    username: str,
    total_rks: float,
    font_path: Path,
    card: dict,
    illust_hires_dir: Path,
    illust_dir: Path,
    repo_root: Path,
    language: str,
) -> Image.Image:
    scale = _HEADER_SCALE
    fonts = {
        "name": _load_font(font_path, _px(scale, 32)),
        "rks_big": _load_font(font_path, _px(scale, 24)),
        "watermark": _load_font(font_path, _px(scale, 30)),
        "bio": _load_font(font_path, _px(scale, 20)),
    }
    avatar = _open_art(str(card.get("avatarId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    banner = _open_art(str(card.get("backgroundId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    title = player_title(str(card.get("bioId1") or ""), str(card.get("bioId2") or ""), repo_root, language)
    colors = layout_colors(str(card.get("layoutId") or ""), repo_root)
    pos = card.get("avatarPos") if isinstance(card.get("avatarPos"), dict) else {}
    return _player_header(username, total_rks, fonts, scale, avatar, banner, title, pos, colors)


def _chip(base: Image.Image, text: str, right: int, top: int, font: ImageFont.ImageFont) -> None:
    draw = ImageDraw.Draw(base)
    pad_x, height = 16, 36
    width = int(draw.textlength(text, font=font)) + pad_x * 2 + 18
    left = right - width
    chip = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pen = ImageDraw.Draw(chip)
    pen.rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 2, fill=(*_PALE, 255))
    pen.ellipse((10, 12, 22, 24), fill=(*_BLUE, 255))
    pen.text((28, height // 2), text, font=font, fill=(*_BLUE_DEEP, 255), anchor="lm")
    base.alpha_composite(chip, (left, top))


def _disk(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, fill: tuple[int, int, int, int]) -> None:
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)


def _ring_mask(size: int, outer: int, inner: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    pen = ImageDraw.Draw(mask)
    mid = size // 2
    _disk(pen, mid, mid, outer, 255)
    if inner > 0:
        _disk(pen, mid, mid, inner, 0)
    return mask


def _song_circle(
    image: Image.Image,
    center: tuple[int, int],
    radius: int,
    label: str,
    font: ImageFont.ImageFont,
    *,
    filled: bool,
    emphasize: bool,
) -> None:
    """Draw an antialiased circle from filled disks (no outline strokes), then the label."""
    scale = 4
    pad = 14
    outer = radius + pad
    size = outer * 2 * scale
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(tile)
    ox = oy = outer * scale
    r = radius * scale
    rim = max(3, radius // 10) * scale
    ink = _WHITE if filled else _BLUE
    if filled:
        _disk(pen, ox, oy, (radius + 5) * scale, (*_PALE, 255))
        _disk(pen, ox, oy, r, (*_WHITE, 255))
        _disk(pen, ox, oy, max(1, r - rim), (*_BLUE, 255))
    else:
        _disk(pen, ox, oy, r, (*_BLUE, 255))
        _disk(pen, ox, oy, max(1, r - rim), (*_WHITE, 255))
    if emphasize:
        ring_outer = (radius + 8) * scale
        ring_inner = ring_outer - 3 * scale
        band = Image.new("RGBA", (size, size), (*_BLUE, 255))
        band.putalpha(_ring_mask(size, ring_outer, max(0, ring_inner)))
        tile.alpha_composite(band)
    smooth = tile.resize((outer * 2, outer * 2), Image.Resampling.LANCZOS)
    image.alpha_composite(smooth, (center[0] - outer, center[1] - outer))
    ImageDraw.Draw(image).text(center, label, font=font, fill=(*ink, 255), anchor="mm")


def _journey(base: Image.Image, view: AsyncombatView, fonts: dict[str, ImageFont.ImageFont], box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    card = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    _round_rect(draw, (0, 0, card.width - 1, card.height - 1), 28, fill=(255, 255, 255, 255), outline=(*_BLUE, 255), width=3)
    draw.text((28, 22), "ASYNCOMBAT", font=fonts["kicker"], fill=(*_BLUE, 255))
    draw.text((28, 48), "Rank journey", font=fonts["heading"], fill=(*_INK, 255))
    current = view.current
    stars = "" if current.stars is None else f"{current.stars}{'+' if current.is_plus else ''}"
    chip = f"CURRENT  ·  {current.segment or '—'} {stars}".strip()
    base.alpha_composite(card, (left, top))
    _chip(base, chip, right - 24, top + 36, fonts["chip"])

    peak_i = segment_index(view.peak)
    current_i = segment_index(view.current)
    radius = _RAIL_RADIUS
    inner_left, inner_right = 48 + radius, card.width - 48 - radius
    row1 = RAIL_LABELS[:_RAIL_ROW1]
    row2 = RAIL_LABELS[_RAIL_ROW1:]

    def _row_centers(count: int) -> list[int]:
        if count <= 1:
            return [(inner_left + inner_right) // 2]
        gap = (inner_right - inner_left) / (count - 1)
        return [int(inner_left + index * gap) for index in range(count)]

    # Top row left→right; bottom row right→left so the path snakes down the right edge.
    centers1 = _row_centers(len(row1))
    centers2 = list(reversed(_row_centers(len(row2))))
    y1, y2 = _RAIL_ROW1_Y, _RAIL_ROW2_Y
    rail = ImageDraw.Draw(base)
    stroke = (*_BLUE, 255)
    if len(centers1) > 1:
        rail.line((left + centers1[0], top + y1, left + centers1[-1], top + y1), fill=stroke, width=_RAIL_STROKE)
    if len(centers2) > 1:
        rail.line((left + centers2[0], top + y2, left + centers2[-1], top + y2), fill=stroke, width=_RAIL_STROKE)
    if centers1 and centers2:
        rail.line(
            (left + centers1[-1], top + y1, left + centers2[0], top + y2),
            fill=stroke,
            width=_RAIL_STROKE,
        )
    for index, (name, center) in enumerate(zip(row1, centers1)):
        _song_circle(
            base,
            (left + center, top + y1),
            radius,
            name,
            fonts["node"],
            filled=peak_i >= index,
            emphasize=current_i == index,
        )
    for offset, (name, center) in enumerate(zip(row2, centers2)):
        index = _RAIL_ROW1 + offset
        _song_circle(
            base,
            (left + center, top + y2),
            radius,
            name,
            fonts["node"],
            filled=peak_i >= index,
            emphasize=current_i == index,
        )

    foot_y = bottom - 36
    rail.text((left + 28, foot_y), "INITIAL", font=fonts["kicker"], fill=(*_MUTED, 255), anchor="lm")
    rail.text((left + 118, foot_y), view.initial.label, font=fonts["foot"], fill=(*_INK, 255), anchor="lm")
    status = "ALL RANKS UNLOCKED" if peak_i >= len(RAIL_LABELS) - 1 else "IN PROGRESS"
    rail.text(((left + right) // 2, foot_y), status, font=fonts["kicker"], fill=(*_BLUE, 255), anchor="mm")
    peak_text = view.peak.label
    rail.text((right - 28, foot_y), peak_text, font=fonts["foot"], fill=(*_INK, 255), anchor="rm")
    rail.text((right - 28 - int(rail.textlength(peak_text, font=fonts["foot"])) - 12, foot_y), "PEAK", font=fonts["kicker"], fill=(*_MUTED, 255), anchor="rm")


def _stat_card(
    base: Image.Image,
    box: tuple[int, int, int, int],
    *,
    title: str,
    subtitle: str,
    rate: int,
    matches: int,
    wins: int,
    streak: int,
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    left, top, right, bottom = box
    card = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    _round_rect(draw, (0, 0, card.width - 1, card.height - 1), 40, fill=(255, 255, 255, 255), outline=(*_BLUE, 255), width=3)
    title_x, title_top = 28, 18
    draw.text((title_x, title_top), title, font=fonts["kicker"], fill=(*_BLUE, 255))
    title_box = draw.textbbox((title_x, title_top), title, font=fonts["kicker"])
    sub_top = title_box[3] + 4
    draw.text((title_x, sub_top), subtitle, font=fonts["sub"], fill=(*_MUTED, 255))
    draw.text((card.width - 24, title_box[1] + (title_box[3] - title_box[1]) // 2), f"{rate}%", font=fonts["rate"], fill=(*_BLUE_DEEP, 255), anchor="rm")
    draw.text((card.width - 24, sub_top), "WIN RATE", font=fonts["kicker"], fill=(*_MUTED, 255), anchor="rt")
    labels = (("MATCHES", matches), ("WINS", wins), ("STREAK", streak))
    bubble = _STAT_BUBBLE
    slot = card.width // 3
    cy = _STAT_CY
    for index, (label, value) in enumerate(labels):
        cx = slot * index + slot // 2
        _song_circle(card, (cx, cy), bubble // 2, str(value), fonts["stat"], filled=True, emphasize=False)
        draw.text((cx, cy + bubble // 2 + 16), label, font=fonts["kicker"], fill=(*_MUTED, 255), anchor="mt")
    base.alpha_composite(card, (left, top))


def render_asyncombat(
    view: AsyncombatView,
    *,
    username: str,
    font_path: Path,
    card: dict | None = None,
    illust_hires_dir: Path | None = None,
    illust_dir: Path | None = None,
    repo_root: Path | None = None,
    language: str = "en",
    total_rks: float = 0.0,
) -> bytes:
    fonts = {
        "kicker": _font(font_path, 16),
        "heading": _font(font_path, 36),
        "chip": _font(font_path, 16),
        "node": _font(font_path, 15),
        "foot": _font(font_path, 22),
        "sub": _font(font_path, 16),
        "rate": _font(font_path, 18),
        "stat": _font(font_path, 22),
    }
    content_left = _PAD
    content_right = _WIDTH - _PAD
    top = 24
    header = None
    if illust_hires_dir is not None and illust_dir is not None:
        header = _profile_header(
            username=username or "Player",
            total_rks=float(total_rks or 0),
            font_path=font_path,
            card=card or {},
            illust_hires_dir=illust_hires_dir,
            illust_dir=illust_dir,
            repo_root=repo_root or font_path.parent,
            language=language,
        )
        block = header.height + 16
    else:
        block = 56
    journey_top = top + block
    journey_bottom = journey_top + _JOURNEY_H
    stat_top = journey_bottom + 16
    stat_bottom = stat_top + _STAT_H
    image = Image.new("RGBA", (_WIDTH, stat_bottom + 20), (*_WHITE, 255))
    aa = 2
    dots = Image.new("RGBA", (image.width * aa, image.height * aa), (0, 0, 0, 0))
    blob = ImageDraw.Draw(dots)
    for fx, fy, fd, alpha in _DOTS:
        left = int(image.width * fx * aa)
        top_dot = int(image.height * fy * aa)
        size = int(image.width * fd * aa)
        blob.ellipse((left, top_dot, left + size, top_dot + size), fill=(*_BLUE, alpha))
    image.alpha_composite(dots.resize(image.size, Image.Resampling.LANCZOS))
    if header is not None:
        image.alpha_composite(header, ((_WIDTH - header.width) // 2, top))
    else:
        ImageDraw.Draw(image).text((content_left, top), username or "Player", font=_font(font_path, 36), fill=(*_INK, 255))

    _journey(image, view, fonts, (content_left, journey_top, content_right, journey_bottom))
    gap = 20
    width = (content_right - content_left - gap) // 2
    _stat_card(
        image,
        (content_left, stat_top, content_left + width, stat_bottom),
        title="CHALLENGE",
        subtitle="Challenge other Players",
        rate=win_rate(view.challenge),
        matches=view.challenge.matches,
        wins=view.challenge.wins,
        streak=view.challenge.streak,
        fonts=fonts,
    )
    _stat_card(
        image,
        (content_left + width + gap, stat_top, content_right, stat_bottom),
        title="ENGAGE",
        subtitle="Defend from Players",
        rate=win_rate(view.engage),
        matches=view.engage.matches,
        wins=view.engage.wins,
        streak=view.engage.streak,
        fonts=fonts,
    )

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
