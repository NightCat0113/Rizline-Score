from bot.models import ChartInfo, Song
from bot.services.recommendation import recommend_score_targets
from bot.services.rks import compute_h, get_acc_rks, score_riz_perfect
from bot.services.songdata import SongIndex
from bot.ui.recommendation_view import RecommendationPlanView


ACCURACY = get_acc_rks(100)


def _song(asset_id: str, title: str, level: float, riz_hit: int, chart_score: int) -> Song:
    return Song(
        asset_id=asset_id,
        title=title,
        artist="",
        disc_name="",
        illustration_id="",
        charts={
            "IN": ChartInfo("IN", level, riz_hit, riz_hit, chart_score, riz_hit, ""),
        },
    )


def _play(asset_id: str, score: int, level: float, riz_hit: int) -> tuple[dict, dict]:
    hits = compute_h(riz_hit, "IN")
    quotient = min(hits, int(score_riz_perfect(score)))
    rks = 10 * level + ACCURACY + level * quotient / hits
    best = {
        "trackAssetId": asset_id,
        "difficultyClassName": "IN",
        "score": score,
        "completeRate": 100,
        "isFullCombo": False,
        "isClear": True,
    }
    level_row = {
        "trackId": asset_id,
        "difficultyClassName": "IN",
        "rks": rks,
    }
    return best, level_row


def _index_and_cache(plays: list[tuple[Song, int]]) -> tuple[SongIndex, dict]:
    songs = []
    bests = []
    levels = []
    for song, score in plays:
        chart = song.charts["IN"]
        best, level_row = _play(song.asset_id, score, chart.level, chart.riz_hit)
        songs.append(song)
        bests.append(best)
        levels.append(level_row)
    return SongIndex(songs, "test"), {"myBest": bests, "levelsRks": levels}


def _two_chart_board() -> tuple[SongIndex, dict, Song, Song]:
    easy = _song("easy", "EasyFinish", 8, 55, 1_005_000)
    deep = _song("deep", "DeepGrind", 15, 25, 1_002_000)
    index, cache = _index_and_cache([(easy, 1_004_900), (deep, 1_000_000)])
    return index, cache, easy, deep


def test_default_plans_the_full_score_only_maximum():
    index, cache, _easy, _deep = _two_chart_board()
    plan, maximum = recommend_score_targets(cache, index, increase=None)
    assert {row["title"] for row in plan} == {"EasyFinish", "DeepGrind"}
    assert abs(sum(row["rks_gain"] for row in plan) - maximum) < 1e-6
    assert maximum > 0.01


def test_small_increase_is_a_short_plan_that_prefers_the_nearly_finished_chart():
    index, cache, _easy, deep = _two_chart_board()
    plan, maximum = recommend_score_targets(cache, index, increase=0.01)
    assert plan[0]["title"] == "EasyFinish"
    deep_row = next(row for row in plan if row["title"] == "DeepGrind")
    assert deep_row["target_score"] < deep.charts["IN"].score
    assert sum(row["rks_gain"] for row in plan) < maximum


def test_song_filter_keeps_only_the_selected_chart():
    index, cache, _easy, _deep = _two_chart_board()
    plan, maximum = recommend_score_targets(cache, index, increase=None, song_ids={"easy"})
    assert [row["title"] for row in plan] == ["EasyFinish"]
    assert abs(sum(row["rks_gain"] for row in plan) - maximum) < 1e-6


def test_large_target_keeps_the_partial_in_b40_plan():
    index, cache, _easy, _deep = _two_chart_board()
    plan, maximum = recommend_score_targets(cache, index, increase=10)
    assert plan
    gained = sum(row["rks_gain"] for row in plan)
    assert gained < 10
    assert abs(gained - maximum) < 1e-6


def test_outsiders_prefer_the_smaller_entry_jump():
    fillers = [
        (_song(f"fill{number}", f"Filler {number}", 13, 25, 1_002_000), 1_002_000)
        for number in range(40)
    ]
    easy = _song("outsider-easy", "SmallJump", 13.5, 15, 1_001_000)
    hard = _song("outsider-hard", "LongJump", 14, 205, 1_020_000)
    index, cache = _index_and_cache([*fillers, (easy, 1_000_500), (hard, 1_000_000)])
    plan, _maximum = recommend_score_targets(cache, index, increase=0.01)
    assert plan
    assert plan[0]["title"] == "SmallJump"
    assert plan[0]["in_top40"] is False
    assert all(row["title"] != "LongJump" for row in plan)


def test_max_plan_header_and_shortfall_copy():
    full = RecommendationPlanView(owner_id=1, increase=None, rows=[{"title": "A", "difficulty": "IN", "current_score": 1, "target_score": 2, "rks_gain": 0.2, "in_top40": True}])
    assert "max score-only gain (+0.200 RKS)" in full.render()
    short = RecommendationPlanView(
        owner_id=1,
        increase=1.0,
        rows=[{"title": "A", "difficulty": "IN", "current_score": 1, "target_score": 2, "rks_gain": 0.2, "in_top40": True}],
    )
    text = short.render()
    assert "Requested +1.00" in text
    assert "+0.200" in text
