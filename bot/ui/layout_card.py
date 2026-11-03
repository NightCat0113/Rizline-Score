"""Layout cards for the collection grid.

Empty arts windows are filled with the blank-card env stripe texture. Frames come
from layout bundles; prefab ornaments (particles, decorative avatars, baked
scenes) are layered on top without redrawing the card chrome.
"""

from __future__ import annotations

import base64
import json
import math
import random
import struct
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from bot.ui.b40_image import load_layout_frame


_LOCK = threading.Lock()
_CARDS: dict[tuple[str, str], Image.Image | None] = {}
_PREFAB: dict[str, Path] | None = None
_PREFAB_DEPS: dict[str, tuple[Path, ...]] | None = None
_ENV_FILL: Image.Image | None = None
_ENV_FILL_READY = False
# Skip player chrome only. Layout ornaments are often named "Avatar" (e.g. 00031's sun).
# ShadowContainer / "shadow" are applied afterwards as a soft edge vignette — stamping
# the raw sprite on top greys out pale cards like 00031.
_SKIP_OBJECTS = {"cover", "name", "text", "shadowcontainer", "mask"}
# Layout 00042: CoverOverlay is real chrome under Cover; CoverBG frosts over bg_00.
_COVER_ART_SPRITES = {"coveroverlay"}
# Player HUD roots (00042) sit on Y-rotated 3D panels — flat 2D stamps land off-card.
_PLAYER_CHROME_ROOTS = {"avatarcontainer", "namecontainer", "biocontainer"}
# Full-card soft shadows are applied as a vignette after the base layers. Small
# local shadows (layout 00036) still draw as normal sprites.
_SKIP_SPRITES = {"默认头像"}
_FULL_SHADOW_SPRITES = {"shadow"}
# When a real frame already carries chrome + env fill, only keep decorative extras.
_ORNAMENT_OBJECTS = {
    "avatardecorative",
    "biobg",
    "grad",
    "overlay",
    "particles",
    "textglow",
}
_ORNAMENT_SKIP_SPRITES = {"coverbg", "shadow", "默认头像", "空白卡"}
# Own mid-art (36 character plate, 42 hallway+cover, 45 purple kalpa plate).
_SKIP_ENV_LAYOUTS = {"00036", "00042", "00045"}
# Drawn after the soft vignette so bottom chrome stays above the wash and the
# ornament avatar stays on top of that chrome (layout 00031).
_FRONT_AFTER_SHADOW = {"bottompanel"}
_KALPA_PARTICLE_COUNT = 14
_KALPA_PARTICLE_COLOR = (188, 109, 255)  # Color(0.7372, 0.4274, 1) from ParticleInit.lua


def load_collection_layout(repo_root: Path, layout_id: str) -> Image.Image | None:
    """Layout art for the collection grid.

    Prefers ``output/layouts/*.png`` (baked for production without game bundles).
    Otherwise composites from local download frames/prefabs.
    """
    key = (str(repo_root), layout_id.strip())
    with _LOCK:
        if key in _CARDS:
            image = _CARDS[key]
            return None if image is None else image.copy()
    baked = _load_baked_layout(repo_root, layout_id)
    if baked is not None:
        with _LOCK:
            _CARDS[key] = baked.copy()
        return baked
    image = _render_collection_layout(repo_root, layout_id)
    with _LOCK:
        _CARDS[key] = None if image is None else image.copy()
    return None if image is None else image.copy()


def bake_collection_layouts(
    repo_root: Path,
    layout_ids: list[str] | None = None,
) -> tuple[int, int]:
    """Write ``output/layouts/layout.NNNNN.png`` for production deploys. Returns (ok, failed)."""
    from bot.services.collection import collection_rows

    ids = layout_ids or [row["id"] for row in collection_rows(repo_root, "en", "layout")]
    out_dir = _layouts_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _CARDS.clear()
    ok = 0
    failed = 0
    for layout_id in ids:
        image = _render_collection_layout(repo_root, layout_id)
        if image is None:
            failed += 1
            continue
        try:
            image.save(_baked_layout_path(repo_root, layout_id), format="PNG", optimize=True)
            ok += 1
        except OSError:
            failed += 1
        finally:
            image.close()
    with _LOCK:
        _CARDS.clear()
    return ok, failed


def _layouts_dir(repo_root: Path) -> Path:
    return repo_root / "output" / "layouts"


def _baked_layout_path(repo_root: Path, layout_id: str) -> Path:
    name = layout_id.strip()
    if not name.startswith("layout."):
        name = f"layout.{name}"
    return _layouts_dir(repo_root) / f"{name}.png"


def _load_baked_layout(repo_root: Path, layout_id: str) -> Image.Image | None:
    path = _baked_layout_path(repo_root, layout_id)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except OSError:
        return None


