from pathlib import Path

from PIL import Image

from bot.models import ChartInfo, SeriesVolume, Song, TrackSeries
from bot.services.language import normalize_language, strings, user_language
from bot.services.profile import player_title
from bot.services.seriesdata import series_tag
from bot.store.crypto import CryptoBox
from bot.store.db import Database
from bot.ui.series_image import open_series_art, render_series
from bot.ui.song_image import render_song

from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"


def test_language_names_and_fallback():
    assert normalize_language("ja") == "ja"
    assert normalize_language("fr") == "en"
    assert strings("zh-Hans")["track_series"] == "曲目系列"
    assert strings("zh-Hant")["preorder_ends"] == "預購截止"
    assert strings("ja")["score"] == "スコア"


def test_player_bio_follows_the_language():
    first, second = "bio.spbio00049.1", "bio.exbio00007.2"
    assert player_title(first, second, ROOT) == "Musical Cat"
    assert player_title(first, second, ROOT, "zh-Hans") == "音乐与 猫咪"
    assert player_title(first, second, ROOT, "zh-Hant") == "音樂與 貓咪"
    assert player_title(first, second, ROOT, "ja") == "音楽と 猫"
    assert player_title("ach.[leonids].title1", "", ROOT, "zh-Hans") == "星海中的"
    assert series_tag("spbio00049", ROOT, "ja") == "音楽と 世界"


def test_b40_header_uses_the_bio_language(tmp_path: Path):
    from bot.services.songdata import SongIndex
    from bot.ui.b40_image import render_b40

    kwargs = {
        "username": "Tester",
        "total_rks": 1.0,
        "special": [],
        "ordinary": [],
        "overflow": [],
        "index": SongIndex([], "test"),
        "illust_hires_dir": tmp_path / "hires",
        "illust_dir": tmp_path / "illust",
        "font_path": FONT,
        "repo_root": ROOT,
        "card": {"bioId1": "bio.spbio00049.1", "bioId2": "bio.exbio00007.2"},
    }
    assert render_b40(language="en", **kwargs) != render_b40(language="ja", **kwargs)


def test_song_commands_have_no_difficulty_option():
    from bot.commands.scores import ScoresCog
    from bot.commands.songs import SongsCog

    assert [item.name for item in SongsCog.song.parameters] == ["query"]
    assert [item.name for item in ScoresCog.score.parameters] == ["query", "user"]


def test_saved_language_survives_unbind(tmp_path: Path):
    database = Database(tmp_path / "bot.db", CryptoBox(Fernet.generate_key().decode()))
    assert database.get_language(42) == "en"
    database.set_language(42, "zh-Hant")
    assert user_language(database, 42) == "zh-Hant"
    database.upsert_binding(42)
    database.unbind(42)
    assert database.get_language(42) == "zh-Hant"
    database.close()


def test_series_art_prefers_the_saved_language(tmp_path: Path):
    english = tmp_path / "seriesPoster.00014.png"
    chinese = tmp_path / "zh-Hans" / "seriesPoster.00014.png"
    chinese.parent.mkdir()
    Image.new("RGB", (8, 8), (200, 0, 0)).save(english)
    Image.new("RGB", (8, 8), (0, 0, 200)).save(chinese)
    picked = open_series_art(tmp_path, "Poster", 14, "zh-Hans")
    fallback = open_series_art(tmp_path, "Poster", 14, "ja")
    assert picked is not None and picked.getpixel((0, 0)) == (0, 0, 200)
    assert fallback is not None and fallback.getpixel((0, 0)) == (200, 0, 0)


def _song() -> Song:
    return Song(
        asset_id="Song.A.0",
        title="Alpha",
        artist="Artist",
        disc_name="Disc 1",
        illustration_id="illustration.missing",
        charts={"EZ": ChartInfo("EZ", 5, 100, 80, 1_000_000, 10, "Charter")},
        bpm=150,
        series_index=12,
        series_name="Phigros",
    )


def test_card_text_follows_the_language(tmp_path: Path):
    kwargs = {
        "song": _song(),
        "personal": {},
        "highlight": None,
        "illust_hires_dir": tmp_path / "hires",
        "illust_dir": tmp_path / "illust",
        "font_path": FONT,
    }
    english = render_song(language="en", **kwargs)
    chinese = render_song(language="zh-Hans", **kwargs)
    assert english != chinese


def test_series_card_text_follows_the_language():
    series = TrackSeries(
        series_index=18,
        name="Astral Streams",
        volumes=(SeriesVolume("", "2027-01-01", ("Song.A.0",)),),
    )
    kwargs = {
        "series": series,
        "songs": {"Song.A.0": _song()},
        "tag": "",
        "banner": None,
        "poster": None,
        "font_path": FONT,
    }
    assert render_series(language="en", **kwargs) != render_series(language="ja", **kwargs)
