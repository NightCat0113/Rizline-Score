"""Song and chart card rendered as one PNG."""

from __future__ import annotations

import colorsys
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.models import ChartInfo, Song
from bot.services.language import strings
from bot.services.seriesdata import series_mark
from bot.services.songdata import illustration_path
from bot.ui.textfont import clip as _clip_text
from bot.ui.textfont import load_hangul


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
_FACT_LABEL = (128, 128, 136)
_BORDER_DEFAULT = (0, 178, 236)
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
    language: str = "en",
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
            language=language,
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
    language: str = "en",
    scale: float = 1.0,
) -> Image.Image:
    text = strings(language)
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
        "fact_label": _load_font(font_path, _px(scale, 11)),
        "fact_value": _load_font(font_path, _px(scale, 18)),
        "detail_label": _load_font(font_path, _px(scale, 11)),
        "detail_value": _load_font(font_path, _px(scale, 11)),
    }
    fonts["title_kr"] = load_hangul(_px(scale, 30))
    fonts["artist_kr"] = load_hangul(_px(scale, 18))
    fonts["meta_kr"] = load_hangul(_px(scale, 13))
    fonts["small_kr"] = load_hangul(_px(scale, 14))
    fonts["fact_kr"] = load_hangul(_px(scale, 18))
    fonts["detail_kr"] = load_hangul(_px(scale, 11))
    border = _theme_color(artwork)
    draw = ImageDraw.Draw(image)
    _header(image, draw, song, artwork, text, fonts, font_path, scale, pad, width - pad, pad, header_h, border=border)
    top = pad + header_h + gap
    if not charts:
        _empty_row(image, draw, text, fonts, scale, pad, width - pad, top, row_h)
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
            text=text,
            fonts=fonts,
            scale=scale,
            left=pad,
            right=width - pad,
            top=y,
            height=row_h,
            border=border,
        )
    return image


