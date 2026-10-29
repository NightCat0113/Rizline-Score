"""Best 40 card sheet, matching the pill layout in index.html."""

from __future__ import annotations

import io
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.services.language import strings
from bot.services.profile import layout_colors, player_title
from bot.services.rks import strip_track_prefix
from bot.services.songdata import SongIndex, illustration_file, illustration_path
from bot.ui.textfont import clip as _clip_text
from bot.ui.textfont import load_hangul


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
    language: str = "en",
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
            language=language,
            scale=scale,
        )
        last = _encode(image)
        if len(last) <= max_bytes:
            return last
    return last


_FILE_INDEX: dict[str, dict[str, str]] = {}
_LAYOUT_FRAMES: dict[tuple[str, str], Image.Image | None] = {}


def load_layout_frame(repo_root: Path, layout_id: str) -> Image.Image | None:
    """Cropped layout texture from the local catalog bundle, or None."""
    key = (str(repo_root), layout_id.strip())
    if key not in _LAYOUT_FRAMES:
        _LAYOUT_FRAMES[key] = _read_layout_frame(repo_root, layout_id)
    image = _LAYOUT_FRAMES[key]
    return None if image is None else image.copy()


def render_rizcard(
    *,
    username: str,
    total_rks: float,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    repo_root: Path | None = None,
    card: dict | None = None,
    language: str = "en",
    scale: float = 2.0,
) -> bytes:
    del total_rks
    profile = card or {}
    profile_root = repo_root or font_path.parent
    avatar = _open_art(str(profile.get("avatarId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    banner = _open_art(str(profile.get("backgroundId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    title = player_title(str(profile.get("bioId1") or ""), str(profile.get("bioId2") or ""), profile_root, language)
    colors = layout_colors(str(profile.get("layoutId") or ""), profile_root)
    pos = profile.get("avatarPos") if isinstance(profile.get("avatarPos"), dict) else {}
    frame = load_layout_frame(profile_root, str(profile.get("layoutId") or ""))
    image = _rizcard_image(
        username or "Player",
        font_path,
        scale,
        avatar,
        banner,
        title,
        pos,
        colors[2],
        frame,
    )
    return _png_within(image, MAX_PNG_BYTES)


def _rizcard_image(
    username: str,
    font_path: Path,
    scale: float,
    avatar_art: Image.Image | None,
    banner_art: Image.Image | None,
    title: str,
    avatar_pos: dict,
    ink: tuple[int, int, int],
    frame: Image.Image | None,
) -> Image.Image:
    if frame is None:
        return _plain_rizcard(username, font_path, scale, avatar_art, banner_art, title, avatar_pos, ink)
    card_w, card_h = frame.size
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    art = _card_art(banner_art, card_w, card_h)
    art.putalpha(_card_silhouette(frame))
    canvas.alpha_composite(art)
    canvas.alpha_composite(frame)
    pill = _title_pill(frame)
    portrait = _portrait_slot(frame)
    if pill is None:
        footer_top, footer_bottom = _footer_band(frame.copy())
        title_x = card_w // 2
        title_y = (footer_top + footer_bottom) // 2
        title_span = max(8, footer_bottom - footer_top)
        pill_left, pill_right = card_w // 5, card_w - card_w // 5
    else:
        title_x, title_y, title_span, pill_left, pill_right = pill
    draw = ImageDraw.Draw(canvas)
    title_size = max(18, int(title_span * 0.55))
    name_size = max(title_size + 8, int(title_span * 1.05))
    _draw_username(
        draw,
        username,
        _load_font(font_path, name_size),
        card_w,
        *_name_anchor(card_w, title_x, title_y, title_span, pill_left, pill_right),
    )
    _cover_with_frame(canvas, frame)
    _draw_title(draw, title, _load_font(font_path, title_size), title_x, title_y, pill_right - pill_left, ink)
    _place_portrait(canvas, avatar_art, avatar_pos, (portrait[0], portrait[1]), portrait[2], ring=True)
    return canvas


def _plain_rizcard(
    username: str,
    font_path: Path,
    scale: float,
    avatar_art: Image.Image | None,
    banner_art: Image.Image | None,
    title: str,
    avatar_pos: dict,
    ink: tuple[int, int, int],
) -> Image.Image:
    card_w, card_h = _px(scale, 600), _px(scale, 860)
    canvas = _card_art(banner_art, card_w, card_h)
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=_px(scale, 28), fill=255)
    canvas.putalpha(mask)
    fonts = _rizcard_fonts(font_path, card_w)
    draw = ImageDraw.Draw(canvas)
    footer_top = int(card_h * 0.88)
    pad = card_w // 28
    _draw_username(draw, username, fonts["name"], card_w, card_w - pad, footer_top - pad, "rs")
    _draw_title(draw, title, fonts["bio"], card_w // 2, (footer_top + card_h - card_w // 28) // 2, card_w, ink)
    _place_portrait(
        canvas,
        avatar_art,
        avatar_pos,
        (int(card_w * 0.098), int(card_h * 0.085)),
        max(8, _px(scale, 92)),
    )
    return canvas


def _rizcard_fonts(font_path: Path, card_w: int) -> dict[str, ImageFont.ImageFont]:
    return {
        "name": _load_font(font_path, max(12, card_w * 26 // 600)),
        "bio": _load_font(font_path, max(12, card_w * 18 // 600)),
    }


def _card_art(banner_art: Image.Image | None, width: int, height: int) -> Image.Image:
    if banner_art is None:
        return Image.new("RGBA", (width, height), (24, 26, 34, 255))
    return _cover(banner_art, width, height).convert("RGBA")


def _draw_username(
    draw: ImageDraw.ImageDraw,
    username: str,
    font: ImageFont.ImageFont,
    card_w: int,
    x: int,
    y: int,
    anchor: str,
) -> None:
    name = _clip(username, font, int(card_w * 0.62), draw)
    draw.text(
        (x, y),
        name,
        font=font,
        anchor=anchor,
        fill=(255, 255, 255, 255),
        stroke_width=max(2, getattr(font, "size", 28) // 28),
        stroke_fill=(24, 22, 32, 255),
    )


def _name_anchor(
    card_w: int,
    title_x: int,
    title_y: int,
    title_span: int,
    pill_left: int,
    pill_right: int,
) -> tuple[int, int, str]:
    on_right = title_x >= card_w * 0.5
    gap = max(24, int(title_span * 1.35))
    tuck = max(12, title_span // 2)
    if on_right:
        return min(card_w - 16, pill_right + tuck), title_y - title_span // 2 - gap, "rs"
    return max(16, pill_left - tuck), title_y - title_span // 2 - gap, "ls"


def _portrait_slot(frame: Image.Image) -> tuple[int, int, int]:
    """Portrait sits beside this layout's lanyard hole. The large round window is the illustration."""
    width, height = frame.size
    diameter = max(8, int(width * 0.148))
    hole = _lanyard_hole(frame)
    if hole is None:
        return int(width * 0.171), int(height * 0.144), diameter
    hole_x, hole_y, _hole_d = hole
    dx = int(diameter * 0.41)
    dy = int(diameter * 0.59)
    center_x = hole_x + dx if hole_x < width * 0.5 else hole_x - dx
    return center_x, hole_y + dy, diameter


def _lanyard_hole(frame: Image.Image) -> tuple[int, int, int] | None:
    pixels = frame.load()
    width, height = frame.size
    best: tuple[int, int, int] | None = None
    for cy in range(20, int(height * 0.28), 4):
        for cx in range(20, int(width * 0.55), 4):
            red, green, blue, alpha = pixels[cx, cy]
            if alpha < 200 or (red + green + blue) / 3 > 45:
                continue
            inner = 0
            ring = 0
            for step in range(12):
                radians = step * math.pi / 6
                ix = int(cx + 10 * math.cos(radians))
                iy = int(cy + 10 * math.sin(radians))
                if 0 <= ix < width and 0 <= iy < height:
                    sample = pixels[ix, iy]
                    if sample[3] > 180 and (sample[0] + sample[1] + sample[2]) / 3 < 80:
                        inner += 1
                bright = False
                for radius in (22, 28):
                    ox = int(cx + radius * math.cos(radians))
                    oy = int(cy + radius * math.sin(radians))
                    if 0 <= ox < width and 0 <= oy < height:
                        sample = pixels[ox, oy]
                        if sample[3] > 180 and (sample[0] + sample[1] + sample[2]) / 3 > 170:
                            bright = True
                if bright:
                    ring += 1
            if inner >= 8 and ring >= 7:
                score = ring * 10 + inner
                if best is None or score > best[0] or (score == best[0] and cy < best[2]):
                    best = (score, cx, cy)
    if best is None:
        return None
    return best[1], best[2], 56


def _draw_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    font: ImageFont.ImageFont,
    center_x: int,
    center_y: int,
    max_width: int,
    ink: tuple[int, int, int],
) -> None:
    label = _clip(title or "—", font, max(8, max_width), draw)
    draw.text(
        (center_x, center_y),
        label,
        font=font,
        anchor="mm",
        fill=(*ink, 255),
        stroke_width=max(1, getattr(font, "size", 28) // 32),
        stroke_fill=(24, 22, 32, 255),
    )


def _cover_with_frame(canvas: Image.Image, frame: Image.Image) -> None:
    """Put the solid layout pieces back over the name so the folded corner clips it."""
    cover = frame.copy()
    cover.putalpha(cover.getchannel("A").point(lambda value: 255 if value >= 200 else 0))
    canvas.alpha_composite(cover)


def _place_portrait(
    canvas: Image.Image,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    center: tuple[int, int],
    diameter: int,
    *,
    ring: bool = True,
) -> None:
    avatar = _avatar(avatar_art, diameter, avatar_pos)
    if not ring:
        canvas.alpha_composite(avatar, (center[0] - diameter // 2, center[1] - diameter // 2))
        return
    band = max(2, diameter // 40)
    framed = Image.new("RGBA", (diameter + band * 2, diameter + band * 2), (0, 0, 0, 0))
    ImageDraw.Draw(framed).ellipse((0, 0, framed.width - 1, framed.height - 1), fill=(255, 255, 255, 255))
    framed.paste(avatar, (band, band), avatar)
    canvas.alpha_composite(framed, (center[0] - framed.width // 2, center[1] - framed.height // 2))


def _read_layout_frame(repo_root: Path, layout_id: str) -> Image.Image | None:
    stem = layout_id.strip()
    if not stem:
        return None
    if not stem.startswith("layout."):
        stem = f"layout.{stem}"
    index = _bundle_index(repo_root)
    bundle_name = index.get(f"{stem}.HiRes") or index.get(stem)
    if not bundle_name:
        return None
    path = repo_root / "download" / "bundles" / bundle_name
    if not path.is_file():
        return None
    try:
        import UnityPy
    except ImportError:
        return None
    try:
        env = UnityPy.load(str(path))
    except Exception:
        return None
    best: Image.Image | None = None
    best_area = 0
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            image = getattr(data, "image", None)
        except Exception:
            continue
        if image is None:
            continue
        area = image.width * image.height
        if area > best_area:
            best = image
            best_area = area
    if best is None:
        return None
    return _crop_side_margins(best.convert("RGBA"))


def _bundle_index(repo_root: Path) -> dict[str, str]:
    path = repo_root / "download" / "fileList.json"
    key = str(path)
    cached = _FILE_INDEX.get(key)
    if cached is not None:
        return cached
    index: dict[str, str] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _FILE_INDEX[key] = index
        return index
    if isinstance(payload, list):
        for entry in payload:
            if (
                isinstance(entry, list)
                and len(entry) >= 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
                and entry[1].endswith(".bundle")
            ):
                index.setdefault(entry[0], entry[1])
    _FILE_INDEX[key] = index
    return index


def _crop_side_margins(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()

    def _opaque(x: int) -> bool:
        for y in range(0, height, 2):
            if pixels[x, y] > 16:
                return True
        return False

    left = 0
    while left < width and not _opaque(left):
        left += 1
    right = width - 1
    while right > left and not _opaque(right):
        right -= 1
    if left >= right:
        return image
    return image.crop((left, 0, right + 1, height))


def _card_silhouette(layout: Image.Image) -> Image.Image:
    alpha = layout.getchannel("A")
    width, height = alpha.size
    top = alpha.crop((0, 0, width, max(1, height // 7)))
    if top.getextrema()[1] < 16:
        return Image.new("L", (width, height), 255)
    exterior = alpha.point(lambda value: 0 if value < 16 else 255)
    if exterior.getpixel((0, 0)) == 0:
        ImageDraw.floodfill(exterior, (0, 0), 64, thresh=0)
    return exterior.point(lambda value: 0 if value == 64 else 255)


def _title_pill(layout: Image.Image) -> tuple[int, int, int, int, int] | None:
    """Grey title capsule: center x, center y, height, left, right. Each layout places this differently."""
    image = layout.copy()
    pixels = image.load()
    width, height = image.size
    runs: list[tuple[int, int, int]] = []
    for y in range(int(height * 0.72), height - 2):
        best: tuple[int, int, int] | None = None
        in_run = False
        start = 0
        for x in range(0, width, 2):
            red, green, blue, alpha = pixels[x, y]
            luma = (red + green + blue) / 3
            grey = alpha > 220 and 90 <= luma <= 125 and abs(red - green) < 12 and abs(green - blue) < 12
            if grey and not in_run:
                in_run = True
                start = x
            elif not grey and in_run:
                span = x - start
                if best is None or span > best[0]:
                    best = (span, start, x)
                in_run = False
        if in_run:
            span = width - start
            if best is None or span > best[0]:
                best = (span, start, width)
        if best is not None and width * 0.18 < best[0] < width * 0.70:
            runs.append((y, best[1], best[2]))
    if len(runs) < 8:
        return None
    best_run = [runs[0]]
    current = [runs[0]]
    for previous, row in zip(runs, runs[1:]):
        if row[0] == previous[0] + 1:
            current.append(row)
        else:
            if len(current) > len(best_run):
                best_run = current
            current = [row]
    if len(current) > len(best_run):
        best_run = current
    if len(best_run) < 8:
        return None
    top, bottom = best_run[0][0], best_run[-1][0]
    _y, left, right = best_run[len(best_run) // 2]
    return (left + right) // 2, (top + bottom) // 2, bottom - top + 1, left, right


def _footer_band(layout: Image.Image) -> tuple[int, int]:
    alpha = layout.getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    ratios: list[float] = []
    for y in range(height):
        opaque = 0
        samples = 0
        for x in range(0, width, 8):
            samples += 1
            if pixels[x, y] > 200:
                opaque += 1
        ratios.append(opaque / samples)
    bottom = height - 1
    while bottom > 0 and ratios[bottom] < 0.45:
        bottom -= 1
    top = bottom
    while top > 0 and ratios[top] >= 0.45:
        top -= 1
    if bottom - top < 8:
        return int(height * 0.90), int(height * 0.98)
    return top + 1, bottom


def _png_within(image: Image.Image, max_bytes: int) -> bytes:
    data = _save_png(image)
    if len(data) <= max_bytes:
        return data
    for factor in (0.75, 0.5, 0.35):
        resized = image.resize(
            (max(1, int(image.width * factor)), max(1, int(image.height * factor))),
            Image.Resampling.LANCZOS,
        )
        data = _save_png(resized)
        if len(data) <= max_bytes:
            return data
    return data


def _save_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


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
    language: str,
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
    stamp_h = _px(scale, 28)
    height += stamp_h + pad

    artwork = _random_artwork(illust_dir, illust_hires_dir)
    image = _background(width, height, artwork).convert("RGBA")
    fonts = {
        "name": _load_font(font_path, _px(scale, 32)),
        "section": _load_font(font_path, _px(scale, 22)),
        "title": _load_font(font_path, _px(scale, 16)),
        "title_kr": load_hangul(_px(scale, 16)),
        "const": _load_font(font_path, _px(scale, 13)),
        "rks": _load_font(font_path, _px(scale, 16)),
        "score": _load_font(font_path, _px(scale, 17)),
        "rank": _load_font(font_path, _px(scale, 13)),
        "rks_big": _load_font(font_path, _px(scale, 24)),
        "watermark": _load_font(font_path, _px(scale, 30)),
        "bio": _load_font(font_path, _px(scale, 20)),
        "stamp": _load_font(font_path, _px(scale, 14)),
    }
    profile_root = repo_root or font_path.parent
    avatar = _open_art(str(card.get("avatarId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    banner = _open_art(str(card.get("backgroundId") or ""), illust_hires_dir, illust_dir, prefer_low=False)
    title = player_title(str(card.get("bioId1") or ""), str(card.get("bioId2") or ""), profile_root, language)
    colors = layout_colors(str(card.get("layoutId") or ""), profile_root)
    pos = card.get("avatarPos") if isinstance(card.get("avatarPos"), dict) else {}
    header = _player_header(username, total_rks, fonts, scale, avatar, banner, title, pos, colors)
    image.alpha_composite(header, ((width - header.width) // 2, pad))

    draw = ImageDraw.Draw(image)
    y = pad + _px(scale, _HEADER_BLOCK)
    if not sections:
        draw.text((pad, y), strings(language)["no_charts_group"], font=fonts["section"], fill=(255, 255, 255, 255))
    else:
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
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("Generated %Y-%m-%d %H:%M:%S GMT+8")
    draw.text(
        (width // 2, height - pad - stamp_h // 2),
        stamp,
        font=fonts["stamp"],
        fill=(255, 255, 255, 200),
        anchor="mm",
    )
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

    # Match index.html: avatar diameter equals the pill height (white ring inside).
    ring = max(2, _px(scale, 4))
    avatar_size = max(1, height - ring * 2)
    avatar = _avatar(avatar_art, avatar_size, avatar_pos)
    framed = Image.new("RGBA", (height, height), (0, 0, 0, 0))
    ImageDraw.Draw(framed).ellipse((0, 0, height - 1, height - 1), fill=(255, 255, 255, 255))
    framed.paste(avatar, (ring, ring), avatar)
    # Nudge left like .user-avatar { margin-left: -4px }, keep vertically flush.
    header.alpha_composite(framed, (-ring // 2, 0))
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
        if not math.isfinite(zoom) or zoom <= 0:
            zoom = 1.0
        try:
            saved_x = float(pos.get("x"))
        except (TypeError, ValueError):
            saved_x = 0.5
        if not math.isfinite(saved_x):
            saved_x = 0.5
        try:
            saved_y = float(pos.get("y"))
        except (TypeError, ValueError):
            saved_y = 0.5
        if not math.isfinite(saved_y):
            saved_y = 0.5
        # Match index.html: object-fit cover, then pan by (x-0.5, 0.5-y) and zoom.
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
    title, title_font = _clip_text(str(row.get("title") or "—"), fonts["title"], text_right - text_x, draw, fonts.get("title_kr"))
    draw.text((text_x, _px(scale, 12)), title, font=title_font, fill=(0, 0, 0, 255))

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
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
