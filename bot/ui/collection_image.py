"""Paginated collage of owned and missing layouts or illustrations."""

from __future__ import annotations

import io
import random
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from bot.services.profile import layout_colors
from bot.services.songdata import illustration_file
from bot.ui.b40_image import _aa_round_mask, load_bundle_texture
from bot.ui.layout_card import load_collection_layout
from bot.ui.textfont import hangul_face, load_face, load_hangul, one_line


_PAPER = (255, 255, 255)
_PURPLE_SHADES = (
    (142, 72, 214),
    (176, 118, 228),
    (98, 62, 184),
    (198, 156, 236),
    (118, 86, 196),
)
_INK = (32, 36, 42)
_MUTED = (96, 104, 112)
_BIO = (132, 84, 214)
_BIO_DEEP = (98, 52, 168)
_BIO_RING = (186, 164, 224)
# Same edge placement as the asyncombat sheet, in purple, for the bio page only.
_BIO_DOTS = (
    (-0.10, -0.12, 0.46, 88),
    (0.72, -0.08, 0.38, 76),
    (0.86, 0.12, 0.24, 70),
    (-0.08, 0.18, 0.22, 64),
    (0.38, -0.06, 0.16, 58),
    (0.06, 0.36, 0.12, 80),
    (0.84, 0.42, 0.18, 66),
    (-0.06, 0.55, 0.16, 72),
    (0.82, 0.64, 0.22, 82),
    (0.58, 0.74, 0.14, 68),
    (-0.12, 0.78, 0.32, 90),
    (0.12, 0.88, 0.20, 60),
    (0.42, 0.90, 0.26, 78),
    (0.78, 0.82, 0.28, 84),
    (0.22, 0.02, 0.10, 66),
    (0.54, 0.22, 0.11, 54),
)
_GAP = 16
_HEADER = 52
_FRAME = 36
# Native layout cards are ~1488×2078; keep aspect and enough pixels for Discord embeds.
_LAYOUT_W = 320
_LAYOUT_H = 446
_ILLUST = 360
_CAPTION = 36
# Soft dark rim behind layouts so near-white cards (e.g. 00031) stay readable.
# Side segments stop before corners so the bezel never wraps past the round.
_LAYOUT_WELL = (34, 38, 46, 56)
_LAYOUT_PAD = 3
_LAYOUT_CORNER = 18
_LAYOUT_EDGE_FEATHER = 4
_LAYOUT_BORDER_GAP = 40  # clear space at each corner end of a side segment
_LAYOUT_BORDER_WIDTH = 2
_TILES: dict[tuple, Image.Image] = {}
_TILE_LOCK = threading.Lock()
_LAYOUT_EDGE_MASKS: dict[tuple[int, int, int, int], Image.Image] = {}


