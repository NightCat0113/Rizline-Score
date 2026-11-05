"""Best 40 card sheet, matching the pill layout in index.html."""

from __future__ import annotations

import io
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from bot.services.language import strings
from bot.services.profile import layout_colors, player_title
from bot.services.rks import strip_track_prefix
from bot.services.songdata import SongIndex, illustration_file, illustration_path
from bot.ui.textfont import clip as _clip_text
from bot.ui.textfont import load_hangul


MAX_PNG_BYTES = 10_000_000
# B40 draws ~40 jacket circles; keep 2× (smooth AA) so Discord stays responsive.
# /song /series stay on their own higher _SCALES.
_SCALES = (2.0, 1.5)
_AA = 3
_ELLIPSE_MASKS: dict[int, Image.Image] = {}
_ROUND_MASKS: dict[tuple[int, int, int], Image.Image] = {}
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
_BUNDLE_TEXTURES: dict[tuple[str, str], Image.Image | None] = {}


def load_bundle_texture(repo_root: Path, asset_id: str) -> Image.Image | None:
    """Largest texture for a catalog asset, including special illustrations."""
    key = (str(repo_root), asset_id.strip())
    if key not in _BUNDLE_TEXTURES:
        _BUNDLE_TEXTURES[key] = _read_bundle_texture(repo_root, asset_id)
    image = _BUNDLE_TEXTURES[key]
    return None if image is None else image.copy()


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
    layout_id = str(profile.get("layoutId") or "")
    frame = _rizcard_frame(profile_root, layout_id)
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
        repo_root=profile_root,
        layout_id=layout_id,
        accent=colors[0],
    )
    return _png_within(image, MAX_PNG_BYTES)


def _is_layout(layout_id: str, number: str) -> bool:
    """True when ``layout_id`` is ``layout.00NNN`` / ``00NNN`` for ``number``."""
    cleaned = layout_id.strip()
    if not cleaned:
        return False
    if cleaned == number or cleaned == f"layout.{number}":
        return True
    suffix = cleaned.rsplit(".", 1)[-1]
    return suffix.lstrip("0") == number.lstrip("0") and suffix.isdigit() and number.isdigit()


def _rizcard_frame(repo_root: Path, layout_id: str) -> Image.Image | None:
    """Frame chrome for a player rizcard.

    Normal layouts prefer the bundle texture when it has a transparent env hole so
    arts composite *behind* the layout. Baked collection cards often paint the env
    opaque, which forced arts in front after punching. Layout 37 keeps the bake
    (CoverMask / prefab coords match that size).
    """
    try:
        from bot.ui.layout_card import load_collection_layout
    except ImportError:
        load_collection_layout = None  # type: ignore[assignment]

    def _baked() -> Image.Image | None:
        if load_collection_layout is None or not layout_id.strip():
            return None
        return load_collection_layout(repo_root, layout_id)

    if _is_layout(layout_id, "00037"):
        return _baked() or load_layout_frame(repo_root, layout_id)

    bundle = load_layout_frame(repo_root, layout_id)
    if bundle is not None:
        clear = bundle.getchannel("A").histogram()[0]
        if clear > (bundle.width * bundle.height) // 50:
            return bundle
    return _baked() or bundle


# Layouts 1–4: avatar opposite the name+bio tag, one pair per corner.
_STANDARD_CORNER_HUD: dict[str, tuple[str, str]] = {
    "00001": ("tl", "tr"),  # avatar top-left, name+tag top-right
    "00002": ("bl", "br"),  # avatar bottom-left, name+tag bottom-right
    "00003": ("tr", "tl"),  # avatar top-right, name+tag top-left
    "00004": ("br", "bl"),  # avatar bottom-right, name+tag bottom-left
}

# Notch-split HUDs: (avatar_corner, name_corner, bio_corner).
# 8–10/30 = TL avatar + TR name + BR bio; 5–7 = vertical+horizontal mirror.
_NOTCH_SPLIT_HUD: dict[str, tuple[str, str, str]] = {
    "00005": ("br", "bl", "tl"),
    "00006": ("br", "bl", "tl"),
    "00007": ("br", "bl", "tl"),
    "00008": ("tl", "tr", "br"),
    "00009": ("tl", "tr", "br"),
    "00010": ("tl", "tr", "br"),
    "00030": ("tl", "tr", "br"),
}
_NOTCH_AVATAR_X_NUDGE = 22  # positive shifts TL avatar right into the cutout
_NOTCH_AVATAR_Y_NUDGE = -18  # negative shifts avatar up (TL family)
_NOTCH_AVATAR_BR_X_EXTRA = 6  # layouts 5–7: extra right
_NOTCH_AVATAR_BR_Y_EXTRA = 33  # layouts 5–7: extra down
_NOTCH_NAME_RIGHT_INSET = 128  # extra inset from the right edge
_NOTCH_NAME_TOP_INSET = 60  # extra drop from the top edge

# Center-band HUDs: (avatar_band, text_band) where band is "top" | "bottom".
# 11/20 = avatar on top curve, name+bio stacked on bottom pill.
# 12/29 = bio+name on top pill, avatar on bottom curve (vertical flip).
_BAND_CENTER_HUD: dict[str, tuple[str, str]] = {
    "00011": ("top", "bottom"),
    "00020": ("top", "bottom"),
    "00012": ("bottom", "top"),
    "00029": ("bottom", "top"),
}
_BAND_AVATAR_DIAM_RATIO = 0.20
_BAND_NAME_PILL_GAP = 14  # gap between name and bio pill

# Footer-stack HUDs (13–15): BL avatar + wide name bar + bio pill under it.
_FOOTER_STACK_HUD: frozenset[str] = frozenset({"00013", "00014", "00015"})
# Tunable nudges (px @ card resolution). +X = right, +Y = down.
_FOOTER_AVATAR_X_NUDGE = 58
_FOOTER_AVATAR_Y_NUDGE = 34
_FOOTER_NAME_X_NUDGE = 304
_FOOTER_NAME_Y_NUDGE = 15

# Layouts 16–19. Each value is extra pixels on top of the reference layout.
# +X moves that element right. +Y moves it down. 0 keeps the reference placement.
#
# 16 matches layout 02: avatar bottom-left, name just above the bottom-right bio pill.
_L16_AVATAR_X_NUDGE = 53  # bottom-left portrait; +X = right
_L16_AVATAR_Y_NUDGE = -64  # bottom-left portrait; -Y = up
_L16_NAME_X_NUDGE = -16  # username above the bio pill; -X = left
_L16_NAME_Y_NUDGE = 14  # username above the bio pill; +Y = down
#
# 17 matches layout 03 sizes and the top-right avatar, but the name sits under the bio pill.
_L17_AVATAR_X_NUDGE = -65  # top-right portrait
_L17_AVATAR_Y_NUDGE = 60  # top-right portrait
_L17_NAME_X_NUDGE = 15  # username below the bio pill
_L17_NAME_Y_NUDGE = 15  # extra drop under the pill; negative lifts the name toward the pill
#
# 18 matches layout 14 (bottom-left avatar, name on the wide bar, bio under it) with the name raised.
# These add to the _FOOTER_* nudges above, so layout 14 itself does not move.
_L18_AVATAR_X_NUDGE = 0  # extra shift of the bottom-left portrait
_L18_AVATAR_Y_NUDGE = 20  # extra shift of the bottom-left portrait
_L18_NAME_X_NUDGE = -46  # extra shift after right-align; +X moves the name's right edge right
_L18_NAME_Y_NUDGE = -43  # negative raises the name above layout 14's vertical center
#
# 19 is layout 18 mirrored left-right and moved from the bottom edge to the top.
_L19_AVATAR_X_NUDGE = -6  # top-right portrait
_L19_AVATAR_Y_NUDGE = 88  # top-right portrait; negative lifts it
_L19_NAME_X_NUDGE = 170  # username on the top bar (mirrored, so it sits toward the left)
_L19_NAME_Y_NUDGE = -10  # negative raises the name on the top bar; 0 keeps it on the plate

# Layouts 21–28. Layouts 1–20 stay locked — do not retune them from here.
# Each pair is (x, y) in pixels. +X moves that element right. +Y moves it down.
# avatar — circular portrait on the colored banner's corner
# name — username sitting on that banner
# bio — text inside the small accent pill
_WAVE_HUD: dict[str, tuple[str, str, str]] = {
    # avatar corner, name side, how the bio relates to the name
    "00021": ("bl", "r", "split"),       # name on the bottom banner, bio pill top-right
    "00022": ("br", "l", "split"),       # name on the bottom banner, bio pill top-right
    "00023": ("tr", "l", "split"),       # name on the top banner, bio pill bottom-right
    "00024": ("tl", "r", "split"),       # name on the top banner, bio pill bottom-right
    "00025": ("tl", "r", "name_above"),  # name above the bio pill, both on the top banner
    "00026": ("tr", "l", "name_above"),  # name above the bio pill, both on the top banner
    "00027": ("br", "l", "bio_above"),   # bio pill above the name, both on the bottom banner
    "00028": ("bl", "r", "bio_above"),   # bio pill above the name, both on the bottom banner
}
_WAVE_NUDGE: dict[str, dict[str, tuple[int, int]]] = {
    "00021": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00022": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00023": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00024": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00025": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00026": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00027": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
    "00028": {"avatar": (0, 0), "name": (0, 18), "bio": (0, 0)},
}

# Tuned on layout.00001 @ 1468×2048 — reuse for later standard rizcards.
_HUD_AVATAR_DIAM_RATIO = 0.195
_HUD_AVATAR_DIAM_MIN = 151
_HUD_AVATAR_DIAM_NUDGE = -1  # final diameter = max(MIN, int(w*RATIO) + NUDGE)
_HUD_AVATAR_GAP_X_DIV = 48
_HUD_AVATAR_GAP_Y_DIV = 72
_HUD_NAME_SIZE_RATIO = 0.064
_HUD_NAME_SIZE_MIN = 46
_HUD_NAME_TRACK_DIV = 47  # tracking = max(1, name_size // DIV)
_HUD_NAME_STROKE_DIV = 28  # stroke = max(1, name_size // DIV)
_HUD_NAME_FLUSH = -9  # added to stroke_w; pulls right-side names inside the pillar cap
_HUD_NAME_CLEAR_BASE = 23
# Negative EXTRA lowers the name (was ignored when max() always picked the pillar term).
_HUD_NAME_CLEAR_EXTRA = -3
_HUD_NAME_CLEAR_MIN = 10
_HUD_BIO_SIZE_PILL_RATIO = 0.42
_HUD_BIO_SIZE_WIDTH_RATIO = 0.028
_HUD_BIO_SIZE_MIN = 16
_HUD_BIO_SIZE_FLOOR = 11


def _standard_corner_hud(layout_id: str) -> tuple[str, str] | None:
    for number, corners in _STANDARD_CORNER_HUD.items():
        if _is_layout(layout_id, number):
            return corners
    return None


def _notch_split_hud(layout_id: str) -> tuple[str, str, str] | None:
    for number, corners in _NOTCH_SPLIT_HUD.items():
        if _is_layout(layout_id, number):
            return corners
    return None


def _band_center_hud(layout_id: str) -> tuple[str, str] | None:
    for number, bands in _BAND_CENTER_HUD.items():
        if _is_layout(layout_id, number):
            return bands
    return None


def _footer_stack_hud(layout_id: str) -> bool:
    return any(_is_layout(layout_id, number) for number in _FOOTER_STACK_HUD)


