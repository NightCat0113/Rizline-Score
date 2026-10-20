from pathlib import Path

from bot.services.songdata import SongIndex, illustration_path, normalize


ROOT = Path(__file__).resolve().parents[1]


def _index() -> SongIndex:
    return SongIndex.load(ROOT / "bot" / "static" / "songs_index.json")


def test_normalize_matches_letters_and_numbers():
    assert normalize("LINK x LIN＃S") == "linkxlins"
    assert normalize("竹") == "竹"


def test_pastel_lines_resolves_with_designer():
    index = _index()
    song, alternatives = index.resolve("Pastel Lines")
    assert alternatives == []
    assert song is not None
    assert song.asset_id == "PastelLines.RekuMochizuki.0"
    assert song.charts["EZ"].level == 1.0
    assert song.charts["EZ"].designer == "NerSAN"
    assert song.charts["IN"].designer == "百九十八"
    assert song.disc_name
    assert all(len(item.asset_id) <= 100 for item in index.songs)


def test_alias_and_autocomplete_search():
    index = _index()
    song, _alternatives = index.resolve("bamboo")
    assert song is not None
    assert song.title == "竹"
    hits = index.search("gleam", limit=5)
    assert hits and hits[0].title.lower().startswith("gleam")


def test_illustration_is_optional():
    index = _index()
    song, _alternatives = index.resolve("Pastel Lines")
    assert song is not None
    path = illustration_path(song, ROOT / "output" / "illust_HiRes", ROOT / "output" / "illust")
    if (ROOT / "output" / "illust_HiRes").is_dir():
        assert path is not None
        assert path.is_file()