def render_collection_grid(
    *,
    rows: list[dict[str, str]],
    owned: set[str] | None,
    title: str,
    progress: str,
    page_label: str,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    repo_root: Path,
) -> bytes:
    kind = str(rows[0].get("kind") or "") if rows else "illustration"
    cell_w, cell_h = (_LAYOUT_W, _LAYOUT_H) if kind == "layout" else (_ILLUST, _ILLUST)
    columns = 4 if kind == "layout" else 3
    count = max(1, len(rows))
    row_count = max(1, (count + columns - 1) // columns)
    width = _FRAME * 2 + columns * cell_w + (columns - 1) * _GAP
    height = _HEADER + row_count * (cell_h + _CAPTION) + (row_count - 1) * _GAP + _FRAME
    canvas = _pattern_sheet(width, height).convert("RGBA")
    ImageDraw.Draw(canvas).rectangle((0, 0, width, _HEADER - 6), fill=(*_PAPER, 255))
    panel = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    panel_pen = ImageDraw.Draw(panel)
    panel_pen.rounded_rectangle(
        (_FRAME - 14, _HEADER - 8, width - _FRAME + 14, height - _FRAME + 14),
        radius=22,
        fill=(255, 255, 255, 248),
    )
    canvas.alpha_composite(panel)
    draw = ImageDraw.Draw(canvas)
    title_font = load_face(font_path, 22)
    caption_font = load_face(font_path, 14)
    caption_hangul = load_hangul(14)
    header_font = hangul_face(title_font, load_hangul(22), f"{title} {progress} {page_label}")
    header = one_line(f"{title}  |  {progress}  |  {page_label}" if progress else f"{title}  |  {page_label}")
    draw.text((_FRAME, 14), _fit(header, header_font, width - _FRAME * 2, draw), font=header_font, fill=_INK)
    track_owned = owned is not None

    for index, row in enumerate(rows):
        column = index % columns
        grid_row = index // columns
        x = _FRAME + column * (cell_w + _GAP)
        y = _HEADER + grid_row * (cell_h + _CAPTION + _GAP)
        asset_id = str(row.get("id") or "")
        is_owned = True if not track_owned else asset_id in owned
        tile = _tile(row, is_owned, cell_w, cell_h, illust_hires_dir, illust_dir, repo_root)
        if tile.mode == "RGBA":
            canvas.alpha_composite(tile, (x, y))
        else:
            canvas.paste(tile, (x, y))
        if track_owned:
            _badge(draw, x + cell_w - 28, y + 8, is_owned)
        _draw_caption(
            draw,
            str(row.get("name") or asset_id),
            caption_font,
            caption_hangul,
            x,
            y + cell_h + 3,
            cell_w,
            _INK if is_owned else _MUTED,
        )

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def render_bio_sheet(
    *,
    rows: list[dict[str, str]],
    owned: set[str] | None,
    title: str,
    part1: str,
    part2: str,
    progress: str,
    page_label: str,
    font_path: Path,
) -> bytes:
    """Two columns of pills. Owned halves use a filled circle when ownership is tracked."""
    width = 1080
    margin = 36
    header = 64
    label_h = 30
    row_h = 62
    height = header + label_h + max(1, len(rows)) * row_h + 24
    canvas = _circle_sheet(width, height)
    draw = ImageDraw.Draw(canvas)
    title_font = load_face(font_path, 26)
    title_hangul = load_hangul(26)
    label_font = load_face(font_path, 16)
    label_hangul = load_hangul(16)
    cell_font = load_face(font_path, 22)
    cell_hangul = load_hangul(22)
    header_text = one_line(f"{title}   |   {progress}   |   {page_label}" if progress else f"{title}   |   {page_label}")
    face = hangul_face(title_font, title_hangul, header_text)
    draw.text((margin, 18), _fit(header_text, face, width - margin * 2, draw), font=face, fill=_INK)
    gap = 16
    col_w = (width - margin * 2 - gap) // 2
    left_x = margin
    right_x = margin + col_w + gap
    _column_label(draw, part1, label_font, label_hangul, left_x, header, col_w)
    _column_label(draw, part2, label_font, label_hangul, right_x, header, col_w)
    track_owned = owned is not None
    for index, row in enumerate(rows):
        top = header + label_h + index * row_h
        if track_owned:
            left_owned, right_owned = _bio_owned(row, owned)
        else:
            left_owned = right_owned = None
        _bio_pill(canvas, row.get("title1") or "—", left_owned, left_x, top, col_w, row_h, cell_font, cell_hangul)
        _bio_pill(canvas, row.get("title2") or "—", right_owned, right_x, top, col_w, row_h, cell_font, cell_hangul)
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def _circle_sheet(width: int, height: int) -> Image.Image:
    """White sheet with the same soft circles as asyncombat, colored purple."""
    image = Image.new("RGBA", (width, height), (*_PAPER, 255))
    scale = 2
    dots = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    blob = ImageDraw.Draw(dots)
    for fx, fy, fd, alpha in _BIO_DOTS:
        left = int(width * fx * scale)
        top = int(height * fy * scale)
        size = int(width * fd * scale)
        blob.ellipse((left, top, left + size, top + size), fill=(*_BIO, alpha))
    image.alpha_composite(dots.resize(image.size, Image.Resampling.LANCZOS))
    return image


# Corner marks only. Each page size shifts them a little, but they stay in the frame.
_MARKS = (
    (-0.08, -0.10, 0.34, 0.72, 0),
    (0.74, -0.12, 0.38, 0.46, 8),
    (0.82, 0.38, 0.24, 1.35, -12),
    (-0.10, 0.42, 0.22, 1.2, 10),
    (0.68, 0.78, 0.36, 0.55, -6),
    (-0.12, 0.80, 0.32, 0.64, 4),
)


def _pattern_sheet(width: int, height: int) -> Image.Image:
    """White sheet with a few rounded purple blocks in the corners."""
    image = Image.new("RGBA", (width, height), (*_PAPER, 255))
    scale = 2
    layer = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    rng = random.Random(width * 10007 + height * 17)
    for index, (fx, fy, size, aspect, tilt) in enumerate(_MARKS):
        shade = _PURPLE_SHADES[index % len(_PURPLE_SHADES)]
        left = int(width * (fx + rng.uniform(-0.02, 0.02)) * scale)
        top = int(height * (fy + rng.uniform(-0.02, 0.02)) * scale)
        wide = max(64, int(width * size))
        tall = max(48, int(wide * aspect))
        tile = _corner_block(wide * scale, tall * scale, (*shade, 78), tilt + rng.uniform(-4, 4))
        _stamp(layer, tile, left, top)
    image.alpha_composite(layer.resize(image.size, Image.Resampling.LANCZOS))
    return image.convert("RGB")


def _corner_block(wide: int, tall: int, color: tuple[int, int, int, int], angle: float) -> Image.Image:
    """A rounded block. The corner radius stays small so it does not become a circle."""
    wide = max(8, wide)
    tall = max(8, tall)
    pad = 8
    tile = Image.new("RGBA", (wide + pad * 2, tall + pad * 2), (0, 0, 0, 0))
    radius = max(10, int(min(wide, tall) * 0.16))
    ImageDraw.Draw(tile).rounded_rectangle((pad, pad, pad + wide - 1, pad + tall - 1), radius=radius, fill=color)
    if abs(angle) < 0.5:
        return tile
    return tile.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)


