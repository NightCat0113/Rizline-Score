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
    assert song.bpm == 150
    assert song.length_seconds is not None
    assert 100 < song.length_seconds < 140
    assert song.illustrator == "山山奇"
    assert song.series_index is None
    bamboo, _bamboo_alternatives = index.resolve("竹")
    assert bamboo is not None
    sp = bamboo.charts["SP"]
    assert sp.level_text == "竹"
    assert sp.track_id == "Bamboo.rissyuu.1"
    assert sp.hit == 1048
    assert sp.combo == 4168
    assert sp.score == 1015600
    assert sp.riz_hit == 156
    assert sp.designer.startswith("竹竹")
    dot = index.by_asset["DotLinefeatななひら.A39沙包Pななひら.0"]
    assert dot.charts["SP"].designer == "Dot --> Line"
    inevitability = index.by_asset["Inevitability.kuro.0"]
    assert inevitability.charts["SP"].designer == "→↘↓↙←"
    turning, _alternatives = index.resolve("Turning POINT")
    assert turning is not None
    assert turning.series_index == 10001
    assert turning.series_name == "Paradigm: Reboot"
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
