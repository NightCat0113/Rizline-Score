"""Layout cards for the collection grid.

Empty arts windows are filled with the blank-card env stripe texture. Frames come
from layout bundles; prefab ornaments (particles, decorative avatars, baked
scenes) are layered on top without redrawing the card chrome.
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import struct
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

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
# Layout 00042: CoverOverlay and CoverBG are real chrome. The flat composite
# skips them; _place_layout_42_panels projects both onto the cover plane.
_COVER_ART_SPRITES = {"coveroverlay"}
# Player HUD roots (00042) sit on Y-rotated 3D panels — flat 2D stamps land off-card.
# _place_layout_42_panels projects those panels (and the art window) after the composite.
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
            # Layout 00045's bio pillar is solid chrome. Particles sit behind it,
            # otherwise the triangles read as the plate being see-through.
            if number == "00045":
                particled = _stamp_kalpa_particles(card, bundle, deps)
                if particled is not card:
                    card.close()
                    card = particled
            ornamented = _composite(bundle, card, deps, ornaments_only=True)
            if ornamented is not None:
                card.close()
                card = ornamented
        return _finish_special_layout(card, number, bundle, deps)
    image = _composite(bundle, None, deps) if bundle is not None else None
    if image is not None and use_env and env_fill is not None:
        filled = _with_env_arts(image, env_fill)
        image.close()
        image = filled
    return _finish_special_layout(image, number, bundle, deps)


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
    shapes: list[dict] = []
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
            elif "fill" in tree and "thickness" in tree and "m_Color" in tree:
                shapes.append(tree)
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
    front_queue: list[tuple[int, tuple[float, float], tuple[float, float], tuple[float, float], bool]] = []
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
            shapes=shapes,
        )
    if canvas.getchannel("A").getextrema()[1] < 16:
        return frame
    if ornaments_only:
        return canvas
    canvas = _soft_shadow_vignette(canvas, sprites)
    for path_id, parent_size, origin, parent_scale, parent_flip_y in front_queue:
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
            parent_flip_y=parent_flip_y,
            shapes=shapes,
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
    front_queue: list[tuple[int, tuple[float, float], tuple[float, float], tuple[float, float], bool]] | None = None,
    parent_flip_y: bool = False,
    shapes: list[dict] | None = None,
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
        # Empty portrait slots (layout 00045) are a solid disk inside the ornament.
        # Player photos stay out; white plates (layout 00036) stay out too.
        fill = _solid_portrait_fill(path_id, order, rects, images) or _avatar_disk_fill(
            path_id, order, rects, shapes
        )
        if fill is not None:
            _stamp_ellipse(canvas, box, fill)
        return
    if front_queue is not None and _defer_until_after_shadow(name, path_id, order, rects, names):
        front_queue.append((path_id, parent_size, origin, parent_scale, parent_flip_y))
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
                    parent_flip_y=parent_flip_y,
                )
            else:
                _draw_image(
                    canvas,
                    image,
                    tree,
                    box,
                    sprites,
                    ornaments_only=ornaments_only,
                    parent_flip_y=parent_flip_y,
                )
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
    # 00036: debris, then the square tiles, then 00036_1 so the character stays in front.
    own_flip_y = float((tree.get("m_LocalScale") or {}).get("y") or 1) < 0
    child_flip_y = parent_flip_y or own_flip_y
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
            parent_flip_y=child_flip_y,
            shapes=shapes,
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
    parent_flip_y: bool = False,
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
                if sprite_name in {"bg_00", "CoverBG"} and _layout_42_env_frame(sprites) is not None:
                    # Layout 00042. A flat stamp uses the scaled rect and crops the
                    # scene tight. _place_layout_42_panels projects the hallway and
                    # the frosted CoverBG at their camera distances.
                    return None
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
    # Mask1's negative scale mirrors the whole subtree. The grid sprite flips
    # with that scale; the border sprite does not, so inherit the parent flip
    # or its stroke lands off the squares and the mask clips it away.
    flip_border = parent_flip_y and sprite_name == "Gardenofeden_boarder"
    if float(scale.get("y") or 1) < 0 or flip_border:
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
    elif sprite_name == "Gardenofeden_boarder":
        # Same sampler as the tiles so a 1px stroke stays on the square edge.
        resized = art.resize((max(1, int(width)), max(1, int(height))), Image.Resampling.NEAREST)
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


def _layout_42_env_frame(sprites: dict[tuple[int, int], object]) -> Image.Image | None:
    """Layout 00042's hallway loop. The still card uses bg_01, not the rest pose bg_00."""
    frames: dict[str, Image.Image] = {}
    seen: set[int] = set()
    for obj in sprites.values():
        marker = id(obj)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            data = obj.read()
            name = str(getattr(data, "m_Name", "") or "")
            image = getattr(data, "image", None)
        except Exception:
            continue
        if image is not None and name in {"bg_01", "bg_47"}:
            frames[name] = image
        if "bg_01" in frames and "bg_47" in frames:
            break
    frame = frames.get("bg_01")
    if frame is None or "bg_47" not in frames:
        return None
    return frame


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


