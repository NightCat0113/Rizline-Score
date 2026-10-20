"""Best 40 card sheet, drawn from the same local jackets index.html uses."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bot.services.rks import strip_track_prefix
from bot.services.songdata import SongIndex, illustration_path


MAX_PNG_BYTES = 8_000_000
_SCALES = (1.0, 0.75, 0.5)
_DIFF_COLORS = {
    "EZ": (87, 228, 196),
    "HD": (253, 186, 97),
    "IN": (254, 134, 97),
    "AT": (76, 54, 75),
}
_CARD_W = 310
_CARD_H = 110
_GAP = 16
_PAD = 28
_COLS = 5
_HEADER_H = 78
_SECTION_H = 36


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


def _draw(
    *,
    username: str,
    total_rks: float,
    sections: list[tuple[str, list[dict]]],
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    scale: float,
) -> Image.Image:
    def px(value: int) -> int:
        return max(1, int(round(value * scale)))

    card_w, card_h, gap, pad = px(_CARD_W), px(_CARD_H), px(_GAP), px(_PAD)
    width = pad * 2 + _COLS * card_w + (_COLS - 1) * gap
    height = pad + px(_HEADER_H)
    if not sections:
        height += px(40)
    for _label, rows in sections:
        row_count = (len(rows) + _COLS - 1) // _COLS
        height += px(_SECTION_H) + row_count * card_h + max(0, row_count - 1) * gap + px(18)
    height += pad

    image = Image.new("RGB", (width, height), (32, 32, 42))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / max(height - 1, 1)
        color = tuple(int(32 + (52 - 32) * blend) for _ in range(3))
        color = (color[0], color[1], int(42 + (71 - 42) * blend))
        draw.line([(0, y), (width, y)], fill=color)

    fonts = {
        "name": _load_font(font_path, px(30)),
        "header": _load_font(font_path, px(20)),
        "section": _load_font(font_path, px(20)),
        "title": _load_font(font_path, px(16)),
        "const": _load_font(font_path, px(13)),
        "rks": _load_font(font_path, px(15)),
        "score": _load_font(font_path, px(16)),
        "rank": _load_font(font_path, px(13)),
    }
    draw.text((pad, pad), username, font=fonts["name"], fill=(255, 255, 255))
    draw.text((pad, pad + px(38)), f"RKS {total_rks:.2f}", font=fonts["header"], fill=(97, 216, 255))

    y = pad + px(_HEADER_H)
    if not sections:
        draw.text((pad, y), "No charts in this group.", font=fonts["section"], fill=(200, 200, 200))
        return image

    for label, rows in sections:
        draw.text((pad, y), label, font=fonts["section"], fill=(0, 178, 236))
        y += px(_SECTION_H)
        for start in range(0, len(rows), _COLS):
            chunk = rows[start : start + _COLS]
            for column, row in enumerate(chunk):
                origin = (pad + column * (card_w + gap), y)
                _draw_card(
                    image,
                    draw,
                    origin,
                    (card_w, card_h),
                    row,
                    index,
                    illust_hires_dir,
                    illust_dir,
                    fonts,
                    scale,
                )
            y += card_h
            if start + _COLS < len(rows):
                y += gap
        y += px(18)
    return image


def _draw_card(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    size: tuple[int, int],
    row: dict,
    index: SongIndex,
    illust_hires_dir: Path,
    illust_dir: Path,
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
) -> None:
    def px(value: int) -> int:
        return max(1, int(round(value * scale)))

    x, y = origin
    card_w, card_h = size
    radius = min(px(55), card_h // 2)
    draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=radius, fill=(214, 214, 220))

    circle = px(78)
    circle_xy = (x + px(14), y + (card_h - circle) // 2)
    text_x = circle_xy[0] + circle + px(8)
    text_right = x + card_w - px(14)
    text_w = text_right - text_x
    title = _wrap(str(row.get("title") or "—"), fonts["title"], text_w, draw, lines=2)
    draw.multiline_text((text_x, y + px(10)), "\n".join(title), font=fonts["title"], fill=(0, 0, 0), spacing=px(1))

    constant = row.get("const")
    const_text = f"{float(constant):.1f}" if isinstance(constant, (int, float)) else "?"
    diff = str(row.get("diff") or "")
    pill_w = int(draw.textlength(const_text, font=fonts["const"])) + px(22)
    pill_h = px(22)
    pill_x = circle_xy[0] + circle - px(10)
    pill_y = y + px(50)
    draw.rounded_rectangle(
        (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
        radius=pill_h // 2,
        fill=_DIFF_COLORS.get(diff, (107, 70, 193)),
    )
    draw.text((pill_x + px(12), pill_y + px(3)), const_text, font=fonts["const"], fill=(255, 255, 255))

    jacket = _circle_jacket(row, index, illust_hires_dir, illust_dir, circle)
    image.paste(jacket, circle_xy, jacket)

    max_rks = (11 * float(constant) + 10.5) if isinstance(constant, (int, float)) else None
    rks = float(row.get("rks") or 0)
    rks_text = f"{rks:.3f}/{max_rks:.3f}" if max_rks is not None else f"{rks:.3f}"
    rks_stroke = (255, 215, 0) if max_rks is not None and rks >= max_rks - 1e-3 else None
    rks_x = pill_x + pill_w + px(6)
    draw.text(
        (rks_x, pill_y + px(2)),
        _clip(rks_text, fonts["rks"], text_right - rks_x, draw),
        font=fonts["rks"],
        fill=(34, 34, 34),
        stroke_width=1 if rks_stroke else 0,
        stroke_fill=rks_stroke or (34, 34, 34),
    )

    score = int(row.get("score") or 0)
    song = _song_for(index, row)
    chart = song.charts.get(diff) if song else None
    full_score = chart is not None and chart.score > 0 and score >= chart.score - 1
    score_stroke = (255, 215, 0) if full_score else None
    score_y = y + card_h - px(28)
    draw.text(
        (text_x, score_y),
        str(score),
        font=fonts["score"],
        fill=(34, 34, 34),
        stroke_width=1 if score_stroke else 0,
        stroke_fill=score_stroke or (34, 34, 34),
    )
    rank = f"#{int(row.get('sourceRank') or 0)}"
    rank_w = int(draw.textlength(rank, font=fonts["rank"]))
    draw.text((x + card_w - px(18) - rank_w, score_y + px(2)), rank, font=fonts["rank"], fill=(85, 85, 85))


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
        path = illustration_path(song, illust_hires_dir, illust_dir, prefer_low=True)
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


def _wrap(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw, lines: int) -> list[str]:
    if width <= 0:
        return ["…"]
    if draw.textlength(text, font=font) <= width:
        return [text]
    rows: list[str] = []
    remaining = text
    while remaining and len(rows) < lines:
        if draw.textlength(remaining, font=font) <= width:
            rows.append(remaining)
            break
        if len(rows) == lines - 1:
            rows.append(_clip(remaining, font, width, draw))
            break
        cut = len(remaining)
        while cut > 1 and draw.textlength(remaining[:cut], font=font) > width:
            cut -= 1
        space = remaining.rfind(" ", 0, cut)
        if space > 0:
            cut = space
        rows.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return rows or ["—"]
