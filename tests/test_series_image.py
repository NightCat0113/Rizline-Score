import io
from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, SeriesVolume, Song, TrackSeries
from bot.ui.series_image import render_series


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"
BANNER = (200, 20, 20)
POSTER = (20, 20, 200)
JACKET = (12, 90, 40)
EZ = (87, 228, 196)


def _series() -> TrackSeries:
    return TrackSeries(
        series_index=12,
        name="Phigros",
        volumes=(
            SeriesVolume(
                "",
                "",
                ("SpeedUp.DarTokki.0",),
            ),
        ),
    )


def _song() -> Song:
    return Song(
        asset_id="SpeedUp.DarTokki.0",
        title="Speed Up",
        artist="DarTokki",
        disc_name="Disc",
        illustration_id="illustration.SpeedUp.DarTokki.0",
        charts={"EZ": ChartInfo("EZ", 1, 10, 10, 1000, 1, "Charter"), "IN": ChartInfo("IN", 12.4, 10, 10, 1000, 1, "Charter")},
    )


def _render(poster: Image.Image | None) -> bytes:
    banner = Image.new("RGB", (160, 28), BANNER)
    return render_series(
        series=_series(),
        songs={"SpeedUp.DarTokki.0": _song()},
        tag="",
        banner=banner,
        poster=poster,
        font_path=FONT,
    )


def _has_color(image: Image.Image, color: tuple[int, int, int]) -> bool:
    pixels = image.convert("RGB").load()
    for x in range(image.width):
        for y in range(image.height):
            if pixels[x, y] == color:
                return True
    return False


def test_series_png_keeps_its_height_and_drops_the_poster_column():
    poster = Image.new("RGB", (20, 40), POSTER)
    first = _render(poster)
    second = _render(poster)
    plain = _render(None)
    assert first == second
    with Image.open(io.BytesIO(first)) as marked, Image.open(io.BytesIO(plain)) as bare:
        assert marked.size[0] == bare.size[0]
        assert marked.size[1] > bare.size[1]
        assert _has_color(marked, BANNER)
        assert _has_color(marked, POSTER)
        assert not _has_color(bare, POSTER)
        assert _has_color(bare, BANNER)
        banner_box = _color_box(marked, BANNER)
        poster_box = _color_box(marked, POSTER)
        mid = (banner_box[1] + banner_box[3]) // 2
        banner_row = _row_extent(marked, BANNER, mid)
        poster_row = _row_extent(marked, POSTER, mid)
        assert banner_row[1] < poster_row[0]
        assert abs((banner_row[1] + 1) - poster_row[0]) <= 2
        assert abs(banner_box[3] - poster_box[3]) <= 2
        pixels = marked.convert("RGB").load()
        assert pixels[banner_box[0], banner_box[1]] != BANNER


def test_song_row_uses_the_jacket_and_difficulty_color(tmp_path: Path):
    hires = tmp_path / "hires"
    low = tmp_path / "low"
    hires.mkdir()
    low.mkdir()
    Image.new("RGB", (32, 32), JACKET).save(hires / "illustration.SpeedUp.DarTokki.0.HiRes.png")
    poster = Image.new("RGB", (20, 40), POSTER)
    png = render_series(
        series=_series(),
        songs={"SpeedUp.DarTokki.0": _song()},
        tag="",
        banner=Image.new("RGB", (160, 28), BANNER),
        poster=poster,
        font_path=FONT,
        illust_hires_dir=hires,
        illust_dir=low,
    )
    with Image.open(io.BytesIO(png)) as image:
        assert image.size[0] == 1960
        assert _has_color(image, JACKET)
        assert _has_color(image, EZ)


def test_a_title_with_a_line_break_still_renders():
    series = TrackSeries(
        series_index=7,
        name="KALPA",
        volumes=(SeriesVolume("VOL. 1", "", ("Planetarium.0", "Short.0")),),
    )
    songs = {
        "Planetarium.0": Song(
            "Planetarium.0",
            "너를 그리는 밤하늘의 이야기\n(Planetarium) prod. Scarlette",
            "kuripurin",
            "Disc",
            "illustration.Planetarium.0",
            charts={"EZ": ChartInfo("EZ", 1, 1, 1, 1, 1, "Charter")},
        ),
        "Short.0": Song(
            "Short.0",
            "A",
            "Scarlette",
            "Disc",
            "illustration.Short.0",
            charts={"EZ": ChartInfo("EZ", 1, 1, 1, 1, 1, "Charter"), "IN": ChartInfo("IN", 12, 1, 1, 1, 1, "Charter")},
        ),
    }
    png = render_series(
        series=series,
        songs=songs,
        tag="",
        banner=Image.new("RGB", (160, 28), BANNER),
        poster=Image.new("RGB", (20, 40), POSTER),
        font_path=FONT,
    )
    assert png.startswith(b"\x89PNG")


def _color_box(image: Image.Image, color: tuple[int, int, int]) -> tuple[int, int, int, int]:
    pixels = image.convert("RGB").load()
    min_x = min_y = 10**9
    max_x = max_y = -1
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y] != color:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    assert max_x >= 0
    return min_x, min_y, max_x, max_y


def _row_extent(image: Image.Image, color: tuple[int, int, int], y: int) -> tuple[int, int]:
    pixels = image.convert("RGB").load()
    found = [x for x in range(image.width) if pixels[x, y] == color]
    assert found
    return found[0], found[-1]
