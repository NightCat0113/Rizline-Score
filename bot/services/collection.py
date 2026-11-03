"""Owned bios, layouts, and illustrations from the score cache plus local catalogs."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from bot.config import REPO_ROOT, catalog_dir
from bot.services.language import normalize_language
from bot.services.songdata import SongIndex
from bot.ui.textfont import one_line


def owned_item_ids(cache: dict) -> set[str] | None:
    """Return owned asset ids, or None when the cache predates collection tracking."""
    if "items" not in cache:
        return None
    result: set[str] = set()
    items = cache.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                asset = str(item.get("id") or item.get("itemAssetId") or "").strip()
            else:
                asset = str(item or "").strip()
            if asset:
                result.add(asset)
    return result


def collection_rows(
    repo_root: Path,
    language: str,
    kind: str,
    songs: SongIndex | None = None,
) -> list[dict[str, str]]:
    if kind == "bio":
        return _bio_rows(repo_root, language)
    if kind == "layout":
        return _layout_rows(repo_root)
    if kind == "illustration":
        return _illustration_rows(repo_root, songs)
    return []


def filter_collection(
    rows: list[dict[str, str]],
    owned: set[str],
    status: str,
    kind: str,
) -> tuple[list[dict[str, str]], int, int]:
    """Return filtered rows plus owned/total progress against the catalog."""
    mode = status if status in {"owned", "missing", "all"} else "all"
    if kind == "bio":
        return _filter_bios(rows, owned, mode)
    prefix = ("layout.",) if kind == "layout" else ("illustration.", "altIllustration.")
    return _filter_assets(rows, owned, mode, kind, prefix)


def _filter_bios(
    rows: list[dict[str, str]],
    owned: set[str],
    status: str,
) -> tuple[list[dict[str, str]], int, int]:
    slots = [slot for row in rows for slot in _bio_slots(row["id"])]
    owned_count = sum(1 for slot in slots if slot in owned)
    known = {row["id"] for row in rows}

    def held(row: dict[str, str]) -> bool:
        return any(slot in owned for slot in _bio_slots(row["id"]))

    if status == "owned":
        filtered = [row for row in rows if held(row)]
        filtered.extend(_extra_bios(owned, known))
    elif status == "missing":
        filtered = [row for row in rows if not held(row)]
    else:
        filtered = list(rows)
    return filtered, owned_count, len(slots)


def _filter_assets(
    rows: list[dict[str, str]],
    owned: set[str],
    status: str,
    kind: str,
    prefix: tuple[str, ...],
) -> tuple[list[dict[str, str]], int, int]:
    catalog_ids = {row["id"] for row in rows}
    owned_ids = {asset for asset in owned if asset.startswith(prefix)}
    owned_count = len(catalog_ids & owned_ids)
    if status == "owned":
        filtered = [row for row in rows if row["id"] in owned]
        extras = sorted(owned_ids - catalog_ids)
        if kind == "layout":
            extras = [asset for asset in extras if asset.removeprefix("layout.").isdigit()]
        filtered.extend({"id": asset, "kind": kind, "name": asset} for asset in extras)
    elif status == "missing":
        filtered = [row for row in rows if row["id"] not in owned]
    else:
        filtered = list(rows)
    return filtered, owned_count, len(catalog_ids)


def _extra_bios(owned: set[str], known: set[str]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    hidden = _cn_only_bio_stems()
    for asset in sorted(asset for asset in owned if asset.startswith("bio.")):
        stem, _slot = _split_bio(asset)
        if not stem or stem in known or stem in grouped or stem in hidden:
            continue
        grouped[stem] = {"id": stem, "kind": "bio", "title1": stem, "title2": "", "name": stem}
    return list(grouped.values())


@lru_cache(maxsize=1)
def _cn_only_bio_stems() -> frozenset[str]:
    """Bios that exist only on the Chinese server. International players cannot own them."""
    root = catalog_dir(REPO_ROOT)
    international = _catalog_stems(root / "bio_en.json")
    chinese = _catalog_stems(root / "bio.json") | _catalog_stems(root / "bio_zh-Hans.json")
    return frozenset(chinese - international)


def _catalog_stems(path: Path) -> set[str]:
    catalog = _catalog(path)
    return {stem for stem, entry in catalog.items() if isinstance(entry, dict)}


def _bio_slots(stem: str) -> tuple[str, str]:
    return f"bio.{stem}.1", f"bio.{stem}.2"


def _split_bio(asset_id: str) -> tuple[str, str]:
    rest = asset_id[4:] if asset_id.startswith("bio.") else asset_id
    if rest.endswith(".1") or rest.endswith(".2"):
        return rest[:-2], rest[-1]
    return rest, ""


def _bio_rows(repo_root: Path, language: str) -> list[dict[str, str]]:
    code = normalize_language(language)
    filenames = [f"bio_{code}.json", "bio_en.json", "bio.json"]
    root = catalog_dir(repo_root)
    catalogs = [_catalog(root / filename) for filename in filenames]
    hidden = _cn_only_bio_stems()
    stems = dict.fromkeys(
        stem
        for catalog in catalogs
        for stem, entry in catalog.items()
        if isinstance(entry, dict) and stem not in hidden
    )
    rows: list[dict[str, str]] = []
    for stem in stems:
        entry: dict = {}
        for catalog in reversed(catalogs):
            localized = catalog.get(stem)
            if isinstance(localized, dict):
                entry.update(localized)
        title1 = str(entry.get("title1") or "").strip()
        title2 = str(entry.get("title2") or "").strip()
        if not title1 and not title2:
            continue
        rows.append(
            {
                "id": str(stem),
                "kind": "bio",
                "title1": title1,
                "title2": title2,
                "name": " ".join(part for part in (title1, title2) if part),
            }
        )
    return rows


# 46–48 only have color swatches. 49 has a card but no layoutColors row.
_LAYOUT_PLACEHOLDERS = {"layout.00046", "layout.00047", "layout.00048"}
_LAYOUT_WITHOUT_COLORS = {"layout.00049"}


def _layout_rows(repo_root: Path) -> list[dict[str, str]]:
    payload = _catalog(catalog_dir(repo_root) / "layout.json")
    drawable = _drawable_layout_ids(repo_root)
    seen: set[str] = set()
    for row in payload.get("layoutColors") or []:
        if not isinstance(row, dict):
            continue
        layout_id = str(row.get("id") or "").strip()
        if layout_id:
            seen.add(layout_id)
    # Numbered cards only. layout.Static* are character rizcards, not collectible layouts.
    # Without a local file list (production), still drop 46–48 and keep 49.
    seen -= _LAYOUT_PLACEHOLDERS
    seen |= _LAYOUT_WITHOUT_COLORS
    if drawable:
        seen = (seen & drawable) | (drawable - _LAYOUT_PLACEHOLDERS) | _LAYOUT_WITHOUT_COLORS
    rows = [
        {"id": layout_id, "kind": "layout", "name": layout_id}
        for layout_id in sorted(seen, key=_layout_sort)
    ]
    return rows


def _drawable_layout_ids(repo_root: Path) -> set[str]:
    """Layout ids that have a frame or a rizcard prefab in the local file list."""
    found: set[str] = set()
    for entry in _json_list(repo_root / "download" / "fileList.json"):
        if not (isinstance(entry, list) and entry and isinstance(entry[0], str)):
            continue
        key = entry[0].strip()
        if key.startswith("layout.") and ".cn" not in key:
            layout_id = key.removesuffix(".HiRes")
            if layout_id.removeprefix("layout.").isdigit():
                found.add(layout_id)
        elif key.startswith("rizcard."):
            number = key.removeprefix("rizcard.")
            if number.isdigit():
                found.add(f"layout.{number}")
    return found


def _layout_sort(layout_id: str) -> tuple[int, int | str]:
    number = layout_id.rsplit(".", 1)[-1]
    if number.isdigit():
        return (0, int(number))
    return (1, layout_id)


def _illustration_rows(repo_root: Path, songs: SongIndex | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if songs is not None:
        for song in songs.songs:
            asset = song.illustration_id.strip()
            if not asset and song.asset_id:
                asset = f"illustration.{song.asset_id}"
            if asset and not asset.startswith("illustration."):
                asset = f"illustration.{asset}"
            if not asset or asset in seen:
                continue
            seen.add(asset)
            rows.append({"id": asset, "kind": "illustration", "name": one_line(song.title) or asset})
    for asset in _special_illustration_ids(repo_root):
        if asset in seen:
            continue
        seen.add(asset)
        rows.append({"id": asset, "kind": "illustration", "name": _special_name(asset, songs)})
    return rows


def special_illustration_ids(repo_root: Path) -> list[str]:
    """Every special illustration, without HiRes or region copies."""
    return _special_illustration_ids(repo_root)


def specials_catalog_path(repo_root: Path) -> Path:
    return repo_root / "bot" / "static" / "special_illustrations.json"


def write_special_illustrations(repo_root: Path) -> int:
    """Refresh the committed special-art catalog from download/fileList.json."""
    found = _specials_from_filelist(repo_root)
    if not found:
        return 0
    path = specials_catalog_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(found)


def _special_illustration_ids(repo_root: Path) -> list[str]:
    listed = _specials_from_filelist(repo_root)
    if listed:
        return listed
    return _specials_from_catalog(repo_root)


def _specials_from_filelist(repo_root: Path) -> list[str]:
    return _filter_special_keys(_json_list(repo_root / "download" / "fileList.json"))


def _specials_from_catalog(repo_root: Path) -> list[str]:
    path = specials_catalog_path(repo_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return _filter_special_keys([[item] for item in payload if isinstance(item, str)])


def _filter_special_keys(payload: object) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    if not isinstance(payload, (list, tuple)):
        return found
    for entry in payload:
        if not (isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], str)):
            continue
        key = entry[0].strip()
        if not key.startswith("altIllustration.") or key.endswith(".HiRes") or ".cn" in key or key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found


def song_art_rows(song, repo_root: Path) -> list[dict[str, str]]:
    """Default jacket plus any special arts for one song."""
    rows: list[dict[str, str]] = []
    asset = str(getattr(song, "illustration_id", "") or "").strip()
    if not asset and getattr(song, "asset_id", ""):
        asset = f"illustration.{song.asset_id}"
    if asset and not asset.startswith("illustration."):
        asset = f"illustration.{asset}"
    title = one_line(getattr(song, "title", "") or "") or asset
    if asset:
        rows.append({"id": asset, "kind": "illustration", "name": title})
    asset_id = str(getattr(song, "asset_id", "") or "").strip()
    for special in _special_illustration_ids(repo_root):
        rest = special[len("altIllustration.") :]
        if not _rest_matches_song(rest, asset_id):
            continue
        rows.append({"id": special, "kind": "illustration", "name": f"{title} (Special)"})
    return rows


def search_art_choices(
    songs: SongIndex,
    repo_root: Path,
    query: str,
    *,
    limit: int = 25,
) -> list[tuple[str, str]]:
    """Autocomplete rows as (label, value). Specials use '{title} (Special) - composer'."""
    cleaned = query.strip()
    choices: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: str) -> None:
        if value in seen or len(choices) >= limit:
            return
        seen.add(value)
        choices.append((one_line(label)[:100], value[:100]))

    if cleaned.startswith("altIllustration.") and cleaned in set(_special_illustration_ids(repo_root)):
        add(_art_choice_label(cleaned, songs), cleaned)
        return choices

    for song in songs.search(cleaned, limit=limit):
        add(_song_choice_label(song), song.asset_id)
        for row in song_art_rows(song, repo_root):
            if row["id"].startswith("altIllustration."):
                add(_art_choice_label(row["id"], songs), row["id"])

    needle = re.sub(r"[^a-z0-9]", "", cleaned.lower())
    if needle and len(choices) < limit:
        for asset in _special_illustration_ids(repo_root):
            if asset in seen:
                continue
            label = _art_choice_label(asset, songs)
            hay = re.sub(r"[^a-z0-9]", "", label.lower())
            if needle in hay or "special" in needle and needle.replace("special", "") in hay:
                add(label, asset)
            if len(choices) >= limit:
                break
    return choices[:limit]


def resolve_art_query(
    songs: SongIndex,
    repo_root: Path,
    query: str,
) -> tuple[list[dict[str, str]], list]:
    """Return art rows to show, or ambiguous song candidates."""
    cleaned = query.strip()
    if cleaned.startswith("altIllustration."):
        if cleaned.endswith(".HiRes") or ".cn" in cleaned:
            return [], []
        known = set(_special_illustration_ids(repo_root))
        if cleaned not in known:
            return [], []
        return [{"id": cleaned, "kind": "illustration", "name": _special_name(cleaned, songs)}], []
    song, candidates = songs.resolve(cleaned)
    if song is None:
        return [], candidates
    return song_art_rows(song, repo_root), []


def _song_choice_label(song) -> str:
    title = one_line(getattr(song, "title", "") or "") or song.asset_id
    artist = one_line(getattr(song, "artist", "") or "")
    return f"{title} - {artist}" if artist else title


def _art_choice_label(asset_id: str, songs: SongIndex | None) -> str:
    rest = asset_id[len("altIllustration.") :] if asset_id.startswith("altIllustration.") else asset_id
    song = _song_for_special(rest, songs)
    if song is not None:
        title = one_line(song.title) or song.asset_id
        artist = one_line(song.artist or "")
        label = f"{title} (Special)"
        return f"{label} - {artist}" if artist else label
    return _special_name(asset_id, songs)


def _special_name(asset_id: str, songs: SongIndex | None) -> str:
    rest = asset_id[len("altIllustration.") :]
    song = _song_for_special(rest, songs)
    if song is not None:
        title = one_line(song.title) or song.asset_id
        return f"{title} (Special)"
    label = rest.split(".", 1)[0] or asset_id
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label).replace("_", " ")
    return f"{spaced} (Special)"


def _song_for_special(rest: str, songs: SongIndex | None):
    if songs is None:
        return None
    candidate = rest
    while candidate:
        song = songs.by_asset.get(candidate)
        if song is not None:
            return song
        if "." not in candidate:
            return None
        candidate = candidate.rsplit(".", 1)[0]
    return None


def _rest_matches_song(rest: str, asset_id: str) -> bool:
    if not asset_id:
        return False
    candidate = rest
    while candidate:
        if candidate == asset_id:
            return True
        if "." not in candidate:
            return False
        candidate = candidate.rsplit(".", 1)[0]
    return False


@lru_cache(maxsize=4)
def _json_list(path: Path) -> tuple:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(payload) if isinstance(payload, list) else ()


@lru_cache(maxsize=16)
def _catalog(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
