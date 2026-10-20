import json
from pathlib import Path

from bot.services.rks import (
    build_records,
    compute_h,
    get_acc_rks,
    score_counts,
    select_top40,
    top_levels,
)
from bot.services.songdata import SongIndex


ROOT = Path(__file__).resolve().parents[1]


def test_accuracy_and_hit_thresholds():
    assert get_acc_rks(120) == 10.5
    assert get_acc_rks(119.9999) == 10.5
    assert get_acc_rks(119) == 10.2
    assert get_acc_rks(100) == 7.5
    assert get_acc_rks(59) == 0.0
    assert compute_h(0, "EZ") == 0
    assert compute_h(20, "EZ") == 10
    assert compute_h(8, "EZ") == 3


def _keys(value, found: set[str]) -> None:
    if isinstance(value, dict):
        found.update(str(key) for key in value)
        for item in value.values():
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)


def test_b40_on_sanitized_fixture():
    raw = (ROOT / "tests" / "fixtures" / "sanitized_save.json").read_text(encoding="utf-8")
    cache = json.loads(raw)
    keys: set[str] = set()
    _keys(cache, keys)
    assert keys.isdisjoint({"mails", "userId", "_id", "mailSyncId", "getProducts", "password", "token", "email"})
    assert "@" not in raw
    index = SongIndex.load(ROOT / "bot" / "static" / "songs_index.json")
    records, _missing = build_records(cache, index)
    assert len(records) > 20
    special, ordinary, overflow = select_top40(records)
    assert 1 <= len(special) <= 5
    assert len(ordinary) <= 35
    assert len(overflow) <= 10
    assert special == sorted(special, key=lambda row: row["rks"], reverse=True)
    selected = {(row["trackId"], row["diff"]) for row in special}
    assert all((row["trackId"], row["diff"]) not in selected for row in ordinary)
    counts = score_counts(cache)
    assert counts["records"] == len(cache["myBest"])
    assert top_levels(cache, index, limit=5)
