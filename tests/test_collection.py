import io
import json
from pathlib import Path

from PIL import Image

from bot.models import Song
from bot.services.collection import (
    collection_rows,
    filter_collection,
    owned_item_ids,
    resolve_art_query,
    search_art_choices,
    song_art_rows,
)
from bot.services.songdata import SongIndex
from bot.ui.collection_image import render_bio_sheet, render_collection_grid
from bot.ui.collection_view import CollectionBioView, _bio_line


ROOT = Path(__file__).resolve().parents[1]


def test_owned_item_ids_requires_cache_key():
    assert owned_item_ids({}) is None
    assert owned_item_ids({"items": ["bio.a.1", "", {"id": "layout.00001"}]}) == {
        "bio.a.1",
        "layout.00001",
    }


def test_filter_bios_owned_missing_and_all():
    rows = [
        {"id": "a", "kind": "bio", "title1": "Harmonic", "title2": "Magician"},
        {"id": "b", "kind": "bio", "title1": "Solo", "title2": "Cat"},
    ]
    owned = {"bio.a.1", "bio.extra.2"}
    owned_rows, owned_count, total = filter_collection(rows, owned, "owned", "bio")
    missing_rows, _, _ = filter_collection(rows, owned, "missing", "bio")
    all_rows, _, _ = filter_collection(rows, owned, "all", "bio")
    assert [row["id"] for row in owned_rows] == ["a", "extra"]
    assert [row["id"] for row in missing_rows] == ["b"]
    assert [row["id"] for row in all_rows] == ["a", "b"]
    assert owned_count == 1
    assert total == 4
    assert "✓ Harmonic" in _bio_line(rows[0], owned)
    assert "☐ Magician" in _bio_line(rows[0], owned)
    both = {"bio.a.1", "bio.a.2"}
    assert _bio_line(rows[0], both) == "| ✓ Harmonic | ✓ Magician |"


def test_filter_layouts_appends_uncatalogued_owned_ids():
    rows = [{"id": "layout.00001", "kind": "layout", "name": "layout.00001"}]
    owned = {"layout.00001", "layout.00999", "bio.a.1"}
    owned_rows, owned_count, total = filter_collection(rows, owned, "owned", "layout")
    missing_rows, _, _ = filter_collection(rows, set(), "missing", "layout")
    assert [row["id"] for row in owned_rows] == ["layout.00001", "layout.00999"]
    assert owned_count == 1
    assert total == 1
    assert [row["id"] for row in missing_rows] == ["layout.00001"]


def test_titles_stay_one_line_and_specials_are_catalogued(tmp_path: Path):
    # fileList.json lives under gitignored download/; CI has no copy, so fixture one.
    download = tmp_path / "download"
    download.mkdir()
    file_list = [
        ["altIllustration.MilK.morimoriatsushi.0.0"],
        ["altIllustration.MilK.morimoriatsushi.0.0.HiRes"],
        ["altIllustration.MuseDashCollab.0.HiRes"],
        # Drawable layouts (skip 46–48 which have color entries but no art).
        *[[f"layout.{index:05d}"] for index in list(range(1, 46)) + [49, 50, 51, 52, 53, 54, 55]],
    ]
    (download / "fileList.json").write_text(json.dumps(file_list), encoding="utf-8")
    songs = SongIndex(
        [
            Song(
                asset_id="MilK.morimoriatsushi.0",
                title="MilK",
                artist="",
                disc_name="",
                illustration_id="illustration.MilK.morimoriatsushi.0",
            ),
            Song(
                asset_id="PlanetariumprodScarlette.kuripurinKyueMYULee.0",
                title="너를 그리는 밤하늘의 이야기\n(Planetarium) prod. Scarlette",
                artist="kuripurin",
                disc_name="",
                illustration_id="illustration.PlanetariumprodScarlette.kuripurinKyueMYULee.0",
            ),
        ],
        "test",
    )
    rows = collection_rows(tmp_path, "en", "illustration", songs)
    names = {row["id"]: row["name"] for row in rows}
    assert "\n" not in names["illustration.PlanetariumprodScarlette.kuripurinKyueMYULee.0"]
    assert names["illustration.PlanetariumprodScarlette.kuripurinKyueMYULee.0"].endswith("Scarlette")
    assert names["altIllustration.MilK.morimoriatsushi.0.0"] == "MilK (Special)"
    assert "altIllustration.MuseDashCollab.0.HiRes" not in names
    milk = songs.by_asset["MilK.morimoriatsushi.0"]
    arts = song_art_rows(milk, tmp_path)
    assert [row["name"] for row in arts] == ["MilK", "MilK (Special)"]
    assert arts[1]["id"] == "altIllustration.MilK.morimoriatsushi.0.0"
    milk_with_artist = Song(
        asset_id="MilK.morimoriatsushi.0",
        title="MilK",
        artist="morimori atsushi",
        disc_name="",
        illustration_id="illustration.MilK.morimoriatsushi.0",
    )
    labeled = SongIndex([milk_with_artist], "test")
    choices = dict(search_art_choices(labeled, tmp_path, "MilK"))
    assert "MilK - morimori atsushi" in choices
    assert any(label.startswith("MilK (Special) - morimori atsushi") for label in choices)
    special_id = "altIllustration.MilK.morimoriatsushi.0.0"
    assert choices.get("MilK (Special) - morimori atsushi") == special_id
    rows, ambiguous = resolve_art_query(labeled, tmp_path, special_id)
    assert ambiguous == []
    assert rows == [{"id": special_id, "kind": "illustration", "name": "MilK (Special)"}]
    owned_rows, owned_count, total = filter_collection(
        rows,
        {"altIllustration.MilK.morimoriatsushi.0.0"},
        "owned",
        "illustration",
    )
    assert any(row["id"].startswith("altIllustration.") for row in owned_rows)
    assert owned_count == 1
    assert total == len(rows)
    bios = collection_rows(ROOT, "en", "bio")
    chinese = collection_rows(ROOT, "zh-Hans", "bio")
    bio_ids = {row["id"] for row in bios}
    assert bio_ids == {row["id"] for row in chinese}
    assert "spbio00001" not in bio_ids
    assert "spbio00040" not in bio_ids
    assert "spbio00049" in bio_ids
    owned_rows, _, _ = filter_collection(
        bios,
        {"bio.spbio00001.1", "bio.spbio00049.1"},
        "owned",
        "bio",
    )
    owned_ids = {row["id"] for row in owned_rows}
    assert "spbio00001" not in owned_ids
    assert "spbio00049" in owned_ids
    layouts = collection_rows(tmp_path, "en", "layout")
    assert any(row["id"] == "exbio00001" and row["title1"] for row in bios)
    layout_ids = [row["id"] for row in layouts]
    assert "layout.00001" in layout_ids
    assert "layout.00049" in layout_ids
    assert "layout.00046" not in layout_ids
    assert "layout.00047" not in layout_ids
    assert "layout.00048" not in layout_ids
    assert not any(layout_id.startswith("layout.Static") for layout_id in layout_ids)
    assert layout_ids.index("layout.00045") < layout_ids.index("layout.00049") < layout_ids.index("layout.00050")
    assert len(bios) > 20
    assert len(layouts) > 20


