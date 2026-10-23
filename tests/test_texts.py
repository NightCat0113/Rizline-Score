from pathlib import Path

from bot.models import ChartInfo, Song
from bot.services.songdata import SongIndex
from bot.ui.texts import ambiguous_text, profile_text, series_text, song_text


ROOT = Path(__file__).resolve().parents[1]


def _song() -> Song:
    return Song(
        asset_id="Song.A.0",
        title="Alpha",
        artist="Artist",
        disc_name="Disc 1",
        illustration_id="illustration.missing",
        charts={"EZ": ChartInfo("EZ", 1.0, 100, 376, 1_002_900, 29, "NerSAN")},
    )


def test_song_text_is_plain_message_content():
    text = song_text(_song())
    assert text.startswith("**Alpha**\nArtist\nDisc 1")
    assert "**EZ** Level 1 · Designer NerSAN" in text
    assert "Hit 100 · Combo 376 · Max 1,002,900" in text


def test_ambiguous_text_lists_candidates():
    text = ambiguous_text([_song()])
    assert text.startswith("Several songs match")
    assert "• Alpha — Artist" in text


def test_profile_and_series_text_stay_within_discord_limit():
    index = SongIndex.load(ROOT / "bot" / "static" / "songs_index.json")
    cache = {"username": "Player", "totalRks": 12.5, "myBest": {}, "levelsRks": {}}
    assert len(profile_text(cache, index)) <= 2000
    biggest = max(index.series, key=lambda item: sum(len(volume.song_ids) for volume in item.volumes))
    text = series_text(biggest, index.by_asset, "")
    assert text.startswith("**")
    assert len(text) <= 2000
