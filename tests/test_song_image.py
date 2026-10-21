import io
from dataclasses import replace
from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, Song
from bot.ui.song_image import MAX_PNG_BYTES, _HEADER_H, _PAD, _draw, render_song


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"


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


def test_song_png_shrinks_when_the_cap_is_tiny(tmp_path: Path):
    song = _song(1)
    tiny = _render(song, tmp_path, max_bytes=1)
    full = _render(song, tmp_path)
    assert tiny.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(tiny) < len(full)