def _stamp(canvas: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
    left = max(0, -x)
    top = max(0, -y)
    right = min(sprite.width, canvas.width - x)
    bottom = min(sprite.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(sprite.crop((left, top, right, bottom)), (max(0, x), max(0, y)))


def _bio_owned(row: dict[str, str], owned: set[str]) -> tuple[bool, bool]:
    stem = row.get("id") or ""
    left = f"bio.{stem}.1" in owned
    right = f"bio.{stem}.2" in owned
    if not left and not right and (stem in owned or f"bio.{stem}" in owned):
        return True, True
    return left, right


def _column_label(
    pen: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    hangul: ImageFont.ImageFont | None,
    x: int,
    y: int,
    width: int,
) -> None:
    face = hangul_face(font, hangul, text)
    pen.text((x + 22, y + 8), _fit(one_line(text), face, width - 32, pen), font=face, fill=_BIO_DEEP, anchor="lm")


def _bio_pill(
    canvas: Image.Image,
    text: str,
    held: bool | None,
    x: int,
    y: int,
    width: int,
    height: int,
    font: ImageFont.ImageFont,
    hangul: ImageFont.ImageFont | None,
) -> None:
    pill_h = height - 12
    top = y + (height - pill_h) // 2
    pen = ImageDraw.Draw(canvas)
    pen.rounded_rectangle((x, top, x + width, top + pill_h), radius=pill_h // 2, fill=(255, 255, 255), outline=_BIO_RING, width=2)
    face = hangul_face(font, hangul, text)
    if held is None:
        label = _fit(one_line(text), face, width - 36, pen)
        pen.text((x + 22, top + pill_h // 2), label, font=face, fill=_INK, anchor="lm")
        return
    radius = 11
    center = (x + 26, top + pill_h // 2)
    _status_circle(canvas, center, radius, held)
    label = _fit(one_line(text), face, width - 62, pen)
    pen.text((center[0] + radius + 12, center[1]), label, font=face, fill=_INK if held else _MUTED, anchor="lm")


def _status_circle(image: Image.Image, center: tuple[int, int], radius: int, held: bool) -> None:
    """Owned is a filled disk inside a white ring. Missing is an empty ring."""
    scale = 4
    pad = 4
    outer = radius + pad
    size = outer * 2 * scale
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(tile)
    origin = outer * scale
    rim = max(2, radius // 4) * scale
    if held:
        _disk(pen, origin, origin, radius * scale, (255, 255, 255, 255))
        _disk(pen, origin, origin, max(1, radius * scale - rim), (*_BIO, 255))
    else:
        _disk(pen, origin, origin, radius * scale, (*_BIO_RING, 255))
        _disk(pen, origin, origin, max(1, radius * scale - rim), (255, 255, 255, 255))
    smooth = tile.resize((outer * 2, outer * 2), Image.Resampling.LANCZOS)
    image.alpha_composite(smooth, (center[0] - outer, center[1] - outer))


def _disk(pen: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, fill: tuple[int, int, int, int]) -> None:
    pen.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)


def _tile(
    row: dict[str, str],
    is_owned: bool,
    cell_w: int,
    cell_h: int,
    illust_hires_dir: Path,
    illust_dir: Path,
    repo_root: Path,
) -> Image.Image:
    kind = row.get("kind") or ""
    asset_id = str(row.get("id") or "")
    key = (kind, asset_id, is_owned, cell_w, cell_h, str(repo_root))
    with _TILE_LOCK:
        cached = _TILES.get(key)
        if cached is not None:
            return cached.copy()
    if kind == "layout":
        image = _layout_tile(repo_root, asset_id, cell_w, cell_h)
    else:
        image = _illustration_tile(asset_id, illust_hires_dir, illust_dir, repo_root, cell_w)
    if not is_owned:
        image = _dim_tile(image)
    with _TILE_LOCK:
        if len(_TILES) > 320:
            _TILES.clear()
        _TILES.setdefault(key, image.copy())
    return image


def _illustration_tile(
    asset_id: str,
    hires_dir: Path,
    low_dir: Path,
    repo_root: Path,
    size: int,
) -> Image.Image:
    trim_matte = asset_id.startswith("altIllustration.")
    path = illustration_file(asset_id, hires_dir, low_dir, prefer_low=False)
    if path is not None:
        try:
            with Image.open(path) as source:
                return _round_cover(source.convert("RGBA"), size, trim_matte=trim_matte)
        except OSError:
            pass
    try:
        texture = load_bundle_texture(repo_root, asset_id)
    except Exception:
        texture = None
    if texture is not None:
        try:
            return _round_cover(texture.convert("RGBA"), size, trim_matte=trim_matte)
        finally:
            texture.close()
    return _round_cover(Image.new("RGBA", (size, size), (210, 214, 218, 255)), size)


def _layout_tile(repo_root: Path, layout_id: str, cell_w: int, cell_h: int) -> Image.Image:
    """Fit the card on a soft well; round+feather so prefab cards match framed corners."""
    frame = load_collection_layout(repo_root, layout_id)
    tile = _layout_well(cell_w, cell_h)
    inset_w = cell_w - _LAYOUT_PAD * 2
    inset_h = cell_h - _LAYOUT_PAD * 2
    if frame is None:
        art = _swatch(layout_id, repo_root, inset_w, inset_h)
        tile.alpha_composite(art, (_LAYOUT_PAD, _LAYOUT_PAD))
        return _soft_round_layout(tile)
    try:
        fitted = _fit_rgba(frame, inset_w, inset_h)
    finally:
        frame.close()
    tile.alpha_composite(fitted, (_LAYOUT_PAD, _LAYOUT_PAD))
    return _soft_round_layout(tile)


def _layout_well(cell_w: int, cell_h: int) -> Image.Image:
    """Four mid-side rims that fade out before the corners — never wraps the round."""
    image = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
    alpha = Image.new("L", (cell_w, cell_h), 0)
    pixels = alpha.load()
    gap = max(_LAYOUT_BORDER_GAP, _LAYOUT_CORNER + 6)
    thick = max(1, _LAYOUT_BORDER_WIDTH)
    inset = 1
    ramp = max(10, gap // 2)

    def _strength(pos: int, start: int, stop: int) -> int:
        """Full in the middle; ease to 0 over `ramp` px at each end."""
        dist = min(pos - start, stop - pos)
        if dist <= 0:
            return 0
        if dist >= ramp:
            return 255
        t = dist / ramp
        # smoothstep for fade-in / fade-out
        t = t * t * (3 - 2 * t)
        return int(255 * t)

    # Top / bottom
    y_top = inset
    y_bot = cell_h - inset - thick
    for x in range(gap, cell_w - gap):
        value = _strength(x, gap, cell_w - 1 - gap)
        if value <= 0:
            continue
        for dy in range(thick):
            pixels[x, y_top + dy] = max(pixels[x, y_top + dy], value)
            pixels[x, y_bot + dy] = max(pixels[x, y_bot + dy], value)
    # Left / right
    x_left = inset
    x_right = cell_w - inset - thick
    for y in range(gap, cell_h - gap):
        value = _strength(y, gap, cell_h - 1 - gap)
        if value <= 0:
            continue
        for dx in range(thick):
            pixels[x_left + dx, y] = max(pixels[x_left + dx, y], value)
            pixels[x_right + dx, y] = max(pixels[x_right + dx, y], value)

    # Tiny blur for anti-alias only — not enough to spill into the corner gap.
    soft = alpha.filter(ImageFilter.GaussianBlur(radius=1))
    color = Image.new("RGBA", (cell_w, cell_h), (*_LAYOUT_WELL[:3], 255))
    color.putalpha(soft.point(lambda value: int(value * _LAYOUT_WELL[3] / 255)))
    image.alpha_composite(color)
    return image


def _soft_round_layout(image: Image.Image) -> Image.Image:
    """Clip sharp prefab cards (00031/36/42) to the same soft round rim as framed layouts."""
    mask = _layout_edge_mask(image.width, image.height)
    out = image.copy()
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out


def _layout_edge_mask(width: int, height: int) -> Image.Image:
    """Rounded coverage; blur stays inset so the fade does not spill past the corner."""
    key = (width, height, _LAYOUT_CORNER, _LAYOUT_EDGE_FEATHER)
    cached = _LAYOUT_EDGE_MASKS.get(key)
    if cached is not None:
        return cached.copy()
    feather = max(1, _LAYOUT_EDGE_FEATHER)
    # Shrink the hard rect before blur so the soft rim ends at the true corner.
    inset = feather
    solid = Image.new("L", (width, height), 0)
    ImageDraw.Draw(solid).rounded_rectangle(
        (inset, inset, width - 1 - inset, height - 1 - inset),
        radius=max(1, _LAYOUT_CORNER - inset),
        fill=255,
    )
    soft = solid.filter(ImageFilter.GaussianBlur(radius=feather))
    _LAYOUT_EDGE_MASKS[key] = soft
    return soft.copy()


def _fit_rgba(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
    scale = min(box_w / max(1, image.width), box_h / max(1, image.height))
    resized = _downscale(
        image,
        max(1, int(round(image.width * scale))),
        max(1, int(round(image.height * scale))),
    )
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    x = (box_w - resized.width) // 2
    y = (box_h - resized.height) // 2
    if resized.mode == "RGBA":
        canvas.paste(resized, (x, y), resized)
    else:
        canvas.paste(resized, (x, y))
    return canvas


def _swatch(layout_id: str, repo_root: Path, cell_w: int, cell_h: int) -> Image.Image:
    left, right, _ink = layout_colors(layout_id, repo_root)
    image = Image.new("RGBA", (cell_w, cell_h), (*left, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, cell_h // 2, cell_w - 10, cell_h - 16), fill=(*right, 255))
    image.putalpha(_layout_edge_mask(cell_w, cell_h))
    return image


def _round_cover(image: Image.Image, size: int, *, trim_matte: bool = False) -> Image.Image:
    """Fill a square and clip to a soft rounded mask — no stroked border edge."""
    trimmed = _trim_frame(image, trim_matte=trim_matte)
    scale = max(size / max(1, trimmed.width), size / max(1, trimmed.height))
    resized = _downscale(
        trimmed,
        max(1, int(round(trimmed.width * scale))),
        max(1, int(round(trimmed.height * scale))),
    )
    left = max(0, (resized.width - size) // 2)
    top = max(0, (resized.height - size) // 2)
    tile = resized.crop((left, top, left + size, top + size)).convert("RGBA")
    tile.putalpha(_aa_round_mask(size, size, 18))
    return tile


def _trim_frame(image: Image.Image, *, trim_matte: bool = False) -> Image.Image:
    """Drop empty alpha, and for specials also drop a flat outer matte."""
    current = image.convert("RGBA") if image.mode != "RGBA" else image
    current = _trim_transparent(current)
    if trim_matte:
        current = _trim_flat_border(current)
    return current


def _trim_transparent(image: Image.Image, threshold: int = 16) -> Image.Image:
    """Crop empty alpha margins so soft texture edges do not leave a halo."""
    if image.mode != "RGBA":
        return image
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value > threshold else 0).getbbox()
    if bbox is None or bbox == (0, 0, image.width, image.height):
        return image
    return image.crop(bbox)


def _trim_flat_border(image: Image.Image, tolerance: int = 12, min_keep: float = 0.45) -> Image.Image:
    """Crop a near-solid outer matte (common on special jackets)."""
    width, height = image.size
    if width < 32 or height < 32:
        return image
    pixels = image.load()
    sample = (
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
        pixels[width // 2, 0],
        pixels[width // 2, height - 1],
        pixels[0, height // 2],
        pixels[width - 1, height // 2],
    )
    base = sample[0]
    if any(not _near(pixel, base, tolerance) for pixel in sample[1:]):
        return image

    def content(x: int, y: int) -> bool:
        pixel = pixels[x, y]
        return pixel[3] > 16 and not _near(pixel, base, tolerance)

    left = 0
    while left < width and not any(content(left, y) for y in range(0, height, 2)):
        left += 1
    right = width - 1
    while right > left and not any(content(right, y) for y in range(0, height, 2)):
        right -= 1
    top = 0
    while top < height and not any(content(x, top) for x in range(0, width, 2)):
        top += 1
    bottom = height - 1
    while bottom > top and not any(content(x, bottom) for x in range(0, width, 2)):
        bottom -= 1
    if left >= right or top >= bottom:
        return image
    kept_w = right - left + 1
    kept_h = bottom - top + 1
    if kept_w < width * min_keep or kept_h < height * min_keep:
        return image
    if (left, top, right + 1, bottom + 1) == (0, 0, width, height):
        return image
    return image.crop((left, top, right + 1, bottom + 1))


def _near(pixel: tuple[int, ...], base: tuple[int, ...], tolerance: int) -> bool:
    return (
        abs(pixel[0] - base[0]) <= tolerance
        and abs(pixel[1] - base[1]) <= tolerance
        and abs(pixel[2] - base[2]) <= tolerance
    )


def _dim_tile(image: Image.Image) -> Image.Image:
    if image.mode == "RGBA":
        color = image.convert("RGB")
        veil = Image.new("RGB", color.size, (248, 249, 251))
        blended = Image.blend(color, veil, 0.22).convert("RGBA")
        blended.putalpha(image.getchannel("A"))
        return blended
    veil = Image.new("RGB", image.size, (248, 249, 251))
    return Image.blend(image.convert("RGB"), veil, 0.22)


def _downscale(image: Image.Image, width: int, height: int) -> Image.Image:
    """Halve with a cheap filter until Lanczos only finishes a small image."""
    current = image
    while current.width > width * 2 and current.height > height * 2:
        current = current.resize(
            (max(width, current.width // 2), max(height, current.height // 2)),
            Image.Resampling.BOX,
        )
    if current.size != (width, height):
        current = current.resize((width, height), Image.Resampling.LANCZOS)
    return current


def _badge(draw: ImageDraw.ImageDraw, x: int, y: int, owned: bool) -> None:
    box = (x, y, x + 22, y + 22)
    if owned:
        draw.rounded_rectangle(box, radius=6, fill=(36, 140, 86))
        draw.line((x + 4, y + 11, x + 9, y + 16), fill=(255, 255, 255), width=3)
        draw.line((x + 9, y + 16, x + 18, y + 6), fill=(255, 255, 255), width=3)
    else:
        draw.rounded_rectangle(box, radius=6, fill=(255, 255, 255), outline=(180, 186, 194), width=2)


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    hangul: ImageFont.ImageFont | None,
    x: int,
    y: int,
    width: int,
    fill: tuple[int, int, int],
) -> None:
    chosen = hangul_face(font, hangul, text)
    lines = _wrap(one_line(text), chosen, width, draw, limit=2)
    line_h = 16
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_h), line, font=chosen, fill=fill)


def _wrap(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw, limit: int) -> list[str]:
    if not text:
        return []
    if draw.textlength(text, font=font) <= width:
        return [text]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    index = 0
    while index < len(words):
        word = words[index]
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= width:
            current = trial
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
        if len(lines) >= limit - 1:
            lines.append(_fit(" ".join(words[index:]), font, width, draw))
            return lines[:limit]
        if draw.textlength(word, font=font) <= width:
            current = word
            index += 1
            continue
        lines.append(_fit(word, font, width, draw))
        index += 1
        if len(lines) >= limit:
            return lines[:limit]
    if current and len(lines) < limit:
        lines.append(current)
    return lines[:limit]


def _fit(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw) -> str:
    text = one_line(text)
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
