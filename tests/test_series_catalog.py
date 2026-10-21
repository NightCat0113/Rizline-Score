from pathlib import Path

from bot.models import SeriesVolume, Song, TrackSeries
from bot.services.seriesdata import bio_ids_from_locale, build_series_records, preorder_date, series_mark, series_tag
from bot.services.songdata import SongIndex


ROOT = Path(__file__).resolve().parents[1]
NAMES = {12: "Phigros", 18: "Astral Streams", 10002: "去远方"}


def _songs(*rows: tuple[str, int]) -> list[dict]:
    return [{"assetId": asset_id, "seriesIndex": index} for asset_id, index in rows]


def test_phigros_keeps_config_order_and_skips_a_zero_deadline():
    configs = [
        {
            "seriesIndex": 12,
            "volGroups": [
                {
                    "volLabel": "",
                    "preOrderTimeConfig": {"deadline": 0},
                    "levelIds": [
                        "SpeedUp.DarTokki.0",
                        "SnowDesert.WyvernP.0",
                        "Concvssion.Halv.0",
                    ],
                }
            ],
        }
    ]
    songs = _songs(
        ("Concvssion.Halv.0", 12),
        ("SpeedUp.DarTokki.0", 12),
        ("SnowDesert.WyvernP.0", 12),
    )
    records = build_series_records(configs, songs, NAMES, {})
    volume = records[0]["volumes"][0]
    assert records[0]["name"] == "Phigros"
    assert volume["songs"] == [
        "SpeedUp.DarTokki.0",
        "SnowDesert.WyvernP.0",
        "Concvssion.Halv.0",
    ]
    assert "preorderEnds" not in volume
    assert "bioId" not in records[0]


def test_deadline_becomes_a_utc_date_and_a_song_only_series_is_kept():
    configs = [
        {
            "seriesIndex": 18,
            "volGroups": [
                {
                    "volLabel": "",
                    "preOrderTimeConfig": {"deadline": 1791536399},
                    "levelIds": ["Astral.TitanChaos.0"],
                }
            ],
        }
    ]
    songs = _songs(("Astral.TitanChaos.0", 18), ("FarAway.Example.0", 10002))
    songs[1]["seriesName"] = "去远方"
    records = build_series_records(configs, songs, {18: "Astral Streams"}, {18: "spbio00049"})
    by_index = {row["seriesIndex"]: row for row in records}
    assert by_index[18]["volumes"][0]["preorderEnds"] == preorder_date(1791536399)
    assert by_index[18]["bioId"] == "spbio00049"
    assert by_index[10002]["name"] == "去远方"
    assert by_index[10002]["volumes"][0]["songs"] == ["FarAway.Example.0"]
    assert "preorderEnds" not in by_index[10002]["volumes"][0]


def test_locale_bio_line_is_kept_and_plain_series_text_is_not():
    assert bio_ids_from_locale("events.preorder.purchaseAll=Get Track Series\n") == {}
    assert bio_ids_from_locale("seriesBio.12=bio.spbio00049\n") == {12: "spbio00049"}
    assert series_tag("spbio00049", ROOT) == "Musical World"
    assert series_tag("", ROOT) == ""


def test_built_index_lists_phigros_and_a_preorder_date():
    index = SongIndex.load(ROOT / "bot" / "static" / "songs_index.json")
    phigros = index.resolve_series("Phigros")[0]
    assert phigros is not None
    assert [song_id for volume in phigros.volumes for song_id in volume.song_ids] == [
        "SpeedUp.DarTokki.0",
        "SnowDesert.WyvernP.0",
        "Concvssion.Halv.0",
    ]
    assert all(not volume.preorder_ends for volume in phigros.volumes)
    streams = index.series_by_index[18]
    assert streams.volumes[0].preorder_ends == preorder_date(1791536399)
    assert index.series_by_index[10002].name == "去远方"
    cytus = index.series_by_index[6]
    dates = [volume.preorder_ends for volume in cytus.volumes if volume.preorder_ends]
    assert len(dates) == 2
    assert dates[0] != dates[1]
    assert index.resolve_series("SP")[0] == phigros
    assert index.resolve_series("i12")[0] == phigros
    assert index.resolve_series("12")[0].name == "kuro"
    assert index.resolve_series("13")[0].name == "Cosmos Panorama"


def test_printed_series_number_treats_phigros_as_sp():
    assert series_mark(11) == "11"
    assert series_mark(12) == "SP"
    assert series_mark(13) == "12"
    assert series_mark(14) == "13"
    assert series_mark(17) == "16"
    assert series_mark(18) == "17"
    assert series_mark(10001) == "10001"
    phigros = TrackSeries(12, "Phigros")
    kuro = TrackSeries(13, "kuro")
    cosmos = TrackSeries(14, "Cosmos Panorama")
    index = SongIndex([], "test", [phigros, kuro, cosmos])
    assert index.resolve_series("sp")[0] is phigros
    assert index.resolve_series("12")[0] is kuro
    assert index.resolve_series("i13")[0] is kuro
    assert index.resolve_series("13")[0] is cosmos
    assert index.search_series("12") == [kuro]


def test_song_index_still_constructs_without_series():
    song = Song("Song.A.0", "Alpha", "Artist", "Disc 1", "illustration.Song.A.0", charts={})
    index = SongIndex([song], "test")
    assert index.series == []
    assert index.search_series("phigros") == []
    volume = SeriesVolume("", "", ("Song.A.0",))
    series = TrackSeries(1, "Juggernaut", volumes=(volume,))
    loaded = SongIndex([song], "test", [series])
    assert loaded.resolve_series("1")[0].name == "Juggernaut"