def _finish_special_layout(
    card: Image.Image | None,
    number: str,
    bundle: Path | None,
    dependencies: tuple[Path, ...],
) -> Image.Image | None:
    card = _open_avatar_ring(card, number)
    if card is not None and number == "00036":
        _stamp_tone_sphere(card)
    if card is None or number != "00042" or bundle is None:
        return card
    return _place_layout_42_panels(card, bundle, dependencies)


def _stamp_tone_sphere(card: Image.Image) -> None:
    """Layout 00036's footer label: '*      T o n e   S p h e r e'."""
    # Prefab text is 28pt italic-looking grey, middle-left. The letters are
    # already separated in the string: one space inside each word, three between
    # Tone and Sphere. The black bar's top edge is y=261 on the 2078 card.
    scale_x = card.width / 1488
    scale_y = card.height / 2078
    font_size = max(1, int(round(28 * scale_y)))
    font = _ui_font(font_size, italic=True)
    # ToneSphere is one name. Every letter is separated, and the join between
    # Tone and Sphere is only a little wider than the other gaps.
    letter_gap = int(round(font_size * 0.4))
    word_gap = int(round(font_size * 1.05))
    mark_gap = int(round(font_size * 1.45))
    pieces = ["*"] + list("Tone") + list("Sphere")
    gaps = [mark_gap] + [letter_gap] * 3 + [word_gap] + [letter_gap] * 5
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = []
    tops = []
    bottoms = []
    for piece in pieces:
        bounds = probe.textbbox((0, 0), piece, font=font)
        widths.append(bounds[2] - bounds[0])
        tops.append(bounds[1])
        bottoms.append(bounds[3])
    width = sum(widths) + sum(gaps) + 2
    top = min(tops)
    bottom = max(bottoms)
    layer = Image.new("RGBA", (max(1, width), max(1, bottom - top + 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cursor = 1
    fill = (142, 142, 142, 255)
    for index, piece in enumerate(pieces):
        draw.text((cursor, 1 - top), piece, font=font, fill=fill)
        cursor += widths[index]
        if index < len(gaps):
            cursor += gaps[index]
    paste_x = int(round(82 * scale_x))
    bar_top = 261 * scale_y
    paste_y = int(round(card.height - bar_top - layer.height - 6 * scale_y))
    _stamp(card, layer, paste_x, paste_y)


# World-space canvas for layout 00042: Card Camera sits at the origin, FOV 60°,
# canvas center at z=500 with scale 0.27. Flat UI stamps ignore that yaw.
_LAYOUT_42_CANVAS = (1488.0, 2078.0)
_LAYOUT_42_CAMERA_Z = 500.0
_LAYOUT_42_CANVAS_SCALE = 0.27
_LAYOUT_42_FOV = 60.0
# Left, top, right, bottom of the card. The neon frame and the frost share this square.
_LAYOUT_42_COVER_BOX = (0.189, 0.216, 0.811, 0.787)


def _place_layout_42_panels(
    card: Image.Image,
    bundle: Path,
    dependencies: tuple[Path, ...],
) -> Image.Image:
    """Project layout 00042's tilted avatar, name, bio lines, and art window."""
    scene = _layout_42_scene(bundle, dependencies)
    if scene is None:
        return card
    rects, names, order, images, sprites = scene
    canvas_id = _named_rect(rects, names, "canvas")
    if canvas_id is None:
        return card
    sizes = _rect_sizes(canvas_id, rects, order)
    panels = _layout_42_panels(rects, names, order, images, sprites, sizes)
    scale_x = card.width / _LAYOUT_42_CANVAS[0]
    scale_y = card.height / _LAYOUT_42_CANVAS[1]
    for role, sprite, fill, corners in panels:
        if role == "coverbg" and sprite is not None:
            # Drop the faint halo so the solid grid ends on the neon line.
            sprite = _crop_to_alpha(sprite, 80)
            projected = _cover_box_quad(card)
        elif role == "overlay":
            projected = _layout_42_cover_quad(card, sprite)
        else:
            projected = None
        if projected is None:
            projected = []
            for point in corners:
                screen = _project_layout_42(point)
                if screen is None:
                    projected = []
                    break
                projected.append((screen[0] * scale_x, screen[1] * scale_y))
        if len(projected) != 4:
            continue
        if sprite is not None:
            layer = _warp_quad(sprite, projected, card.size)
            if layer is not None:
                card.alpha_composite(layer)
                layer.close()
        elif fill is not None:
            overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).polygon(projected, fill=fill)
            card.alpha_composite(overlay)
            overlay.close()
    return card


def _cover_box_quad(card: Image.Image) -> list[tuple[float, float]]:
    """The shared square: frost fills it, neon lines sit on its edges."""
    box_left, box_top, box_right, box_bottom = _LAYOUT_42_COVER_BOX
    left = box_left * card.width
    top = box_top * card.height
    right = box_right * card.width
    bottom = box_bottom * card.height
    return [(left, bottom), (right, bottom), (right, top), (left, top)]


def _layout_42_cover_quad(
    card: Image.Image,
    sprite: Image.Image | None,
) -> list[tuple[float, float]] | None:
    """Screen quad for CoverBG or CoverOverlay, both locked to the same square.

    The overlay's neon lines land on the square's edges. The frost's visible
    pixels fill that same square, so the two meet.
    """
    if sprite is None:
        return None
    # The long white run is the line. The short runs at each end are dots.
    content = _neon_line_frac(sprite)
    if content is None:
        return None
    box_left, box_top, box_right, box_bottom = _LAYOUT_42_COVER_BOX
    left = box_left * card.width
    top = box_top * card.height
    right = box_right * card.width
    bottom = box_bottom * card.height
    content_left, content_top, content_right, content_bottom = content
    span_x = content_right - content_left
    span_y = content_bottom - content_top
    if abs(span_x) < 1e-6 or abs(span_y) < 1e-6:
        return None
    scale_x = (right - left) / span_x
    scale_y = (bottom - top) / span_y
    origin_x = left - content_left * scale_x
    origin_y = top - content_top * scale_y
    x1 = origin_x + scale_x
    y1 = origin_y + scale_y
    return [(origin_x, y1), (x1, y1), (x1, origin_y), (origin_x, origin_y)]


def _layout_42_scene(
    bundle: Path,
    dependencies: tuple[Path, ...],
):
    try:
        import UnityPy
    except ImportError:
        return None
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
        return None
    names: dict[int, str] = {}
    rects: dict[int, dict] = {}
    images: list[dict] = []
    sprites: dict[str, Image.Image] = {}
    sprite_names: dict[int, str] = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                names[obj.path_id] = str(obj.read().m_Name)
            except Exception:
                continue
        elif obj.type.name == "RectTransform":
            try:
                rects[obj.path_id] = obj.read_typetree()
            except Exception:
                continue
        elif obj.type.name == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if isinstance(tree.get("m_Sprite"), dict) or "m_FillCenter" in tree:
                images.append(tree)
        elif obj.type.name == "Sprite":
            try:
                data = obj.read()
                name = str(getattr(data, "m_Name", "") or "")
                image = data.image
            except Exception:
                continue
            if not name or image is None:
                continue
            sprite_names[obj.path_id] = name
            if name not in sprites:
                sprites[name] = image.convert("RGBA")
    for image in images:
        pointer = image.get("m_Sprite") if isinstance(image.get("m_Sprite"), dict) else None
        if pointer is not None:
            image["_sprite_name"] = sprite_names.get(pointer.get("m_PathID"), "")
    if not rects:
        return None
    return rects, names, _child_order(rects), images, sprites


def _named_rect(rects: dict[int, dict], names: dict[int, str], wanted: str) -> int | None:
    for path_id, tree in rects.items():
        go = _pointer(tree.get("m_GameObject"))
        if names.get(go or -1, "").strip().lower() == wanted:
            return path_id
    return None


def _rect_sizes(
    root_id: int,
    rects: dict[int, dict],
    order: dict[int, list[int]],
) -> dict[int, tuple[float, float]]:
    root = rects[root_id]
    size = root.get("m_SizeDelta") or {}
    sizes = {root_id: (abs(float(size.get("x") or 0)), abs(float(size.get("y") or 0)))}

    def walk(path_id: int) -> None:
        parent_w, parent_h = sizes[path_id]
        for child in order.get(path_id, []):
            _x, _y, width, height = _local_rect((parent_w, parent_h), rects[child])
            sizes[child] = (abs(width), abs(height))
            walk(child)

    walk(root_id)
    return sizes


def _solid_portrait_fill(
    path_id: int,
    order: dict[int, list[int]],
    rects: dict[int, dict],
    images: list[dict],
) -> tuple[int, int, int, int] | None:
    """Color of an empty avatar disk. White or grey plates are not placeholders to draw."""
    stack = [path_id]
    while stack:
        current = stack.pop()
        go = _pointer(rects[current].get("m_GameObject"))
        for image in images:
            if _pointer(image.get("m_GameObject")) != go:
                continue
            sprite = image.get("m_Sprite") if isinstance(image.get("m_Sprite"), dict) else None
            if sprite and sprite.get("m_PathID"):
                continue
            color = image.get("m_Color") or {}
            red = float(color.get("r", 1) or 0)
            green = float(color.get("g", 1) or 0)
            blue = float(color.get("b", 1) or 0)
            alpha = float(color.get("a", 1) or 0)
            if alpha < 0.05:
                continue
            if max(red, green, blue) - min(red, green, blue) < 0.08 and min(red, green, blue) > 0.7:
                continue
            return (int(red * 255), int(green * 255), int(blue * 255), int(alpha * 255))
        stack.extend(order.get(current, []))
    return None


def _avatar_disk_fill(
    path_id: int,
    order: dict[int, list[int]],
    rects: dict[int, dict],
    shapes: list[dict] | None,
) -> tuple[int, int, int, int] | None:
    """Filled avatar shape (layout 00045's purple disk). Stroke-only borders are not disks."""
    if not shapes:
        return None
    stack = [path_id]
    while stack:
        current = stack.pop()
        go = _pointer(rects[current].get("m_GameObject"))
        for shape in shapes:
            if _pointer(shape.get("m_GameObject")) != go:
                continue
            if float(shape.get("fill", 0) or 0) < 0.99:
                continue
            color = shape.get("m_Color") or {}
            alpha = float(color.get("a", 1) or 0)
            if alpha < 0.05:
                continue
            return (
                int(float(color.get("r", 1) or 0) * 255),
                int(float(color.get("g", 1) or 0) * 255),
                int(float(color.get("b", 1) or 0) * 255),
                int(alpha * 255),
            )
        stack.extend(order.get(current, []))
    return None


def _stamp_ellipse(
    canvas: Image.Image,
    box: tuple[float, float, float, float],
    fill: tuple[int, int, int, int],
) -> None:
    _x, _y, width, height = box
    if width < 4 or height < 4:
        return
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    left = int(_x)
    top = int(canvas.height - (_y + height))
    ImageDraw.Draw(layer).ellipse((left, top, left + int(width), top + int(height)), fill=fill)
    canvas.alpha_composite(layer)


def _opaque_bio_plate(art: Image.Image) -> Image.Image:
    """Make layout 00045's BioBG tag solid while keeping its shaped silhouette.

    The colored bar is already opaque. The surrounding texels are black with a
    partial alpha (the texture has no color bleed), so raising that alpha alone
    would paint a black slab. Those texels take the plate color, then the whole
    silhouette becomes alpha 255. Fully clear pixels stay clear.
    """
    image = art.convert("RGBA").copy()
    pixels = image.load()
    width, height = image.size
    total_r = total_g = total_b = 0
    samples = 0
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 255 and red < 80 and blue > red and blue > green:
                total_r += red
                total_g += green
                total_b += blue
                samples += 1
    if samples:
        plate = (total_r // samples, total_g // samples, total_b // samples)
    else:
        plate = (20, 16, 53)
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha <= 0:
                continue
            if alpha >= 250:
                pixels[x, y] = (red, green, blue, 255)
            elif red + green + blue < 40:
                pixels[x, y] = (*plate, 255)
            else:
                pixels[x, y] = (red, green, blue, 255)
    return image


def _ui_font(size: int, *, italic: bool = False) -> ImageFont.ImageFont:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if italic:
        candidates = (
            windows / "ariali.ttf",
            windows / "segoeuii.ttf",
            windows / "calibrii.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
        )
    else:
        candidates = (
            windows / "arial.ttf",
            windows / "segoeui.ttf",
            windows / "calibri.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _layout_42_title_panel(
    rects: dict[int, dict],
    names: dict[int, str],
    sizes: dict[int, tuple[float, float]],
) -> tuple[Image.Image, None, list[tuple[float, float, float]]] | None:
    """Username plate label. The Title text is the placeholder 'USER ID'."""
    title_id = None
    for path_id in rects:
        if _rect_name(path_id, rects, names).strip().lower() != "title":
            continue
        parents = {_rect_name(parent, rects, names).strip().lower() for parent in _ancestors(path_id, rects, names)}
        if "namecontainer" in parents:
            title_id = path_id
            break
    if title_id is None:
        return None
    corners = _layout_42_corners(title_id, rects, names, sizes)
    if corners is None:
        return None
    # Prefab: 160×30, font 16, upper-left, color (0.969, 0.792, 0.808).
    scale = 4
    image = Image.new("RGBA", (160 * scale, 30 * scale), (0, 0, 0, 0))
    ImageDraw.Draw(image).text(
        (2 * scale, 0),
        "USER ID",
        font=_ui_font(16 * scale),
        fill=(247, 202, 206, 255),
    )
    return image, None, corners


def _offset_in_ancestor(
    child: int,
    ancestor: int,
    rects: dict[int, dict],
) -> tuple[float, float, float, float] | None:
    """Child rect in an ancestor's space, origin at the ancestor's bottom-left."""
    chain: list[int] = []
    current = child
    while current != ancestor:
        chain.append(current)
        father = _pointer(rects[current].get("m_Father"))
        if father not in rects:
            return None
        current = father
    origin_x = origin_y = 0.0
    parent_size = rects[ancestor].get("m_SizeDelta") or {}
    parent_w = abs(float(parent_size.get("x") or 0))
    parent_h = abs(float(parent_size.get("y") or 0))
    for node in reversed(chain):
        x, y, width, height = _local_rect((parent_w, parent_h), rects[node])
        if node == child:
            return origin_x + x, origin_y + y, width, height
        origin_x += x
        origin_y += y
        parent_w, parent_h = abs(width), abs(height)
    return None


def _name_label_panel(
    rects: dict[int, dict],
    names: dict[int, str],
    sizes: dict[int, tuple[float, float]],
) -> tuple[Image.Image, None, list[tuple[float, float, float]]] | None:
    """USER ID drawn on the name plate so it shares that plate's tilt."""
    frame_id = title_id = None
    for path_id in rects:
        label = _rect_name(path_id, rects, names).strip().lower()
        parents = {_rect_name(parent, rects, names).strip().lower() for parent in _ancestors(path_id, rects, names)}
        if "namecontainer" not in parents:
            continue
        if label == "frame":
            frame_id = path_id
        elif label == "title":
            title_id = path_id
    if frame_id is None or title_id is None:
        return None
    corners = _layout_42_corners(frame_id, rects, names, sizes)
    placed = _offset_in_ancestor(title_id, frame_id, rects)
    if corners is None or placed is None:
        return None
    frame = rects[frame_id].get("m_SizeDelta") or {}
    frame_w = abs(float(frame.get("x") or 0))
    frame_h = abs(float(frame.get("y") or 0))
    if frame_w < 2 or frame_h < 2:
        return None
    x, y, width, height = placed
    scale = 4
    image = Image.new("RGBA", (max(1, int(frame_w * scale)), max(1, int(frame_h * scale))), (0, 0, 0, 0))
    ImageDraw.Draw(image).text(
        (int(round(x * scale)), int(round((frame_h - (y + height)) * scale))),
        "USER ID",
        font=_ui_font(16 * scale),
        fill=(247, 202, 206, 255),
    )
    return image, None, corners


def _layout_42_panels(
    rects: dict[int, dict],
    names: dict[int, str],
    order: dict[int, list[int]],
    images: list[dict],
    sprites: dict[str, Image.Image],
    sizes: dict[int, tuple[float, float]],
) -> list[tuple[Image.Image | None, tuple[int, int, int, int] | None, list[tuple[float, float, float]]]]:
    """Draw list of (sprite, solid fill, canvas-space corners)."""
    del order
    found: dict[str, tuple] = {}
    for path_id in rects:
        label = _layout_42_role(path_id, rects, names)
        if label is None or label in found:
            continue
        corners = _layout_42_corners(path_id, rects, names, sizes)
        sprite, fill = _layout_42_paint(path_id, rects, names, images, sprites)
        if label == "portrait" or corners is None or (sprite is None and fill is None):
            continue
        found[label] = (sprite, fill, corners)
    # The inner cover quad is about twice the painted screen and would fog the
    # hallway. The white screen in the env frame is the art slot; the overlay is its chrome.
    # BG is the hallway plane (deeper than the canvas) and has to land behind that chrome.
    overlay = found.get("overlay")
    if overlay is not None and overlay[0] is not None:
        sprite, fill, corners = overlay
        corners = _fit_quad_to_sprite(corners, sprite)
        found["overlay"] = (sprite, fill, corners)
        coverbg = found.get("coverbg")
        if coverbg is not None:
            # Same quad as the neon frame so the frost meets CoverOverlay.
            plate, plate_fill, _plate_corners = coverbg
            found["coverbg"] = (plate, plate_fill, corners)
    panels = []
    for label in ("bg", "coverbg", "overlay", "avatar", "name"):
        panel = found.get(label)
        if panel is not None and len(panel[2]) == 4:
            panels.append((label, *panel))
    label = _name_label_panel(rects, names, sizes)
    if label is not None:
        panels.append(("userid", *label))
    for path_id in rects:
        if _rect_name(path_id, rects, names).strip().lower() not in {"lineu", "lined"}:
            continue
        corners = _layout_42_corners(path_id, rects, names, sizes)
        if corners is None:
            continue
        _sprite, fill = _layout_42_paint(path_id, rects, names, images, sprites)
        if fill is not None:
            panels.append(("line", None, fill, corners))
    return panels


def _overlay_frame_frac(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Neon-line bounds as (left, bottom, right, top), Y growing upward.

    Falls back to any visible pixel when the sprite has no solid white core.
    """
    core = _neon_core_frac(image)
    if core is not None:
        left, top, right, bottom = core
        return (left, 1 - bottom, right, 1 - top)
    return _sprite_visible_frac(image)


def _alpha_bounds_ydown(image: Image.Image, threshold: int) -> tuple[float, float, float, float] | None:
    """Bounds of pixels at or above ``threshold`` alpha. Origin is the top-left."""
    pixels = image.convert("RGBA").load()
    width, height = image.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] < threshold:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0 or width < 1 or height < 1:
        return None
    return (min_x / width, min_y / height, (max_x + 1) / width, (max_y + 1) / height)


def _sprite_visible_frac(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Opaque bounds as (left, bottom, right, top), Y growing upward."""
    pixels = image.convert("RGBA").load()
    width, height = image.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] < 12:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0 or width < 1 or height < 1:
        return None
    return (
        min_x / width,
        1 - (max_y + 1) / height,
        (max_x + 1) / width,
        1 - min_y / height,
    )


def _crop_to_alpha(image: Image.Image, threshold: int) -> Image.Image:
    bounds = _alpha_bounds_ydown(image, threshold)
    if bounds is None:
        return image
    left, top, right, bottom = bounds
    width, height = image.size
    box = (
        int(left * width),
        int(top * height),
        max(int(left * width) + 1, int(right * width)),
        max(int(top * height) + 1, int(bottom * height)),
    )
    return image.crop(box)


def _neon_line_frac(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Bounds of the long neon bars, ignoring the dots at each end.

    Returns (left, top, right, bottom) in image space, origin at the top-left.
    """
    pixels = image.convert("RGBA").load()
    width, height = image.size
    runs: list[tuple[int, int, int]] = []
    for y in range(height):
        white = [x for x in range(width) if pixels[x, y][3] > 200 and min(pixels[x, y][:3]) > 220]
        if not white:
            continue
        start = previous = white[0]
        best: tuple[int, int] | None = None
        for x in white[1:]:
            if x > previous + 2:
                if best is None or previous - start > best[1] - best[0]:
                    best = (start, previous)
                start = x
            previous = x
        if best is None or previous - start > best[1] - best[0]:
            best = (start, previous)
        if best[1] - best[0] > width * 0.4:
            runs.append((y, best[0], best[1]))
    if not runs:
        return _neon_core_frac(image)
    top = runs[0][0]
    bottom = runs[-1][0] + 1
    left = min(item[1] for item in runs)
    right = max(item[2] for item in runs) + 1
    return (left / width, top / height, right / width, bottom / height)


def _neon_core_frac(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Bounding box of the solid neon lines, as fractions of the sprite.

    The pink bloom is a low-alpha wash. The core is the near-white opaque stroke.
    Returns (left, top, right, bottom) in image space, origin at the top-left.
    """
    pixels = image.convert("RGBA").load()
    width, height = image.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 200 or min(red, green, blue) < 200:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0:
        return None
    return (min_x / width, min_y / height, (max_x + 1) / width, (max_y + 1) / height)


def _quad_matching_content(
    corners: list[tuple[float, float, float]],
    content: tuple[float, float, float, float],
    target: tuple[float, float, float, float],
) -> list[tuple[float, float, float]]:
    """Scale a quad so one inner region lands on another.

    ``content`` and ``target`` are (left, bottom, right, top) in 0–1 along the
    quad, with Y growing upward. The content slice of the returned quad covers
    the target slice of ``corners``.
    """
    bottom_left, bottom_right, _top_right, top_left = corners
    content_left, content_bottom, content_right, content_top = content
    target_left, target_bottom, target_right, target_top = target
    span_u = content_right - content_left
    span_v = content_top - content_bottom
    if abs(span_u) < 1e-6 or abs(span_v) < 1e-6:
        return corners
    scale_u = (target_right - target_left) / span_u
    scale_v = (target_top - target_bottom) / span_v
    origin_u = target_left - content_left * scale_u
    origin_v = target_bottom - content_bottom * scale_v

    def point(u: float, v: float) -> tuple[float, float, float]:
        return tuple(
            bottom_left[index]
            + (bottom_right[index] - bottom_left[index]) * u
            + (top_left[index] - bottom_left[index]) * v
            for index in range(3)
        )

    return [
        point(origin_u, origin_v),
        point(origin_u + scale_u, origin_v),
        point(origin_u + scale_u, origin_v + scale_v),
        point(origin_u, origin_v + scale_v),
    ]


def _fit_quad_to_sprite(
    corners: list[tuple[float, float, float]],
    sprite: Image.Image,
) -> list[tuple[float, float, float]]:
    """Shrink an axis-aligned quad so the sprite's aspect fits inside it."""
    if sprite.width < 1 or sprite.height < 1:
        return corners
    bottom_left, bottom_right, top_right, top_left = corners
    width = math.hypot(bottom_right[0] - bottom_left[0], bottom_right[1] - bottom_left[1])
    height = math.hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
    if width < 2 or height < 2:
        return corners
    target = sprite.width / sprite.height
    current = width / height
    if abs(current - target) < 0.02:
        return corners

    def mix(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        amount: float,
    ) -> tuple[float, float, float]:
        return tuple(start[index] + (end[index] - start[index]) * amount for index in range(3))

    if current < target:
        inset = (1 - (width / target) / height) / 2
        return [
            mix(bottom_left, top_left, inset),
            mix(bottom_right, top_right, inset),
            mix(bottom_right, top_right, 1 - inset),
            mix(bottom_left, top_left, 1 - inset),
        ]
    inset = (1 - (height * target) / width) / 2
    return [
        mix(bottom_left, bottom_right, inset),
        mix(bottom_left, bottom_right, 1 - inset),
        mix(top_left, top_right, 1 - inset),
        mix(top_left, top_right, inset),
    ]


def _layout_42_role(
    path_id: int,
    rects: dict[int, dict],
    names: dict[int, str],
) -> str | None:
    name = _rect_name(path_id, rects, names).strip().lower()
    if name == "bg":
        return "bg"
    parents = {_rect_name(parent, rects, names).strip().lower() for parent in _ancestors(path_id, rects, names)}
    if "avatarcontainer" in parents and name == "frame":
        return "avatar"
    if "avatarcontainer" in parents and name == "image":
        return "portrait"
    if "namecontainer" in parents and name == "frame":
        return "name"
    if "covermask" in parents and name == "cover":
        return "art"
    if name == "cover" and "covermask" not in parents:
        return "coverbg"
    if name == "overlay" and "cover" in parents:
        return "overlay"
    if name in {"lineu", "lined"}:
        return "bio-line"
    return None


def _layout_42_paint(
    path_id: int,
    rects: dict[int, dict],
    names: dict[int, str],
    images: list[dict],
    sprites: dict[str, Image.Image],
) -> tuple[Image.Image | None, tuple[int, int, int, int] | None]:
    go = _pointer(rects[path_id].get("m_GameObject"))
    for image in images:
        if _pointer(image.get("m_GameObject")) != go:
            continue
        color = image.get("m_Color") or {}
        alpha = float(color.get("a", 1) or 0)
        if alpha <= 0.01:
            continue
        sprite_name = _sprite_on(path_id, rects, names, images)
        sprite = sprites.get(sprite_name) if sprite_name else None
        if sprite is not None:
            # Still card uses the hallway loop frame, not the rest pose.
            if sprite_name == "bg_00" and "bg_01" in sprites and "bg_47" in sprites:
                return sprites["bg_01"], None
            return sprite, None
        fill = (
            int(float(color.get("r", 1) or 0) * 255),
            int(float(color.get("g", 1) or 0) * 255),
            int(float(color.get("b", 1) or 0) * 255),
            int(alpha * 255),
        )
        return None, fill
    return None, None


def _sprite_on(
    path_id: int,
    rects: dict[int, dict],
    names: dict[int, str],
    images: list[dict],
) -> str:
    go = _pointer(rects[path_id].get("m_GameObject"))
    for image in images:
        if _pointer(image.get("m_GameObject")) != go:
            continue
        pointer = image.get("m_Sprite") if isinstance(image.get("m_Sprite"), dict) else None
        if not pointer:
            continue
        # Resolved later by name via the sprite table stored on the image only as a path.
        # The caller passes sprites keyed by name; look up through a side channel below.
        return str(image.get("_sprite_name") or "")
    return ""


def _layout_42_corners(
    path_id: int,
    rects: dict[int, dict],
    names: dict[int, str],
    sizes: dict[int, tuple[float, float]],
) -> list[tuple[float, float, float]] | None:
    width, height = sizes.get(path_id, (0.0, 0.0))
    if width < 2 or height < 2:
        return None
    tree = rects[path_id]
    pivot = tree.get("m_Pivot") or {}
    px = float(pivot.get("x") or 0.5)
    py = float(pivot.get("y") or 0.5)
    left, right = -px * width, (1 - px) * width
    bottom, top = -py * height, (1 - py) * height
    local = ((left, bottom, 0.0), (right, bottom, 0.0), (right, top, 0.0), (left, top, 0.0))
    corners = [_to_canvas(path_id, point, rects, names, sizes) for point in local]
    if any(corner is None for corner in corners):
        return None
    return corners


def _to_canvas(
    path_id: int,
    point: tuple[float, float, float],
    rects: dict[int, dict],
    names: dict[int, str],
    sizes: dict[int, tuple[float, float]],
) -> tuple[float, float, float] | None:
    current = path_id
    while True:
        tree = rects[current]
        father = _pointer(tree.get("m_Father"))
        if father not in rects or father not in sizes:
            return None
        scale = tree.get("m_LocalScale") or {}
        scaled = (
            point[0] * float(scale.get("x") or 1),
            point[1] * float(scale.get("y") or 1),
            point[2] * float(scale.get("z") or 1),
        )
        rotated = _quat_rotate(_quat(tree), scaled)
        parent_w, parent_h = sizes[father]
        offset = _pivot_offset(parent_w, parent_h, tree)
        point = (rotated[0] + offset[0], rotated[1] + offset[1], rotated[2] + offset[2])
        if _rect_name(father, rects, names).strip().lower() == "canvas":
            return point
        current = father


def _pivot_offset(parent_w: float, parent_h: float, tree: dict) -> tuple[float, float, float]:
    x, y, width, height = _local_rect((parent_w, parent_h), tree)
    pivot = tree.get("m_Pivot") or {}
    px = x + float(pivot.get("x") or 0) * width
    py = y + float(pivot.get("y") or 0) * height
    local = tree.get("m_LocalPosition") or {}
    return px - parent_w / 2, py - parent_h / 2, float(local.get("z") or 0)


def _project_layout_42(point: tuple[float, float, float]) -> tuple[float, float] | None:
    width, height = _LAYOUT_42_CANVAS
    scale = _LAYOUT_42_CANVAS_SCALE
    camera_z = _LAYOUT_42_CAMERA_Z + point[2] * scale
    if camera_z <= 1:
        return None
    half_v = math.tan(math.radians(_LAYOUT_42_FOV / 2))
    half_h = half_v * (width / height)
    nx = (point[0] * scale / camera_z) / half_h
    ny = (point[1] * scale / camera_z) / half_v
    return (nx * 0.5 + 0.5) * width, height - ((ny * 0.5 + 0.5) * height)


def _warp_quad(
    sprite: Image.Image,
    corners: list[tuple[float, float]],
    size: tuple[int, int],
) -> Image.Image | None:
    src = [(0, sprite.height), (sprite.width, sprite.height), (sprite.width, 0), (0, 0)]
    coeffs = _perspective_coeffs(src, corners)
    if coeffs is None:
        return None
    warped = sprite.transform(size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(corners, fill=255)
    warped.putalpha(ImageChops.multiply(warped.getchannel("A"), mask))
    return warped


def _perspective_coeffs(
    src: list[tuple[float, float]],
    dst: list[tuple[float, float]],
) -> tuple[float, ...] | None:
    """Map output pixels (dst) back to sprite pixels (src)."""
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, v])
    solved = _solve_linear(rows)
    if solved is None:
        return None
    return tuple(solved)


def _solve_linear(rows: list[list[float]]) -> list[float] | None:
    size = len(rows)
    matrix = [list(row) for row in rows]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(matrix[row][col]))
        if abs(matrix[pivot][col]) < 1e-8:
            return None
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        scale = matrix[col][col]
        for col_index in range(col, size + 1):
            matrix[col][col_index] /= scale
        for row in range(size):
            if row == col:
                continue
            factor = matrix[row][col]
            if factor == 0:
                continue
            for col_index in range(col, size + 1):
                matrix[row][col_index] -= factor * matrix[col][col_index]
    return [matrix[row][size] for row in range(size)]


def _quat(tree: dict) -> tuple[float, float, float, float]:
    rotation = tree.get("m_LocalRotation") or {}
    return (
        float(rotation.get("x") or 0),
        float(rotation.get("y") or 0),
        float(rotation.get("z") or 0),
        float(rotation.get("w") or 1),
    )


def _quat_rotate(
    quat: tuple[float, float, float, float],
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z, w = quat
    vx, vy, vz = point
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _rect_name(path_id: int, rects: dict[int, dict], names: dict[int, str]) -> str:
    go = _pointer(rects[path_id].get("m_GameObject"))
    return names.get(go or -1, "")


def _ancestors(path_id: int, rects: dict[int, dict], names: dict[int, str]) -> list[int]:
    chain = []
    current = _pointer(rects[path_id].get("m_Father"))
    while current in rects:
        chain.append(current)
        current = _pointer(rects[current].get("m_Father"))
    return chain


def _open_avatar_ring(card: Image.Image | None, number: str) -> Image.Image | None:
    """Make layout 00031's dashed sun interior transparent.

    The sun sprite is a hollow ring. The white footer sits behind that hole, so
    the disk renders as solid white. Env fill runs after the composite and would
    paint the hole shut again, so the punch happens on the finished card.
    """
    if card is None or number != "00031":
        return card
    hole = _dashed_ring_hole(card)
    if hole is None:
        return card
    cx, cy, radius = hole
    _clear_disk(card, cx, cy, radius)
    return card


def _dashed_ring_hole(card: Image.Image) -> tuple[float, float, float] | None:
    """Center and inner radius of a small dashed black ring, in card pixels."""
    pixels = card.load()
    width, height = card.size
    points: list[tuple[int, int]] = []
    min_x, min_y = width, height
    max_x, max_y = 0, 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 200 or red > 35 or green > 35 or blue > 35:
                continue
            points.append((x, y))
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if len(points) < 250:
        return None
    box_w = max_x - min_x
    box_h = max_y - min_y
    if box_w < 70 or box_h < 70 or box_w > 520 or box_h > 520:
        return None
    if abs(box_w - box_h) > 0.2 * max(box_w, box_h):
        return None
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    radii = sorted(math.hypot(x - cx, y - cy) for x, y in points)
    inner = radii[int(len(radii) * 0.05)]
    outer = radii[int(len(radii) * 0.95)]
    # Dashes share one radius. A filled mark or a cluster of separate strokes does not.
    if outer - inner > 36 or inner < 24:
        return None
    sample_x = min(width - 1, max(0, int(cx)))
    sample_y = min(height - 1, max(0, int(cy)))
    red, green, blue, alpha = pixels[sample_x, sample_y]
    if alpha < 200 or (red + green + blue) / 3 < 170:
        return None
    return cx, cy, inner - 2


def _clear_disk(canvas: Image.Image, cx: float, cy: float, radius: float) -> None:
    """Punch a circular hole through everything already on the canvas."""
    if radius < 8:
        return
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    canvas.putalpha(ImageChops.subtract(canvas.getchannel("A"), mask))


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