def _header(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    song: Song,
    artwork: Image.Image | None,
    text: dict[str, str],
    fonts: dict[str, ImageFont.ImageFont],
    font_path: Path,
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
    border: tuple[int, int, int] = _BORDER_DEFAULT,
) -> None:
    _paste_panel(image, left, top, right - left, height, height // 2)
    circle = _px(scale, _HEADER_H - 10)
    inset = (height - circle) // 2
    image.alpha_composite(_circle_art(artwork, circle, _px(scale, 6)), (left + inset, top + inset))
    text_x = left + inset + circle + _px(scale, 18)
    text_w = right - height // 3 - text_x
    title, title_font = _clip_text(song.title or "—", fonts["title"], text_w, draw, fonts.get("title_kr"))
    artist, artist_font = _clip_text(song.artist or "—", fonts["artist"], text_w, draw, fonts.get("artist_kr"))
    alias_label = " · ".join(name.strip() for name in song.aliases if name and name.strip())
    alias_gap = _px(scale, 14)
    detail_limit = text_w
    if alias_label:
        detail_limit = max(_px(scale, 80), int(text_w * 0.62) - alias_gap)
    details = [
        _detail_segments(line, fonts, draw, detail_limit, scale)
        for line in _meta_lines(song, text)
    ]
    title_box = title_font.getbbox(title)
    artist_box = artist_font.getbbox(artist)
    pair_gap = _px(scale, 4)
    section_gap = _px(scale, 12)
    detail_gap = _px(scale, 5)
    detail_line_h = getattr(fonts["detail_value"], "size", _px(scale, 15))
    title_h = title_box[3] - title_box[1]
    artist_h = artist_box[3] - artist_box[1]
    detail_h = detail_line_h * len(details) + detail_gap * (len(details) - 1) if details else 0
    block_h = title_h + pair_gap + artist_h + (section_gap + detail_h if details else 0)
    ink_y = top + max(_px(scale, 8), (height - block_h) // 2)
    draw.text((text_x, ink_y - title_box[1]), title, font=title_font, fill=(*_INK, 255), anchor="lt")
    artist_ink = ink_y + title_h + pair_gap
    draw.text((text_x, artist_ink - artist_box[1]), artist, font=artist_font, fill=(*_MUTED, 255), anchor="lt")
    line_y = artist_ink + artist_h + section_gap
    detail_top = line_y
    for segments in details:
        baseline = line_y + detail_line_h
        x = text_x
        for index, (segment, segment_font, fill, kind) in enumerate(segments):
            draw.text((x, baseline), segment, font=segment_font, fill=fill, anchor="ls")
            x += draw.textlength(segment, font=segment_font)
            if index + 1 < len(segments):
                x += _segment_gap(kind, segments[index + 1][3], scale)
        line_y += detail_line_h + detail_gap
    if alias_label and details:
        _alias_column(
            draw,
            alias_label,
            fonts["meta"],
            fonts.get("meta_kr"),
            text_x + detail_limit + alias_gap // 2,
            text_x + text_w,
            detail_top,
            detail_h,
            scale,
        )
    _outline(draw, left, top, right, top + height, (*border, 255), _px(scale, 4))
    # Last, so the header outline cannot slice through the badge text.
    _original_badge(draw, song, font_path, scale, left + inset + circle // 2, top + inset + circle, circle)


def _original_badge(
    draw: ImageDraw.ImageDraw,
    song: Song,
    font_path: Path,
    scale: float,
    center_x: int,
    circle_bottom: int,
    circle_size: int,
) -> None:
    label = (song.original or "").strip()
    if not label:
        return
    partner = (song.original_with or "").strip()
    sub = f"with {partner}" if partner else ""
    pad_x = _px(scale, 12)
    pad_y = _px(scale, 5)
    # Shrink long labels so the pill never spills past the jacket circle
    # onto the white header panel, where a white pill would disappear.
    max_text_w = circle_size - _px(scale, 12) - pad_x * 2
    main_font = _load_font(font_path, _px(scale, 8))
    sub_font = _load_font(font_path, _px(scale, 6))
    for size in (11, 10, 9, 8):
        candidate = _load_font(font_path, _px(scale, size))
        candidate_sub = _load_font(font_path, _px(scale, max(6, size - 3)))
        widest = draw.textlength(label, font=candidate)
        if sub:
            widest = max(widest, draw.textlength(sub, font=candidate_sub))
        main_font, sub_font = candidate, candidate_sub
        if widest <= max_text_w:
            break
    main_h = getattr(main_font, "size", _px(scale, 11))
    text_w = draw.textlength(label, font=main_font)
    height = main_h + pad_y * 2
    if sub:
        sub_h = getattr(sub_font, "size", _px(scale, 8))
        text_w = max(text_w, draw.textlength(sub, font=sub_font))
        height += _px(scale, 2) + sub_h
    width = int(text_w) + pad_x * 2
    bottom = circle_bottom - _px(scale, 6)
    pill_top = bottom - height
    pill_left = center_x - width // 2
    draw.rounded_rectangle(
        (pill_left, pill_top, pill_left + width - 1, bottom - 1),
        radius=height // 2,
        fill=(255, 255, 255, 255),
        outline=(188, 188, 196, 255),
        width=max(1, _px(scale, 1)),
    )
    if not sub:
        draw.text((center_x, pill_top + height / 2), label, font=main_font, fill=(*_INK, 255), anchor="mm")
        return
    sub_h = getattr(sub_font, "size", _px(scale, 8))
    main_y = pill_top + pad_y + main_h / 2
    sub_y = main_y + main_h / 2 + _px(scale, 2) + sub_h / 2
    draw.text((center_x, main_y), label, font=main_font, fill=(*_INK, 255), anchor="mm")
    draw.text((center_x, sub_y), sub, font=sub_font, fill=(*_INK, 255), anchor="mm")


def _alias_column(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.ImageFont,
    fallback: ImageFont.ImageFont | None,
    split_x: int,
    text_right: int,
    top: int,
    height: int,
    scale: float,
) -> None:
    draw.line(
        [(split_x, top), (split_x, top + height)],
        fill=(170, 170, 176, 255),
        width=max(2, _px(scale, 2)),
    )
    gap = _px(scale, 14)
    alias_x = split_x + gap
    clipped, alias_font = _clip_text(label, font, text_right - alias_x, draw, fallback)
    box = alias_font.getbbox(clipped)
    alias_h = box[3] - box[1]
    draw.text(
        (alias_x, top + height / 2 - alias_h / 2 - box[1]),
        clipped,
        font=alias_font,
        fill=(*_INK, 255),
        anchor="lt",
    )


def _chart_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    difficulty: str,
    chart: ChartInfo,
    best: dict | None,
    *,
    highlighted: bool,
    text: dict[str, str],
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
    border: tuple[int, int, int] = _BORDER_DEFAULT,
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
    score_text = f"{text['score']} {shown} / {chart_score}"
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
            _clip(_result_line(best, text), fonts["small"], column_w, draw),
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
    for line_text, font, fill in lines:
        draw.text((line_x, line_y), line_text, font=font, fill=fill, anchor="lt")
        line_y += getattr(font, "size", _px(scale, 14)) + gap

    _chart_details(draw, chart, text, fonts, scale, split + _px(scale, 16), text_right, top, height)
    if highlighted:
        _outline(draw, left, top, right, top + height, (*border, 255), _px(scale, 4))


def _chart_details(
    draw: ImageDraw.ImageDraw,
    chart: ChartInfo,
    text: dict[str, str],
    fonts: dict[str, ImageFont.ImageFont],
    scale: float,
    left: int,
    right: int,
    top: int,
    height: int,
) -> None:
    """Attribute names small and grey; the values themselves large and black."""
    label_font = fonts["fact_label"]
    value_font = fonts["fact_value"]
    label_h = getattr(label_font, "size", _px(scale, 11))
    value_h = getattr(value_font, "size", _px(scale, 18))
    label_gap = _px(scale, 2)
    section_gap = _px(scale, 9)
    block_h = label_h + label_gap + value_h + section_gap + label_h + label_gap + value_h
    y = top + max(_px(scale, 6), (height - block_h) // 2)
    columns = (
        (text["hit"], f"{chart.hit:,}"),
        (text["riz_hit"], f"{chart.riz_hit:,}"),
        (text["combo"], f"{chart.combo:,}"),
    )
    column_w = max(1, (right - left) // len(columns))
    for index, (label, value) in enumerate(columns):
        x = left + index * column_w
        limit = column_w - _px(scale, 8)
        draw.text((x, y), _clip(label, label_font, limit, draw), font=label_font, fill=(*_FACT_LABEL, 255), anchor="lt")
        draw.text(
            (x, y + label_h + label_gap),
            _clip(value, value_font, limit, draw),
            font=value_font,
            fill=(*_INK, 255),
            anchor="lt",
        )
    charter_y = y + label_h + label_gap + value_h + section_gap
    draw.text(
        (left, charter_y),
        _clip(text["charter"], label_font, right - left, draw),
        font=label_font,
        fill=(*_FACT_LABEL, 255),
        anchor="lt",
    )
    name, name_font = _clip_text(chart.designer or "—", value_font, right - left, draw, fonts.get("fact_kr"))
    draw.text(
        (left, charter_y + label_h + label_gap),
        name,
        font=name_font,
        fill=(*_INK, 255),
        anchor="lt",
    )


def _empty_row(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: dict[str, str],
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
        text["no_chart_details"],
        font=fonts["body"],
        fill=(*_MUTED, 255),
    )


def _result_line(best: dict | None, text: dict[str, str]) -> str:
    if best is None or _player_score(best) is None:
        return text["no_record"]
    if best.get("isFullCombo"):
        status = "FC"
    elif best.get("isClear"):
        status = text["clear"]
    else:
        status = text["not_cleared"]
    try:
        accuracy = f"{float(best.get('completeRate')):.2f}%"
    except (TypeError, ValueError):
        accuracy = "—"
    return f"{text['accuracy']} {accuracy}  ·  {status}"


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


def _meta_lines(song: Song, text: dict[str, str]) -> list[list[tuple[str, str]]]:
    """Header details as (segment, kind) lines; kind is label, value, or sep."""
    lines: list[list[tuple[str, str]]] = []
    first: list[tuple[str, str]] = []
    if song.bpm:
        first += [("BPM", "label"), (_fmt_bpm(song.bpm), "value")]
    if song.length_seconds:
        if first:
            first.append(("·", "sep"))
        first += [(text["length"], "label"), (_fmt_length(song.length_seconds), "value")]
    if first:
        lines.append(first)
    if song.illustrator:
        lines.append([(text["illustrator"], "label"), (song.illustrator, "value")])
    if song.disc_name:
        name = song.disc_name.strip()
        label, _, rest = name.partition(" ")
        if name.lower().startswith("disc") and rest:
            lines.append([(label, "label"), (rest, "value")])
        else:
            lines.append([(text["disc"], "label"), (name, "value")])
    if song.series_index is not None:
        value = series_mark(song.series_index)
        if song.series_name:
            value = f"{value} - {song.series_name}"
        lines.append([(text["track_series"], "label"), (value, "value")])
    return lines


def _segment_gap(kind: str, next_kind: str, scale: float) -> int:
    if kind == "sep" or next_kind == "sep":
        return _px(scale, 10)
    return _px(scale, 6)


def _detail_segments(
    line: list[tuple[str, str]],
    fonts: dict[str, ImageFont.ImageFont],
    draw: ImageDraw.ImageDraw,
    limit: int,
    scale: float,
) -> list[tuple[str, ImageFont.ImageFont, tuple[int, int, int, int], str]]:
    """Style one detail line: labels and values at one size, all grey.

    Overlong values are shortened with an ellipsis so the line fits.
    """
    segments: list[tuple[str, ImageFont.ImageFont, tuple[int, int, int, int], str]] = []
    for segment, kind in line:
        if kind == "value":
            rendered, font = _clip_text(segment, fonts["detail_value"], max(limit, 1), draw, fonts.get("detail_kr"))
            segments.append((rendered, font, (*_FACT_LABEL, 255), kind))
        else:
            segments.append((segment, fonts["detail_label"], (*_FACT_LABEL, 255), kind))

    def total_width() -> float:
        width = sum(draw.textlength(segment, font=font) for segment, font, _fill, _kind in segments)
        width += sum(
            _segment_gap(kind, segments[index + 1][3], scale)
            for index, (_segment, _font, _fill, kind) in enumerate(segments[:-1])
        )
        return width

    while total_width() > limit:
        values = [index for index, item in enumerate(segments) if item[3] == "value" and len(item[0]) > 1]
        if not values:
            break
        index = max(values, key=lambda item: draw.textlength(segments[item][0], font=segments[item][1]))
        segment, font, fill, kind = segments[index]
        allowed = draw.textlength(segment, font=font) - (total_width() - limit)
        if allowed <= draw.textlength("…", font=font):
            segments[index] = ("…", font, fill, kind)
            break
        segments[index] = (_clip(segment, font, int(allowed), draw), font, fill, kind)
    return segments


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


def _theme_color(artwork: Image.Image | None) -> tuple[int, int, int]:
    """The illustration's dominant vivid colour, normalised so it stays
    visible as a thin border on the white panel. Cyan when there is no art."""
    if artwork is None:
        return _BORDER_DEFAULT
    try:
        thumb = artwork.convert("RGB").resize((48, 48), Image.Resampling.LANCZOS)
        quantized = thumb.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts = quantized.getcolors() or []
        best: tuple[int, int, int] | None = None
        best_score = -1.0
        for count, index in counts:
            red, green, blue = palette[index * 3 : index * 3 + 3]
            _hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            # Favour colours that are common, saturated, and not near black/white.
            score = count * (0.25 + saturation) * (1.0 - abs(value - 0.55))
            if score > best_score:
                best = (red, green, blue)
                best_score = score
        if best is None:
            return _BORDER_DEFAULT
        hue, saturation, value = colorsys.rgb_to_hsv(best[0] / 255, best[1] / 255, best[2] / 255)
        saturation = min(0.85, max(0.50, saturation))
        value = min(0.80, max(0.50, value))
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
        return (round(red * 255), round(green * 255), round(blue * 255))
    except (ValueError, IndexError, OSError):
        return _BORDER_DEFAULT


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
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
