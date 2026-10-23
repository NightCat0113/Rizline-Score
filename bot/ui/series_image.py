"""Track series card: banner, poster, songs, preorder date, and unlockable title."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.models import ChartInfo, Song, TrackSeries
from bot.services.language import normalize_language, strings
from bot.services.seriesdata import series_art_name, series_mark
from bot.services.songdata import illustration_path
from bot.ui.textfont import clip as _clip_text
from bot.ui.textfont import load_face, load_hangul


MAX_PNG_BYTES = 8_000_000
_SCALES = (2.0, 1.5, 1.0)
_DIFFS = ("EZ", "HD", "IN", "AT", "SP")
_DIFF_COLORS = {
    "EZ": (87, 228, 196),
    "HD": (253, 186, 97),
    "IN": (254, 134, 97),
    "AT": (76, 54, 75),
    "SP": (0, 0, 0),
}
_INK = (28, 28, 32)
_MUTED = (90, 90, 98)
_PLACEHOLDER = (48, 50, 58)
_WIDTH = 980
_PAD = 28
_INSET = 28
_GAP = 16
_POSTER_W = 412
_POSTER_H = round(_POSTER_W * 2048 / 1448)
_JACKET = 62
_ROW_H = 80
_PILL_H = 28


def render_series(
    *,
    series: TrackSeries,
    songs: dict[str, Song],
    tag: str,
    banner: Image.Image | None,
    poster: Image.Image | None,
    font_path: Path,
    illust_hires_dir: Path | None = None,
    illust_dir: Path | None = None,
    language: str = "en",
    max_bytes: int = MAX_PNG_BYTES,
) -> bytes:
    jackets = _load_jackets(series, songs, illust_hires_dir, illust_dir)
    last = b""
    for scale in _SCALES:
        image = _draw(
            series=series,
            songs=songs,
            tag=tag,
            banner=banner,
            poster=poster,
            jackets=jackets,
            font_path=font_path,
            language=language,
            scale=scale,
        )
        last = _encode(image)
        if len(last) <= max_bytes:
            return last
    return last


def open_series_art(directory: Path, kind: str, index: int, language: str = "en") -> Image.Image | None:
    filename = f"{series_art_name(kind, index)}.png"
    lang = normalize_language(language)
    candidates = [directory / lang / filename] if lang != "en" else []
    candidates.append(directory / filename)
    for path in candidates:
        if not path.is_file() or path.stat().st_size > MAX_PNG_BYTES:
            continue
        try:
            with Image.open(path) as opened:
                return opened.convert("RGB")
        except (OSError, ValueError):
            continue
    return None


def chart_levels(song: Song) -> str:
    parts: list[str] = []
    for name in _DIFFS:
        chart = song.charts.get(name)
        if chart is None:
            continue
        parts.append(_chart_label(name, chart))
    return "  ·  ".join(parts)


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw(
    *,
    series: TrackSeries,
    songs: dict[str, Song],
    tag: str,
    banner: Image.Image | None,
    poster: Image.Image | None,
    jackets: dict[str, Image.Image],
    font_path: Path,
    language: str,
    scale: float,
) -> Image.Image:
    text = strings(language)
    fonts = _fonts(font_path, scale)
    width = _px(scale, _WIDTH)
    pad = _px(scale, _PAD)
    inset = _px(scale, _INSET)
    gap = _px(scale, _GAP)
    layout = _header_layout(width, pad, inset, gap, tag, banner, poster, scale)
    song_h = _songs_height(series, text, scale)
    height = pad + inset + layout["header_h"] + gap + song_h + inset + pad
    image = _background(width, height, poster or banner).convert("RGBA")
    draw = ImageDraw.Draw(image)
    content_w = width - pad * 2
    _paste_panel(image, pad, pad, content_w, height - pad * 2, _px(scale, 28))
    if banner is not None and layout["banner_w"] > 0:
        _paste_banner(image, banner, layout["banner_x"], layout["banner_y"], layout["banner_w"], layout["banner_h"])
    if poster is not None:
        _paste_rounded(
            image,
            _cover(poster, layout["poster_w"], layout["poster_h"]),
            layout["poster_x"],
            layout["poster_y"],
            _px(scale, 18),
        )
    _draw_info(draw, series, tag, text, fonts, layout["info_x"], layout["info_y"], layout["info_w"], scale)
    _draw_songs(
        image,
        draw,
        series,
        songs,
        jackets,
        text,
        fonts,
        pad + inset,
        pad + inset + layout["header_h"] + gap,
        content_w - inset * 2,
        scale,
    )
    return image


def _header_layout(
    width: int,
    pad: int,
    inset: int,
    gap: int,
    tag: str,
    banner: Image.Image | None,
    poster: Image.Image | None,
    scale: float,
) -> dict[str, int]:
    info_h = _info_height(tag, scale)
    poster_w = _px(scale, _POSTER_W) if poster is not None else 0
    poster_h = _px(scale, _POSTER_H) if poster is not None else 0
    content_left = pad + inset
    content_right = width - pad - inset
    poster_x = content_right - poster_w
    poster_y = pad + inset
    info_x = content_left
    info_w = max(1, (poster_x if poster is not None else content_right) - info_x - gap)
    banner_x = banner_y = banner_w = banner_h = 0
    if banner is not None:
        if poster is not None:
            visible = max(1, poster_x - content_left)
            banner_w = max(1, round(visible * 16 / 15))
            banner_h = max(1, round(banner_w * banner.height / max(1, banner.width)))
            free = poster_h - info_h - gap
            if banner_h > free > _px(scale, 24):
                banner_h = free
                banner_w = max(1, round(banner_h * banner.width / max(1, banner.height)))
            overlap = max(1, banner_w // 16)
            banner_x = poster_x - (banner_w - overlap)
            banner_y = poster_y + poster_h - banner_h
        else:
            banner_w = max(1, content_right - content_left)
            banner_h = max(1, round(banner_w * banner.height / max(1, banner.width)))
            banner_x = content_left
            banner_y = poster_y + info_h + gap
    if poster is not None:
        header_h = max(poster_h, info_h)
    else:
        header_h = info_h + (gap + banner_h if banner is not None else 0)
    return {
        "poster_x": poster_x,
        "poster_y": poster_y,
        "poster_w": poster_w,
        "poster_h": poster_h,
        "banner_x": banner_x,
        "banner_y": banner_y,
        "banner_w": banner_w,
        "banner_h": banner_h,
        "info_x": info_x,
        "info_y": pad + inset + _px(scale, 8),
        "info_w": info_w,
        "header_h": header_h,
    }


def _info_height(tag: str, scale: float) -> int:
    height = _px(scale, 8) + _px(scale, 44) + _px(scale, 32)
    if tag:
        height += _px(scale, 28)
    return height


def _songs_height(series: TrackSeries, text: dict[str, str], scale: float) -> int:
    total = 0
    count = len(series.volumes)
    for index, volume in enumerate(series.volumes, start=1):
        if _volume_heading(volume.label, count, index, text):
            total += _px(scale, 28)
        if volume.preorder_ends:
            total += _px(scale, 22)
        total += _px(scale, _ROW_H) * max(1, len(volume.song_ids))
        total += _px(scale, 8)
    return total


def _volume_heading(label: str, count: int, index: int, text: dict[str, str]) -> str:
    if label:
        return label
    if count > 1:
        return f"{text['volume']} {index}"
    return ""


def _draw_info(
    draw: ImageDraw.ImageDraw,
    series: TrackSeries,
    tag: str,
    text: dict[str, str],
    fonts: dict,
    left: int,
    top: int,
    width: int,
    scale: float,
) -> None:
    title, title_font = _clip(series.name or f"{text['track_series']} {series.series_index}", fonts["title"], width, draw, fonts.get("title_kr"))
    draw.text((left, top), title, font=title_font, fill=(*_INK, 255))
    mark, mark_font = _clip(f"{text['track_series']} {series_mark(series.series_index)}", fonts["meta"], width, draw, fonts.get("meta_kr"))
    draw.text(
        (left, top + _px(scale, 44)),
        mark,
        font=mark_font,
        fill=(*_MUTED, 255),
    )
    if tag:
        label, label_font = _clip(tag, fonts["body"], width, draw, fonts.get("body_kr"))
        draw.text(
            (left, top + _px(scale, 80)),
            label,
            font=label_font,
            fill=(*_INK, 255),
        )


def _draw_songs(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    series: TrackSeries,
    songs: dict[str, Song],
    jackets: dict[str, Image.Image],
    text: dict[str, str],
    fonts: dict,
    left: int,
    top: int,
    width: int,
    scale: float,
) -> None:
    line_y = top
    count = len(series.volumes)
    jacket = _px(scale, _JACKET)
    gap = _px(scale, 14)
    for index, volume in enumerate(series.volumes, start=1):
        heading = _volume_heading(volume.label, count, index, text)
        if heading:
            label, label_font = _clip(heading, fonts["body"], width, draw, fonts.get("body_kr"))
            draw.text((left, line_y), label, font=label_font, fill=(*_INK, 255))
            line_y += _px(scale, 28)
        if volume.preorder_ends:
            label, label_font = _clip(f"{text['preorder_ends']} {volume.preorder_ends}", fonts["small"], width, draw, fonts.get("small_kr"))
            draw.text(
                (left, line_y),
                label,
                font=label_font,
                fill=(*_MUTED, 255),
            )
            line_y += _px(scale, 22)
        song_ids = volume.song_ids or ("",)
        row_h = _px(scale, _ROW_H)
        columns = _song_columns(draw, series, songs, fonts["pill"], left, width, jacket, gap, scale)
        for song_id in song_ids:
            song = songs.get(song_id)
            jacket_y = line_y + max(0, (row_h - jacket) // 2)
            _paste_jacket(image, jackets.get(song_id), left, jacket_y, jacket, _px(scale, 10))
            title = song.title if song else (song_id or "—")
            artist = song.artist if song else ""
            pills_w = _pills_width(draw, song, fonts["pill"], width, scale) if song is not None else 0
            text_left, title_w, artist_x, artist_w = columns
            title, title_font = _clip(title, fonts["body"], title_w, draw, fonts.get("body_kr"))
            artist, artist_font = _clip(artist, fonts["small"], artist_w, draw, fonts.get("small_kr"))
            mid = line_y + row_h // 2
            _draw_centered_text(draw, text_left, mid, title, title_font, (*_INK, 255))
            _draw_centered_text(draw, artist_x, mid, artist, artist_font, (*_MUTED, 255))
            if song is not None and pills_w:
                _draw_pills(draw, song, fonts["pill"], left + width - pills_w, mid - _px(scale, _PILL_H) // 2, pills_w, scale)
            line_y += row_h
        line_y += _px(scale, 8)


def _song_columns(
    draw: ImageDraw.ImageDraw,
    series: TrackSeries,
    songs: dict[str, Song],
    font: ImageFont.ImageFont,
    left: int,
    width: int,
    jacket: int,
    gap: int,
    scale: float,
) -> tuple[int, int, int, int]:
    widest = 0
    for volume in series.volumes:
        for song_id in volume.song_ids:
            song = songs.get(song_id)
            if song is not None:
                widest = max(widest, _pills_width(draw, song, font, width, scale))
    text_left = left + jacket + gap
    artist_limit = left + width - widest - (gap if widest else 0)
    span = max(1, artist_limit - text_left)
    title_w = max(1, int(span * 0.55))
    artist_x = text_left + title_w + gap
    artist_w = max(1, artist_limit - artist_x)
    return text_left, title_w, artist_x, artist_w


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    left: int,
    mid_y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    if not text:
        return
    bbox = font.getbbox(text)
    top = mid_y - (bbox[3] - bbox[1]) // 2 - bbox[1]
    draw.text((left, top), text, font=font, fill=fill)


def _pills_width(
    draw: ImageDraw.ImageDraw,
    song: Song,
    font: ImageFont.ImageFont,
    width: int,
    scale: float,
) -> int:
    gap = _px(scale, 6)
    pad_x = _px(scale, 8)
    total = 0
    for name in _DIFFS:
        chart = song.charts.get(name)
        if chart is None:
            continue
        pill_w = int(draw.textlength(_chart_label(name, chart), font=font)) + pad_x * 2
        next_total = pill_w if total == 0 else total + gap + pill_w
        if total and next_total > width:
            break
        total = next_total
    return total


def _draw_pills(
    draw: ImageDraw.ImageDraw,
    song: Song,
    font: ImageFont.ImageFont,
    left: int,
    top: int,
    width: int,
    scale: float,
) -> None:
    x = left
    height = _px(scale, _PILL_H)
    gap = _px(scale, 6)
    pad_x = _px(scale, 8)
    for name in _DIFFS:
        chart = song.charts.get(name)
        if chart is None:
            continue
        label = _chart_label(name, chart)
        text_w = int(draw.textlength(label, font=font))
        pill_w = text_w + pad_x * 2
        if x > left and x + pill_w > left + width:
            break
        color = _DIFF_COLORS[name]
        draw.rounded_rectangle((x, top, x + pill_w, top + height), radius=height // 2, fill=(*color, 255))
        bbox = font.getbbox(label)
        text_h = bbox[3] - bbox[1]
        draw.text(
            (x + pad_x, top + (height - text_h) // 2 - bbox[1]),
            label,
            font=font,
            fill=(255, 255, 255, 255),
        )
        x += pill_w + gap


def _paste_jacket(image: Image.Image, jacket: Image.Image | None, left: int, top: int, size: int, radius: int) -> None:
    art = jacket if jacket is not None else Image.new("RGB", (size, size), _PLACEHOLDER)
    _paste_rounded(image, _cover(art, size, size), left, top, radius)


def _load_jackets(
    series: TrackSeries,
    songs: dict[str, Song],
    hires_dir: Path | None,
    low_dir: Path | None,
) -> dict[str, Image.Image]:
    if hires_dir is None or low_dir is None:
        return {}
    loaded: dict[str, Image.Image] = {}
    for volume in series.volumes:
        for song_id in volume.song_ids:
            song = songs.get(song_id)
            if song is None or song_id in loaded:
                continue
            opened = _open_jacket(song, hires_dir, low_dir)
            if opened is not None:
                loaded[song_id] = opened
    return loaded


def _open_jacket(song: Song, hires_dir: Path, low_dir: Path) -> Image.Image | None:
    path = illustration_path(song, hires_dir, low_dir, prefer_low=False)
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            return image
    except (OSError, ValueError):
        return None


def _chart_label(name: str, chart: ChartInfo) -> str:
    if chart.level_text:
        return f"{name} {chart.level_text}"
    if chart.level > 0:
        shown = str(int(chart.level)) if float(chart.level).is_integer() else f"{chart.level:.1f}"
        return f"{name} {shown}"
    return name


def _paste_banner(image: Image.Image, banner: Image.Image, left: int, top: int, width: int, height: int) -> None:
    fitted = banner.resize((width, height), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    radius = max(1, height // 2)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    if width > radius:
        draw.rectangle((radius, 0, width, height), fill=255)
    fitted.putalpha(mask)
    image.alpha_composite(fitted, (left, top))


def _paste_rounded(image: Image.Image, art: Image.Image, left: int, top: int, radius: int) -> None:
    art = art.convert("RGBA")
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, art.width - 1, art.height - 1), radius=radius, fill=255)
    art.putalpha(mask)
    image.alpha_composite(art, (left, top))


def _paste_panel(image: Image.Image, left: int, top: int, width: int, height: int, radius: int) -> None:
    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(255, 255, 255, 214))
    image.alpha_composite(panel, (left, top))


def _background(width: int, height: int, artwork: Image.Image | None) -> Image.Image:
    if artwork is None:
        return Image.new("RGB", (width, height), (24, 26, 34))
    long_side = max(width, height, 1)
    work = min(long_side, 1800)
    ratio = work / long_side
    blurred = _cover(artwork, max(8, int(width * ratio)), max(8, int(height * ratio)))
    blurred = blurred.filter(ImageFilter.GaussianBlur(radius=max(2, int(15 * ratio))))
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


def _fonts(font_path: Path, scale: float) -> dict[str, ImageFont.ImageFont | None]:
    sizes = {"title": 34, "body": 22, "meta": 20, "small": 18, "pill": 16}
    loaded: dict[str, ImageFont.ImageFont | None] = {}
    for name, size in sizes.items():
        loaded[name] = load_face(font_path, _px(scale, size))
        loaded[f"{name}_kr"] = load_hangul(_px(scale, size))
    return loaded


def _clip(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw, fallback: ImageFont.ImageFont | None = None) -> tuple[str, ImageFont.ImageFont]:
    return _clip_text(text, font, width, draw, fallback)


def _px(scale: float, value: int) -> int:
    return max(1, int(round(value * scale)))