def _render_collection_layout(repo_root: Path, layout_id: str) -> Image.Image | None:
    """Composite from download frames/prefabs. No baked-PNG or memory cache."""
    number = layout_id.rsplit(".", 1)[-1]
    bundle = _prefab_bundle(repo_root, layout_id)
    deps = _prefab_dependencies(repo_root, layout_id)
    use_env = number not in _SKIP_ENV_LAYOUTS
    env_fill = _env_fill_texture(repo_root) if use_env else None
    frame = load_layout_frame(repo_root, layout_id)
    if frame is not None:
        card = _with_env_arts(frame, env_fill) if use_env else frame.convert("RGBA")
        frame.close()
        if bundle is not None:
            ornamented = _composite(bundle, card, deps, ornaments_only=True)
            if ornamented is not None:
                card.close()
                card = ornamented
            if number == "00045":
                particled = _stamp_kalpa_particles(card, bundle, deps)
                if particled is not card:
                    card.close()
                    card = particled
        return card
    image = _composite(bundle, None, deps) if bundle is not None else None
    if image is not None and use_env and env_fill is not None:
        filled = _with_env_arts(image, env_fill)
        image.close()
        image = filled
    return image


def _env_fill_texture(repo_root: Path) -> Image.Image | None:
    """Blank-card stripe used as the collection arts-window fill."""
    global _ENV_FILL, _ENV_FILL_READY
    with _LOCK:
        if _ENV_FILL_READY:
            return None if _ENV_FILL is None else _ENV_FILL.copy()
    image: Image.Image | None = None
    debug = repo_root / "output" / "_debug_31env_Texture2D_x_512.png"
    if debug.is_file():
        try:
            image = Image.open(debug).convert("RGBA")
        except OSError:
            image = None
    if image is None:
        image = _extract_blank_card(repo_root)
    with _LOCK:
        _ENV_FILL = image
        _ENV_FILL_READY = True
    return None if image is None else image.copy()


def _extract_blank_card(repo_root: Path) -> Image.Image | None:
    """Pull 空白卡 from any local rizcard dependency pack."""
    try:
        import UnityPy
    except ImportError:
        return None
    _prefab_index(repo_root)
    with _LOCK:
        deps = list((_PREFAB_DEPS or {}).values())
    seen: set[Path] = set()
    for group in deps:
        for path in group:
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            try:
                env = UnityPy.load(str(path))
            except Exception:
                continue
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    data = obj.read()
                    if str(getattr(data, "m_Name", "") or "") != "空白卡":
                        continue
                    texture = data.image
                except Exception:
                    continue
                if texture is not None:
                    return texture.convert("RGBA")
    return None


def _with_env_arts(frame: Image.Image, env_fill: Image.Image | None) -> Image.Image:
    """Put env stripes under the frame; punch flat grey/dark arts panels first."""
    chrome = _punch_placeholder_panel(frame)
    if env_fill is None:
        return chrome
    base = _cover_rgba(env_fill, frame.size)
    base.alpha_composite(chrome)
    chrome.close()
    return base