def test_layouts_without_filelist_skip_placeholders(tmp_path: Path):
    locale = tmp_path / "locale"
    locale.mkdir()
    (locale / "layout.json").write_text(
        json.dumps(
            {
                "layoutColors": [
                    {"id": "layout.00045"},
                    {"id": "layout.00046"},
                    {"id": "layout.00047"},
                    {"id": "layout.00048"},
                    {"id": "layout.00050"},
                ]
            }
        ),
        encoding="utf-8",
    )
    layout_ids = [row["id"] for row in collection_rows(tmp_path, "en", "layout")]
    assert "layout.00046" not in layout_ids
    assert "layout.00047" not in layout_ids
    assert "layout.00048" not in layout_ids
    assert layout_ids.index("layout.00045") < layout_ids.index("layout.00049") < layout_ids.index("layout.00050")


def test_bio_view_pages_ten_stems():
    rows = [
        {"id": f"bio{index:02d}", "kind": "bio", "title1": f"Left{index}", "title2": f"Right{index}"}
        for index in range(12)
    ]
    font = ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"
    view = CollectionBioView(
        owner_id=1,
        rows=rows,
        owned=set(),
        owned_count=0,
        total=24,
        language="en",
        font_path=font,
    )
    text = view.caption()
    assert "Owned 0 / 24" in text
    assert "Page 1/2" in text
    first = view.render_png()
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    view.page = 1
    second = view.render_png()
    assert second != first
    assert view.rows[9]["title1"] == "Left9"
    assert view.rows[10]["title1"] == "Left10"


def test_collection_grid_renders_png(tmp_path: Path):
    illust = tmp_path / "illust"
    hires = tmp_path / "hires"
    illust.mkdir()
    hires.mkdir()
    Image.new("RGB", (24, 24), (20, 120, 180)).save(illust / "illustration.Test.0.png")
    rows = [
        {"id": "illustration.Test.0", "kind": "illustration", "name": "Owned Song"},
        {"id": "illustration.Missing.0", "kind": "illustration", "name": "Missing Song"},
        {"id": "layout.00001", "kind": "layout", "name": "layout.00001"},
    ]
    png = render_collection_grid(
        rows=rows,
        owned={"illustration.Test.0"},
        title="Illustrations",
        progress="Owned 1 / 3",
        page_label="Page 1/1",
        illust_hires_dir=hires,
        illust_dir=illust,
        font_path=ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf",
        repo_root=ROOT,
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(png)) as image:
        assert image.width > 200
        assert image.height > 160


def test_catalog_mode_hides_ownership_marks(tmp_path: Path):
    font = ROOT / "assets" / "fonts" / "Source Han Sans CN&Comfortaa Hybrid Bold.ttf"
    illust = tmp_path / "illust"
    hires = tmp_path / "hires"
    illust.mkdir()
    hires.mkdir()
    Image.new("RGB", (32, 32), (40, 90, 160)).save(illust / "illustration.Test.0.png")
    grid = render_collection_grid(
        rows=[{"id": "illustration.Test.0", "kind": "illustration", "name": "Catalog Song"}],
        owned=None,
        title="Arts",
        progress="Catalog 1",
        page_label="Page 1/1",
        illust_hires_dir=hires,
        illust_dir=illust,
        font_path=font,
        repo_root=ROOT,
    )
    assert grid.startswith(b"\x89PNG\r\n\x1a\n")
    bios = render_bio_sheet(
        rows=[{"id": "a", "kind": "bio", "title1": "Harmonic", "title2": "Magician"}],
        owned=None,
        title="Bios",
        part1="Part 1",
        part2="Part 2",
        progress="Catalog 1",
        page_label="Page 1/1",
        font_path=font,
    )
    assert bios.startswith(b"\x89PNG\r\n\x1a\n")
    view = CollectionBioView(
        owner_id=1,
        rows=[{"id": "a", "kind": "bio", "title1": "Harmonic", "title2": "Magician"}],
        owned=None,
        owned_count=0,
        total=2,
        language="en",
        font_path=font,
    )
    assert "Catalog 2" in view.caption()
    assert "Owned" not in view.caption()
