import io
from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, Song
from bot.services.songdata import SongIndex
from bot.ui.b40_image import MAX_PNG_BYTES, render_b40


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"


def _song(asset_id: str, title: str, score: int) -> Song:
    return Song(
        asset_id=asset_id,
        title=title,
        artist="",
        disc_name="",
        illustration_id=f"illustration.{asset_id}",
        charts={"IN": ChartInfo("IN", 12.5, 1000, 800, score, 1000, "")},
    )


def test_b40_png_draws_a_missing_jacket(tmp_path: Path):
    jacket_dir = tmp_path / "illust"
    jacket_dir.mkdir()
    Image.new("RGB", (24, 24), (12, 80, 160)).save(jacket_dir / "illustration.Song.A.0.png")
    index = SongIndex(
        [_song("Song.A.0", "Alpha", 1_010_000), _song("Song.B.0", "竹", 1_000_000)],
        "test",
    )
    special = [
        {
            "trackId": "track.Song.A.0",
            "title": "Alpha",
            "diff": "IN",
            "rks": 140.0,
            "score": 1_008_000,
            "const": 12.5,
            "sourceRank": 1,
        }
    ]
    ordinary = [
        {
            "trackId": "track.Song.B.0",
            "title": "竹",
            "diff": "AT",
            "rks": 120.0,
            "score": 990_000,
            "const": 13.0,
            "sourceRank": 6,
        }
    ]
    data = render_b40(
        username="Tester",
        total_rks=16.5,
        special=special,
        ordinary=ordinary,
        overflow=[],
        index=index,
        illust_hires_dir=tmp_path / "hires",
        illust_dir=jacket_dir,
        font_path=FONT,
    )
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) < MAX_PNG_BYTES
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.size[0] > 200
        assert image.size[1] > 120


def test_b40_png_shrinks_when_the_cap_is_tiny(tmp_path: Path):
    index = SongIndex([_song("Song.A.0", "Alpha", 1_010_000)], "test")
    row = {
        "trackId": "track.Song.A.0",
        "title": "Alpha",
        "diff": "IN",
        "rks": 10.0,
        "score": 900_000,
        "const": 8.0,
        "sourceRank": 1,
    }
    data = render_b40(
        username="Tester",
        total_rks=1.0,
        special=[row],
        ordinary=[],
        overflow=[],
        index=index,
        illust_hires_dir=tmp_path / "hires",
        illust_dir=tmp_path / "illust",
        font_path=FONT,
        max_bytes=1,
    )
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    full = render_b40(
        username="Tester",
        total_rks=1.0,
        special=[row],
        ordinary=[],
        overflow=[],
        index=index,
        illust_hires_dir=tmp_path / "hires",
        illust_dir=tmp_path / "illust",
        font_path=FONT,
    )
    assert len(data) < len(full)
