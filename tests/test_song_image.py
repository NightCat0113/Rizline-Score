import io
from dataclasses import replace
from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, Song
from bot.ui.song_image import (
    MAX_PNG_BYTES,
    _BORDER_DEFAULT,
    _FACT_LABEL,
    _HEADER_H,
    _INK,
    _PAD,
    _draw,
    _theme_color,
    render_song,
)


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"
# The hybrid card font is gitignored; CI falls back to Pillow's default face and
# text metrics drift. Layout probes below search regions instead of fixed pixels.


def _clip_box(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return (
        max(0, left),
        max(0, top),
        min(image.width, right),
        min(image.height, bottom),
    )


def _count_near_white(image: Image.Image, box: tuple[int, int, int, int], *, floor: int = 248) -> int:
    left, top, right, bottom = _clip_box(image, box)
    pixels = image.load()
    return sum(
        1
        for y in range(top, bottom)
        for x in range(left, right)
        if pixels[x, y][0] >= floor and pixels[x, y][1] >= floor and pixels[x, y][2] >= floor
    )


def _has_dark_ink(image: Image.Image, box: tuple[int, int, int, int], *, ceiling: int = 80) -> bool:
    left, top, right, bottom = _clip_box(image, box)
    pixels = image.load()
    return any(
        pixels[x, y][0] < ceiling and pixels[x, y][1] < ceiling and pixels[x, y][2] < ceiling
        for y in range(top, bottom)
        for x in range(left, right)
    )


def _region_has_rgb(
    image: Image.Image,
    box: tuple[int, int, int, int],
    rgb: tuple[int, int, int],
    *,
    tolerance: int = 0,
) -> bool:
    left, top, right, bottom = _clip_box(image, box)
    pixels = image.load()
    return any(
        all(abs(pixels[x, y][i] - rgb[i]) <= tolerance for i in range(3))
        for y in range(top, bottom)
        for x in range(left, right)
    )


def _song(chart_count: int, illustration_id: str = "illustration.missing") -> Song:
    names = ("EZ", "HD", "IN", "AT")
    charts = {
        name: ChartInfo(name, 10 + index, 1000, 800, 1_010_000 + index, 100, "NerSAN")
        for index, name in enumerate(names[:chart_count])
    }
    return Song(
        asset_id="Song.A.0",
        title="Alpha",
        artist="Artist",
        disc_name="Disc 1",
        illustration_id=illustration_id,
        charts=charts,
        bpm=150,
        illustrator="山山奇",
        series_index=12,
    )


def _render(song: Song, tmp_path: Path, **kwargs) -> bytes:
    return render_song(
        song=song,
        personal=kwargs.get("personal"),
        highlight=kwargs.get("highlight"),
        illust_hires_dir=tmp_path / "hires",
        illust_dir=tmp_path / "illust",
        font_path=FONT,
        max_bytes=kwargs.get("max_bytes", MAX_PNG_BYTES),
    )


def test_song_png_grows_with_charts(tmp_path: Path):
    one = _render(_song(1), tmp_path)
    three = _render(_song(3), tmp_path)
    assert one.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(three) < MAX_PNG_BYTES
    with Image.open(io.BytesIO(one)) as image, Image.open(io.BytesIO(three)) as taller:
        assert image.format == "PNG"
        assert image.size[0] >= 1960
        assert taller.size[1] > image.size[1]


def test_song_png_with_and_without_a_score_differ(tmp_path: Path):
    song = _song(2)
    blank = _render(song, tmp_path)
    played = _render(
        song,
        tmp_path,
        personal={"HD": {"score": 1_009_000, "completeRate": 98.5, "isClear": True, "rks": 120.25}},
        highlight="HD",
    )
    assert blank != played


def _grey_separator(image: Image.Image, *, bottom: int) -> tuple[int, int, int] | None:
    pixels = image.load()
    best: tuple[int, int, int] | None = None
    for x in range(image.width):
        run = 0
        start = 0
        longest = 0
        long_start = 0
        for y in range(bottom):
            red, green, blue, alpha = pixels[x, y]
            grey = abs(red - 170) < 8 and abs(green - 170) < 8 and abs(blue - 176) < 12 and alpha > 200
            if grey:
                if run == 0:
                    start = y
                run += 1
                if run > longest:
                    longest = run
                    long_start = start
            else:
                run = 0
        if longest >= 20 and (best is None or longest > best[0]):
            best = (longest, x, long_start)
    return best


def test_aliases_sit_beside_the_detail_stack() -> None:
    plain_song = _song(1)
    aliased = replace(plain_song, aliases=("bamboo",))
    plain = _draw(song=plain_song, personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    marked = _draw(song=aliased, personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    assert plain.size == marked.size
    header_bottom = _PAD + _HEADER_H
    assert _grey_separator(plain, bottom=header_bottom) is None
    found = _grey_separator(marked, bottom=header_bottom)
    assert found is not None
    _length, column, top = found
    plain_pixels = plain.load()
    marked_pixels = marked.load()
    darker = False
    for y in range(top, top + found[0]):
        for x in range(column + 4, min(marked.width, column + 80)):
            red, green, blue, _alpha = marked_pixels[x, y]
            other = plain_pixels[x, y]
            if red < 80 and (red, green, blue) != other[:3]:
                darker = True
                break
        if darker:
            break
    assert darker


def test_original_badge_sits_at_the_bottom_centre_of_the_jacket() -> None:
    plain_song = _song(1)
    marked = replace(plain_song, original="Rizline Original")
    plain = _draw(song=plain_song, personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    badged = _draw(song=marked, personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    assert plain.size == badged.size
    # Jacket circle sits near the left header; the white original pill hangs on its bottom edge.
    jacket_bottom = (40, 175, 210, 220)
    assert _count_near_white(badged, jacket_bottom) > _count_near_white(plain, jacket_bottom) + 40
    assert _has_dark_ink(badged, jacket_bottom)


def test_collaboration_badge_renders_its_second_line() -> None:
    song = replace(_song(1), original="Collaboration Original", original_with="Paradigm: Reboot")
    image = _draw(song=song, personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    # Two-line collaboration pill is taller, so search a slightly deeper jacket-bottom box.
    badge_box = (30, 165, 230, 230)
    assert _count_near_white(image, badge_box) > 80
    assert _has_dark_ink(image, badge_box)


def test_chart_details_have_grey_labels_and_black_values() -> None:
    image = _draw(song=_song(1), personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    # First chart row's right-hand details (labels grey, values black). Widen the
    # scan and allow a small RGB tolerance so Pillow's default face (CI, no
    # checked-in TTF) still matches after antialiasing.
    box = (520, _PAD + _HEADER_H + 4, image.width, _PAD + _HEADER_H + 4 + 140)
    assert _region_has_rgb(image, box, _FACT_LABEL, tolerance=4)
    assert _region_has_rgb(image, box, _INK, tolerance=12)


def test_header_details_are_all_grey() -> None:
    image = _draw(song=_song(1), personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    # Header detail lines (BPM/length, illustrator, disc, track series),
    # to the right of the jacket circle and below the title/artist.
    # Start below the title/artist so black title ink is outside the probe.
    box = (230, 135, 900, _PAD + _HEADER_H)
    assert _region_has_rgb(image, box, _FACT_LABEL, tolerance=4)
    assert not _region_has_rgb(image, box, _INK)


def test_theme_color_follows_the_illustration() -> None:
    red_art = Image.new("RGB", (120, 120), (205, 38, 48))
    red, green, blue = _theme_color(red_art)
    assert red > 120 and red > green + 60 and red > blue + 40
    blue_art = Image.new("RGB", (120, 120), (36, 84, 196))
    red, green, blue = _theme_color(blue_art)
    assert blue > 120 and blue > red + 40
    pale_art = Image.new("RGB", (120, 120), (238, 232, 220))
    red, green, blue = _theme_color(pale_art)
    assert max(red, green, blue) - min(red, green, blue) >= 40
    assert _theme_color(None) == _BORDER_DEFAULT


def test_header_border_uses_the_theme_color() -> None:
    artwork = Image.new("RGB", (200, 200), (205, 38, 48))
    themed = _draw(song=_song(1), personal={}, highlight=None, artwork=artwork, font_path=FONT, scale=1.0)
    plain = _draw(song=_song(1), personal={}, highlight=None, artwork=None, font_path=FONT, scale=1.0)
    themed_pixel = themed.load()[500, _PAD + 1][:3]
    plain_pixel = plain.load()[500, _PAD + 1][:3]
    assert themed_pixel[0] > themed_pixel[1] + 60
    assert plain_pixel == _BORDER_DEFAULT


def test_song_png_shrinks_when_the_cap_is_tiny(tmp_path: Path):
    song = _song(1)
    tiny = _render(song, tmp_path, max_bytes=1)
    full = _render(song, tmp_path)
    assert tiny.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(tiny) < len(full)
