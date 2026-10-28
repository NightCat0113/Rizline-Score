import json
from pathlib import Path

from PIL import Image
import io

from bot.services.asyncombat import RAIL_LABELS, RankBadge, display_name, map_weekly_rank, segment_index
from bot.services.rizcard import normalize_rizcard
from bot.services.weekly_tasks import map_weekly_tasks
from bot.ui.asyncombat_image import render_asyncombat
from bot.ui.rizcard_image import render_live_rizcard
from bot.ui.weekly_view import WeeklyTaskView


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"


def _load(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def test_weekly_rank_maps_stage_and_sides():
    view = map_weekly_rank(_load("asyncombat_rank.json"))
    assert view.initial.label == "Do 5"
    assert view.current.label == "Do△ 54+"
    assert view.peak.label == "Do△ 60"
    assert (view.challenge.matches, view.challenge.wins, view.challenge.streak) == (12, 9, 4)
    assert (view.engage.matches, view.engage.wins, view.engage.streak) == (7, 3, 1)
    assert display_name(_load("asyncombat_rank.json")) == "Player"


def test_weekly_rank_maps_numeric_segment():
    view = map_weekly_rank(
        {
            "currentSeasonStartingRank": {"segment": 0, "stars": 5},
            "currentRank": {"segment": 7, "stars": 54, "isPlus": True},
            "currentSeasonBestRank": {"segmentName": "Do△", "stars": 60},
        }
    )
    assert view.initial.label == "Do 5"
    assert view.initial.segment == "Do"
    assert view.current.label == "Do△ 54+"
    assert view.current.is_plus is True
    assert view.peak.segment == "Do△"


def test_rank_rail_includes_plus_tiers():
    assert RAIL_LABELS == (
        "Do",
        "Do+",
        "Re",
        "Re+",
        "Mi",
        "Mi+",
        "Fa",
        "Fa+",
        "So",
        "So+",
        "La",
        "La+",
        "Ti",
        "Ti+",
        "Do△",
    )
    assert segment_index(RankBadge("Do 5", segment="Do", stars=5)) == 0
    assert segment_index(RankBadge("Do 5+", segment="Do", stars=5, is_plus=True)) == 1
    assert segment_index(RankBadge("Mi+", segment="Mi+", stars=None)) == 5
    assert segment_index(RankBadge("Sol 3+", segment="Sol", stars=3, is_plus=True)) == 9
    assert segment_index(RankBadge("Do△ 54+", segment="Do△", stars=54, is_plus=True)) == 14


def test_asyncombat_png_is_a_sheet():
    view = map_weekly_rank(_load("asyncombat_rank.json"))
    data = render_asyncombat(
        view,
        username="Player",
        font_path=FONT,
        card={"avatarId": "", "backgroundId": "", "layoutId": "", "bioId1": "", "bioId2": "", "totalRks": 12.3},
        illust_hires_dir=ROOT / "output" / "illust_HiRes",
        illust_dir=ROOT / "output" / "illust",
        repo_root=ROOT,
        total_rks=12.3,
    )
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(data)) as image:
        assert image.size[0] == 1080
        assert image.size[1] < 760


def test_weekly_tasks_map_progress_and_status():
    board = map_weekly_tasks(_load("weekly_tasks.json"))
    assert board.week_index == "12"
    assert [task.status for task in board.tasks] == ["incomplete", "claimable", "claimed"]
    assert board.tasks[0].title == "Play Asyncombat 5 times"
    assert board.tasks[0].progress == 2
    client_fields = map_weekly_tasks(
        {
            "weekIndex": 1,
            "tasks": [
                {"taskId": "100301", "progress": 1, "target": 5, "completed": False, "rewarded": False},
                {"taskId": "100401", "progress": 5, "target": 5, "completed": True, "rewarded": False},
                {"taskId": "100502", "progress": 5, "target": 5, "completed": True, "rewarded": True},
            ],
        }
    )
    assert [task.status for task in client_fields.tasks] == ["incomplete", "claimable", "claimed"]
    text = WeeklyTaskView(owner_id=1, board=board, language="en").render()
    assert "Play Asyncombat 5 times" in text
    assert "How to: Finish 5 Asyncombat matches." in text
    assert "Claimable" in text
    assert "Claimed" in text
    assert "Week 12" not in text
    assert "Refreshes" not in text
    english = map_weekly_tasks(
        {"tasks": [{"id": "100502", "title": "中文标题", "description": "服务器说明", "progress": 1, "target": 5}]},
        language="en",
        repo_root=ROOT,
    )
    assert english.tasks[0].title == "Play Asyncombat 5 times"
    assert english.tasks[0].desc == "Finish 5 Asyncombat matches."
    chinese = map_weekly_tasks(
        {"tasks": [{"id": "100502", "progress": 1, "target": 5}]},
        language="zh-Hans",
        repo_root=ROOT,
    )
    assert chinese.tasks[0].title == "进行异步对战 5 次"
    assert "5 场" in chinese.tasks[0].desc


def test_live_rizcard_uses_the_socket_card():
    payload = _load("own_rizcard.json")
    card = normalize_rizcard(payload)
    assert card["layoutId"] == "layout.00056"
    assert card["username"] == "LivePlayer"
    nested = normalize_rizcard(
        {"cards": [{"userName": "CardName", "rizcard": {"layoutId": "layout.00001", "avatarId": "a"}}]}
    )
    assert nested["username"] == "CardName"
    assert nested["layoutId"] == "layout.00001"
    owned = normalize_rizcard(
        {
            "ownRizcards": [
                {"userName": "Skip"},
                {"userName": "Owner", "rizcard": {"avatarId": "illustration.live", "layoutId": "layout.9", "backgroundId": "illustration.bg"}},
            ]
        }
    )
    assert owned["username"] == "Owner"
    assert owned["avatarId"] == "illustration.live"
    assert owned["layoutId"] == "layout.9"
    assert owned["backgroundId"] == "illustration.bg"
    data = render_live_rizcard(
        payload,
        username="Ignored",
        total_rks=0,
        illust_hires_dir=ROOT / "output" / "illust_HiRes",
        illust_dir=ROOT / "output" / "illust",
        font_path=FONT,
        repo_root=ROOT,
    )
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_equipped_rizcard_comes_from_the_save(monkeypatch):
    from rizline.client import fetch_equipped_rizcard

    def _api(_base, path, _payload, _headers, **_kwargs):
        assert path == "game/rn_login"
        body = json.dumps(
            {
                "username": "Night",
                "totalRks": 12.5,
                "token": "secret-token",
                "rizcard": {
                    "avatarId": "illustration.me",
                    "layoutId": "layout.1",
                    "backgroundId": "illustration.bg",
                },
                "ownRizcards": [{"rizcard": {"avatarId": "illustration.other"}}],
            }
        ).encode()
        return body, None

    monkeypatch.setattr("rizline.client.api_request", _api)
    result = fetch_equipped_rizcard("a@b.c", "tok", "device-123")
    assert result["username"] == "Night"
    assert result["rizcard"]["avatarId"] == "illustration.me"
    assert "ownRizcards" not in result
    assert "token" not in result
    assert normalize_rizcard(result)["avatarId"] == "illustration.me"
