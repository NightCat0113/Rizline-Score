#!/usr/bin/env python3
"""Build bot/static/songs_index.json from portable song files plus optional local chart metadata.

songs.json is the canonical source for levels, hits, combos, and max scores.
output/default.json (or Database.txt) adds the chart designer, disc name, and illustration id.
all_cache.json is not merged: its cargo query includes extra SP columns.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.seriesdata import bio_ids_from_locale, build_series_records  # noqa: E402
from bot.services.songdata import normalize  # noqa: E402


DIFFICULTIES = ("EZ", "HD", "IN", "AT")
# Names are the English titles on the official banners. seriesIndex 12 is
# Phigros and is printed as SP, so the banner number after that is seriesIndex - 1.
SERIES_NAMES = {
    1: "Juggernaut",
    2: "Diverse System",
    3: "Sobrem",
    4: "Tone Sphere",
    5: "BlackY",
    6: "Cytus & Muse Dash",
    7: "KALPA",
    8: "Rotaeno",
    9: "宇宙ラジヲ 2024",
    10: "HARDCORE TANO*C",
    11: "DEEMO",
    12: "Phigros",
    13: "kuro",
    14: "Cosmos Panorama",
    15: "Tanchiky",
    16: "ルゼ & LisicA",
    17: "Diachronic Resonance",
    18: "Astral Streams",
    10001: "Paradigm: Reboot",
    10002: "去远方",
}
ALIASES = {
    "houkagooverdrive": "Houkago OVERDRIVE!!!!! (Game ver.)",
    "linklins": "LINK x LIN＃S",
    "swingsweettweedance": "Swing Sweet Twee Dance feat. ななきなな",
    "bamboo": "竹",
}
# Songs written for Rizline itself. The game data has no "original" flag, so
# this list is maintained by hand from the official original-song roster:
# assetId -> (badge label, collaboration partner or ""). Unmarked songs on the
# roster are Rizline Originals; "(Pigeon Games独占)" songs are Pigeon Games
# Originals; Paradial Resonator is a collaboration original.
ORIGINALS = {
    "PastelLines.RekuMochizuki.0": ("Rizline Original", ""),
    "JourneyToTheRainbows.Ardolf.0": ("Rizline Original", ""),
    "NOONEYESMAN.MYUKKE.0": ("Pigeon Games Original", ""),
    "ClockParadox.WyvernP.0": ("Pigeon Games Original", ""),
    "macrowav.dandeless.0": ("Rizline Original", ""),
    "ArcadeViruZ.AspidCat.0": ("Rizline Original", ""),
    "LINKLINS.Halv.0": ("Rizline Original", ""),
    "LEONIDS.SaMZIngTitanChaos.0": ("Rizline Original", ""),
    "ParadialResonator.RekuMochizuki.0": ("Collaboration Original", "Paradigm: Reboot"),
    "ViciousMockery.Kryexe.0": ("Rizline Original", ""),
    "BRAVEROAD.umavsMorimoriAtsushi.0": ("Pigeon Games Original", ""),
    "DotLinefeatななひら.A39沙包Pななひら.0": ("Rizline Original", ""),
    "光阿卡姆巫师Remix.姜米條Remixedby阿卡姆巫师.0": ("Rizline Original", ""),
    "LostFuture.AspidCat.0": ("Rizline Original", ""),
    "YellowShiningfeat成田なる.にーえぬ.0": ("Rizline Original", ""),
    "AbsolutionPulse.nmy.0": ("Rizline Original", ""),
    "NeverSayGoodbye.黒魔.0": ("Rizline Original", ""),
    "SpeedUp.DarTokki.0": ("Pigeon Games Original", ""),
    "Inevitability.kuro.0": ("Rizline Original", ""),
    "GreatnessEarth.Axya.0": ("Rizline Original", ""),
    "LAIGN.KiufeatNikkiSimons.0": ("Rizline Original", ""),
    "PierrotFixer.ルゼ.0": ("Rizline Original", ""),
    "TalesofDelonix.Zris.0": ("Rizline Original", ""),
    "地区ShangriLA.Drazically.0": ("Rizline Original", ""),
    "千星光輪依頼症.KNYORGft無機ビョウ.0": ("Rizline Original", ""),
    "FrozenHeart.A39沙包P.0": ("Rizline Original", ""),
    "8BLUE.ariiolPIKASONIC.0": ("Rizline Original", ""),
    "溶けてゆく.A39.0": ("Rizline Original", ""),
}


def parse_float(value: object) -> float:
    text = str(value or "").strip().replace(",", "")
    if text.endswith("+"):
        text = text[:-1]
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_int(value: object) -> int:
    return int(round(parse_float(value)))


_SERIES_ART_RE = re.compile(
    r"^series(?P<kind>Poster|Banner)\.(?P<number>\d+)(?:\.(?P<lang>[A-Za-z][\w-]*))?$"
)
_ENGLISH_SPRITE = re.compile(r"(?i)(?:^|[^a-z])en$")
_ART_LANGUAGES = ("en", "zh-Hans", "zh-Hant", "ja")
_BPM_RE = re.compile(r'"bPM"\s*:\s*([0-9]+(?:\.[0-9]+)?)')
_TIME_RE = re.compile(br'"time"\s*:\s*([0-9]+(?:\.[0-9]+)?)')


def load_default(path: Path) -> tuple[dict, dict, dict, dict, dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    designers: dict[tuple[str, str], str] = {}
    for chart in payload.get("charts") or []:
        chart_id = str(chart.get("id") or "")
        level = str(chart.get("level") or "")
        prefix = "chart."
        suffix = f".{level}"
        if not chart_id.startswith(prefix) or not level or not chart_id.endswith(suffix):
            continue
        music_id = chart_id[len(prefix) : -len(suffix)]
        designers[(music_id, level)] = str(chart.get("designer") or "")
    discs: dict[str, str] = {}
    illustrations: dict[str, str] = {}
    series: dict[str, int] = {}
    for level in payload.get("levels") or []:
        music_id = str(level.get("musicId") or level.get("id") or "")
        if not music_id:
            continue
        discs[music_id] = str(level.get("discName") or "")
        illustrations[music_id] = str(level.get("illustrationId") or "")
        raw_series = level.get("seriesIndex")
        if isinstance(raw_series, int):
            series[music_id] = raw_series
    illustrators: dict[str, str] = {}
    for item in payload.get("illustrations") or []:
        illustration_id = str(item.get("id") or "")
        artist = str(item.get("artist") or "").strip()
        if illustration_id and artist:
            illustrators[illustration_id] = artist
    sp_charts: dict[str, dict] = {}
    for level in payload.get("discOLevels") or []:
        if str(level.get("difficultyName") or "") != "SP":
            continue
        music_id = str(level.get("musicId") or "")
        chart_ids = [str(chart_id) for chart_id in level.get("chartIds") or [] if chart_id]
        if not music_id or not chart_ids:
            continue
        sp_charts[music_id] = {
            "trackId": str(level.get("id") or ""),
            "levelText": str(level.get("difficultyText") or ""),
            "chartId": chart_ids[0],
            "designerKey": str(level.get("designerInfoKey") or ""),
        }
    return designers, discs, illustrations, illustrators, series, sp_charts


def read_bpm(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            head = handle.read(8192)
    except OSError:
        return None
    match = _BPM_RE.search(head)
    if match is None:
        return None
    value = round(float(match.group(1)), 2)
    return value if value > 0 else None


def song_bpm(charts_dir: Path, asset_id: str) -> float | None:
    for difficulty in DIFFICULTIES:
        path = charts_dir / f"chart.{asset_id}.{difficulty}.json"
        if not path.is_file():
            continue
        bpm = read_bpm(path)
        if bpm is not None:
            return bpm
    return None


def chart_end_beats(path: Path) -> float:
    best = 0.0
    try:
        handle = path.open("rb")
    except OSError:
        return 0.0
    with handle:
        previous = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            data = previous + chunk
            for match in _TIME_RE.finditer(data):
                best = max(best, float(match.group(1)))
            previous = data[-48:]
    return best


def song_length(charts_dir: Path, asset_id: str, bpm: float | None) -> float | None:
    if not bpm:
        return None
    charts = [
        path
        for difficulty in DIFFICULTIES
        if (path := charts_dir / f"chart.{asset_id}.{difficulty}.json").is_file()
    ]
    if not charts:
        return None
    beats = chart_end_beats(min(charts, key=lambda item: item.stat().st_size))
    if beats <= 0:
        return None
    return round(beats * 60.0 / bpm, 1)


def locale_script(root: Path) -> str:
    file_list = root / "download" / "fileList.json"
    bundle_name = "dfc26ebdd285d9dc61f6ee898b722aa9.bundle"
    if file_list.is_file():
        try:
            pairs = json.loads(file_list.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pairs = []
        for pair in pairs:
            if isinstance(pair, list) and len(pair) >= 2 and pair[0] == "local.en" and isinstance(pair[1], str):
                bundle_name = pair[1]
                break
    path = root / "download" / "bundles" / bundle_name
    if not path.is_file():
        return ""
    try:
        import UnityPy
    except ImportError:
        return ""
    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name != "TextAsset":
            continue
        data = obj.read()
        if getattr(data, "m_Name", "") not in {"", "en"}:
            continue
        script = data.m_Script
        if isinstance(script, (bytes, bytearray)):
            return bytes(script).decode("utf-8-sig", errors="replace")
        return str(script or "")
    return ""


def export_series_art(root: Path) -> int:
    file_list = root / "download" / "fileList.json"
    bundles = root / "download" / "bundles"
    destination = root / "output" / "series"
    if not file_list.is_file():
        print("fileList.json is missing; skipped series art")
        return 0
    try:
        import UnityPy
    except ImportError:
        print("UnityPy is missing; skipped series art")
        return 0
    try:
        pairs = json.loads(file_list.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read fileList.json: {type(exc).__name__}")
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    groups: dict[str, dict[str, tuple[str, Path]]] = {}
    for pair in pairs:
        if not (isinstance(pair, list) and len(pair) >= 2 and isinstance(pair[0], str) and isinstance(pair[1], str)):
            continue
        key = pair[0].strip()
        match = _SERIES_ART_RE.fullmatch(key)
        if match is None:
            continue
        bundle = bundles / pair[1].strip()
        if not bundle.is_file():
            print(f"Skipping {key}: bundle missing")
            continue
        canonical = f"series{match.group('kind')}.{match.group('number')}"
        groups.setdefault(canonical, {})[_art_language(match.group("lang") or "")] = (key, bundle)
    exported = 0
    for canonical, variants in groups.items():
        english = variants.get("en") or variants.get("")
        sources: dict[str, tuple[str, Path] | None] = {
            "en": english,
            # With an explicit English file, the unsuffixed art is Simplified Chinese.
            "zh-Hans": variants.get("zh-Hans") or (variants.get("") if "en" in variants else None),
            "zh-Hant": variants.get("zh-Hant"),
            "ja": variants.get("ja"),
        }
        for language, source in sources.items():
            if source is None:
                continue
            key, bundle = source
            if language != "en" and english is not None and bundle == english[1]:
                continue
            image = _largest_bundle_image(bundle)
            if image is None:
                print(f"Skipping {key}: no image")
                continue
            folder = destination if language == "en" else destination / language
            folder.mkdir(parents=True, exist_ok=True)
            image.save(folder / f"{canonical}.png")
            exported += 1
            print(f"Exported {canonical} [{language}] from {key}")
    exported += _export_embedded_posters(bundles, destination)
    print(f"Exported {exported} series images to {destination.name}.")
    return exported


def _art_language(suffix: str) -> str:
    cleaned = suffix.strip().lower()
    if cleaned in {"zh-hans", "cn"}:
        return "zh-Hans"
    if cleaned == "zh-hant":
        return "zh-Hant"
    if cleaned in {"ja", "jp"}:
        return "ja"
    return cleaned


def _largest_bundle_image(bundle: Path):
    try:
        import UnityPy
    except ImportError:
        return None
    try:
        environment = UnityPy.load(str(bundle))
    except Exception as exc:
        print(f"Skipping {bundle.name}: {type(exc).__name__}")
        return None
    best = None
    best_area = 0
    for obj in environment.objects:
        if obj.type.name not in {"Sprite", "Texture2D"}:
            continue
        try:
            image = obj.read().image
        except Exception:
            continue
        if image is None:
            continue
        area = image.width * image.height
        if area > best_area:
            best = image
            best_area = area
    return best


def _export_embedded_posters(bundles: Path, destination: Path) -> int:
    """Series 14 and later store the poster on the series prefab, not as seriesPoster.00014."""
    try:
        import UnityPy
    except ImportError:
        return 0
    large = sorted(
        (path for path in bundles.iterdir() if path.is_file() and path.stat().st_size >= 90_000_000),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    for bundle_path in large:
        try:
            environment = UnityPy.load(str(bundle_path))
        except Exception:
            continue
        bundle = environment.files.get(next(iter(environment.files), ""))
        if bundle is None:
            continue
        for name, item in getattr(bundle, "files", {}).items():
            if str(name).endswith(".resS"):
                environment.register_cab(str(name), item)
        by_id = {obj.path_id: obj for obj in environment.objects}
        default = _default_tree(by_id)
        if default is None:
            continue
        exported = 0
        for config in default.get("seriesConfigs") or []:
            if not isinstance(config, dict):
                continue
            index = config.get("seriesIndex")
            poster = config.get("poster") if isinstance(config.get("poster"), dict) else {}
            poster_id = poster.get("m_PathID")
            if not isinstance(index, int) or index < 14 or not poster_id:
                continue
            candidates = _poster_sprite_candidates(by_id, int(poster_id))
            if not candidates:
                print(f"Skipping seriesPoster.{index:05d}: sprite missing")
                continue
            filename = f"seriesPoster.{index:05d}.png"
            for language in _ART_LANGUAGES:
                sprite_id, sprite_name = _choose_sprite(candidates, language)
                sprite = by_id.get(sprite_id) if sprite_id else None
                if sprite is None:
                    continue
                try:
                    image = sprite.read().image
                except Exception as exc:
                    print(f"Skipping seriesPoster.{index:05d} [{language}]: {type(exc).__name__}")
                    continue
                if image is None:
                    continue
                folder = destination if language == "en" else destination / language
                folder.mkdir(parents=True, exist_ok=True)
                image.save(folder / filename)
                exported += 1
                print(f"Exported {filename} [{language}] ({sprite_name})")
        return exported
    print("Embedded series posters were not found")
    return 0


def _default_tree(by_id: dict):
    for obj in by_id.values():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if tree.get("m_Name") == "Default" and isinstance(tree.get("seriesConfigs"), list):
            return tree
    return None


def _sprite_rank(name: str, language: str) -> int:
    cleaned = name.strip().lower()
    if "pigeon" in cleaned:
        return 99
    is_en = bool(_ENGLISH_SPRITE.search(cleaned))
    is_hans = "zh-hans" in cleaned or "hans" in cleaned or "postercn" in cleaned.replace(" ", "") or cleaned.endswith("cn")
    is_hant = "zh-hant" in cleaned or "hant" in cleaned
    is_ja = bool(re.search(r"(?:^|[^a-z])(?:jp|ja)$", cleaned))
    marked = is_en or is_hans or is_hant or is_ja or "zh" in cleaned
    if language == "en" and is_en:
        return 0
    if language == "zh-Hans" and is_hans:
        return 0
    if language == "zh-Hant" and is_hant:
        return 0
    if language == "ja" and is_ja:
        return 0
    if not marked:
        return 1
    return 3


def _choose_sprite(candidates: dict[int, str], language: str) -> tuple[int | None, str]:
    best: tuple[int, int, str] | None = None
    for sprite_id, name in candidates.items():
        rank = _sprite_rank(name, language)
        if rank >= 3:
            continue
        if best is None or rank < best[0]:
            best = (rank, sprite_id, name)
    if best is None:
        return None, ""
    return best[1], best[2]


def _poster_sprite_candidates(by_id: dict, game_pid: int) -> dict[int, str]:
    game = by_id.get(game_pid)
    if game is None or game.type.name != "GameObject":
        return {}
    try:
        components = game.read_typetree().get("m_Component") or []
    except Exception:
        return {}
    transform_id = None
    for component in components:
        ref = component.get("component") or {}
        candidate = by_id.get(ref.get("m_PathID"))
        if candidate is not None and candidate.type.name in {"Transform", "RectTransform"}:
            transform_id = ref.get("m_PathID")
            break
    if transform_id is None:
        return {}
    found: dict[int, str] = {}

    def note(sprite_id: object) -> None:
        if not sprite_id:
            return
        sprite = by_id.get(int(sprite_id))
        name = ""
        if sprite is not None:
            try:
                name = str(sprite.read_typetree().get("m_Name") or "")
            except Exception:
                name = ""
        found.setdefault(int(sprite_id), name)

    def walk(current_id: int, parent: str) -> None:
        transform = by_id.get(current_id)
        if transform is None:
            return
        try:
            tree = transform.read_typetree()
        except Exception:
            return
        game_obj = by_id.get((tree.get("m_GameObject") or {}).get("m_PathID"))
        name = ""
        if game_obj is not None:
            try:
                game_tree = game_obj.read_typetree()
            except Exception:
                game_tree = {}
            name = str(game_tree.get("m_Name") or "")
            if name == "Image" and parent == "Poster":
                for component in game_tree.get("m_Component") or []:
                    ref = component.get("component") or {}
                    behaviour = by_id.get(ref.get("m_PathID"))
                    if behaviour is None or behaviour.type.name != "MonoBehaviour":
                        continue
                    try:
                        behaviour_tree = behaviour.read_typetree()
                    except Exception:
                        continue
                    note((behaviour_tree.get("m_Sprite") or {}).get("m_PathID"))
                    for entry in behaviour_tree.get("spriteFiles") or []:
                        image = entry.get("image") if isinstance(entry, dict) else None
                        note((image or {}).get("m_PathID"))
        for child in tree.get("m_Children") or []:
            child_id = (child or {}).get("m_PathID")
            if child_id:
                walk(int(child_id), name)

    walk(int(transform_id), "")
    return found


def disco_display_names(root: Path) -> dict[str, str]:
    file_list = root / "download" / "fileList.json"
    bundle_name = "dfc26ebdd285d9dc61f6ee898b722aa9.bundle"
    if file_list.is_file():
        try:
            pairs = json.loads(file_list.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pairs = []
        for pair in pairs:
            if isinstance(pair, list) and len(pair) >= 2 and pair[0] == "local.en" and isinstance(pair[1], str):
                bundle_name = pair[1]
                break
    path = root / "download" / "bundles" / bundle_name
    if not path.is_file():
        return {}
    try:
        import UnityPy
    except ImportError:
        return {}
    names: dict[str, str] = {}
    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name != "TextAsset":
            continue
        for line in str(obj.read().m_Script).splitlines():
            if not line.startswith("discoDisplay."):
                continue
            key, separator, value = line.partition("=")
            if separator and value:
                names[key] = value
    return names


def sp_chart_record(charts_dir: Path, spec: dict | None, designers: dict[str, str] | None = None) -> dict | None:
    if not spec:
        return None
    chart_id = str(spec.get("chartId") or "")
    path = charts_dir / f"{chart_id}.json"
    hit = combo = score = riz_hit = 0
    if path.is_file():
        from tools.pipelines.Riz_bundle import (
            apply_rizcol_ranges_to_notes,
            compute_hit_combo_score,
            extract_notes_from_chart_obj,
            extract_rizcol_from_chart_obj,
        )

        chart = json.loads(path.read_text(encoding="utf-8"))
        notes = extract_notes_from_chart_obj(chart)
        rizcol = extract_rizcol_from_chart_obj(chart)
        if rizcol and notes:
            notes = apply_rizcol_ranges_to_notes(rizcol, notes)
        hit, combo, score = compute_hit_combo_score(notes)
        riz_hit = max(0, (score - 1_000_000) // 100)
    return {
        "level": 0,
        "levelText": str(spec.get("levelText") or ""),
        "trackId": str(spec.get("trackId") or ""),
        "hit": hit,
        "combo": combo,
        "score": score,
        "rizHit": riz_hit,
        "designer": (designers or {}).get(str(spec.get("designerKey") or ""), ""),
    }


def load_database(path: Path) -> tuple[dict, dict]:
    designers: dict[tuple[str, str], str] = {}
    discs: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) < 10:
            continue
        asset_id, _name, _artist, difficulty, _constant, disc, _hit, _combo, _score, designer = columns[:10]
        designers[(asset_id, difficulty)] = designer
        discs[asset_id] = disc
    return designers, discs


def song_row(asset_id: str, title: str, songs_by_norm: dict[str, dict]) -> dict | None:
    return songs_by_norm.get(normalize(title))


def main() -> int:
    songs_path = ROOT / "songs.json"
    mapping_path = ROOT / "mapping.json"
    default_path = ROOT / "output" / "default.json"
    database_path = ROOT / "Database.txt"
    charts_dir = ROOT / "output" / "charts"
    output_path = ROOT / "bot" / "static" / "songs_index.json"

    songs = json.loads(songs_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(songs, list) or not isinstance(mapping, dict):
        print("songs.json must be a list and mapping.json must be an object", file=sys.stderr)
        return 1

    songs_by_norm: dict[str, dict] = {}
    for row in songs:
        for key in (row.get("Page") or "", row.get("Title") or ""):
            normalized = normalize(str(key))
            if normalized:
                songs_by_norm.setdefault(normalized, row)

    designers: dict[tuple[str, str], str] = {}
    discs: dict[str, str] = {}
    illustrations: dict[str, str] = {}
    illustrators: dict[str, str] = {}
    series: dict[str, int] = {}
    sp_charts: dict[str, dict] = {}
    sources = ["songs.json", "mapping.json"]
    if database_path.is_file():
        designers, discs = load_database(database_path)
        sources.append("Database.txt")
    if default_path.is_file():
        default_designers, default_discs, illustrations, illustrators, series, sp_charts = load_default(default_path)
        designers.update(default_designers)
        discs.update(default_discs)
        sources.append("output/default.json")
    if charts_dir.is_dir():
        sources.append("output/charts")
    sp_designers = disco_display_names(ROOT) if sp_charts else {}

    built: list[dict] = []
    missing_rows = 0
    for asset_id, title in mapping.items():
        if not isinstance(title, str):
            continue
        row = song_row(str(asset_id), title, songs_by_norm)
        if row is None:
            missing_rows += 1
            row = {}
        charts = {}
        for difficulty in DIFFICULTIES:
            raw_level = row.get(f"{difficulty} Lv") if row else None
            if raw_level is None or str(raw_level).strip() == "":
                continue
            charts[difficulty] = {
                "level": parse_float(raw_level),
                "hit": parse_int(row.get(f"{difficulty} Hit")),
                "combo": parse_int(row.get(f"{difficulty} Combo")),
                "score": parse_int(row.get(f"{difficulty} Score")),
                "rizHit": parse_int(row.get(f"{difficulty} RizHit")),
                "designer": designers.get((str(asset_id), difficulty), ""),
            }
        illustration_id = illustrations.get(str(asset_id)) or f"illustration.{asset_id}"
        item = {
            "assetId": str(asset_id),
            "title": str(row.get("Title") or title),
            "artist": str(row.get("Artist") or ""),
            "discName": discs.get(str(asset_id)) or str(row.get("discName") or ""),
            "illustrationId": illustration_id,
            "aliases": [],
            "charts": charts,
        }
        bpm = song_bpm(charts_dir, str(asset_id))
        if bpm is not None:
            item["bpm"] = bpm
        length = song_length(charts_dir, str(asset_id), bpm)
        if length is not None:
            item["length"] = length
        illustrator = illustrators.get(illustration_id, "")
        if illustrator:
            item["illustrator"] = illustrator
        series_index = series.get(str(asset_id))
        if isinstance(series_index, int) and series_index != -1:
            item["seriesIndex"] = series_index
            name = SERIES_NAMES.get(series_index, "")
            if name:
                item["seriesName"] = name
        sp_chart = sp_chart_record(charts_dir, sp_charts.get(str(asset_id)), sp_designers)
        if sp_chart is not None:
            charts["SP"] = sp_chart
        original = ORIGINALS.get(str(asset_id))
        if original is not None:
            item["original"] = original[0]
            if original[1]:
                item["originalWith"] = original[1]
        built.append(item)

    by_title = {normalize(item["title"]): item for item in built}
    for alias, target in ALIASES.items():
        item = by_title.get(normalize(target))
        if item is None:
            print(f"alias not matched: {alias}", file=sys.stderr)
            continue
        if alias not in item["aliases"]:
            item["aliases"].append(alias)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    configs = []
    if default_path.is_file():
        try:
            raw_configs = json.loads(default_path.read_text(encoding="utf-8")).get("seriesConfigs") or []
            configs = raw_configs if isinstance(raw_configs, list) else []
        except (OSError, json.JSONDecodeError):
            configs = []
    series = build_series_records(configs, built, SERIES_NAMES, bio_ids_from_locale(locale_script(ROOT)))
    payload = {
        "source": " + ".join(sources) + "; songs.json is canonical for chart constants",
        "songs": built,
        "series": series,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(built)} songs and {len(series)} series to {output_path.name}. Unmatched mapping rows: {missing_rows}.")
    export_series_art(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
