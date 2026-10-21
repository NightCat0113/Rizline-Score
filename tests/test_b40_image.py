import io
import json
from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, Song
from bot.services.profile import layout_colors, local_profile, player_title
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
        assert image.size[0] >= 3000
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


def test_local_profile_matches_username(tmp_path: Path):
    save = {
        "username": "NightXWind",
        "totalRks": 1,
        "userId": "hidden-user",
        "mails": [{"body": "hidden-mail"}],
        "rizcard": {
            "avatarId": "illustration.Song.0",
            "bioId1": "bio.spbio00049.1",
            "bioId2": "bio.exbio00007.2",
            "backgroundId": "illustration.Other.0",
            "createTime": "hidden-time",
        },
        "myBest": [],
        "levelsRks": [],
    }
    (tmp_path / "NightXWind_gameData.json").write_text(json.dumps(save), encoding="utf-8")
    (tmp_path / "Other_gameData.json").write_text(
        json.dumps({**save, "username": "Someone"}),
        encoding="utf-8",
    )
    found = local_profile(tmp_path, "NightXWind")
    assert found["avatarId"] == "illustration.Song.0"
    assert found["bioId1"] == "bio.spbio00049.1"
    assert "hidden-mail" not in json.dumps(found)
    assert "hidden-user" not in json.dumps(found)
    assert local_profile(tmp_path, "Missing") == {}


def test_layout_00056_bar_is_grey():
    left, right, ink = layout_colors("layout.00056", ROOT)
    assert left == (0x57, 0x57, 0x59)
    assert right == (0xB5, 0xB5, 0xB5)
    assert ink == (255, 255, 255)
    assert layout_colors("layout.missing", ROOT)[0] == (255, 255, 255)


def test_player_title_comes_from_bio_json():
    assert player_title("bio.spbio00049.1", "bio.exbio00007.2", ROOT) == "Musical Cat"
    assert player_title("ach.[leonids].title1", "", ROOT) == "Starry"