def _tracked_text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    tracking: int,
) -> float:
    if not text:
        return 0.0
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font,
    tracking: int,
    *,
    fill,
    stroke_width: int = 0,
    stroke_fill=None,
) -> None:
    x, y = xy
    for index, ch in enumerate(text):
        draw.text(
            (x, y),
            ch,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        x += draw.textlength(ch, font=font)
        if index + 1 < len(text):
            x += tracking


def _stamp_standard_corner_hud(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    avatar_corner: str,
    text_corner: str,
    accent: tuple[int, int, int],
    chrome: Image.Image | None = None,
    avatar_nudge: tuple[int, int] = (0, 0),
    name_nudge: tuple[int, int] = (0, 0),
    name_below: bool = False,
    pillar_box: tuple[int, int, int, int] | None = None,
) -> None:
    """Avatar + username stacked on the chrome bio pillar for layouts 1–4, 16, and 17."""
    width, height = canvas.size
    avatar_gap = max(30, width // _HUD_AVATAR_GAP_X_DIV)
    avatar_gap_y = max(16, width // _HUD_AVATAR_GAP_Y_DIV)
    diameter = max(_HUD_AVATAR_DIAM_MIN, int(width * _HUD_AVATAR_DIAM_RATIO) + _HUD_AVATAR_DIAM_NUDGE)
    ring = max(2, diameter // 40)
    outer = diameter + ring * 2
    avatar_x = avatar_gap + outer // 2 if avatar_corner.endswith("l") else width - avatar_gap - outer // 2
    avatar_y = (
        avatar_gap_y + outer // 2
        if avatar_corner.startswith("t")
        else height - avatar_gap_y - outer // 2
    )
    avatar_x += avatar_nudge[0]
    avatar_y += avatar_nudge[1]
    _place_portrait(canvas, avatar_art, avatar_pos, (avatar_x, avatar_y), diameter, ring=True)

    draw = ImageDraw.Draw(canvas)
    right_text = text_corner.endswith("r")
    top_text = text_corner.startswith("t")
    pillar = pillar_box if pillar_box is not None else _chrome_bio_pillar(chrome or canvas, text_corner)

    name_size = max(_HUD_NAME_SIZE_MIN, int(width * _HUD_NAME_SIZE_RATIO))
    name_font = _load_font(font_path, name_size)
    tracking = max(1, name_size // _HUD_NAME_TRACK_DIV)
    name_max_w = int(width * 0.62)
    if pillar is not None:
        name_max_w = max(8, pillar[2] + pillar[2] // 8)
    name_label = _clip(username or "Player", name_font, name_max_w, draw)
    while len(name_label) > 1 and _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
        name_label = name_label[:-1]
    stroke_w = max(1, name_size // _HUD_NAME_STROKE_DIV)
    edge_pad = max(16, width // 80)
    # Solid layout-tinted outline that stays readable on the accent band.
    stroke_fill = tuple(max(0, min(255, (channel * 2) // 3)) for channel in accent)
    name_box = draw.textbbox((0, 0), name_label, font=name_font)
    tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)

    if pillar is not None:
        left, top, pill_w, pill_h = pillar
        pillar_right = left + pill_w
        pillar_gap = max(8, pill_h // 8)
        # Sit a hair inside the pillar cap (negative = further left on right-side names).
        flush = stroke_w + _HUD_NAME_FLUSH
        if right_text:
            name_x = pillar_right - tracked_w + flush
        else:
            name_x = left - name_box[0] - flush
        # Layouts 1–4 and 16 keep the name above the pill. Layout 17 swaps it underneath.
        ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
        clear = max(
            _HUD_NAME_CLEAR_MIN,
            pillar_gap + stroke_w + _HUD_NAME_CLEAR_BASE + _HUD_NAME_CLEAR_EXTRA,
        )
        if name_below:
            name_y = top + pill_h + clear - ink[1]
        else:
            name_y = top - clear - ink[3]
        name_x += name_nudge[0]
        name_y += name_nudge[1]
    else:
        if right_text:
            name_x = width - edge_pad - tracked_w
        else:
            name_x = edge_pad - name_box[0]
        name_y = (
            edge_pad - name_box[1]
            if top_text
            else height - edge_pad - name_box[3]
        )
        name_x += name_nudge[0]
        name_y += name_nudge[1]

    _draw_tracked_text(
        draw,
        (name_x, name_y),
        name_label,
        name_font,
        tracking,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(*stroke_fill, 255),
    )
    if not title or pillar is None:
        return
    left, top, pill_w, pill_h = pillar
    inner_w = max(8, pill_w - pill_h)
    bio_size = max(
        _HUD_BIO_SIZE_MIN,
        min(int(pill_h * _HUD_BIO_SIZE_PILL_RATIO), int(width * _HUD_BIO_SIZE_WIDTH_RATIO)),
    )
    bio_font = _load_font(font_path, bio_size)
    # Shrink bio text until the full string fits in the chrome pillar.
    while bio_size > _HUD_BIO_SIZE_FLOOR:
        bio_font = _load_font(font_path, bio_size)
        box = draw.textbbox((0, 0), title, font=bio_font)
        if box[2] - box[0] <= inner_w:
            break
        bio_size -= 1
    fitted = draw.textbbox((0, 0), title, font=bio_font)
    bio_label = title if fitted[2] - fitted[0] <= inner_w else _clip(title, bio_font, inner_w, draw)
    draw.text(
        (left + pill_w // 2, top + pill_h // 2),
        bio_label,
        font=bio_font,
        anchor="mm",
        fill=(255, 255, 255, 255),
    )


def _chrome_accent_pill(chrome: Image.Image, corner: str) -> tuple[int, int, int, int] | None:
    """Colored bio capsule (layouts 8–10/30 family) — saturated fill, not white arcs."""
    width, height = chrome.size
    pixels = chrome.load()
    y0, y1 = (int(height * 0.72), height - 4) if corner.startswith("b") else (4, int(height * 0.28))
    x0, x1 = (width // 2, width - 2) if corner.endswith("r") else (2, width // 2)

    def _is_accent(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        if alpha < 220:
            return False
        if red > 230 and green > 230 and blue > 230:
            return False
        return max(red, green, blue) - min(red, green, blue) >= 25

    arcs: list[tuple[int, int, int, int]] = []
    for y in range(y0, y1):
        best: tuple[int, int, int] | None = None
        start: int | None = None
        prev = 0
        for x in range(x0, x1):
            if _is_accent(x, y):
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                span = prev - start + 1
                if best is None or span > best[0]:
                    best = (span, start, prev)
                start = None
        if start is not None:
            span = prev - start + 1
            if best is None or span > best[0]:
                best = (span, start, prev)
        if best is not None and best[0] >= 180:
            arcs.append((y, best[1], best[2], best[0]))
    if len(arcs) < 6:
        return None
    best_band = [arcs[0]]
    current = [arcs[0]]
    for previous, row in zip(arcs, arcs[1:]):
        if (
            row[0] == previous[0] + 1
            and abs(row[1] - previous[1]) < 40
            and abs(row[2] - previous[2]) < 40
        ):
            current.append(row)
        else:
            if len(current) > len(best_band):
                best_band = current
            current = [row]
    if len(current) > len(best_band):
        best_band = current
    if len(best_band) < 6:
        return None
    top_y, bottom_y = best_band[0][0], best_band[-1][0]
    left = min(row[1] for row in best_band)
    right = max(row[2] for row in best_band)
    return (left, top_y, right - left + 1, bottom_y - top_y + 1)


def _notch_avatar_slot(chrome: Image.Image, avatar_corner: str) -> tuple[int, int, int]:
    """Circle that fills the layout's corner cutout (opaque chrome lobe)."""
    width, height = chrome.size
    pixels = chrome.load()
    topish = avatar_corner.startswith("t")
    leftish = avatar_corner.endswith("l")
    y0, y1 = (40, int(height * 0.28)) if topish else (int(height * 0.72), height - 40)
    x_limit = width // 2

    # Walk from the outer edge: rightmost/leftmost opaque run = cutout shoulder.
    # Works for bright white panels (8–10) and frosted grey chrome (30).
    rows: list[tuple[int, int]] = []
    for y in range(y0, y1):
        last: int | None = None
        seen = False
        if leftish:
            for x in range(0, x_limit):
                if pixels[x, y][3] > 200:
                    last = x
                    seen = True
                elif seen:
                    break
        else:
            for x in range(width - 1, x_limit - 1, -1):
                if pixels[x, y][3] > 200:
                    last = x
                    seen = True
                elif seen:
                    break
        if last is not None:
            rows.append((y, last))
    if len(rows) < 20:
        diameter = max(_HUD_AVATAR_DIAM_MIN, int(width * _HUD_AVATAR_DIAM_RATIO) + _HUD_AVATAR_DIAM_NUDGE)
        gap = max(16, width // _HUD_AVATAR_GAP_Y_DIV)
        cx = gap + diameter // 2 if leftish else width - gap - diameter // 2
        cy = gap + diameter // 2 if topish else height - gap - diameter // 2
        return cx, cy, diameter

    threshold = 120
    cut = [(y, x) for y, x in rows if (x > threshold if leftish else x < width - threshold)]
    if len(cut) < 12:
        cut = rows
    y_top, y_bot = cut[0][0], cut[-1][0]
    diameter = max(120, min(int(width * 0.24), y_bot - y_top))
    diameter = int(diameter * 0.92)
    gap = max(12, width // 90)
    cx = gap + diameter // 2 if leftish else width - gap - diameter // 2
    cy = (y_top + y_bot) // 2
    if leftish:
        cx += _NOTCH_AVATAR_X_NUDGE
    else:
        cx -= _NOTCH_AVATAR_X_NUDGE
    # Y_NUDGE is toward the top of the card (negative = up into a bottom cutout too).
    cy += _NOTCH_AVATAR_Y_NUDGE
    if not leftish and not topish:
        cx += _NOTCH_AVATAR_BR_X_EXTRA
        cy += _NOTCH_AVATAR_BR_Y_EXTRA
    return cx, cy, diameter


def _stamp_notch_split_hud(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    avatar_corner: str,
    name_corner: str,
    bio_corner: str,
    accent: tuple[int, int, int],
    chrome: Image.Image | None = None,
) -> None:
    """Split HUD: cutout avatar, name in one corner, bio in the accent pill."""
    width, height = canvas.size
    frame = chrome or canvas
    cx, cy, diameter = _notch_avatar_slot(frame, avatar_corner)
    ring = max(2, diameter // 40)
    _place_portrait(canvas, avatar_art, avatar_pos, (cx, cy), diameter, ring=True)

    draw = ImageDraw.Draw(canvas)
    name_size = max(_HUD_NAME_SIZE_MIN, int(width * _HUD_NAME_SIZE_RATIO))
    name_font = _load_font(font_path, name_size)
    tracking = max(1, name_size // _HUD_NAME_TRACK_DIV)
    stroke_w = max(1, name_size // _HUD_NAME_STROKE_DIV)
    stroke_fill = tuple(max(0, min(255, (channel * 2) // 3)) for channel in accent)
    edge_pad = max(16, width // 80)
    name_max_w = int(width * 0.55)
    name_label = _clip(username or "Player", name_font, name_max_w, draw)
    while len(name_label) > 1 and _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
        name_label = name_label[:-1]
    name_box = draw.textbbox((0, 0), name_label, font=name_font)
    tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)
    ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
    right_name = name_corner.endswith("r")
    top_name = name_corner.startswith("t")
    if right_name:
        name_x = width - edge_pad - _NOTCH_NAME_RIGHT_INSET - tracked_w
    else:
        name_x = edge_pad + _NOTCH_NAME_RIGHT_INSET - name_box[0]
    if top_name:
        name_y = edge_pad + _NOTCH_NAME_TOP_INSET - ink[1]
    else:
        name_y = height - edge_pad - _NOTCH_NAME_TOP_INSET - ink[3]
    _draw_tracked_text(
        draw,
        (name_x, name_y),
        name_label,
        name_font,
        tracking,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(*stroke_fill, 255),
    )

    if not title:
        return
    pill = _chrome_accent_pill(frame, bio_corner)
    if pill is None:
        pill = _chrome_bio_pillar(frame, bio_corner)
    if pill is None:
        return
    left, top, pill_w, pill_h = pill
    inner_w = max(8, pill_w - pill_h)
    bio_size = max(
        _HUD_BIO_SIZE_MIN,
        min(int(pill_h * _HUD_BIO_SIZE_PILL_RATIO), int(width * _HUD_BIO_SIZE_WIDTH_RATIO)),
    )
    bio_font = _load_font(font_path, bio_size)
    while bio_size > _HUD_BIO_SIZE_FLOOR:
        bio_font = _load_font(font_path, bio_size)
        box = draw.textbbox((0, 0), title, font=bio_font)
        if box[2] - box[0] <= inner_w:
            break
        bio_size -= 1
    fitted = draw.textbbox((0, 0), title, font=bio_font)
    bio_label = title if fitted[2] - fitted[0] <= inner_w else _clip(title, bio_font, inner_w, draw)
    draw.text(
        (left + pill_w // 2, top + pill_h // 2),
        bio_label,
        font=bio_font,
        anchor="mm",
        fill=(255, 255, 255, 255),
    )


def _chrome_center_pill(chrome: Image.Image, band: str) -> tuple[int, int, int, int] | None:
    """Centered accent bio capsule along the top or bottom banner."""
    width, height = chrome.size
    pixels = chrome.load()
    if band == "top":
        y0, y1 = 4, int(height * 0.18)
    else:
        y0, y1 = int(height * 0.85), height - 4

    def _is_accent(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        if alpha < 220:
            return False
        if red > 230 and green > 230 and blue > 230:
            return False
        return max(red, green, blue) - min(red, green, blue) >= 20

    arcs: list[tuple[int, int, int, int]] = []
    mid = width // 2
    for y in range(y0, y1):
        runs: list[tuple[int, int]] = []
        start: int | None = None
        prev = 0
        for x in range(40, width - 40):
            if _is_accent(x, y):
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                runs.append((start, prev))
                start = None
        if start is not None:
            runs.append((start, prev))
        best: tuple[float, int, int, int] | None = None
        for left, right in runs:
            span = right - left + 1
            if span < 200:
                continue
            center = (left + right) / 2
            score = span - abs(center - mid) * 0.5
            if best is None or score > best[0]:
                best = (score, left, right, span)
        if best is not None:
            arcs.append((y, best[1], best[2], best[3]))
    if len(arcs) < 5:
        return None
    best_band = [arcs[0]]
    current = [arcs[0]]
    for previous, row in zip(arcs, arcs[1:]):
        if (
            row[0] == previous[0] + 1
            and abs(row[1] - previous[1]) < 50
            and abs(row[2] - previous[2]) < 50
        ):
            current.append(row)
        else:
            if len(current) > len(best_band):
                best_band = current
            current = [row]
    if len(current) > len(best_band):
        best_band = current
    if len(best_band) < 5:
        return None
    top_y, bottom_y = best_band[0][0], best_band[-1][0]
    left = min(row[1] for row in best_band)
    right = max(row[2] for row in best_band)
    return (left, top_y, right - left + 1, bottom_y - top_y + 1)


def _band_panel_edge(chrome: Image.Image, band: str) -> int:
    """Y where the white content panel meets the top/bottom color banner (center column)."""
    width, height = chrome.size
    pixels = chrome.load()
    cx = width // 2
    if band == "top":
        for y in range(10, height // 3):
            red, green, blue, alpha = pixels[cx, y]
            if alpha > 200 and red > 220 and green > 220 and blue > 220:
                return y
        return int(height * 0.09)
    for y in range(height - 10, 2 * height // 3, -1):
        red, green, blue, alpha = pixels[cx, y]
        if alpha > 200 and red > 220 and green > 220 and blue > 220:
            return y
    return int(height * 0.91)


def _band_avatar_slot(chrome: Image.Image, band: str) -> tuple[int, int, int]:
    width, height = chrome.size
    diameter = max(_HUD_AVATAR_DIAM_MIN, int(width * _BAND_AVATAR_DIAM_RATIO))
    edge = _band_panel_edge(chrome, band)
    cx = width // 2
    # Sit on the banner/panel seam (half the circle over the banner).
    cy = edge if band == "top" else edge
    return cx, cy, diameter


def _stamp_band_center_hud(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    avatar_band: str,
    text_band: str,
    accent: tuple[int, int, int],
    chrome: Image.Image | None = None,
) -> None:
    """Centered HUD: avatar on one banner seam, name+bio stacked on the other."""
    width, height = canvas.size
    frame = chrome or canvas
    cx, cy, diameter = _band_avatar_slot(frame, avatar_band)
    ring = max(2, diameter // 40)
    _place_portrait(canvas, avatar_art, avatar_pos, (cx, cy), diameter, ring=True)

    draw = ImageDraw.Draw(canvas)
    pill = _chrome_center_pill(frame, text_band)
    if pill is None:
        pill = _chrome_accent_pill(frame, "bl" if text_band == "bottom" else "tl")
    name_size = max(_HUD_NAME_SIZE_MIN, int(width * _HUD_NAME_SIZE_RATIO))
    name_font = _load_font(font_path, name_size)
    tracking = max(1, name_size // _HUD_NAME_TRACK_DIV)
    stroke_w = max(1, name_size // _HUD_NAME_STROKE_DIV)
    stroke_fill = tuple(max(0, min(255, (channel * 2) // 3)) for channel in accent)
    name_max_w = int(width * 0.62)
    if pill is not None:
        name_max_w = max(8, pill[2] + pill[2] // 8)
    name_label = _clip(username or "Player", name_font, name_max_w, draw)
    while len(name_label) > 1 and _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
        name_label = name_label[:-1]
    tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)
    ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
    name_x = (width - tracked_w) / 2

    if pill is not None:
        left, top, pill_w, pill_h = pill
        gap = max(_BAND_NAME_PILL_GAP, pill_h // 6)
        if text_band == "bottom":
            # Name above bio pill.
            name_y = top - gap - ink[3]
        else:
            # Name below bio pill.
            name_y = top + pill_h + gap - ink[1]
    else:
        edge = _band_panel_edge(frame, text_band)
        if text_band == "bottom":
            name_y = edge - max(24, name_size) - ink[3]
        else:
            name_y = edge + max(12, name_size // 4) - ink[1]

    _draw_tracked_text(
        draw,
        (name_x, name_y),
        name_label,
        name_font,
        tracking,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(*stroke_fill, 255),
    )

    if not title or pill is None:
        return
    left, top, pill_w, pill_h = pill
    inner_w = max(8, pill_w - pill_h)
    bio_size = max(
        _HUD_BIO_SIZE_MIN,
        min(int(pill_h * _HUD_BIO_SIZE_PILL_RATIO), int(width * _HUD_BIO_SIZE_WIDTH_RATIO)),
    )
    bio_font = _load_font(font_path, bio_size)
    while bio_size > _HUD_BIO_SIZE_FLOOR:
        bio_font = _load_font(font_path, bio_size)
        box = draw.textbbox((0, 0), title, font=bio_font)
        if box[2] - box[0] <= inner_w:
            break
        bio_size -= 1
    fitted = draw.textbbox((0, 0), title, font=bio_font)
    bio_label = title if fitted[2] - fitted[0] <= inner_w else _clip(title, bio_font, inner_w, draw)
    draw.text(
        (left + pill_w // 2, top + pill_h // 2),
        bio_label,
        font=bio_font,
        anchor="mm",
        fill=(255, 255, 255, 255),
    )


def _footer_name_bio_bars(
    chrome: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int] | None] | None:
    """Wide name bar + smaller bio pill along the bottom (layouts 13–15)."""
    width, height = chrome.size
    pixels = chrome.load()

    def _is_bar(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        if alpha < 220:
            return False
        if red > 230 and green > 230 and blue > 230:
            return False
        # Colored chrome bar/pill (blue / pink / peach variants).
        return max(red, green, blue) - min(red, green, blue) >= 25

    bands: list[tuple[int, int, int, int]] = []
    for y in range(int(height * 0.75), height - 2):
        start: int | None = None
        prev = 0
        best: tuple[int, int, int] | None = None
        for x in range(0, width):
            if _is_bar(x, y):
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                span = prev - start + 1
                if best is None or span > best[0]:
                    best = (span, start, prev)
                start = None
        if start is not None:
            span = prev - start + 1
            if best is None or span > best[0]:
                best = (span, start, prev)
        if best is not None and best[0] > 200:
            bands.append((y, best[1], best[2], best[0]))
    if not bands:
        return None
    clusters: list[list[tuple[int, int, int, int]]] = []
    current = [bands[0]]
    for previous, row in zip(bands, bands[1:]):
        if row[0] == previous[0] + 1 and abs(row[1] - previous[1]) < 80:
            current.append(row)
        else:
            clusters.append(current)
            current = [row]
    clusters.append(current)

    def _box(cluster: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        top_y, bottom_y = cluster[0][0], cluster[-1][0]
        left = min(row[1] for row in cluster)
        right = max(row[2] for row in cluster)
        return (left, top_y, right - left + 1, bottom_y - top_y + 1)

    # Prefer a tall wide name bar, then a shorter pill below it.
    ranked = sorted(clusters, key=lambda c: (-(c[-1][0] - c[0][0] + 1), -(max(r[3] for r in c))))
    name_bar = _box(ranked[0])
    bio_pill: tuple[int, int, int, int] | None = None
    name_bottom = name_bar[1] + name_bar[3]
    for cluster in ranked[1:]:
        box = _box(cluster)
        if box[3] < 30 or box[2] < 240:
            continue
        if box[1] >= name_bottom - 8:
            bio_pill = box
            break
    return name_bar, bio_pill


def _solid_dark_capsule(chrome: Image.Image, corner: str) -> tuple[int, int, int, int] | None:
    """Opaque black bio capsule (layouts 16–19). Returns left, top, width, height."""
    width, height = chrome.size
    pixels = chrome.load()
    if corner == "br":
        x0, x1 = width // 3, width - 4
        y0, y1 = int(height * 0.78), height - 8
    elif corner == "tl":
        x0, x1 = 4, int(width * 0.72)
        y0, y1 = 8, int(height * 0.30)
    else:
        return None
    rows: list[tuple[int, int, int]] = []
    for y in range(y0, y1):
        start: int | None = None
        prev = 0
        best: tuple[int, int, int] | None = None
        for x in range(x0, x1):
            red, green, blue, alpha = pixels[x, y]
            solid = alpha >= 250 and red < 90 and green < 90 and blue < 90
            if solid:
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                span = prev - start + 1
                if best is None or span > best[0]:
                    best = (span, start, prev)
                start = None
        if start is not None:
            span = prev - start + 1
            if best is None or span > best[0]:
                best = (span, start, prev)
        if best is not None and 420 <= best[0] <= 780:
            rows.append((y, best[1], best[2]))
    if not rows:
        return None
    clusters: list[list[tuple[int, int, int]]] = []
    current = [rows[0]]
    for previous, row in zip(rows, rows[1:]):
        if row[0] <= previous[0] + 2:
            current.append(row)
        else:
            clusters.append(current)
            current = [row]
    clusters.append(current)
    picked: list[tuple[int, int, int]] | None = None
    for cluster in clusters:
        span_y = cluster[-1][0] - cluster[0][0] + 1
        if 55 <= span_y <= 120 and (picked is None or span_y > picked[-1][0] - picked[0][0]):
            picked = cluster
    if picked is None:
        return None
    left = min(row[1] for row in picked)
    right = max(row[2] for row in picked)
    top = picked[0][0]
    bottom = picked[-1][0]
    pad = 8
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(width - 1, right + pad)
    bottom = min(height - 1, bottom + pad)
    return (left, top, right - left + 1, bottom - top + 1)


def _light_name_bar(chrome: Image.Image) -> tuple[int, int, int, int] | None:
    """Wide near-white name plate along the bottom (layout 18)."""
    width, height = chrome.size
    pixels = chrome.load()
    rows: list[tuple[int, int, int]] = []
    for y in range(int(height * 0.78), height - 4):
        start: int | None = None
        prev = 0
        best: tuple[int, int, int] | None = None
        for x in range(0, width):
            red, green, blue, alpha = pixels[x, y]
            light = alpha >= 200 and red > 210 and green > 210 and blue > 210
            if light:
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                span = prev - start + 1
                if best is None or span > best[0]:
                    best = (span, start, prev)
                start = None
        if start is not None:
            span = prev - start + 1
            if best is None or span > best[0]:
                best = (span, start, prev)
        if best is not None and best[0] > 400:
            rows.append((y, best[1], best[2]))
    if len(rows) < 20:
        return None
    clusters: list[list[tuple[int, int, int]]] = []
    current = [rows[0]]
    for previous, row in zip(rows, rows[1:]):
        if row[0] <= previous[0] + 2:
            current.append(row)
        else:
            clusters.append(current)
            current = [row]
    clusters.append(current)
    # The name plate is the long run. The bio pill's white stroke is a short one below it.
    band = max(clusters, key=len)
    if len(band) < 20:
        return None
    left = min(row[1] for row in band)
    right = max(row[2] for row in band)
    return (left, band[0][0], right - left + 1, band[-1][0] - band[0][0] + 1)


def _dark_name_bar(chrome: Image.Image) -> tuple[int, int, int, int] | None:
    """Wide dark name plate along the top (layout 19). Wider than the bio capsule under it."""
    width, height = chrome.size
    pixels = chrome.load()
    rows: list[tuple[int, int, int]] = []
    for y in range(4, int(height * 0.22)):
        start: int | None = None
        prev = 0
        best: tuple[int, int, int] | None = None
        for x in range(0, width):
            red, green, blue, alpha = pixels[x, y]
            dark = alpha >= 220 and red < 80 and green < 80 and blue < 80
            if dark:
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                span = prev - start + 1
                if best is None or span > best[0]:
                    best = (span, start, prev)
                start = None
        if start is not None:
            span = prev - start + 1
            if best is None or span > best[0]:
                best = (span, start, prev)
        if best is not None and best[0] > 700:
            rows.append((y, best[1], best[2]))
    if len(rows) < 20:
        return None
    left = min(row[1] for row in rows)
    right = max(row[2] for row in rows)
    return (left, rows[0][0], right - left + 1, rows[-1][0] - rows[0][0] + 1)


def _plate_bars_18(
    chrome: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int] | None] | None:
    bar = _light_name_bar(chrome)
    if bar is None:
        return None
    return bar, _solid_dark_capsule(chrome, "br")


def _plate_bars_19(
    chrome: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int] | None] | None:
    bar = _dark_name_bar(chrome)
    if bar is None:
        return None
    return bar, _solid_dark_capsule(chrome, "tl")


def _opaque_plate(chrome: Image.Image, *, top: bool) -> Image.Image:
    """Make the header or footer plate fully opaque so the art does not show through."""
    out = chrome.copy()
    pixels = out.load()
    width, height = out.size
    y0, y1 = (0, int(height * 0.24)) if top else (int(height * 0.80), height)
    for y in range(y0, y1):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha >= 200:
                pixels[x, y] = (red, green, blue, 255)
    return out


def _stamp_footer_stack_hud(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    accent: tuple[int, int, int],
    chrome: Image.Image | None = None,
    bars: tuple[tuple[int, int, int, int], tuple[int, int, int, int] | None] | None = None,
    mirror: bool = False,
    flip_y: bool = False,
    avatar_extra: tuple[int, int] = (0, 0),
    name_extra: tuple[int, int] = (0, 0),
    lock_name_size: bool = False,
    align_right: bool = False,
) -> None:
    """Wide name bar + bio pill. Layouts 13–15 and 18 sit on the bottom; 19 is the top mirror."""
    width, height = canvas.size
    frame = chrome or canvas
    if bars is None:
        bars = _footer_name_bio_bars(frame)
    if bars is None:
        return
    name_bar, bio_pill = bars
    bar_left, bar_top, bar_w, bar_h = name_bar

    diameter = max(_HUD_AVATAR_DIAM_MIN, int(width * _HUD_AVATAR_DIAM_RATIO) + _HUD_AVATAR_DIAM_NUDGE)
    gap = max(16, width // _HUD_AVATAR_GAP_X_DIV)
    avatar_shift_x = _FOOTER_AVATAR_X_NUDGE + avatar_extra[0]
    avatar_shift_y = (_FOOTER_AVATAR_Y_NUDGE if not flip_y else -_FOOTER_AVATAR_Y_NUDGE) + avatar_extra[1]
    avatar_x = gap + diameter // 2 + avatar_shift_x
    if mirror:
        avatar_x = width - avatar_x
    avatar_y = bar_top + bar_h // 2 + avatar_shift_y
    ring = max(2, diameter // 40)
    _place_portrait(canvas, avatar_art, avatar_pos, (avatar_x, avatar_y), diameter, ring=True)

    draw = ImageDraw.Draw(canvas)
    # Layouts 18–19 reuse layout 14's name size even when their plate is shorter.
    size_h = max(bar_h, int(width * 0.106)) if lock_name_size else bar_h
    name_size = max(_HUD_NAME_SIZE_MIN, min(int(size_h * 0.55), int(width * _HUD_NAME_SIZE_RATIO)))
    name_font = _load_font(font_path, name_size)
    tracking = max(1, name_size // _HUD_NAME_TRACK_DIV)
    stroke_w = max(1, name_size // _HUD_NAME_STROKE_DIV)
    stroke_fill = tuple(max(0, min(255, (channel * 2) // 3)) for channel in accent)
    pad = max(12, bar_h // 5)
    # Clearance uses the left-side avatar slot so a mirrored card keeps the same gap.
    anchor_x = gap + diameter // 2 + _FOOTER_AVATAR_X_NUDGE + avatar_extra[0]
    if align_right and not mirror:
        # Name's right edge sits on the bar's right inset. +X still moves that edge right.
        name_right = bar_left + bar_w - pad - stroke_w + name_extra[0]
        left_limit = max(bar_left + pad, int(anchor_x + diameter * 0.55))
        name_max_w = max(8, name_right - left_limit)
    else:
        text_left = max(bar_left + pad, int(anchor_x + diameter * 0.55)) + _FOOTER_NAME_X_NUDGE + name_extra[0]
        name_max_w = max(8, (width - pad - text_left) if mirror else (bar_left + bar_w - pad - text_left))
        name_right = 0
    name_label = _clip(username or "Player", name_font, name_max_w, draw)
    while len(name_label) > 1 and _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
        name_label = name_label[:-1]
    ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
    tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)
    name_shift_y = (-_FOOTER_NAME_Y_NUDGE if flip_y else _FOOTER_NAME_Y_NUDGE) + name_extra[1]
    name_y = bar_top + (bar_h - (ink[3] - ink[1])) // 2 - ink[1] + name_shift_y
    if align_right and not mirror:
        name_x = name_right - tracked_w
    else:
        name_x = (width - text_left - tracked_w) if mirror else text_left
    _draw_tracked_text(
        draw,
        (name_x, name_y),
        name_label,
        name_font,
        tracking,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(*stroke_fill, 255),
    )

    if not title or bio_pill is None:
        return
    left, top, pill_w, pill_h = bio_pill
    inner_w = max(8, pill_w - pill_h)
    bio_size = max(
        _HUD_BIO_SIZE_MIN,
        min(int(pill_h * _HUD_BIO_SIZE_PILL_RATIO), int(width * _HUD_BIO_SIZE_WIDTH_RATIO)),
    )
    bio_font = _load_font(font_path, bio_size)
    while bio_size > _HUD_BIO_SIZE_FLOOR:
        bio_font = _load_font(font_path, bio_size)
        box = draw.textbbox((0, 0), title, font=bio_font)
        if box[2] - box[0] <= inner_w:
            break
        bio_size -= 1
    fitted = draw.textbbox((0, 0), title, font=bio_font)
    bio_label = title if fitted[2] - fitted[0] <= inner_w else _clip(title, bio_font, inner_w, draw)
    if align_right and not mirror:
        # Keep the glyphs out of the pill's rounded right cap.
        bio_x = left + pill_w - max(pill_h // 2, 8)
        bio_anchor = "rm"
    else:
        bio_x = left + pill_w // 2
        bio_anchor = "mm"
    draw.text(
        (bio_x, top + pill_h // 2),
        bio_label,
        font=bio_font,
        anchor=bio_anchor,
        fill=(255, 255, 255, 255),
    )


def _chrome_bio_pillar(chrome: Image.Image, text_corner: str) -> tuple[int, int, int, int] | None:
    """Bounding box of the layout's baked bio capsule (white top/bottom arcs)."""
    width, height = chrome.size
    pixels = chrome.load()
    y0, y1 = (40, height // 3) if text_corner.startswith("t") else (2 * height // 3, height - 10)
    x0, x1 = (width // 2, width - 5) if text_corner.endswith("r") else (5, width // 2)

    def _is_white(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        if alpha < 200:
            return False
        luma = red + green + blue
        return luma >= 720 and max(red, green, blue) - min(red, green, blue) < 30

    def _row_runs(y: int) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        start: int | None = None
        prev = -3
        for x in range(x0, x1):
            if _is_white(x, y):
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                runs.append((start, prev))
                start = None
        if start is not None:
            runs.append((start, prev))
        return runs

    arcs: list[tuple[int, int, int, int]] = []
    for y in range(y0, y1):
        for left, right in _row_runs(y):
            span = right - left + 1
            if span >= 200:
                arcs.append((y, left, right, span))
    if len(arcs) < 2:
        return None
    best: tuple[int, tuple[int, int, int, int]] | None = None
    for index, top in enumerate(arcs):
        for bottom in arcs[index + 1 :]:
            gap = bottom[0] - top[0]
            if not (45 <= gap <= 110):
                continue
            overlap = min(top[2], bottom[2]) - max(top[1], bottom[1])
            if overlap < 180:
                continue
            left = min(top[1], bottom[1])
            right = max(top[2], bottom[2])
            box_w = right - left + 1
            if box_w > 720:
                continue
            score = box_w * gap
            box = (left, top[0], box_w, gap + 1)
            if best is None or score > best[0]:
                best = (score, box)
    if best is None:
        return None
    left, top_y, box_w, box_h = best[1]
    right = left + box_w - 1
    # Arc rows miss the rounded end caps; expand to the true white outline.
    for y in range(top_y, top_y + box_h):
        for x in range(x0, left):
            if _is_white(x, y):
                left = x
                break
        for x in range(x1 - 1, right, -1):
            if _is_white(x, y):
                right = x
                break
    return (left, top_y, right - left + 1, box_h)


def _rizcard_layout_37(
    chrome: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    ink: tuple[int, int, int],
    avatar_art: Image.Image | None,
    banner_art: Image.Image | None,
    avatar_pos: dict,
    repo_root: Path | None,
    layout_id: str,
    frame: Image.Image,
) -> Image.Image | None:
    """Special layout 37: line-filtered art in CoverMask, prefab nameplate on top."""
    card_w, card_h = chrome.size
    slots = _rizcard_prefab_slots(repo_root, layout_id, (card_w, card_h)) if repo_root and layout_id else None
    if slots is None or "art" not in slots:
        return None
    left, top, width, height = slots["art"]
    inset = max(6, min(width, height) // 80)
    window = (left + inset, top + inset, left + width - inset, top + height - inset)
    win_l, win_t, win_r, win_b = window
    chrome = _clear_rect_alpha(chrome, win_l, win_t, win_r, win_b)
    art = _bw_card_art(banner_art, max(1, win_r - win_l), max(1, win_b - win_t))
    canvas = Image.new("RGBA", chrome.size, (255, 255, 255, 255))
    canvas.paste(art, (win_l, win_t))
    canvas.alpha_composite(chrome)
    _cover_with_frame(canvas, chrome)
    _stamp_rizcard_nameplate(
        canvas,
        username=username,
        title=title,
        font_path=font_path,
        ink=ink,
        avatar_art=avatar_art,
        avatar_pos=avatar_pos,
        slots=slots,
        frame=frame,
    )
    return canvas


def _unity_rect_box(
    rect: dict,
    card_size: tuple[int, int],
    *,
    design: tuple[float, float] = (1488.0, 2078.0),
) -> tuple[int, int, int, int] | None:
    """Prefab RectTransform to a pillow box (left, top, width, height)."""
    size = rect.get("m_SizeDelta") if isinstance(rect.get("m_SizeDelta"), dict) else {}
    pos = rect.get("m_AnchoredPosition") if isinstance(rect.get("m_AnchoredPosition"), dict) else {}
    anchor = rect.get("m_AnchorMin") if isinstance(rect.get("m_AnchorMin"), dict) else {}
    pivot = rect.get("m_Pivot") if isinstance(rect.get("m_Pivot"), dict) else {}
    try:
        box_w = float(size.get("x") or 0)
        box_h = float(size.get("y") or 0)
        pivot_x = float(pivot.get("x") if pivot.get("x") is not None else 0.5)
        pivot_y = float(pivot.get("y") if pivot.get("y") is not None else 0.5)
        anchor_x = float(anchor.get("x") or 0) * design[0] + float(pos.get("x") or 0)
        anchor_y = float(anchor.get("y") or 0) * design[1] + float(pos.get("y") or 0)
    except (TypeError, ValueError):
        return None
    if box_w < 8 or box_h < 8:
        return None
    left = anchor_x - pivot_x * box_w
    bottom = anchor_y - pivot_y * box_h
    scale_x = card_size[0] / design[0]
    scale_y = card_size[1] / design[1]
    width = box_w * scale_x
    height = box_h * scale_y
    top = card_size[1] - (bottom * scale_y + height)
    return (int(round(left * scale_x)), int(round(top)), int(round(width)), int(round(height)))


_WAVE_PREFAB_BOXES: dict[tuple[str, int, int], dict[str, tuple[int, int, int, int]]] = {}


def _wave_prefab_boxes(
    repo_root: Path | None,
    layout_id: str,
    card_size: tuple[int, int],
) -> dict[str, tuple[int, int, int, int]]:
    """Avatar, name, and bio boxes authored on layouts 21–28."""
    if repo_root is None or not layout_id.strip():
        return {}
    key = (layout_id.strip(), card_size[0], card_size[1])
    cached = _WAVE_PREFAB_BOXES.get(key)
    if cached is not None:
        return cached
    found: dict[str, tuple[int, int, int, int]] = {}
    try:
        from bot.ui.layout_card import _pointer, _prefab_bundle, _prefab_dependencies
        import UnityPy
    except ImportError:
        _WAVE_PREFAB_BOXES[key] = found
        return found
    bundle = _prefab_bundle(repo_root, layout_id)
    if bundle is None or not bundle.is_file():
        _WAVE_PREFAB_BOXES[key] = found
        return found
    try:
        env = UnityPy.Environment()
        env.load_file(str(bundle))
        for path in _prefab_dependencies(repo_root, layout_id):
            try:
                env.load_file(str(path))
            except Exception:
                continue
    except Exception:
        _WAVE_PREFAB_BOXES[key] = found
        return found
    names: dict[int, str] = {}
    go_rects: dict[int, dict] = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                names[obj.path_id] = str(obj.read().m_Name)
            except Exception:
                continue
        elif obj.type.name == "RectTransform":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            go = _pointer(tree.get("m_GameObject"))
            if go is not None and isinstance(tree, dict):
                go_rects[go] = tree
    for go, name in names.items():
        slot = name.strip().lower()
        if slot not in {"avatar", "name", "bio"}:
            continue
        rect = go_rects.get(go)
        if rect is None:
            continue
        box = _unity_rect_box(rect, card_size)
        if box is None or box[2] < 180 or box[3] < 60:
            continue
        previous = found.get(slot)
        if previous is None or box[2] * box[3] > previous[2] * previous[3]:
            found[slot] = box
    _WAVE_PREFAB_BOXES[key] = found
    return found


def _wave_hud(layout_id: str) -> tuple[str, str, str] | None:
    for number, spec in _WAVE_HUD.items():
        if _is_layout(layout_id, number):
            return spec
    return None


def _wave_regions(
    chrome: Image.Image,
) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    """Small accent pill and the wide colored banner on layouts 21–28."""
    width, height = chrome.size
    pixels = chrome.load()
    runs: list[tuple[int, int, int]] = []
    for y in range(0, height, 2):
        start: int | None = None
        prev = 0
        for x in range(0, width, 2):
            red, green, blue, alpha = pixels[x, y]
            saturated = (
                alpha >= 200
                and max(red, green, blue) - min(red, green, blue) >= 28
                and not (red > 225 and green > 225 and blue > 225)
            )
            if saturated:
                if start is None:
                    start = x
                prev = x
            elif start is not None:
                if prev - start + 1 >= 140:
                    runs.append((y, start, prev))
                start = None
        if start is not None and prev - start + 1 >= 140:
            runs.append((y, start, prev))

    def _box(blob: list[tuple[int, int, int]]) -> tuple[int, int, int, int]:
        top_y, bottom_y = blob[0][0], blob[-1][0]
        left = min(row[1] for row in blob)
        right = max(row[2] for row in blob)
        return (left, top_y, right - left + 1, bottom_y - top_y + 1)

    # The bio pill is a short capsule with steady ends. The banner's diagonal
    # edge keeps moving, so it never stays inside that window.
    pill_runs = [run for run in runs if 450 <= run[2] - run[1] + 1 <= 780]
    pills: list[list[tuple[int, int, int]]] = []
    for run in pill_runs:
        y, left, right = run
        placed = False
        for blob in pills:
            by, bl, br = blob[-1]
            if y - by <= 8 and abs(left - bl) < 48 and abs(right - br) < 48:
                blob.append(run)
                placed = True
                break
        if not placed:
            pills.append([run])
    pill: tuple[int, int, int, int] | None = None
    for blob in pills:
        box = _box(blob)
        # Capsules sit in from the card edge. A banner slice that reaches the edge is not one.
        if box[0] < 40 or box[0] + box[2] > width - 40:
            continue
        if 48 <= box[3] <= 110 and 480 <= box[2] <= 720 and (pill is None or box[3] > pill[3]):
            pill = box

    blobs: list[list[tuple[int, int, int]]] = []
    for run in runs:
        y, left, right = run
        if pill is not None and abs(y - (pill[1] + pill[3] // 2)) <= pill[3] and abs(left - pill[0]) < 80:
            continue
        placed = False
        for blob in blobs:
            by, bl, br = blob[-1]
            if y - by <= 8 and min(right, br) - max(left, bl) > 60:
                blob.append(run)
                placed = True
                break
        if not placed:
            blobs.append([run])
    banner: tuple[int, int, int, int] | None = None
    for blob in blobs:
        box = _box(blob)
        if banner is None or box[2] * box[3] > banner[2] * banner[3]:
            banner = box
    return pill, banner


def _stamp_wave_hud(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    avatar_corner: str,
    name_side: str,
    stack: str,
    accent: tuple[int, int, int],
    chrome: Image.Image | None = None,
    nudge: dict[str, tuple[int, int]] | None = None,
    repo_root: Path | None = None,
    layout_id: str = "",
) -> None:
    """Colored banner layouts 21–28. The avatar uses the layout's authored circle."""
    width, height = canvas.size
    frame = chrome or canvas
    slots = _wave_prefab_boxes(repo_root, layout_id, (width, height))
    pill, banner = _wave_regions(frame)
    if slots.get("bio") is not None:
        pill = slots["bio"]
    shifts = nudge or {}
    avatar_dx, avatar_dy = shifts.get("avatar", (0, 0))
    name_dx, name_dy = shifts.get("name", (0, 0))
    bio_dx, bio_dy = shifts.get("bio", (0, 0))

    avatar_box = slots.get("avatar")
    if avatar_box is not None:
        left, top, box_w, box_h = avatar_box
        # Fill the circle the layout already authored. Nudges only shift it.
        diameter = max(8, int(min(box_w, box_h)))
        avatar_x = left + box_w // 2
        avatar_y = top + box_h // 2
        _place_portrait(
            canvas,
            avatar_art,
            avatar_pos,
            (avatar_x + avatar_dx, avatar_y + avatar_dy),
            diameter,
            ring=False,
        )
    else:
        avatar_gap = max(30, width // _HUD_AVATAR_GAP_X_DIV)
        avatar_gap_y = max(16, width // _HUD_AVATAR_GAP_Y_DIV)
        diameter = max(_HUD_AVATAR_DIAM_MIN, int(width * _HUD_AVATAR_DIAM_RATIO) + _HUD_AVATAR_DIAM_NUDGE)
        ring = max(2, diameter // 40)
        outer = diameter + ring * 2
        avatar_x = avatar_gap + outer // 2 if avatar_corner.endswith("l") else width - avatar_gap - outer // 2
        avatar_y = (
            avatar_gap_y + outer // 2
            if avatar_corner.startswith("t")
            else height - avatar_gap_y - outer // 2
        )
        _place_portrait(
            canvas,
            avatar_art,
            avatar_pos,
            (avatar_x + avatar_dx, avatar_y + avatar_dy),
            diameter,
            ring=True,
        )

    draw = ImageDraw.Draw(canvas)
    name_size = max(_HUD_NAME_SIZE_MIN, int(width * _HUD_NAME_SIZE_RATIO))
    name_font = _load_font(font_path, name_size)
    tracking = max(1, name_size // _HUD_NAME_TRACK_DIV)
    stroke_w = max(1, name_size // _HUD_NAME_STROKE_DIV)
    stroke_fill = tuple(max(0, min(255, (channel * 2) // 3)) for channel in accent)
    pad = max(48, width // 24)
    name_max_w = int(width * 0.56)
    name_label = _clip(username or "Player", name_font, name_max_w, draw)
    while len(name_label) > 1 and _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
        name_label = name_label[:-1]
    ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
    tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)
    right_name = name_side == "r"
    clear = 18
    name_box = slots.get("name")
    if name_box is not None:
        left, top, box_w, box_h = name_box
        inset = max(8, box_h // 8)
        name_max_w = max(8, box_w - inset * 2)
        fitted_size = name_size
        raw_name = username or "Player"
        while fitted_size > _HUD_NAME_SIZE_MIN:
            name_font = _load_font(font_path, fitted_size)
            tracking = max(1, fitted_size // _HUD_NAME_TRACK_DIV)
            if _tracked_text_width(draw, raw_name, name_font, tracking) <= name_max_w:
                break
            fitted_size -= 2
        name_label = raw_name
        if _tracked_text_width(draw, name_label, name_font, tracking) > name_max_w:
            name_label = _clip(name_label, name_font, name_max_w, draw)
        stroke_w = max(1, fitted_size // _HUD_NAME_STROKE_DIV)
        ink = draw.textbbox((0, 0), name_label, font=name_font, stroke_width=stroke_w)
        tracked_w = _tracked_text_width(draw, name_label, name_font, tracking)
        # The authored box already sits on the banner. Right-side boxes keep the name's right edge.
        if left + box_w / 2 >= width / 2:
            name_x = left + box_w - inset - tracked_w
        else:
            name_x = left + inset - ink[0]
        name_y = top + (box_h - (ink[3] - ink[1])) // 2 - ink[1]
    elif stack != "split" and pill is not None:
        left, top, pill_w, pill_h = pill
        if stack == "name_above":
            name_y = top - clear - ink[3]
        else:
            name_y = top + pill_h + clear - ink[1]
        name_x = (left + pill_w - tracked_w) if right_name else left
    else:
        if banner is not None:
            band_top, band_h = banner[1], banner[3]
        elif avatar_corner.startswith("t"):
            band_top, band_h = 8, max(80, height // 8)
        else:
            band_h = max(80, height // 8)
            band_top = height - band_h - 8
        name_y = band_top + (band_h - (ink[3] - ink[1])) // 2 - ink[1]
        name_x = (width - pad - tracked_w) if right_name else pad
    _draw_tracked_text(
        draw,
        (name_x + name_dx, name_y + name_dy),
        name_label,
        name_font,
        tracking,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_w,
        stroke_fill=(*stroke_fill, 255),
    )

    if not title or pill is None:
        return
    left, top, pill_w, pill_h = pill
    inner_w = max(8, pill_w - pill_h)
    bio_size = max(
        _HUD_BIO_SIZE_MIN,
        min(int(pill_h * _HUD_BIO_SIZE_PILL_RATIO), int(width * _HUD_BIO_SIZE_WIDTH_RATIO)),
    )
    bio_font = _load_font(font_path, bio_size)
    while bio_size > _HUD_BIO_SIZE_FLOOR:
        bio_font = _load_font(font_path, bio_size)
        box = draw.textbbox((0, 0), title, font=bio_font)
        if box[2] - box[0] <= inner_w:
            break
        bio_size -= 1
    fitted = draw.textbbox((0, 0), title, font=bio_font)
    bio_label = title if fitted[2] - fitted[0] <= inner_w else _clip(title, bio_font, inner_w, draw)
    draw.text(
        (left + pill_w // 2 + bio_dx, top + pill_h // 2 + bio_dy),
        bio_label,
        font=bio_font,
        anchor="mm",
        fill=(255, 255, 255, 255),
    )


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
    *,
    repo_root: Path | None = None,
    layout_id: str = "",
    accent: tuple[int, int, int] | None = None,
) -> Image.Image:
    if frame is None:
        return _plain_rizcard(username, font_path, scale, avatar_art, banner_art, title, avatar_pos, ink)
    chrome = frame.copy()
    # Layouts 18 and 19 ship with a frosted plate. Keep that plate solid.
    if _is_layout(layout_id, "00018"):
        chrome = _opaque_plate(chrome, top=False)
    elif _is_layout(layout_id, "00019"):
        chrome = _opaque_plate(chrome, top=True)
    card_w, card_h = chrome.size
    # Layout 37 is the first special card (edge-filter arts + prefab nameplate).
    # Other specials wait for explicit per-layout instructions; normals just swap env→art.
    special_37 = _is_layout(layout_id, "00037")
    if special_37:
        canvas = _rizcard_layout_37(
            chrome,
            username=username,
            title=title,
            font_path=font_path,
            ink=ink,
            avatar_art=avatar_art,
            banner_art=banner_art,
            avatar_pos=avatar_pos,
            repo_root=repo_root,
            layout_id=layout_id,
            frame=frame,
        )
        if canvas is not None:
            return canvas
    # Normal layouts: colour art replaces the env *behind* the intact chrome.
    # Never punch the frame here — that was putting arts in front of the layout.
    art = _card_art(banner_art, card_w, card_h)
    art.putalpha(_card_silhouette(frame))
    canvas = Image.new("RGBA", chrome.size, (0, 0, 0, 0))
    canvas.alpha_composite(art)
    canvas.alpha_composite(chrome)
    corners = _standard_corner_hud(layout_id)
    if corners is not None:
        _stamp_standard_corner_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_corner=corners[0],
            text_corner=corners[1],
            accent=accent or (127, 212, 255),
            chrome=chrome,
        )
        return canvas
    notch = _notch_split_hud(layout_id)
    if notch is not None:
        _stamp_notch_split_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_corner=notch[0],
            name_corner=notch[1],
            bio_corner=notch[2],
            accent=accent or (127, 212, 255),
            chrome=chrome,
        )
        return canvas
    bands = _band_center_hud(layout_id)
    if bands is not None:
        _stamp_band_center_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_band=bands[0],
            text_band=bands[1],
            accent=accent or (127, 212, 255),
            chrome=chrome,
        )
        return canvas
    if _is_layout(layout_id, "00016"):
        _stamp_standard_corner_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_corner="bl",
            text_corner="br",
            accent=accent or (127, 212, 255),
            chrome=chrome,
            avatar_nudge=(_L16_AVATAR_X_NUDGE, _L16_AVATAR_Y_NUDGE),
            name_nudge=(_L16_NAME_X_NUDGE, _L16_NAME_Y_NUDGE),
            pillar_box=_solid_dark_capsule(chrome, "br"),
        )
        return canvas
    if _is_layout(layout_id, "00017"):
        _stamp_standard_corner_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_corner="tr",
            text_corner="tl",
            accent=accent or (127, 212, 255),
            chrome=chrome,
            avatar_nudge=(_L17_AVATAR_X_NUDGE, _L17_AVATAR_Y_NUDGE),
            name_nudge=(_L17_NAME_X_NUDGE, _L17_NAME_Y_NUDGE),
            name_below=True,
            pillar_box=_solid_dark_capsule(chrome, "tl"),
        )
        return canvas
    if _is_layout(layout_id, "00018"):
        _stamp_footer_stack_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            accent=accent or (127, 212, 255),
            chrome=chrome,
            bars=_plate_bars_18(chrome),
            avatar_extra=(_L18_AVATAR_X_NUDGE, _L18_AVATAR_Y_NUDGE),
            name_extra=(_L18_NAME_X_NUDGE, _L18_NAME_Y_NUDGE),
            lock_name_size=True,
            align_right=True,
        )
        return canvas
    if _is_layout(layout_id, "00019"):
        _stamp_footer_stack_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            accent=accent or (127, 212, 255),
            chrome=chrome,
            bars=_plate_bars_19(chrome),
            mirror=True,
            flip_y=True,
            avatar_extra=(_L19_AVATAR_X_NUDGE, _L19_AVATAR_Y_NUDGE),
            name_extra=(_L19_NAME_X_NUDGE, _L19_NAME_Y_NUDGE),
            lock_name_size=True,
        )
        return canvas
    wave = _wave_hud(layout_id)
    if wave is not None:
        number = layout_id.strip().rsplit(".", 1)[-1].zfill(5)
        _stamp_wave_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            avatar_corner=wave[0],
            name_side=wave[1],
            stack=wave[2],
            accent=accent or (127, 212, 255),
            chrome=chrome,
            nudge=_WAVE_NUDGE.get(number) or _WAVE_NUDGE.get(number.lstrip("0").zfill(5)),
            repo_root=repo_root,
            layout_id=layout_id,
        )
        return canvas
    if _footer_stack_hud(layout_id):
        _stamp_footer_stack_hud(
            canvas,
            username=username,
            title=title,
            font_path=font_path,
            avatar_art=avatar_art,
            avatar_pos=avatar_pos,
            accent=accent or (127, 212, 255),
            chrome=chrome,
        )
        return canvas
    pill = _title_pill(chrome)
    portrait = _portrait_slot(chrome)
    if pill is None:
        footer_top, footer_bottom = _footer_band(chrome.copy())
        title_span = max(8, footer_bottom - footer_top)
        # Flat placeholder panels make footer_band span the whole card; keep text tiny.
        max_span = max(24, card_h // 14)
        if title_span > max_span:
            title_span = max_span
            title_x = card_w // 2
            title_y = int(card_h * 0.92)
            pill_left, pill_right = card_w // 5, card_w - card_w // 5
        else:
            title_x = card_w // 2
            title_y = (footer_top + footer_bottom) // 2
            pill_left, pill_right = card_w // 5, card_w - card_w // 5
    else:
        title_x, title_y, title_span, pill_left, pill_right = pill
        title_span = min(title_span, max(24, card_h // 14))
    draw = ImageDraw.Draw(canvas)
    title_size = max(18, min(int(title_span * 0.55), card_h // 28))
    name_size = max(title_size + 8, min(int(title_span * 1.05), card_h // 22))
    _draw_username(
        draw,
        username,
        _load_font(font_path, name_size),
        card_w,
        *_name_anchor(card_w, title_x, title_y, title_span, pill_left, pill_right),
    )
    _cover_with_frame(canvas, chrome)
    _draw_title(draw, title, _load_font(font_path, title_size), title_x, title_y, pill_right - pill_left, ink)
    _place_portrait(canvas, avatar_art, avatar_pos, (portrait[0], portrait[1]), portrait[2], ring=True)
    return canvas


def _art_window_box(frame: Image.Image, chrome: Image.Image) -> tuple[int, int, int, int] | None:
    """Inner arts rectangle after punching a flat panel. None if the frame has no panel hole."""
    if chrome.size != frame.size:
        return None
    alpha = chrome.getchannel("A")
    width, height = alpha.size
    pixels = alpha.load()
    left, top, right, bottom = width, height, 0, 0
    found = False
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            if pixels[x, y] < 16:
                found = True
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    if not found or right - left < width * 0.2 or bottom - top < height * 0.2:
        return None
    return left, top, min(width, right + 2), min(height, bottom + 2)


def _clear_rect_alpha(image: Image.Image, left: int, top: int, right: int, bottom: int) -> Image.Image:
    """Make a rectangle fully transparent so art underneath can show."""
    out = image.copy()
    width = max(0, right - left)
    height = max(0, bottom - top)
    if width == 0 or height == 0:
        return out
    clear = Image.new("L", (width, height), 0)
    alpha = out.getchannel("A")
    alpha.paste(clear, (left, top))
    out.putalpha(alpha)
    return out


def _bw_card_art(banner_art: Image.Image | None, width: int, height: int) -> Image.Image:
    """Cover-fit illustration with layout 37's shaded line effect (00036Mat).

    Matches ``Custom/EdgeDetectionShader``: light luma wash via ``_Base``, then
    continuous Roberts edge ink (``_ColorScale`` / ``_Draw``) so soft edges stay
    grey instead of hard black/white.
    """
    if banner_art is None:
        return Image.new("RGBA", (width, height), (255, 255, 255, 255))
    covered = _cover(banner_art, width, height).convert("RGB")
    lines = _layout_37_line_art(covered)
    return Image.merge("RGBA", (lines, lines, lines, Image.new("L", (width, height), 255)))


def _layout_37_line_art(
    rgb: Image.Image,
    *,
    sample_size: float = 1.0,
    color_scale: float = 1.5,
    base: float = 0.1,
    draw: float = 1.0,
    color_offset: float = 0.0,
) -> Image.Image:
    """Match Unity ``Custom/EdgeDetectionShader`` (material ``00036Mat``).

    Roberts-style luma edges over a light grey wash:
    ``shade = lerp(1, luma, _Base)``, ``out = lerp(shade, Image.color, ink)``
    with continuous ``ink`` (soft edges stay grey, not binary B/W).
    """
    width, height = rgb.size
    luma = rgb.convert("L")
    # Shader UV step is ``_SampleSize / 512``; map that to pixels on this bitmap.
    dx = max(1, int(round(float(sample_size) / 512.0 * width)))
    dy = max(1, int(round(float(sample_size) / 512.0 * height)))
    right = _shift_clamp(luma, dx, 0)
    up = _shift_clamp(luma, 0, dy)
    diag = _shift_clamp(luma, dx, dy)
    # edge ≈ |c - ru| + |r - u|  (Roberts cross; continuous 0–255)
    edge = ImageChops.add(
        ImageChops.difference(luma, diag),
        ImageChops.difference(right, up),
        scale=1.0,
        offset=0,
    )
    # ink = (1 - saturate(1 + ColorOffset - edge * ColorScale)) * Draw
    scale_u8 = max(1, int(round(color_scale * 256)))
    offset_u8 = int(round(color_offset * 255))
    draw_u8 = max(0, min(256, int(round(draw * 256))))

    def _ink(value: int) -> int:
        # edge is 0–255; treat as 0–1 then * ColorScale
        strength = (value * scale_u8) // 256
        # saturate(1 + offset - strength) → ink = 1 - that
        paper = 255 + offset_u8 - strength
        if paper < 0:
            paper = 0
        elif paper > 255:
            paper = 255
        ink = 255 - paper
        return (ink * draw_u8) // 256 if draw_u8 != 256 else ink

    ink = edge.point(_ink)
    # shade = (1 - Base) + Base * luma  → mostly white with soft grey from the art
    base_u8 = max(0, min(255, int(round(base * 255))))
    if base_u8 == 0:
        shade = Image.new("L", (width, height), 255)
    else:
        shade = luma.point(lambda value, b=base_u8: 255 - ((255 - value) * b) // 255)
    # lerp(shade, black, ink) = shade * (1 - ink)
    return ImageChops.multiply(shade, ImageChops.invert(ink))


def _shift_clamp(image: Image.Image, dx: int, dy: int) -> Image.Image:
    """Translate ``image`` by ``(dx, dy)`` pixels, clamping at the edges."""
    if dx == 0 and dy == 0:
        return image
    width, height = image.size
    # AFFINE sample from (x - dx, y - dy); clamp via a padded edge-replicate canvas.
    pad_x, pad_y = abs(dx), abs(dy)
    padded = Image.new(image.mode, (width + pad_x * 2, height + pad_y * 2))
    padded.paste(image, (pad_x, pad_y))
    if pad_x:
        left = image.crop((0, 0, 1, height))
        right = image.crop((width - 1, 0, width, height))
        for i in range(pad_x):
            padded.paste(left, (i, pad_y))
            padded.paste(right, (pad_x + width + i, pad_y))
    if pad_y:
        top = padded.crop((0, pad_y, width + pad_x * 2, pad_y + 1))
        bottom = padded.crop((0, pad_y + height - 1, width + pad_x * 2, pad_y + height))
        for i in range(pad_y):
            padded.paste(top, (0, i))
            padded.paste(bottom, (0, pad_y + height + i))
    return padded.crop((pad_x - dx, pad_y - dy, pad_x - dx + width, pad_y - dy + height))


def _rizcard_prefab_slots(
    repo_root: Path,
    layout_id: str,
    card_size: tuple[int, int],
) -> dict[str, tuple[int, int, int, int]] | None:
    """Avatar/Name/Bio boxes from the layout prefab, in pillow y-down pixels."""
    try:
        from bot.ui.layout_card import _pointer, _prefab_bundle, _prefab_dependencies
        import UnityPy
    except ImportError:
        return None
    bundle = _prefab_bundle(repo_root, layout_id)
    if bundle is None or not bundle.is_file():
        return None
    try:
        env = UnityPy.Environment()
        env.load_file(str(bundle))
        for path in _prefab_dependencies(repo_root, layout_id):
            try:
                env.load_file(str(path))
            except Exception:
                continue
    except Exception:
        return None
    names: dict[int, str] = {}
    go_rects: dict[int, dict] = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                names[obj.path_id] = str(obj.read().m_Name)
            except Exception:
                continue
        elif obj.type.name == "RectTransform":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            go = _pointer(tree.get("m_GameObject"))
            if go is not None:
                go_rects[go] = tree
    design_w, design_h = 1488.0, 2078.0
    scale_x = card_size[0] / design_w
    scale_y = card_size[1] / design_h
    found: dict[str, tuple[int, int, int, int]] = {}
    for go, name in names.items():
        key = name.strip().lower()
        if key not in {"avatar", "name", "bio", "covermask", "bg"}:
            continue
        rect = go_rects.get(go)
        if not isinstance(rect, dict):
            continue
        anchor_min = rect.get("m_AnchorMin") if isinstance(rect.get("m_AnchorMin"), dict) else {}
        anchor_max = rect.get("m_AnchorMax") if isinstance(rect.get("m_AnchorMax"), dict) else {}
        pos = rect.get("m_AnchoredPosition") if isinstance(rect.get("m_AnchoredPosition"), dict) else {}
        size = rect.get("m_SizeDelta") if isinstance(rect.get("m_SizeDelta"), dict) else {}
        try:
            width = float(size.get("x") or 0) * scale_x
            height = float(size.get("y") or 0) * scale_y
        except (TypeError, ValueError):
            continue
        if width < 8 or height < 8:
            continue
        # Centered art windows (CoverMask / BG).
        if key in {"covermask", "bg"}:
            left = (card_size[0] - width) / 2 + float(pos.get("x") or 0) * scale_x
            top = (card_size[1] - height) / 2 - float(pos.get("y") or 0) * scale_y
            box = (int(round(left)), int(round(top)), int(round(width)), int(round(height)))
            # Prefer the narrower CoverMask over the full BG square.
            if "art" not in found or key == "covermask":
                found["art"] = box
            continue
        # Player HUD sits on the bottom-left anchor. Skip centered stub nodes.
        if float(anchor_min.get("x") or 0) > 0.05 or float(anchor_min.get("y") or 0) > 0.05:
            continue
        if float(anchor_max.get("x") or 0) > 0.05 or float(anchor_max.get("y") or 0) > 0.05:
            if float(anchor_min.get("x") or 0) >= 0.45:
                continue
        try:
            left = float(pos.get("x") or 0) * scale_x
            bottom = float(pos.get("y") or 0) * scale_y
        except (TypeError, ValueError):
            continue
        top = card_size[1] - bottom - height
        box = (int(round(left)), int(round(top)), int(round(width)), int(round(height)))
        previous = found.get(key)
        if previous is None or box[2] * box[3] > previous[2] * previous[3]:
            found[key] = box
    if "avatar" in found and "name" in found:
        return found
    return None


def _stamp_rizcard_nameplate(
    canvas: Image.Image,
    *,
    username: str,
    title: str,
    font_path: Path,
    ink: tuple[int, int, int],
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    slots: dict[str, tuple[int, int, int, int]],
    frame: Image.Image | None = None,
) -> None:
    """Draw avatar + username + bio using prefab boxes (matches in-game layout 37)."""
    del ink
    avatar_box = slots.get("avatar")
    if avatar_box is not None:
        left, top, width, height = avatar_box
        side = max(8, min(width, height))
        _place_square_portrait(canvas, avatar_art, avatar_pos, (left, top), side)
    draw = ImageDraw.Draw(canvas)
    name_box = slots.get("name")
    bio_box = slots.get("bio")
    name_left = name_box[0] if name_box is not None else (avatar_box[0] + avatar_box[2] + 16 if avatar_box else 24)
    name_width = name_box[2] if name_box is not None else max(64, canvas.width // 2)
    # Sit under the grey tile bar: align with the avatar tile, never over the art window.
    if avatar_box is not None:
        name_top = avatar_box[1]
    elif name_box is not None:
        name_top = name_box[1]
    else:
        name_top = canvas.height - canvas.height // 8
    tile_bottom = _nameplate_tile_bottom(frame, name_top) if frame is not None else None
    if tile_bottom is not None:
        name_top = max(name_top, tile_bottom + 8)
    name_size = max(26, min(48, (name_box[3] if name_box is not None else 56) // 2))
    name_font = _load_font(font_path, name_size)
    name_label = _clip(username or "Player", name_font, max(8, name_width - 8), draw)
    name_cy = name_top + name_size // 2
    draw.text(
        (name_left, name_cy),
        name_label,
        font=name_font,
        anchor="lm",
        fill=(28, 28, 32, 255),
    )
    if title:
        bio_left = bio_box[0] if bio_box is not None else name_left
        bio_width = bio_box[2] if bio_box is not None else name_width
        bio_size = 26
        # Always stack under the drawn name so tile-bar shifts can't overlap them.
        name_bottom = name_cy + name_size // 2
        bio_top = name_bottom + 16
        bio_font = _load_font(font_path, bio_size)
        bio_label = _clip(title, bio_font, max(8, bio_width - 8), draw)
        draw.text(
            (bio_left, bio_top + bio_size // 2),
            bio_label,
            font=bio_font,
            anchor="lm",
            fill=(198, 198, 202, 255),
        )


def _place_square_portrait(
    canvas: Image.Image,
    avatar_art: Image.Image | None,
    avatar_pos: dict,
    origin: tuple[int, int],
    side: int,
) -> None:
    """Square avatar tile (layout 37), not a circular disk."""
    if avatar_art is None:
        tile = Image.new("RGBA", (side, side), (245, 245, 245, 255))
    else:
        try:
            zoom = float(avatar_pos.get("z") or 1.0)
        except (TypeError, ValueError):
            zoom = 1.0
        if not math.isfinite(zoom) or zoom <= 0:
            zoom = 1.0
        try:
            saved_x = float(avatar_pos.get("x") if avatar_pos.get("x") is not None else 0.5)
        except (TypeError, ValueError):
            saved_x = 0.5
        try:
            saved_y = float(avatar_pos.get("y") if avatar_pos.get("y") is not None else 0.5)
        except (TypeError, ValueError):
            saved_y = 0.5
        if not math.isfinite(saved_x):
            saved_x = 0.5
        if not math.isfinite(saved_y):
            saved_y = 0.5
        width_px = float(avatar_art.width)
        height_px = float(avatar_art.height)
        window = min(width_px, height_px, max(1.0, min(width_px, height_px) / zoom))
        left = (1.0 - saved_x) * (width_px - window)
        top = saved_y * (height_px - window)
        left = min(max(0.0, left), max(0.0, width_px - window))
        top = min(max(0.0, top), max(0.0, height_px - window))
        crop = avatar_art.crop((int(left), int(top), int(left + window), int(top + window)))
        tile = crop.resize((side, side), Image.Resampling.LANCZOS).convert("RGBA")
    canvas.alpha_composite(tile, origin)


def _nameplate_tile_bottom(frame: Image.Image, below_limit: int) -> int | None:
    """Bottom edge of the light-grey tile bar above the avatar/nameplate."""
    width, height = frame.size
    pixels = frame.load()
    limit = min(below_limit - 1, height - 1)
    start = max(int(height * 0.72), 0)
    last = None
    for y in range(limit, start, -1):
        run = 0
        for x in range(0, width // 2):
            red, green, blue, alpha = pixels[x, y]
            luma = (red + green + blue) / 3
            if alpha > 200 and 175 <= luma <= 235 and abs(red - green) < 14 and abs(green - blue) < 14:
                run += 1
                if run >= 80:
                    last = y
                    break
            else:
                run = 0
        if last is not None and run < 80:
            return last
    return last


def _punch_flat_art_panel(frame: Image.Image, *, tolerance: int = 22) -> Image.Image:
    """Clear a flat grey/white arts window so the illustration can show through."""
    width, height = frame.size
    cx, cy = width // 2, height // 3
    red, green, blue, alpha = frame.getpixel((cx, cy))
    if alpha < 16:
        return frame.copy()
    chroma = max(red, green, blue) - min(red, green, blue)
    luma = (red + green + blue) / 3
    if chroma >= 14 or not (40 <= luma <= 255):
        return frame.copy()
    seed_rgb = Image.new("RGB", (width, height), (red, green, blue))
    diff = ImageChops.difference(frame.convert("RGB"), seed_rgb).convert("L")
    candidates = ImageChops.multiply(
        diff.point(lambda value: 255 if value <= tolerance else 0),
        frame.getchannel("A").point(lambda value: 255 if value > 8 else 0),
    )
    if candidates.getpixel((cx, cy)) != 255:
        return frame.copy()
    ImageDraw.floodfill(candidates, (cx, cy), 128, thresh=0)
    hole = candidates.point(lambda value: 255 if value == 128 else 0)
    samples = max(1, ((width + 11) // 12) * ((height + 11) // 12))
    hole_ratio = sum(hole.getpixel((x, y)) for y in range(0, height, 12) for x in range(0, width, 12)) / (255 * samples)
    if hole_ratio < 0.08:
        return frame.copy()
    channels = list(frame.split())
    channels[3] = ImageChops.subtract(channels[3], hole)
    return Image.merge("RGBA", channels)


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
    framed = Image.new("RGBA", (diameter + band * 2, diameter + band * 2), (255, 255, 255, 255))
    framed.putalpha(_aa_ellipse_mask(framed.width))
    framed.paste(avatar, (band, band), avatar)
    canvas.alpha_composite(framed, (center[0] - framed.width // 2, center[1] - framed.height // 2))


def _read_layout_frame(repo_root: Path, layout_id: str) -> Image.Image | None:
    image = _read_bundle_texture(repo_root, layout_id if layout_id.strip().startswith("layout.") else f"layout.{layout_id.strip()}")
    if image is None:
        return None
    return _crop_side_margins(image)


def _read_bundle_texture(repo_root: Path, asset_id: str) -> Image.Image | None:
    stem = asset_id.strip()
    if not stem:
        return None
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
    return best.convert("RGBA")


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
    chrome = alpha.point(lambda value: 255 if value >= 16 else 0)
    bbox = chrome.getbbox()
    # Only seed the top-left: bottom-corner floods open the art window on layouts 1/11.
    exterior = chrome.copy()
    if exterior.getpixel((0, 0)) == 0:
        ImageDraw.floodfill(exterior, (0, 0), 64, thresh=0)
    silhouette = exterior.point(lambda value: 0 if value == 64 else 255)
    # Open frames (12/29): art window connects to the canvas edge, so flood-fill
    # marks the center as exterior. Fall back to the chrome bounding box.
    cx, cy = width // 2, height // 2
    if (
        bbox is not None
        and silhouette.getpixel((cx, cy)) == 0
        and bbox[0] <= cx < bbox[2]
        and bbox[1] <= cy < bbox[3]
    ):
        filled = Image.new("L", (width, height), 0)
        filled.paste(255, bbox)
        return filled
    return silhouette


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


def _aa_mask(size: tuple[int, int], paint) -> Image.Image:
    """Supersample a coverage mask so circles and pills stay smooth when zoomed."""
    width, height = size
    big = Image.new("L", (max(1, width * _AA), max(1, height * _AA)), 0)
    paint(ImageDraw.Draw(big), _AA)
    return big.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)


def _aa_ellipse_mask(size: int) -> Image.Image:
    cached = _ELLIPSE_MASKS.get(size)
    if cached is not None:
        return cached.copy()

    def paint(pen: ImageDraw.ImageDraw, factor: int) -> None:
        edge = max(1, size * factor) - 1
        pen.ellipse((0, 0, edge, edge), fill=255)

    mask = _aa_mask((size, size), paint)
    _ELLIPSE_MASKS[size] = mask
    return mask.copy()


def _aa_round_mask(width: int, height: int, radius: int) -> Image.Image:
    key = (width, height, radius)
    cached = _ROUND_MASKS.get(key)
    if cached is not None:
        return cached.copy()

    def paint(pen: ImageDraw.ImageDraw, factor: int) -> None:
        pen.rounded_rectangle(
            (0, 0, max(1, width * factor) - 1, max(1, height * factor) - 1),
            radius=max(1, radius * factor),
            fill=255,
        )

    mask = _aa_mask((width, height), paint)
    _ROUND_MASKS[key] = mask
    return mask.copy()


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
    # Match index.html: .user-wrapper (blue) > .user-rks (pill) > .user-avatar.
    # Avatar is the same diameter as the pill height; the blue stroke lives on an
    # outer canvas so the circle is never flush-clipped against the page.
    inner_w, inner_h = _px(scale, 680), _px(scale, 118)
    blue = max(2, _px(scale, 3))
    width, height = inner_w + blue * 2, inner_h + blue * 2
    bg1, bg2, ink = colors
    body = Image.new("RGBA", (inner_w, inner_h), (255, 255, 255, 255))
    band_h = int(inner_h * 0.64)
    body.paste(_horizontal_gradient(inner_w, inner_h - band_h, bg1, bg2), (0, band_h))
    draw = ImageDraw.Draw(body)
    number = f"{total_rks:.4f}"
    number_w = int(draw.textlength(number, font=fonts["rks_big"]))
    rks_x = inner_w - _px(scale, 28) - number_w
    mark = "RKS"
    mark_box = fonts["watermark"].getbbox(mark)
    mark_h = max(1, mark_box[3] - mark_box[1])
    mark_w = int(draw.textlength(mark, font=fonts["watermark"]))
    mark_x = rks_x + number_w - mark_w + _px(scale, 6)
    mark_y = int(band_h - mark_h / 8 - mark_box[1])
    # Page color is the layout ink at #80, then CSS opacity 0.7. Draw on a
    # clear layer and composite it, or the pill mask later turns the white solid.
    ghost = Image.new("RGBA", (inner_w, inner_h), (0, 0, 0, 0))
    ImageDraw.Draw(ghost).text(
        (mark_x, mark_y),
        mark,
        font=fonts["watermark"],
        fill=(*ink, 90),
    )
    body.alpha_composite(ghost)
    band = _name_band(banner_art, inner_w - _px(scale, 70), band_h)
    body.paste(band, (_px(scale, 70), 0))
    name = _clip(username, fonts["name"], inner_w - _px(scale, 250), draw)
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

    mask = _aa_round_mask(inner_w, inner_h, inner_h // 2)
    body.putalpha(mask)

    # .user-avatar: 115×115, border 4px white, box-sizing border-box.
    # CSS margin-left:-4px aligns the circle with the pill's left edge; we place
    # it at the body origin (x=blue on the outer canvas) so nothing is clipped.
    white = max(2, _px(scale, 4))
    avatar_size = max(1, inner_h - white * 2)
    avatar = _avatar(avatar_art, avatar_size, avatar_pos)
    framed = Image.new("RGBA", (inner_h, inner_h), (255, 255, 255, 255))
    framed.putalpha(_aa_ellipse_mask(inner_h))
    framed.paste(avatar, (white, white), avatar)

    header = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    header.alpha_composite(body, (blue, blue))
    # Blue stroke as an outer ring only — a width>1 outline would paint over the
    # avatar's left edge and look like a clipped circle.
    outer = _aa_round_mask(width, height, height // 2)
    hole = Image.new("L", (width, height), 0)
    hole.paste(_aa_round_mask(inner_w, inner_h, max(1, inner_h // 2)), (blue, blue))
    ring = Image.new("RGBA", (width, height), (0, 178, 236, 255))
    ring.putalpha(ImageChops.subtract(outer, hole))
    header.alpha_composite(ring)
    # CSS .user-avatar { margin-left: -4px } pulls the circle into the border.
    # Keep x >= 0 so Pillow does not clip (unlike CSS overflow). Draw avatar
    # after the ring so the left arc stays visible over the blue stroke.
    nudge = min(blue, white)
    header.alpha_composite(framed, (blue - nudge, blue))
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
        # Cover-fit, then zoom. The saved point slides the window through the
        # leftover pan range: x=0 shows the right edge, x=1 the left, y=0 the top.
        width_px = float(artwork.width)
        height_px = float(artwork.height)
        window = min(width_px, height_px, max(1.0, min(width_px, height_px) / zoom))
        left = (1.0 - saved_x) * (width_px - window)
        top = saved_y * (height_px - window)
        left = min(max(0.0, left), max(0.0, width_px - window))
        top = min(max(0.0, top), max(0.0, height_px - window))
        crop = artwork.crop((int(left), int(top), int(left + window), int(top + window)))
        source = crop.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    mask = _aa_ellipse_mask(size)
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
    panel = Image.new("RGBA", size, (255, 255, 255, 214))
    panel.putalpha(_aa_round_mask(card_w, card_h, radius).point(lambda value: value * 214 // 255))
    card.alpha_composite(panel)

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
        # Chart circles are ~170px; low jackets decode much faster than HiRes.
        path = illustration_path(song, illust_hires_dir, illust_dir, prefer_low=True)
    source = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    if path is not None:
        try:
            with Image.open(path) as opened:
                source = opened.convert("RGBA")
        except (OSError, ValueError):
            source = Image.new("RGBA", (size, size), (208, 208, 208, 255))
    fitted = _cover_square(source, size)
    fitted.putalpha(_aa_ellipse_mask(size))
    return fitted


def _cover_square(image: Image.Image, size: int) -> Image.Image:
    width, height = image.size
    if width < 1 or height < 1:
        return Image.new("RGBA", (size, size), (208, 208, 208, 255))
    scale = max(size / width, size / height)
    resized = image.resize(
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - size) // 2)
    top = max(0, (resized.height - size) // 2)
    return resized.crop((left, top, left + size, top + size)).convert("RGBA")


def _clip(text: str, font: ImageFont.ImageFont, width: int, draw: ImageDraw.ImageDraw) -> str:
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if width <= 0 or draw.textlength(text, font=font) <= width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"