def _cover_rgba(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    scale = max(width / max(1, image.width), height / max(1, image.height))
    resized = image.resize(
        (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _stamp_kalpa_particles(
    canvas: Image.Image,
    bundle: Path,
    dependencies: tuple[Path, ...] = (),
) -> Image.Image:
    """Bake layout 00045's Lua-driven Kalpa triangle particles into a still frame."""
    sprites = _load_named_sprites(bundle, dependencies, ("KalpaParticle1", "KalpaParticle2", "KalpaParticle3"))
    if not sprites:
        return canvas
    width, height = canvas.size
    rng = random.Random(45)
    result = canvas.copy()
    # Mirror ParticleInit.lua: Length-2 particle slots, random pose, purple tint.
    for _ in range(_KALPA_PARTICLE_COUNT):
        art = sprites[rng.randrange(len(sprites))].copy()
        size = (rng.randint(100, 500), rng.randint(100, 500))
        art = art.resize(size, Image.Resampling.LANCZOS)
        angle = rng.uniform(0, 360)
        art = art.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)
        alpha = rng.uniform(0.3, 0.8)
        # Mid-life opacity peak from Clamp01((10 - abs(ttl - 10)) / 1.5) with ttl in 0..20.
        ttl = rng.random() * 20
        fade = max(0.0, min(1.0, (10.0 - abs(ttl - 10.0)) / 1.5))
        strength = alpha * fade
        if strength < 0.05:
            continue
        tinted = Image.new("RGBA", art.size, (*_KALPA_PARTICLE_COLOR, 255))
        tinted.putalpha(art.getchannel("A").point(lambda value: int(value * strength)))
        # Unity anchoredPosition is bottom-left origin; Pillow paste is top-left.
        x = int(rng.random() * width - tinted.width / 2)
        y = int(height - rng.random() * height - tinted.height / 2)
        _stamp(result, tinted, x, y)
    return result


def _load_named_sprites(
    bundle: Path,
    dependencies: tuple[Path, ...],
    names: tuple[str, ...],
) -> list[Image.Image]:
    try:
        import UnityPy
    except ImportError:
        return []
    try:
        env = UnityPy.Environment()
        env.load_file(str(bundle))
        for path in dependencies:
            if path.resolve() == bundle.resolve():
                continue
            try:
                env.load_file(str(path))
            except Exception:
                continue
    except Exception:
        return []
    wanted = set(names)
    found: dict[str, Image.Image] = {}
    for obj in env.objects:
        if obj.type.name not in {"Sprite", "Texture2D"}:
            continue
        try:
            data = obj.read()
            name = str(getattr(data, "m_Name", "") or "")
            if name not in wanted or name in found:
                continue
            image = data.image
        except Exception:
            continue
        if image is not None:
            found[name] = image.convert("RGBA")
    return [found[name] for name in names if name in found]


def _punch_placeholder_panel(frame: Image.Image, *, tolerance: int = 22) -> Image.Image:
    """Clear flat grey arts panels (e.g. 37) so env can show. Never punch chromatic BGs like 45."""
    width, height = frame.size
    cx, cy = width // 2, height // 3
    red, green, blue, alpha = frame.getpixel((cx, cy))
    if alpha < 16:
        return frame.copy()
    chroma = max(red, green, blue) - min(red, green, blue)
    luma = (red + green + blue) / 3
    # Seed only — character ornaments may sit in a local patch and inflate variance.
    flat_grey = chroma < 14 and 40 <= luma <= 210
    if not flat_grey:
        return frame.copy()
    seed_rgb = Image.new("RGB", (width, height), (red, green, blue))
    diff = ImageChops.difference(frame.convert("RGB"), seed_rgb).convert("L")
    candidates = ImageChops.multiply(
        diff.point(lambda value: 255 if value <= tolerance else 0),
        frame.getchannel("A").point(lambda value: 255 if value > 8 else 0),
    )
    if candidates.getpixel((cx, cy)) != 255:
        return frame.copy()
    ImageDraw.floodfill(candidates, (cx, cy), 128, thresh=0)
    hole = candidates.point(lambda value: 255 if value == 128 else 0)
    # Ignore tiny accidental matches; arts windows are a large share of the card.
    hole_ratio = sum(hole.getpixel((x, y)) for y in range(0, height, 12) for x in range(0, width, 12)) / (
        255 * max(1, ((width + 11) // 12) * ((height + 11) // 12))
    )
    if hole_ratio < 0.08:
        return frame.copy()
    channels = list(frame.split())
    channels[3] = ImageChops.subtract(channels[3], hole)
    return Image.merge("RGBA", channels)


def _prefab_bundle(repo_root: Path, layout_id: str) -> Path | None:
    number = layout_id.rsplit(".", 1)[-1]
    if not number.isdigit():
        return None
    path = _prefab_index(repo_root).get(number)
    if path is None or not path.is_file():
        return None
    return path


def _prefab_dependencies(repo_root: Path, layout_id: str) -> tuple[Path, ...]:
    number = layout_id.rsplit(".", 1)[-1]
    if not number.isdigit():
        return ()
    _prefab_index(repo_root)
    with _LOCK:
        deps = (_PREFAB_DEPS or {}).get(number, ())
    return tuple(path for path in deps if path.is_file())


def _prefab_index(repo_root: Path) -> dict[str, Path]:
    global _PREFAB, _PREFAB_DEPS
    with _LOCK:
        if _PREFAB is not None and _PREFAB_DEPS is not None:
            return _PREFAB
    chosen, deps = _read_prefab_index(repo_root)
    with _LOCK:
        _PREFAB = chosen
        _PREFAB_DEPS = deps
    return chosen


def _read_prefab_index(repo_root: Path) -> tuple[dict[str, Path], dict[str, tuple[Path, ...]]]:
    """Largest local rizcard bundle for each layout number, plus its dependency packs."""
    catalog_path = repo_root / "download" / "catalog_catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    try:
        rows, ids, entry_bytes = _catalog_rows(catalog)
    except (KeyError, ValueError, struct.error):
        return {}, {}
    layout_files = _layout_bundle_names(repo_root)
    counts: dict[str, int] = {}
    deps: list[tuple[str, list[str]]] = []
    for key, positions in rows:
        if not (isinstance(key, str) and key.startswith("rizcard.")):
            continue
        number = key.split(".")[-1]
        if not number.isdigit() or not positions:
            continue
        files = _dependency_files(rows, ids, entry_bytes, positions[0])
        deps.append((number, files))
        for name in files:
            counts[name] = counts.get(name, 0) + 1
    shared = {name for name, count in counts.items() if count >= 5}
    chosen: dict[str, Path] = {}
    dep_paths: dict[str, tuple[Path, ...]] = {}
    root = repo_root / "download" / "bundles"
    for number, files in deps:
        best: Path | None = None
        best_size = -1
        resolved = tuple(root / name for name in files if (root / name).is_file())
        dep_paths[number] = resolved
        for name in files:
            if name in shared or name in layout_files.get(number, set()):
                continue
            path = root / name
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > best_size:
                best = path
                best_size = size
        if best is not None:
            chosen[number] = best
    return chosen, dep_paths


def _layout_bundle_names(repo_root: Path) -> dict[str, set[str]]:
    path = repo_root / "download" / "fileList.json"
    grouped: dict[str, set[str]] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return grouped
    if not isinstance(payload, list):
        return grouped
    for entry in payload:
        if not (isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str) and isinstance(entry[1], str)):
            continue
        if not entry[1].endswith(".bundle"):
            continue
        stem = entry[0].removesuffix(".HiRes")
        if not stem.startswith("layout."):
            continue
        number = stem.split(".")[-1]
        if number.isdigit():
            grouped.setdefault(number, set()).add(entry[1])
    return grouped


def _catalog_rows(catalog: dict) -> tuple[list[tuple[object, list[int]]], list, bytes]:
    key_bytes = base64.b64decode(catalog["m_KeyDataString"])
    bucket_bytes = base64.b64decode(catalog["m_BucketDataString"])
    entry_bytes = base64.b64decode(catalog["m_EntryDataString"])
    ids = catalog.get("m_InternalIds")
    if not isinstance(ids, list):
        raise ValueError("catalog has no internal ids")

    def read_i(data: bytes, offset: int) -> int:
        return struct.unpack_from("<i", data, offset)[0]

    def key_at(key_pos: int) -> object:
        if not 0 <= key_pos < len(key_bytes):
            return None
        kind = key_bytes[key_pos]
        current = key_pos + 1
        if kind in (0, 1) and current + 4 <= len(key_bytes):
            length = key_bytes[current]
            current += 4
            raw = key_bytes[current : current + length]
            return raw.decode("utf-8" if kind == 0 else "utf-16-le", "ignore")
        return None

    count = read_i(bucket_bytes, 0)
    offset = 4
    rows: list[tuple[object, list[int]]] = []
    for _ in range(count):
        key_pos = read_i(bucket_bytes, offset)
        entry_count = read_i(bucket_bytes, offset + 4)
        offset += 8
        positions = []
        for _entry in range(entry_count):
            positions.append(read_i(bucket_bytes, offset))
            offset += 4
        rows.append((key_at(key_pos), positions))
    return rows, ids, entry_bytes


def _dependency_files(
    rows: list[tuple[object, list[int]]],
    ids: list,
    entry_bytes: bytes,
    entry_pos: int,
) -> list[str]:
    if entry_pos < 0:
        return []
    start = 4 + 28 * entry_pos
    if start + 12 > len(entry_bytes):
        return []
    dep = struct.unpack_from("<i", entry_bytes, start + 8)[0]
    if not 0 <= dep < len(rows):
        return []
    _key, positions = rows[dep]
    files: list[str] = []
    for pos in positions:
        loc = 4 + 28 * pos
        if loc + 4 > len(entry_bytes):
            continue
        internal = struct.unpack_from("<i", entry_bytes, loc)[0]
        if not 0 <= internal < len(ids):
            continue
        value = ids[internal]
        if isinstance(value, str) and value.endswith(".bundle"):
            files.append(value.rsplit("/", 1)[-1])
    return files


def _composite(
    bundle: Path,
    frame: Image.Image | None,
    dependencies: tuple[Path, ...] = (),
    *,
    ornaments_only: bool = False,
) -> Image.Image | None:
    try:
        import UnityPy
    except ImportError:
        return frame
    try:
        env = UnityPy.Environment()
        env.load_file(str(bundle))
        for path in dependencies:
            if path.resolve() == bundle.resolve():
                continue
            try:
                env.load_file(str(path))
            except Exception:
                continue
    except Exception:
        try:
            env = UnityPy.load(str(bundle))
        except Exception:
            return frame
    names: dict[int, str] = {}
    rects: dict[int, dict] = {}
    images: list[dict] = []
    borders: list[dict] = []
    main_file = _main_serialized(env, bundle)
    main_name = str(getattr(main_file, "name", "") or "")
    sprites = _sprite_tables(env, main_file)
    for obj in env.objects:
        if obj.type.name == "GameObject":
            if not _same_assets(obj, main_file, main_name):
                continue
            try:
                names[obj.path_id] = str(obj.read().m_Name)
            except Exception:
                continue
        elif obj.type.name == "RectTransform":
            if not _same_assets(obj, main_file, main_name):
                continue
            try:
                rects[obj.path_id] = obj.read_typetree()
            except Exception:
                continue
        elif obj.type.name == "MonoBehaviour":
            if not _same_assets(obj, main_file, main_name):
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if isinstance(tree.get("m_Sprite"), dict) or "m_FillCenter" in tree:
                images.append(tree)
            if "radius" in tree and "thickness" in tree:
                borders.append(tree)
    if not rects:
        return frame
    roots = [path_id for path_id, tree in rects.items() if _pointer(tree.get("m_Father")) not in rects]
    if not roots:
        roots = list(rects)
    root = max((rects[path_id] for path_id in roots), key=_size_area)
    card_w = max(1, int(abs(root["m_SizeDelta"]["x"])))
    card_h = max(1, int(abs(root["m_SizeDelta"]["y"])))
    if card_w < 64 or card_h < 64:
        return frame
    canvas = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    if frame is not None:
        pasted = frame.convert("RGBA").resize((card_w, card_h), Image.Resampling.LANCZOS)
        canvas.alpha_composite(pasted)
    order = _child_order(rects)
    front_queue: list[tuple[int, tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    for root_id in roots:
        _draw_branch(
            canvas,
            root_id,
            (float(card_w), float(card_h)),
            (0.0, 0.0),
            (1.0, 1.0),
            rects,
            names,
            images,
            borders,
            sprites,
            order,
            root=True,
            ornaments_only=ornaments_only,
            front_queue=None if ornaments_only else front_queue,
        )
    if canvas.getchannel("A").getextrema()[1] < 16:
        return frame
    if ornaments_only:
        return canvas
    canvas = _soft_shadow_vignette(canvas, sprites)
    for path_id, parent_size, origin, parent_scale in front_queue:
        _draw_branch(
            canvas,
            path_id,
            parent_size,
            origin,
            parent_scale,
            rects,
            names,
            images,
            borders,
            sprites,
            order,
            ornaments_only=False,
            front_queue=None,
        )
    return canvas


def _main_serialized(env, bundle: Path):
    target = bundle.name.lower()
    for name, file in getattr(env, "files", {}).items():
        nested = getattr(file, "files", None)
        if not nested:
            continue
        if target not in str(name).lower().replace("\\", "/"):
            continue
        for inner in nested.values():
            if type(inner).__name__ == "SerializedFile":
                return inner
    for file in getattr(env, "files", {}).values():
        nested = getattr(file, "files", None) or {}
        for inner in nested.values():
            if type(inner).__name__ == "SerializedFile":
                return inner
    return None


def _same_assets(obj, main_file, main_name: str) -> bool:
    if main_file is None:
        return True
    assets = getattr(obj, "assetsfile", None)
    if assets is None:
        return True
    if assets is main_file:
        return True
    return bool(main_name) and str(getattr(assets, "name", "") or "") == main_name


def _sprite_tables(env, main_file) -> dict[tuple[int, int], object]:
    """Map (FileID, PathID) and (0, PathID) to Sprite objects across loaded bundles."""
    cab_to_fileid: dict[str, int] = {}
    if main_file is not None:
        for index, external in enumerate(getattr(main_file, "externals", []) or [], start=1):
            path = str(getattr(external, "path", "") or getattr(external, "name", "") or "")
            cab = path.replace("\\", "/").rsplit("/", 1)[-1]
            if cab:
                lowered = cab.lower()
                cab_to_fileid[lowered] = index
                cab_to_fileid[lowered.removesuffix(".ress")] = index
    tables: dict[tuple[int, int], object] = {}
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        assets = getattr(obj, "assetsfile", None)
        file_id = 0
        if assets is not None and main_file is not None and assets is not main_file:
            asset_name = str(getattr(assets, "name", "") or getattr(assets, "path", "") or "").lower()
            for cab, mapped in cab_to_fileid.items():
                if cab and cab in asset_name:
                    file_id = mapped
                    break
        tables[(file_id, obj.path_id)] = obj
        # PathIDs for shared UI sprites are unique enough to resolve without FileID.
        tables.setdefault((0, obj.path_id), obj)
        tables.setdefault((-1, obj.path_id), obj)
    return tables


def _size_area(tree: dict) -> float:
    size = tree.get("m_SizeDelta") or {}
    return float(size.get("x") or 0) * float(size.get("y") or 0)


def _child_order(rects: dict[int, dict]) -> dict[int, list[int]]:
    order: dict[int, list[int]] = {}
    for path_id, tree in rects.items():
        kids = []
        for child in tree.get("m_Children") or []:
            if isinstance(child, dict) and child.get("m_FileID") in (0, None) and child.get("m_PathID") in rects:
                kids.append(child["m_PathID"])
        order[path_id] = kids
    return order


def _draw_branch(
    canvas: Image.Image,
    path_id: int,
    parent_size: tuple[float, float],
    origin: tuple[float, float],
    parent_scale: tuple[float, float],
    rects: dict[int, dict],
    names: dict[int, str],
    images: list[dict],
    borders: list[dict],
    sprites: dict[tuple[int, int], object],
    order: dict[int, list[int]],
    *,
    root: bool = False,
    ornaments_only: bool = False,
    front_queue: list[tuple[int, tuple[float, float], tuple[float, float], tuple[float, float]]] | None = None,
) -> None:
    tree = rects[path_id]
    if root:
        size = tree.get("m_SizeDelta") or {}
        box = (0.0, 0.0, abs(float(size.get("x") or 0)), abs(float(size.get("y") or 0)))
        child_origin = (0.0, 0.0)
        child_scale = (1.0, 1.0)
        child_parent = (box[2], box[3])
    else:
        local = _local_rect(parent_size, tree)
        box, child_origin, child_scale = _scaled_box(local, tree, origin, parent_scale)
        child_parent = (local[2], local[3])
    go = _pointer(tree.get("m_GameObject"))
    name = names.get(go or -1, "")
    lowered = name.strip().lower()
    # 00042 Avatar/Name/Bio containers are player HUD on Y-rotated panels.
    if lowered in _PLAYER_CHROME_ROOTS:
        return
    # Player portrait Avatars nest Mask/Border — skip the whole slot, including a
    # parent Image plate (layout 00036's white square). Ornament Avatars (00031's
    # sun, etc.) are leaves that still must draw.
    if _is_portrait_avatar(name, path_id, order, rects, names) or _hosts_portrait_avatar(
        path_id, order, rects, names
    ):
        return
    if front_queue is not None and _defer_until_after_shadow(name, path_id, order, rects, names):
        front_queue.append((path_id, parent_size, origin, parent_scale))
        return
    # Layout 00036 Mask1/Mask2: Gardenofeden is a UI Mask graphic (ShowMaskGraphic).
    # Draw the grid on the canvas, but clip children to its alpha so their solid
    # washes cannot erase debris (00036_2).
    mask_clip = name.strip().lower() in {"mask1", "mask2"} and not ornaments_only
    stencil: Image.Image | None = None
    skip = _skip_object(name, ornaments_only=ornaments_only)
    if not skip or _has_cover_art(go, images, sprites):
        for image in images:
            if _pointer(image.get("m_GameObject")) != go:
                continue
            if skip and not _image_is_cover_art(image, sprites):
                continue
            if mask_clip:
                stencil = _draw_image(
                    canvas,
                    image,
                    tree,
                    box,
                    sprites,
                    ornaments_only=ornaments_only,
                    return_stencil=True,
                )
            else:
                _draw_image(canvas, image, tree, box, sprites, ornaments_only=ornaments_only)
        if not skip and not ornaments_only:
            for border in borders:
                if _pointer(border.get("m_GameObject")) != go:
                    continue
                _draw_border(canvas, border, box)
    child_canvas = canvas
    child_layer: Image.Image | None = None
    if mask_clip:
        child_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        child_canvas = child_layer
    kids = list(order.get(path_id, []))
    # Official 00036: opaque white Gardenofeden tiles sit above debris + characters.
    if name.strip().lower() == "mask":
        kids = _draw_order_grid_on_top(kids, rects, names)
    for child in kids:
        _draw_branch(
            child_canvas,
            child,
            child_parent,
            child_origin,
            child_scale,
            rects,
            names,
            images,
            borders,
            sprites,
            order,
            ornaments_only=ornaments_only,
            front_queue=front_queue,
        )
    if mask_clip and child_layer is not None:
        _composite_with_stencil(canvas, child_layer, stencil)


def _draw_image(
    canvas: Image.Image,
    image: dict,
    tree: dict,
    box: tuple[float, float, float, float],
    sprites: dict[tuple[int, int], object],
    *,
    ornaments_only: bool = False,
    return_stencil: bool = False,
) -> Image.Image | None:
    _x, _y, width, height = box
    if width < 2 or height < 2:
        return None
    color = image.get("m_Color") or {}
    alpha = float(color.get("a", 1) or 0)
    if alpha <= 0:
        return None
    pointer = image.get("m_Sprite") if isinstance(image.get("m_Sprite"), dict) else None
    art: Image.Image | None = None
    sprite_name = ""
    if pointer and pointer.get("m_PathID"):
        path_id = pointer.get("m_PathID")
        file_id = int(pointer.get("m_FileID") or 0)
        obj = sprites.get((file_id, path_id)) or sprites.get((0, path_id)) or sprites.get((-1, path_id))
        if obj is not None:
            try:
                data = obj.read()
                sprite_name = str(getattr(data, "m_Name", "") or "")
                skipped = _ORNAMENT_SKIP_SPRITES if ornaments_only else _SKIP_SPRITES
                lowered_sprite = sprite_name.lower()
                if lowered_sprite in skipped:
                    return None
                # Full-card shadow sheets become the post-pass vignette; local shadows draw here.
                if (
                    not ornaments_only
                    and lowered_sprite in _FULL_SHADOW_SPRITES
                    and _is_full_card_shadow(width, height, canvas.size)
                ):
                    return None
                # Layout-number sheet (00045, 00037, …) is chrome already on the frame.
                if ornaments_only and sprite_name.isdigit():
                    return None
                art = data.image
            except Exception:
                art = None
    if art is None:
        # Solid panels only — skip full-card white washes that erase the real BG art.
        if ornaments_only or (width >= canvas.width * 0.92 and height >= canvas.height * 0.92):
            return None
        fill = (
            int(float(color.get("r", 1) or 0) * 255),
            int(float(color.get("g", 1) or 0) * 255),
            int(float(color.get("b", 1) or 0) * 255),
            int(alpha * 255),
        )
        if fill[3] < 8:
            return None
        tile = Image.new("RGBA", (max(1, int(width)), max(1, int(height))), fill)
        paste_y = canvas.height - (_y + height)
        _stamp(canvas, tile, int(_x), int(paste_y))
        return None
    art = art.convert("RGBA")
    # 00036's Shadow is a pink TrueShadow plate — do not treat it as a red placeholder.
    if _placeholder(art) and sprite_name.lower() != "shadow":
        return None
    scale = tree.get("m_LocalScale") or {}
    if float(scale.get("x") or 1) < 0:
        art = art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if float(scale.get("y") or 1) < 0:
        art = art.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    # Official 00036 shows a soft white pad here, not the raw pink TrueShadow texture.
    if (
        not ornaments_only
        and sprite_name.lower() in _FULL_SHADOW_SPRITES
        and not _is_full_card_shadow(width, height, canvas.size)
    ):
        white = Image.new("RGBA", art.size, (255, 255, 255, 255))
        white.putalpha(art.getchannel("A"))
        art = white
    # Fit the unrotated RectTransform first. Rotating before resize (old path) turned
    # 00036's 90°-spun Gradiate bars into a white vertical stripe down the card.
    if sprite_name == "Gardenofeden":
        resized = art.resize((max(1, int(width)), max(1, int(height))), Image.Resampling.NEAREST)
        grid_alpha = resized.getchannel("A").point(lambda value: 255 if value > 32 else 0)
        resized = Image.merge(
            "RGBA",
            (*Image.new("RGB", resized.size, (255, 255, 255)).split(), grid_alpha),
        )
    else:
        resized = art.resize((max(1, int(width)), max(1, int(height))), Image.Resampling.LANCZOS)
    color_r = float(color.get("r", 1) or 0)
    color_g = float(color.get("g", 1) or 0)
    color_b = float(color.get("b", 1) or 0)
    tinted_rgb = any(abs(channel - 1) > 0.01 for channel in (color_r, color_g, color_b))
    if tinted_rgb:
        # Solid UI tint (e.g. black footer marks). Do not use this for white×alpha —
        # that used to wipe sprite RGB and erase debris like 00036_2.
        tinted = Image.new(
            "RGBA",
            resized.size,
            (int(color_r * 255), int(color_g * 255), int(color_b * 255), 255),
        )
        tinted.putalpha(resized.getchannel("A").point(lambda value: int(value * alpha)))
        resized = tinted
    elif alpha < 0.99:
        resized.putalpha(resized.getchannel("A").point(lambda value: int(value * alpha)))
    angle = _z_degrees(tree.get("m_LocalRotation") or {})
    paste_x = int(_x)
    paste_y = int(canvas.height - (_y + height))
    if abs(angle) > 0.5:
        resized = resized.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)
        center_x = _x + width / 2
        center_y = _y + height / 2
        paste_x = int(center_x - resized.width / 2)
        paste_y = int(canvas.height - center_y - resized.height / 2)
    _stamp(canvas, resized, paste_x, paste_y)
    if not return_stencil:
        return None
    stencil = Image.new("L", canvas.size, 0)
    alpha_map = resized.getchannel("A")
    stencil.paste(alpha_map, (paste_x, paste_y))
    return stencil


def _soft_shadow_vignette(
    canvas: Image.Image,
    sprites: dict[tuple[int, int], object],
    *,
    strength: float = 0.42,
) -> Image.Image:
    """Use a full-card shadow sprite as a light edge vignette (not a local glow plate)."""
    shade: Image.Image | None = None
    seen: set[int] = set()
    for obj in sprites.values():
        path_id = id(obj)
        if path_id in seen:
            continue
        seen.add(path_id)
        try:
            data = obj.read()
            if str(getattr(data, "m_Name", "") or "").lower() != "shadow":
                continue
            image = getattr(data, "image", None)
        except Exception:
            continue
        if image is None:
            continue
        converted = image.convert("RGBA")
        if not _is_full_card_shadow(converted.width, converted.height, canvas.size):
            continue
        shade = converted
        break
    if shade is None:
        return canvas
    resized = shade.resize(canvas.size, Image.Resampling.LANCZOS)
    alpha = resized.getchannel("A").point(lambda value: min(255, int(value * strength)))
    if alpha.getextrema()[1] < 8:
        return canvas
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.putalpha(alpha)
    result = canvas.copy()
    result.alpha_composite(layer)
    return result


def _is_full_card_shadow(width: float, height: float, canvas_size: tuple[int, int]) -> bool:
    """True for card-sized wash shadows (00031), false for local glow plates (00036)."""
    canvas_w, canvas_h = canvas_size
    return width >= canvas_w * 0.55 and height >= canvas_h * 0.55


def _composite_with_stencil(
    canvas: Image.Image,
    layer: Image.Image,
    stencil: Image.Image | None,
) -> None:
    """Composite a mask-child layer, clipped to the mask graphic's alpha when available."""
    if stencil is not None:
        clipped = layer.copy()
        clipped.putalpha(ImageChops.multiply(clipped.getchannel("A"), stencil))
        canvas.alpha_composite(clipped)
    else:
        canvas.alpha_composite(layer)


def _draw_order_grid_on_top(
    kids: list[int],
    rects: dict[int, dict],
    names: dict[int, str],
) -> list[int]:
    """Draw Masks after 00036 art so opaque white tiles block debris/characters."""
    masks: list[int] = []
    ordered: list[int] = []
    for kid in kids:
        go = _pointer(rects[kid].get("m_GameObject"))
        child_name = names.get(go or -1, "").strip().lower()
        if child_name == "masks":
            masks.append(kid)
            continue
        ordered.append(kid)
    ordered.extend(masks)
    return ordered


def _defer_until_after_shadow(
    name: str,
    path_id: int,
    order: dict[int, list[int]],
    rects: dict[int, dict],
    names: dict[int, str],
) -> bool:
    """Keep bottom chrome + ornament avatars above the soft shadow wash."""
    lowered = name.strip().lower()
    if lowered in _FRONT_AFTER_SHADOW:
        return True
    if lowered != "avatar" and not lowered.startswith("avatar ("):
        return False
    return not _is_portrait_avatar(name, path_id, order, rects, names)


def _draw_border(canvas: Image.Image, border: dict, box: tuple[float, float, float, float]) -> None:
    """Stroke only — filled borders wipe the BG sprite on pale layouts like 00031."""
    _x, _y, width, height = box
    if width < 4 or height < 4:
        return
    color = border.get("m_Color") or {}
    alpha = float(color.get("a", 1) or 0)
    if alpha <= 0.05:
        return
    thickness = max(1, int(round(float(border.get("thickness") or 2))))
    radius = max(0, int(round(float(border.get("radius") or 0))))
    left = int(_x)
    top = int(canvas.height - (_y + height))
    right = int(_x + width) - 1
    bottom = top + int(height) - 1
    outline = (
        int(float(color.get("r", 1) or 0) * 255),
        int(float(color.get("g", 1) or 0) * 255),
        int(float(color.get("b", 1) or 0) * 255),
        int(alpha * 255),
    )
    ImageDraw.Draw(canvas).rounded_rectangle(
        (left, top, right, bottom),
        radius=radius,
        outline=outline,
        width=thickness,
    )


def _local_rect(parent_size: tuple[float, float], tree: dict) -> tuple[float, float, float, float]:
    pw, ph = parent_size
    amin = tree["m_AnchorMin"]
    amax = tree["m_AnchorMax"]
    pivot = tree["m_Pivot"]
    size = tree["m_SizeDelta"]
    pos = tree["m_AnchoredPosition"]
    width = pw * (amax["x"] - amin["x"]) + size["x"]
    height = ph * (amax["y"] - amin["y"]) + size["y"]
    x = pw * amin["x"] + pos["x"] - pivot["x"] * width + pw * (amax["x"] - amin["x"]) * pivot["x"]
    y = ph * amin["y"] + pos["y"] - pivot["y"] * height + ph * (amax["y"] - amin["y"]) * pivot["y"]
    return x, y, width, height


def _scaled_box(
    local: tuple[float, float, float, float],
    tree: dict,
    origin: tuple[float, float],
    parent_scale: tuple[float, float],
) -> tuple[tuple[float, float, float, float], tuple[float, float], tuple[float, float]]:
    x, y, width, height = local
    scale = tree.get("m_LocalScale") or {}
    own_x = abs(float(scale.get("x") or 1)) or 1.0
    own_y = abs(float(scale.get("y") or 1)) or 1.0
    world_x = origin[0] + x * parent_scale[0]
    world_y = origin[1] + y * parent_scale[1]
    world_w = width * parent_scale[0]
    world_h = height * parent_scale[1]
    pivot = tree["m_Pivot"]
    drawn_w = world_w * own_x
    drawn_h = world_h * own_y
    drawn_x = world_x + world_w * pivot["x"] - drawn_w * pivot["x"]
    drawn_y = world_y + world_h * pivot["y"] - drawn_h * pivot["y"]
    return (drawn_x, drawn_y, drawn_w, drawn_h), (drawn_x, drawn_y), (parent_scale[0] * own_x, parent_scale[1] * own_y)


def _stamp(canvas: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
    left = max(0, -x)
    top = max(0, -y)
    right = min(sprite.width, canvas.width - x)
    bottom = min(sprite.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    piece = sprite.crop((left, top, right, bottom))
    canvas.alpha_composite(piece, (max(0, x), max(0, y)))


def _skip_object(name: str, *, ornaments_only: bool = False) -> bool:
    lowered = name.strip().lower()
    if lowered in _SKIP_OBJECTS or lowered.startswith("text"):
        return True
    if not ornaments_only:
        return False
    if lowered in _ORNAMENT_OBJECTS or lowered.startswith("particle"):
        return False
    if lowered == "avatar" or lowered.startswith("avatar ("):
        return False
    return True


def _sprite_name(image: dict, sprites: dict[tuple[int, int], object]) -> str:
    pointer = image.get("m_Sprite") if isinstance(image.get("m_Sprite"), dict) else None
    if not pointer or not pointer.get("m_PathID"):
        return ""
    path_id = pointer.get("m_PathID")
    file_id = int(pointer.get("m_FileID") or 0)
    obj = sprites.get((file_id, path_id)) or sprites.get((0, path_id)) or sprites.get((-1, path_id))
    if obj is None:
        return ""
    try:
        return str(getattr(obj.read(), "m_Name", "") or "")
    except Exception:
        return ""


def _image_is_cover_art(image: dict, sprites: dict[tuple[int, int], object]) -> bool:
    return _sprite_name(image, sprites).lower() in _COVER_ART_SPRITES


def _has_cover_art(go: int | None, images: list[dict], sprites: dict[tuple[int, int], object]) -> bool:
    if go is None:
        return False
    for image in images:
        if _pointer(image.get("m_GameObject")) != go:
            continue
        if _image_is_cover_art(image, sprites):
            return True
    return False


def _is_portrait_avatar(
    name: str,
    path_id: int,
    order: dict[int, list[int]],
    rects: dict[int, dict],
    names: dict[int, str],
) -> bool:
    lowered = name.strip().lower()
    if lowered != "avatar" and not lowered.startswith("avatar ("):
        return False
    for child in order.get(path_id, []):
        go = _pointer(rects[child].get("m_GameObject"))
        child_name = names.get(go or -1, "").strip().lower()
        if child_name in {"mask", "border"} or child_name.startswith("mask"):
            return True
    return False


def _hosts_portrait_avatar(
    path_id: int,
    order: dict[int, list[int]],
    rects: dict[int, dict],
    names: dict[int, str],
) -> bool:
    """True for small portrait holders (00036 Image → Avatar), not card roots/Mask trees."""
    kids = order.get(path_id, [])
    # Layout roots and Mask trees have many children; only skip tight portrait wrappers.
    if not kids or len(kids) > 2:
        return False
    for child in kids:
        go = _pointer(rects[child].get("m_GameObject"))
        child_name = names.get(go or -1, "")
        if _is_portrait_avatar(child_name, child, order, rects, names):
            return True
    return False


def _placeholder(image: Image.Image) -> bool:
    sample = image.resize((16, 16), Image.Resampling.BOX)
    pixels = list(sample.getdata())
    reds = sum(1 for red, green, blue, alpha in pixels if alpha > 200 and red > 220 and green < 40 and blue < 40)
    return reds >= len(pixels) * 0.85


def _z_degrees(rotation: dict) -> float:
    z = float(rotation.get("z") or 0)
    w = float(rotation.get("w") or 1)
    return math.degrees(2 * math.atan2(z, w))


def _pointer(value: object) -> int | None:
    if not isinstance(value, dict) or value.get("m_FileID") not in (0, None):
        return None
    path_id = value.get("m_PathID")
    return path_id if isinstance(path_id, int) else None
