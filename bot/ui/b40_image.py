"""Best 40 card sheet, matching the pill layout in index.html."""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.services.profile import layout_colors, player_title
from bot.services.rks import strip_track_prefix
from bot.services.songdata import SongIndex, illustration_file, illustration_path


MAX_PNG_BYTES = 8_000_000
_SCALES = (2.0, 1.5, 1.0)
_DIFF_COLORS = {
    "EZ": (87, 228, 196),
    "HD": (253, 186, 97),
    "IN": (254, 134, 97),
    "AT": (76, 54, 75),
}
_LIGHT_DIFFS = {"EZ", "HD"}
_CARD_W = 310
_CARD_H = 110
_GAP = 20
_PAD = 40
_COLS = 5
_HEADER_BLOCK = 168
_SECTION_H = 48
_LABELS = {"ah5": "AH5", "b35": "B35", "overflow": "OVERFLOW"}
_GOLD = (214, 164, 38)


def render_b40(
    *,
    username: str,
    total_rks: float,
    special: list[dict],
    ordinary: list[dict],
    overflow: list[dict],
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    repo_root: Path | None = None,
    card: dict | None = None,
    max_bytes: int = MAX_PNG_BYTES,
) -> bytes:
    sections = [
        (label, rows)
        for label, rows in (("ah5", special), ("b35", ordinary), ("overflow", overflow))
        if rows
    ]
    last = b""
    for scale in _SCALES:
        image = _draw(
            username=username or "Player",
            total_rks=total_rks,
            sections=sections,
            index=index,
            illust_hires_dir=illust_hires_dir,
            illust_dir=illust_dir,
            font_path=font_path,
            repo_root=repo_root,
            card=card or {},
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


def _load_font(path: Path, size: int) -> ImageFont.ImageFont:
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _px(scale: float, value: int) -> int:
    return max(1, int(round(value * scale)))


def _draw(
    *,
    username: str,
    total_rks: float,
    sections: list[tuple[str, list[dict]]],
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    repo_root: Path | None,
    card: dict,
    scale: float,
) -> Image.Image:
    card_w, card_h = _px(scale, _CARD_W), _px(scale, _CARD_H)
    gap, pad = _px(scale, _GAP), _px(scale, _PAD)
    width = pad * 2 + _COLS * card_w + (_COLS - 1) * gap
    height = pad + _px(scale, _HEADER_BLOCK)
    if not sections:
        height += _px(scale, 40)
    for _label, rows in sections:
        row_count = (len(rows) + _COLS - 1) // _COLS
        height += _px(scale, _SECTION_H) + row_count * card_h + max(0, row_count - 1) * gap + _px(scale, 28)
    height += pad

    artwork = _random_artwork(illust_dir, illust_hires_dir)
    image = _background(width, height, artwork).convert("RGBA")
    fonts = {
        "name": _load_font(font_path, _px(scale, 32)),
        "section": _load_font(font_path, _px(scale, 22)),
        "title": _load_font(font_path, _px(scale, 16)),
        "const": _load_font(font_path, _px(scale, 13)),
        "rks": _load_font(font_path, _px(scale, 16)),
        "score": _load_font(font_path, _px(scale, 17)),
        "rank": _load_font(font_path, _px(scale, 13)),
        "rks_big": _load_font(font_path, _px(scale, 24)),
        "watermark": _load_font(font_path, _px(scale, 30)),
        "bio": _load_font(font_path, _px(scale, 20)),
    }
    profile_root = repo_root or font_path.parent
    avatar = _open_art(str(card.get("avatarId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    banner = _open_art(str(card.get("backgroundId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    title = player_title(str(card.get("bioId1") or ""), str(card.get("bioId2") or ""), profile_root)
    colors = layout_colors(str(card.get("layoutId") or ""), profile_root)
    pos = card.get("avatarPos") if isinstance(card.get("avatarPos"), dict) else {}
    header = _player_header(username, total_rks, fonts, scale, avatar, banner, title, pos, colors)
    image.alpha_composite(header, ((width - header.width) // 2, pad))

    draw = ImageDraw.Draw(image)
    y = pad + _px(scale, _HEADER_BLOCK)
    if not sections:
        draw.text((pad, y), "No charts in this group.", font=fonts["section"], fill=(255, 255, 255, 255))
        return image

    for label, rows in sections:
        _section_title(draw, _LABELS.get(label, label), y, width, pad, fonts["section"], scale)
        y += _px(scale, _SECTION_H)
        for start in range(0, len(rows), _COLS):
            chunk = rows[start : start + _COLS]
            for column, row in enumerate(chunk):
                card = _card_image(
                    (card_w, card_h),
                    row,
                    index,
                    illust_hires_dir,
                    illust_dir,
                    fonts,
                    scale,
                )
                origin = (pad + column * (card_w + gap), y)
                image.alpha_composite(card, origin)
            y += card_h
            if start + _COLS < len(rows):
                y += gap
        y += _px(scale, 28)
    return image


def _random_artwork(illust_dir: Path, hires_dir: Path) -> Image.Image | None:
    for folder in (hires_dir, illust_dir):
        if not folder.is_dir():
            continue
        files = [path for path in folder.glob("*.png") if _usable_art(path)]
        if not files:
            continue
        path = random.choice(files)
        try:
            with Image.open(path) as opened:
                return opened.convert("RGB")
        except (OSError, ValueError):
            continue
    return None


def _usable_art(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size <= 8_000_000
    except OSError:
        return False


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


def _open_art(illustration_id: str, hires_dir: Path, low_dir: Path, *, prefer_low: bool) -> Image.Image | None:
    path = illustration_file(illustration_id, hires_dir, low_dir, prefer_low=prefer_low)
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB")
    except (OSError, ValueError):
        return None


def _player_header(
    username: str,
    total_rks: float,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    avatar_art: Image.Image | None,
    banner_art: Image.Image | None,
    title: str,
    avatar_pos: dict,
    colors: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]],
) -> Image.Image:
    width, height = _px(scale, 680), _px(scale, 118)
    bg1, bg2, ink = colors
    body = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    band_h = int(height * 0.64)
    body.paste(_horizontal_gradient(width, height - band_h, bg1, bg2), (0, band_h))
    draw = ImageDraw.Draw(body)
    number = f"{total_rks:.4f}"
    number_w = int(draw.textlength(number, font=fonts["rks_big"]))
    rks_x = width - _px(scale, 28) - number_w
    mark = "RKS"
    mark_box = fonts["watermark"].getbbox(mark)
    mark_h = max(1, mark_box[3] - mark_box[1])
    mark_w = int(draw.textlength(mark, font=fonts["watermark"]))
    mark_x = rks_x + number_w - mark_w + _px(scale, 6)
    mark_y = int(band_h - mark_h / 8 - mark_box[1])
    # Page color is the layout ink at #80, then CSS opacity 0.7. Draw on a
    # clear layer and composite it, or the pill mask later turns the white solid.
    ghost = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(ghost).text(
        (mark_x, mark_y),
        mark,
        font=fonts["watermark"],
        fill=(*ink, 90),
    )
    body.alpha_composite(ghost)
    band = _name_band(banner_art, width - _px(scale, 70), band_h)
    body.paste(band, (_px(scale, 70), 0))
    name = _clip(username, fonts["name"], width - _px(scale, 250), draw)
    draw.text((_px(scale, 136), _px(scale, 14)), name, font=fonts["name"], fill=(255, 255, 255, 255))

    rks_y = band_h + _px(scale, 8)
    if title:
        draw.text(
            (_px(scale, 136), rks_y),
            _clip(title, fonts["bio"], rks_x - _px(scale, 150), draw),
            font=fonts["bio"],
            fill=(*ink, 255),
        )
    draw.text((rks_x, rks_y), number, font=fonts["rks_big"], fill=(*ink, 255))

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 2, fill=255)
    body.putalpha(mask)
    header = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ring = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=height // 2,
        outline=(0, 178, 236, 255),
        width=_px(scale, 3),
    )
    header.alpha_composite(body)
    header.alpha_composite(ring)

    avatar_size = _px(scale, 108)
    avatar = _avatar(avatar_art, avatar_size, avatar_pos)
    framed = Image.new("RGBA", (avatar_size + _px(scale, 8), avatar_size + _px(scale, 8)), (0, 0, 0, 0))
    ImageDraw.Draw(framed).ellipse((0, 0, framed.width - 1, framed.height - 1), fill=(255, 255, 255, 255))
    framed.paste(avatar, (_px(scale, 4), _px(scale, 4)), avatar)
    header.alpha_composite(framed, (_px(scale, 4), (height - framed.height) // 2))
    return header


def _horizontal_gradient(
    width: int,
    height: int,
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> Image.Image:
    row = Image.new("RGBA", (max(width, 1), 1))
    pixels = row.load()
    span = max(width - 1, 1)
    for x in range(width):
        blend = x / span
        pixels[x, 0] = tuple(int(start + (end - start) * blend) for start, end in zip(left, right)) + (255,)
    return row.resize((width, max(height, 1)))


def _name_band(artwork: Image.Image | None, width: int, height: int) -> Image.Image:
    if artwork is None:
        band = Image.new("RGBA", (width, height), (14, 14, 18, 255))
    else:
        band = _cover(artwork, width, max(height, int(height * 1.4))).convert("RGBA")
        top = max(0, int(band.height * 0.28))
        band = band.crop((0, top, width, top + height))
    shade = Image.new("L", (width, 1))
    for x in range(width):
        strength = 1 - (x / max(width - 1, 1)) * 0.45
        shade.putpixel((x, 0), int(255 * strength))
    shade = shade.resize((width, height))
    dark = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    dark.putalpha(shade)
    band.alpha_composite(dark)
    return band


def _avatar(artwork: Image.Image | None, size: int, pos: dict) -> Image.Image:
    if artwork is None:
        source = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    else:
        try:
            zoom = float(pos.get("z"))
        except (TypeError, ValueError):
            zoom = 1.0
        if zoom <= 0:
            zoom = 1.0
        try:
            saved_x = float(pos.get("x"))
        except (TypeError, ValueError):
            saved_x = 0.0
        try:
            saved_y = float(pos.get("y"))
        except (TypeError, ValueError):
            saved_y = 0.0
        cover_scale = max(size / artwork.width, size / artwork.height)
        window = min(float(artwork.width), float(artwork.height), max(1.0, (size / cover_scale) / zoom))
        shift_x = (saved_x - 0.5) * window
        shift_y = (0.5 - saved_y) * window
        left = artwork.width / 2 - shift_x - window / 2
        top = artwork.height / 2 - shift_y - window / 2
        left = min(max(0.0, left), max(0.0, artwork.width - window))
        top = min(max(0.0, top), max(0.0, artwork.height - window))
        crop = artwork.crop((int(left), int(top), int(left + window), int(top + window)))
        source = crop.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    source.putalpha(mask)
    return source


def _section_title(
    draw: ImageDraw.ImageDraw,
    label: str,
    top: int,
    width: int,
    pad: int,
    font: ImageFont.ImageFont,
    scale: float,
) -> None:
    text_w = int(draw.textlength(label, font=font))
    center = width // 2
    text_x = center - text_w // 2
    draw.text((text_x, top), label, font=font, fill=(0, 178, 236, 255))
    gap = _px(scale, 16)
    line_y = top + _px(scale, 14)
    _fade_line(draw, pad, text_x - gap, line_y, _px(scale, 400), to_right=True)
    _fade_line(draw, text_x + text_w + gap, width - pad, line_y, _px(scale, 400), to_right=False)


def _fade_line(
    draw: ImageDraw.ImageDraw,
    start: int,
    end: int,
    y: int,
    max_span: int,
    *,
    to_right: bool,
) -> None:
    if end - start > max_span:
        if to_right:
            start = end - max_span
        else:
            end = start + max_span
    length = end - start
    if length <= 1:
        return
    for offset in range(length):
        amount = offset / (length - 1)
        strength = amount if to_right else 1 - amount
        channel = int(255 * strength)
        draw.line([(start + offset, y), (start + offset, y + 2)], fill=(0, 178, 236, channel))


def _card_image(
    size: tuple[int, int],
    row: dict,
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
) -> Image.Image:
    card_w, card_h = size
    card = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    radius = min(_px(scale, 55), card_h // 2)
    draw.rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=radius, fill=(255, 255, 255, 214))

    circle = _px(scale, 85)
    circle_xy = (_px(scale, 13), (card_h - circle) // 2)
    diff = str(row.get("diff") or "")
    constant = row.get("const")
    const_text = f"{float(constant):.1f}" if isinstance(constant, (int, float)) else "?"
    badge_h = _px(scale, 22)
    const_w = int(draw.textlength(const_text, font=fonts["const"]))
    number_x = circle_xy[0] + circle + _px(scale, 2)
    badge_x = circle_xy[0] + circle - _px(scale, 14)
    badge_w = number_x + const_w + _px(scale, 8) - badge_x
    badge_y = circle_xy[1] + (circle - badge_h) // 2
    _right_badge(
        draw,
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        _DIFF_COLORS.get(diff, (107, 70, 193)),
    )
    ink = (28, 28, 32, 255) if diff in _LIGHT_DIFFS else (255, 255, 255, 255)
    draw.text((number_x, badge_y + _px(scale, 3)), const_text, font=fonts["const"], fill=ink)

    jacket = _circle_jacket(row, index, illust_hires_dir, illust_dir, circle)
    card.paste(jacket, circle_xy, jacket)

    text_x = circle_xy[0] + circle + _px(scale, 10)
    text_right = card_w - _px(scale, 16)
    title = _clip(str(row.get("title") or "—"), fonts["title"], text_right - text_x, draw)
    draw.text((text_x, _px(scale, 12)), title, font=fonts["title"], fill=(0, 0, 0, 255))

    max_rks = (11 * float(constant) + 10.5) if isinstance(constant, (int, float)) else None
    rks = float(row.get("rks") or 0)
    full_rks = max_rks is not None and rks >= max_rks - 1e-3
    rks_text = f"{rks:.3f}/{max_rks:.3f}" if max_rks is not None else f"{rks:.3f}"
    rks_x = number_x + const_w + _px(scale, 12)
    draw.text(
        (rks_x, badge_y + _px(scale, 1)),
        _clip(rks_text, fonts["rks"], text_right - rks_x, draw),
        font=fonts["rks"],
        fill=(*_GOLD, 255) if full_rks else (28, 28, 28, 255),
    )

    score = int(row.get("score") or 0)
    song = _song_for(index, row)
    chart = song.charts.get(diff) if song else None
    chart_score = chart.score if chart is not None and chart.score > 0 else 0
    full_score = chart_score > 0 and score >= chart_score - 1
    score_text = f"{score}/{chart_score}" if chart_score else str(score)
    score_y = card_h - _px(scale, 30)
    rank = f"#{int(row.get('sourceRank') or 0)}"
    rank_w = int(draw.textlength(rank, font=fonts["rank"]))
    score_limit = text_right - rank_w - _px(scale, 8) - text_x
    draw.text(
        (text_x, score_y),
        _clip(score_text, fonts["score"], score_limit, draw),
        font=fonts["score"],
        fill=(*_GOLD, 255) if full_score else (196, 154, 106, 255),
    )
    draw.text((text_right - rank_w, score_y + _px(scale, 3)), rank, font=fonts["rank"], fill=(85, 85, 85, 255))
    return card


def _right_badge(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = box
    radius = max(1, (y1 - y0) // 2)
    draw.rounded_rectangle(box, radius=radius, fill=(*fill, 255))
    draw.rectangle((x0, y0, x0 + radius, y1), fill=(*fill, 255))


def _song_for(index: SongIndex, row: dict):
    track_id = str(row.get("trackId") or "")
    return index.by_asset.get(strip_track_prefix(track_id))


def _circle_jacket(
    row: dict,
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    size: int,
) -> Image.Image:
    song = _song_for(index, row)
    path = None
    if song is not None:
        path = illustration_path(song, illust_hires_dir, illust_dir, prefer_low=False)
    source = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    if path is not None:
        try:
            with Image.open(path) as opened:
                source = opened.convert("RGBA")
                source.thumbnail((size, size), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            source = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    fitted = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    left = (size - source.width) // 2
    top = (size - source.height) // 2
    fitted.paste(source, (left, top))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    fitted.putalpha(mask)
    return fitted


def _clip(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw) -> str:
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
