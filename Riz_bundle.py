#!/usr/bin/env python3
"""
Riz_bundle.py

Combined utility (handles bundle renaming/moving, pretty-printing chart JSON exports,
level table export with chart info, and riz/notes processing).

Use `--download` to fetch the current Rizline catalog, patch resources, and base
resources before running the normal export pipeline. Existing downloads are kept;
use `--clear-download` with `--download` only when you explicitly want to remove
the local download cache first.

This version:
 - Ensures a cache folder exists under the working directory named 'charts_info' (preferred)
   or 'chart_info' (legacy). If neither exists, creates 'charts_info'.
 - When exporting the level table, reads output/charts/{chartId}.json and writes per-song cache
   files into charts_info/ (flat files):
     - <Song>_<lv>_col.txt  (rizcol header + rizcol lines if available)
     - <Song>_<lv>_notes.txt (notes summary + notes/type\tnotes/time\tnotes_riz)
 - By default removes all data in charts_info before exporting levels; keeps it when --keep-info is specified.
 - When chart JSONs lack per-note riz flags, merges parsed notes with cache notes by time/type to apply riz flags.
 - Flip test uses the (start, end] range from challengeTimes.
 - CLI: --keep-info controls whether charts_info is preserved.

Note: The export-levels step computes charts/Hit, charts/Combo, and charts/Score.
"""

from pathlib import Path
import json
import re
import shutil
import os
import sys
import tempfile
import base64
import hashlib
import struct
import time
from decimal import Decimal, InvalidOperation
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Any, List, Tuple, Dict

# Requests is only required for the optional resource downloader.
try:
    import requests
except ImportError:
    requests = None

# Optional UnityPy import (only needed for chart export)
try:
    import UnityPy
    UNITYPY_AVAILABLE = True
except Exception:
    UNITYPY_AVAILABLE = False

# --- Configuration / Paths (download/bundles) ---
FILELIST = Path("download") / "fileList.json"
BACKUP = Path("download") / "fileList.json.bak"
BUNDLES_DIR = Path("download") / "bundles"

DIR_CHARTS = BUNDLES_DIR / "charts"
DIR_ILLUST = BUNDLES_DIR / "illust"
DIR_ILLUST_HIRES = BUNDLES_DIR / "illust_HiRes"

OUT_CHARTS_JSON = Path("output") / "charts"
OUT_ILLUST = Path("output") / "illust"
OUT_ILLUST_HIRES = Path("output") / "illust_HiRes"
LEVELS_OUTPUT = Path("output.txt")
DATABASE_OUTPUT = Path("Database.txt")
DATA_DIR = Path(__file__).resolve().parent
SONGS_JSON_OUTPUT = DATA_DIR / "songs.json"
MAPPING_JSON_OUTPUT = DATA_DIR / "mapping.json"
ACHIEVEMENT_LANGUAGES = ("en", "ja", "zh-Hans", "zh-Hant")
LOCALIZED_LANGUAGES = ACHIEVEMENT_LANGUAGES
B40_API_URL = "https://dragonred.cn/project/rizb40/api.php"
ADDITIONAL_API_JSON = ("bio", "achievement", "layout", "all_cache")
DOWNLOAD_DIR = Path("download")
CATALOG_PATH = DOWNLOAD_DIR / "catalog_catalog.json"
DOWNLOAD_WORKERS = 16
DOWNLOAD_TIMEOUT = 30


def get_rizline_version() -> Dict[str, str]:
    if requests is None:
        raise RuntimeError("The downloader requires requests. Install it with: pip install requests")

    url = "https://rizserver.pigeongames.net/game/server_api/v1/dis/"
    headers = {
        "game_id": "pigeongames.rizline",
        "channel_id": "11",
        "i18n": "zh-CN",
        "accept-encoding": "gzip, identity",
        "user-agent": "BestHTTP/2 v2.6.3",
    }
    response = requests.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    configs = data.get("configs")
    if not isinstance(configs, list) or not configs or not isinstance(configs[0], dict):
        raise ValueError("Rizline server response did not contain a valid resource configuration")
    config = configs[0]
    result = {
        "version": str(config["version"]),
        "resourceUrl": str(config["resourceUrl"]),
        "resourceBaseUrl": str(config["resourceBaseUrl"]).rstrip("/"),
        "resourceVersion": str(config["resourceVersion"]),
    }
    print(
        f"Rizline version: {result['version']}\n"
        f"Resource URL: {result['resourceUrl']}\n"
        f"Resource base URL: {result['resourceBaseUrl']}\n"
        f"Resource version: {result['resourceVersion']}"
    )
    return result


def download_resource(url: str, session: Any = None, force: bool = False) -> Tuple[bool, bool, float]:
    parsed_path = url.split("?", 1)[0]
    file_name = parsed_path.rsplit("/", 1)[-1]
    if not file_name:
        raise ValueError(f"Cannot determine filename from resource URL: {url}")
    save_dir = DOWNLOAD_DIR / "bundles" if file_name.endswith(".bundle") else DOWNLOAD_DIR
    if ".acb=" in file_name:
        save_dir = DOWNLOAD_DIR / "acb"
        file_name = file_name.split(".acb=", 1)[0] + ".acb"

    destination = save_dir / file_name
    if destination.is_file() and not force and file_name != "catalog_catalog.json":
        return True, False, 0.0

    if requests is None:
        raise RuntimeError("The downloader requires requests. Install it with: pip install requests")

    start = time.time()
    last_error: Optional[Exception] = None
    for attempt in range(3):
        temporary_path = destination.with_name(destination.name + ".part")
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            client = session or requests
            with client.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True) as response:
                response.raise_for_status()
                with temporary_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
            os.replace(temporary_path, destination)
            return True, False, time.time() - start
        except requests.exceptions.HTTPError as exc:
            temporary_path.unlink(missing_ok=True)
            if exc.response is not None and exc.response.status_code == 404:
                print(f"Resource not present on server (HTTP 404), skipping: {url}")
                return False, True, time.time() - start
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            temporary_path.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2 ** attempt)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            raise

    print(f"Download failed: {url}: {last_error}")
    return False, False, time.time() - start


def download_base_resource(
    original_url: str,
    version_chain: List[str],
    resource_base_url: str,
    session: Any,
) -> Tuple[bool, bool, float]:
    marker = "http://rizastcdn.pigeongames.cn/default"
    if marker not in original_url:
        return download_resource(original_url, session)

    relative_path = original_url.split(marker, 1)[1].lstrip("/")
    start = time.time()
    saw_network_error = False
    ordered_versions = ([version_chain[-1]] + version_chain) if version_chain else []
    for version in ordered_versions:
        url = f"{resource_base_url}/{version}/{relative_path}"
        succeeded, missing, _ = download_resource(url, session)
        if succeeded:
            return True, False, time.time() - start
        if not missing:
            saw_network_error = True
    if not saw_network_error:
        print(f"Base resource is not available in any checked version; skipping: {original_url}")
        return False, True, time.time() - start
    print(f"Could not find base resource in checked versions: {original_url}")
    return False, False, time.time() - start


def read_catalog_urls() -> List[str]:
    with CATALOG_PATH.open("r", encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    internal_ids = catalog.get("m_InternalIds")
    if not isinstance(internal_ids, list):
        raise ValueError(f"Catalog has no valid m_InternalIds list: {CATALOG_PATH}")

    urls = []
    for item in internal_ids:
        if not isinstance(item, str) or not item.startswith("http"):
            continue
        if ".acb=" in item:
            item = item.split(".bundle", 1)[0]
        urls.append(item)
    return urls


def parse_unity_catalog(catalog: Dict[str, Any]) -> List[List[Any]]:
    try:
        key_bytes = base64.b64decode(catalog["m_KeyDataString"])
        bucket_bytes = base64.b64decode(catalog["m_BucketDataString"])
        entry_bytes = base64.b64decode(catalog["m_EntryDataString"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Catalog is missing valid Unity key, bucket, or entry data") from exc
    if len(bucket_bytes) < 4:
        raise ValueError("Unity catalog bucket data is truncated")

    def read_int32(data: bytes, offset: int) -> int:
        if offset + 4 > len(data):
            raise ValueError("Unity catalog contains truncated bucket data")
        return struct.unpack_from("<i", data, offset)[0]

    bucket_count = read_int32(bucket_bytes, 0)
    if bucket_count < 0 or bucket_count > (len(bucket_bytes) - 4) // 8:
        raise ValueError("Unity catalog has an invalid bucket count")

    table: List[List[Any]] = []
    offset = 4
    for _ in range(bucket_count):
        key_pos = read_int32(bucket_bytes, offset)
        entry_count = read_int32(bucket_bytes, offset + 4)
        offset += 8
        if entry_count < 0 or entry_count > (len(bucket_bytes) - offset) // 4:
            raise ValueError("Unity catalog has an invalid entry count")
        key_val: Any = None
        if 0 <= key_pos < len(key_bytes):
            key_type = key_bytes[key_pos]
            current = key_pos + 1
            if key_type in (0, 1) and current + 4 <= len(key_bytes):
                string_length = key_bytes[current]
                current += 4
                value = key_bytes[current:current + string_length]
                key_val = value.decode("utf-8" if key_type == 0 else "utf-16-le", errors="ignore")
            elif key_type == 4 and current < len(key_bytes):
                key_val = key_bytes[current]

        entry_value: Any = 65535
        for _ in range(entry_count):
            entry_pos = read_int32(bucket_bytes, offset)
            offset += 4
            entry_start = 4 + 28 * entry_pos
            if entry_pos >= 0 and entry_start + 10 <= len(entry_bytes):
                entry_value = struct.unpack_from("<H", entry_bytes, entry_start + 8)[0]
        table.append([key_val, entry_value])

    for row in table:
        value = row[1]
        if isinstance(value, int) and value != 65535 and 0 <= value < len(table):
            row[1] = table[value][0]
    return table


def write_catalog_filelist() -> None:
    with CATALOG_PATH.open("r", encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    filelist = parse_unity_catalog(catalog)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (DOWNLOAD_DIR / "fileList.json").write_text(
        json.dumps(filelist, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_default_from_bundles() -> Path:
    if not UNITYPY_AVAILABLE:
        raise RuntimeError("Downloading and parsing Default.json requires UnityPy. Install it with: pip install UnityPy")
    if not BUNDLES_DIR.is_dir():
        raise FileNotFoundError(f"Downloaded bundle directory not found: {BUNDLES_DIR}")

    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for bundle_path in BUNDLES_DIR.iterdir():
        if not bundle_path.is_file():
            continue
        try:
            environment = UnityPy.load(str(bundle_path))
            for obj in environment.objects:
                if obj.type.name != "MonoBehaviour":
                    continue
                metadata = obj.read()
                if getattr(metadata, "m_Name", None) != "Default":
                    continue
                value = obj.read_typetree()
                if isinstance(value, dict) and isinstance(value.get("levels"), list):
                    count = len(value["levels"]) + len(value.get("discOLevels", []))
                    candidates.append((count, value))
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("No Default metadata was found in downloaded bundles")
    candidates.sort(key=lambda item: item[0], reverse=True)
    output_path = Path("output") / "default.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidates[0][1], indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Extracted Default.json ({candidates[0][0]} levels) -> {output_path}")
    return output_path


def export_localized_achievements(
    filelist_path: Path = FILELIST,
    bundles_dir: Path = BUNDLES_DIR,
    output_dir: Path = DATA_DIR,
) -> None:
    if not UNITYPY_AVAILABLE:
        raise RuntimeError("Exporting localized achievements requires UnityPy. Install it with: pip install UnityPy")
    if not filelist_path.is_file():
        raise FileNotFoundError(f"Unity file list not found: {filelist_path}")

    filelist = load_json(filelist_path)
    if not isinstance(filelist, list):
        raise ValueError(f"Unity file list must contain an array: {filelist_path}")

    bundle_names = {
        entry[0].strip(): entry[1].strip()
        for entry in filelist
        if isinstance(entry, list)
        and len(entry) >= 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], str)
    }
    failures = []
    exported = 0

    for language in ACHIEVEMENT_LANGUAGES:
        catalog_key = f"local.{language}.achievement"
        bundle_name = bundle_names.get(catalog_key)
        if not bundle_name:
            failures.append(f"{language}: {catalog_key} is missing from {filelist_path}")
            continue

        bundle_path = bundles_dir / bundle_name
        if not bundle_path.is_file():
            bundle_path = (
                find_case_insensitive(bundles_dir, bundle_name)
                if bundles_dir.is_dir()
                else None
            )
        if bundle_path is None or not bundle_path.is_file():
            failures.append(f"{language}: bundle '{bundle_name}' not found in {bundles_dir}")
            continue

        try:
            environment = UnityPy.load(str(bundle_path))
            text_asset = None
            for obj in environment.objects:
                if obj.type.name != "TextAsset":
                    continue
                data = obj.read()
                if getattr(data, "m_Name", None) == f"{language}.achievement":
                    text_asset = data
                    break
        except Exception as exc:
            failures.append(f"{language}: failed to read '{bundle_path.name}': {exc}")
            continue

        if text_asset is None:
            failures.append(f"{language}: TextAsset '{language}.achievement' not found in '{bundle_path.name}'")
            continue

        script = getattr(text_asset, "m_Script", None)
        if isinstance(script, (bytes, bytearray)):
            try:
                script = bytes(script).decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                failures.append(f"{language}: achievement TextAsset is not valid UTF-8: {exc}")
                continue
        elif not isinstance(script, str):
            failures.append(f"{language}: achievement TextAsset has no text script")
            continue

        achievement_titles: Dict[str, Dict[str, str]] = {}
        for line in script.splitlines():
            entry_key, separator, value = line.partition("=")
            if not separator:
                continue
            match = re.fullmatch(r"ach\.\[([^\]]+)\]\.(title1|title2)", entry_key.strip())
            if match:
                achievement_titles.setdefault(match.group(1), {})[match.group(2)] = value.strip()

        if not achievement_titles:
            failures.append(f"{language}: no achievement title entries found in '{bundle_path.name}'")
            continue

        achievements = {
            achievement_id: {
                title: titles.get(title, "")
                for title in ("title1", "title2")
            }
            for achievement_id, titles in achievement_titles.items()
        }
        output_path = output_dir / f"achievement_{language}.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(achievements, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if language == "zh-Hans":
                shutil.copyfile(output_path, output_dir / "achievement.json")
        except OSError as exc:
            failures.append(f"{language}: failed to write '{output_path}': {exc}")
            continue

        exported += 1
        print(f"Wrote {len(achievements)} localized achievement entries to {output_path}")

    if failures:
        raise RuntimeError("Localized achievement export incomplete: " + "; ".join(failures))
    print(f"Exported localized achievements for {exported}/{len(ACHIEVEMENT_LANGUAGES)} languages")


def export_localized_bios(
    filelist_path: Path = FILELIST,
    bundles_dir: Path = BUNDLES_DIR,
    output_dir: Path = DATA_DIR,
) -> None:
    if not UNITYPY_AVAILABLE:
        raise RuntimeError("Exporting localized bios requires UnityPy. Install it with: pip install UnityPy")
    if not filelist_path.is_file():
        raise FileNotFoundError(f"Unity file list not found: {filelist_path}")

    filelist = load_json(filelist_path)
    if not isinstance(filelist, list):
        raise ValueError(f"Unity file list must contain an array: {filelist_path}")

    bundle_names = {
        entry[0].strip(): entry[1].strip()
        for entry in filelist
        if isinstance(entry, list)
        and len(entry) >= 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], str)
    }
    failures = []
    exported = 0

    for language in LOCALIZED_LANGUAGES:
        catalog_key = f"local.{language}.bio"
        bundle_name = bundle_names.get(catalog_key)
        if not bundle_name:
            failures.append(f"{language}: {catalog_key} is missing from {filelist_path}")
            continue

        bundle_path = bundles_dir / bundle_name
        if not bundle_path.is_file():
            bundle_path = (
                find_case_insensitive(bundles_dir, bundle_name)
                if bundles_dir.is_dir()
                else None
            )
        if bundle_path is None or not bundle_path.is_file():
            failures.append(f"{language}: bundle '{bundle_name}' not found in {bundles_dir}")
            continue

        try:
            environment = UnityPy.load(str(bundle_path))
            text_asset = None
            for obj in environment.objects:
                if obj.type.name != "TextAsset":
                    continue
                data = obj.read()
                if getattr(data, "m_Name", None) == f"{language}.bio":
                    text_asset = data
                    break
        except Exception as exc:
            failures.append(f"{language}: failed to read '{bundle_path.name}': {exc}")
            continue

        if text_asset is None:
            failures.append(f"{language}: TextAsset '{language}.bio' not found in '{bundle_path.name}'")
            continue

        script = getattr(text_asset, "m_Script", None)
        if isinstance(script, (bytes, bytearray)):
            try:
                script = bytes(script).decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                failures.append(f"{language}: bio TextAsset is not valid UTF-8: {exc}")
                continue
        elif not isinstance(script, str):
            failures.append(f"{language}: bio TextAsset has no text script")
            continue

        bio_titles: Dict[str, Dict[str, str]] = {}
        for line in script.splitlines():
            entry_key, separator, value = line.partition("=")
            if not separator:
                continue
            match = re.fullmatch(r"bio\.([^.]+)\.(1|2)", entry_key.strip())
            if match:
                title = "title1" if match.group(2) == "1" else "title2"
                bio_titles.setdefault(match.group(1), {})[title] = value.strip()

        if not bio_titles:
            failures.append(f"{language}: no bio title entries found in '{bundle_path.name}'")
            continue

        bios = {
            bio_id: {
                title: titles.get(title, "")
                for title in ("title1", "title2")
            }
            for bio_id, titles in bio_titles.items()
        }
        output_path = output_dir / f"bio_{language}.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(bios, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if language == "zh-Hans":
                shutil.copyfile(output_path, output_dir / "bio.json")
        except OSError as exc:
            failures.append(f"{language}: failed to write '{output_path}': {exc}")
            continue

        exported += 1
        print(f"Wrote {len(bios)} localized bio entries to {output_path}")

    if failures:
        raise RuntimeError("Localized bio export incomplete: " + "; ".join(failures))
    print(f"Exported localized bios for {exported}/{len(LOCALIZED_LANGUAGES)} languages")


def download_all_game_data(clear_existing: bool = False) -> None:
    if requests is None:
        raise RuntimeError("The downloader requires requests. Install it with: pip install requests")
    if clear_existing and DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)

    version_info = get_rizline_version()
    current_version = version_info["resourceVersion"]
    version_chain = [current_version]

    catalog_url = f"{version_info['resourceBaseUrl']}/{current_version}/Android/catalog_catalog.json"
    print(f"Downloading catalog: {catalog_url}")
    success, _missing, _ = download_resource(catalog_url, force=True)
    if not success:
        if not CATALOG_PATH.is_file():
            print("ERROR: Current catalog download failed and no cached catalog is available; skipping resource downloads.")
            return
        print("Warning: using the existing cached catalog because the current catalog could not be downloaded.")

    base_urls = read_catalog_urls()
    patch_files: Dict[str, List[str]] = {}
    visited_versions = set()
    while current_version not in visited_versions:
        visited_versions.add(current_version)
        metadata_url = f"https://rizlineasset.pigeongames.net/versions/{current_version}/patch_metadata"
        try:
            response = requests.get(metadata_url, timeout=DOWNLOAD_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            print(f"Could not fetch patch metadata for {current_version}; continuing with what is available: {exc}")
            break
        if response.status_code == 404:
            print(f"No patch metadata found for {current_version}; reached end of version history.")
            break
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            print(f"Could not read patch metadata for {current_version}; continuing with what is available: {exc}")
            break
        lines = response.content.decode("utf-8").replace("catalog_catalog.json", "").replace("catalog_catalog.hash", "").splitlines()
        if not lines or not lines[0].strip():
            break
        patch_files[current_version] = [
            path
            for line in lines
            if (path := line.strip()).startswith("Android/")
            and path.rstrip("/")
            and Path(path).name
        ]
        current_version = lines[0].strip()
        if current_version in visited_versions:
            break
        version_chain.append(current_version)

    patch_urls = [
        f"{version_info['resourceBaseUrl']}/{version}/{relative_path}"
        for version, paths in patch_files.items()
        for relative_path in paths
    ]
    print(f"Downloading {len(patch_urls)} patch files and {len(base_urls)} catalog resources")

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=DOWNLOAD_WORKERS, pool_maxsize=DOWNLOAD_WORKERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    failures: List[str] = []
    missing_resources: List[str] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        futures = {
            executor.submit(download_resource, url, session): url
            for url in patch_urls
        }
        futures.update({
            executor.submit(
                download_base_resource,
                url,
                version_chain,
                version_info["resourceBaseUrl"],
                session,
            ): url
            for url in base_urls
        })
        for future in as_completed(futures):
            url = futures[future]
            try:
                succeeded, missing, elapsed = future.result()
            except Exception as exc:
                succeeded, missing, elapsed = False, False, 0.0
                print(f"Download error: {url}: {exc}")
            completed += 1
            if succeeded:
                print(f"Downloaded {completed}/{len(futures)} ({elapsed:.1f}s): {url.rsplit('/', 1)[-1]}")
            elif missing:
                missing_resources.append(url)
            else:
                failures.append(url)
            if completed % 50 == 0:
                print(f"Download progress: {completed}/{len(futures)}; failed {len(failures)}")

    if failures:
        print(f"Warning: {len(failures)} resources failed after retries; continuing with downloaded and cached resources.")
        for url in failures[:10]:
            print(f"  Failed: {url}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
    if missing_resources:
        print(
            f"Warning: {len(missing_resources)} catalog/patch resources returned HTTP 404 "
            "and were skipped; remaining resources will still be exported."
        )

    try:
        write_catalog_filelist()
    except Exception as exc:
        print(f"Warning: could not regenerate download/fileList.json: {exc}")
        if not FILELIST.is_file():
            print("ERROR: no catalog file list is available for bundle exports.")
    try:
        extract_default_from_bundles()
    except Exception as exc:
        print(f"Warning: could not extract a new Default.json: {exc}")
        if not (Path("output") / "default.json").is_file():
            print("ERROR: no Default.json is available for level exports.")
    print(f"Resource download complete. Versions checked: {version_chain}")

# charts_info cache root selection/creation
def ensure_charts_info_root() -> Path:
    """
    Prefer 'charts_info'. If it doesn't exist but legacy 'chart_info' exists, use that.
    If neither exists, create 'charts_info'.
    """
    preferred = Path("charts_info")
    legacy = Path("chart_info")
    if preferred.exists():
        return preferred
    if legacy.exists():
        return legacy
    # neither exists: create preferred folder 'charts_info'
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        # fallback: create legacy
        legacy.mkdir(parents=True, exist_ok=True)
        return legacy

CHARTS_INFO_ROOT = ensure_charts_info_root()

# --- Regex patterns ---
CHART_MR_RE = re.compile(r"^chart\.([^\.]+)\.[^\.]+\.0\.mr\.([^\.]+)$")
CHART_RE = re.compile(r"^chart\.([^\.]+)\.[^\.]+\.0\.([^\.]+)$")
CHART_SP_RE = re.compile(r"^chart\.([^\.]+)\.[^\.]+\.1\.([^\.]+)$")
ILLUST_RE = re.compile(r"^illustration\.([^\.]+)\.[^\.]+\.0(?:\.([^\.]+))?$")

# -------------------------
# JSON helpers (from riz_color)
# -------------------------
def remove_trailing_commas(s: str) -> str:
    s = re.sub(r',\s*(\])', r'\1', s)
    s = re.sub(r',\s*(\})', r'\1', s)
    return s

def find_array_by_key(text: str, key: str) -> Optional[str]:
    pattern = f'"{re.escape(key)}"'
    m = re.search(pattern, text)
    if not m:
        return None
    idx = m.end()
    while idx < len(text) and text[idx] not in '[{':
        idx += 1
    if idx >= len(text) or text[idx] != '[':
        return None
    start = idx
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None

def safe_load_array(text: str, key: str) -> List[Any]:
    try:
        whole = json.loads(text)
        val = whole.get(key, [])
        if isinstance(val, list):
            return val
    except Exception:
        pass
    arr_text = find_array_by_key(text, key)
    if arr_text:
        cleaned = remove_trailing_commas(arr_text)
        try:
            return json.loads(cleaned)
        except Exception:
            try:
                return json.loads(cleaned.replace("'", '"'))
            except Exception:
                return []
    return []

# -------------------------
# Color formatting
# -------------------------
def rgba_to_tuple(color_obj: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(color_obj, dict):
        return None
    try:
        r = int(color_obj.get("r", 0))
        g = int(color_obj.get("g", 0))
        b = int(color_obj.get("b", 0))
        a = int(color_obj.get("a", 0))
        return (r, g, b, a)
    except Exception:
        return None

def rgba_to_string(color_obj: Dict[str, Any]) -> str:
    t = rgba_to_tuple(color_obj)
    if not t:
        return ""
    r, g, b, a = t
    return f"{r},{g},{b},{a}"

def rgba_to_hex(color_obj: Dict[str, Any]) -> str:
    t = rgba_to_tuple(color_obj)
    if not t:
        return ""
    r, g, b, a = t
    if a == 255:
        return "#{:02X}{:02X}{:02X}".format(r & 0xFF, g & 0xFF, b & 0xFF)
    else:
        return "#{:02X}{:02X}{:02X}{:02X}".format(r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF)

# -------------------------
# File writing (atomic)
# -------------------------
def atomic_write_lines(path: Path, lines: List[str]) -> None:
    dirpath = path.parent
    dirpath.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(prefix=path.stem + "_tmp_", dir=str(dirpath), text=True)
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
        try:
            dirfd = os.open(str(dirpath), os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except Exception:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

# -------------------------
# Extraction functions (notes and rizcol)
# -------------------------
def format_rizcol_line(idx: int, colors: List[Dict[str, Any]], cp_entry: Optional[Dict[str, Any]], use_hex: bool) -> str:
    if use_hex:
        vals = [rgba_to_hex(c) for c in colors]
    else:
        vals = [rgba_to_string(c) for c in colors]
    while len(vals) < 3:
        vals.append("")
    bg, notes_col, hit_eff = vals[:3]
    if cp_entry:
        cp = cp_entry.get("checkPoint", "")
        start = cp_entry.get("start", "")
        end = cp_entry.get("end", "")
        trans = cp_entry.get("transTime", "")
        return f"{idx}\t{bg}\t{notes_col}\t{hit_eff}\t{cp}\t{start}\t{end}\t{trans}"
    else:
        return f"{idx}\t{bg}\t{notes_col}\t{hit_eff}\t\t\t\t"

def note_type_sort_key(note_type: Any):
    if isinstance(note_type, int):
        return (0, note_type)
    if isinstance(note_type, str):
        key = note_type.strip().lower()
        if key in {"2a", "2b"}:
            return (0, 2, 0 if key == "2a" else 1)
        try:
            return (0, int(key), 0)
        except Exception:
            return (1, key)
    return (2, str(note_type))


def normalize_note_type(note_type: Any) -> Any:
    if isinstance(note_type, str):
        key = note_type.strip().lower()
        if key in {"2a", "2b"}:
            return key
        if key == "2":
            return 2
        try:
            return int(key)
        except Exception:
            return note_type.strip()
    return note_type


def notes_with_hold_ids(notes: List[Tuple[float, Any, int]]) -> List[Tuple[float, Any, str, int]]:
    chronological = sorted(notes, key=lambda note: float(note[0]))
    pending_hold_ids: List[str] = []
    next_hold_id = 1
    rows: List[Tuple[float, Any, str, int]] = []

    for time_value, note_type, riz in chronological:
        normalized_type = normalize_note_type(note_type)
        note_id = "-1"
        if normalized_type == "2a":
            note_id = str(next_hold_id)
            pending_hold_ids.append(note_id)
            next_hold_id += 1
        elif normalized_type == "2b":
            if pending_hold_ids:
                note_id = pending_hold_ids.pop(0)
            else:
                note_id = str(next_hold_id)
                next_hold_id += 1
        rows.append((time_value, normalized_type, note_id, riz))

    return rows


def synchronize_hold_riz_flags(notes: List[Tuple[float, Any, int]]) -> List[Tuple[float, Any, int]]:
    rows = notes_with_hold_ids(notes)
    head_riz_by_id = {
        note_id: riz
        for _, note_type, note_id, riz in rows
        if note_type == "2a" and note_id != "-1"
    }
    return [
        (time_value, note_type, head_riz_by_id.get(note_id, riz) if note_type == "2b" else riz)
        for time_value, note_type, note_id, riz in rows
    ]


def note_duration_value(note: Dict[str, Any], time_value: Optional[float] = None) -> Any:
    raw_type = note.get("type", note.get("noteType", note.get("tType", 0)))
    if normalize_note_type(raw_type) == 2:
        infos = note.get("otherInformations", [])
        if isinstance(infos, list) and infos:
            try:
                end_time = float(infos[0])
            except Exception:
                end_time = None
            if end_time is not None and time_value is not None:
                return end_time - float(time_value)
    for key in ("duration", "holdDuration", "length", "len", "endTime", "end", "timeEnd"):
        if key in note:
            return note.get(key)
    return None


def split_hold_note(time_value: float, ttype: Any, riz_flag: int, duration_value: Any = None) -> List[Tuple[float, Any, int]]:
    """
    For hold notes, split one note into a head and tail: type 2 -> type 2a / type 2b.
    The head and the tail both carry the same riz flag.
    """
    normalized = normalize_note_type(ttype)
    if normalized != 2:
        return [(float(time_value), normalized, int(riz_flag))]

    if duration_value is None:
        return [(float(time_value), "2a", int(riz_flag))]

    try:
        duration = float(duration_value)
    except Exception:
        try:
            duration = float(str(duration_value).strip())
        except Exception:
            return [(float(time_value), "2a", int(riz_flag))]

    if duration == 0:
        return [(float(time_value), "2a", int(riz_flag))]

    end_time = float(time_value) + abs(duration)
    return [(float(time_value), "2a", int(riz_flag)), (end_time, "2b", int(riz_flag))]


def extract_notes_from_lines(lines_array: List[Any]) -> List[Tuple[float, Any, float]]:
    """
    Returns list of tuples: (time_as_float, type_as_int_or_string, original_time_value)
    Hold notes are split into 2a/2b head/tail pairs when a duration is available.
    """
    out: List[Tuple[float, Any, float]] = []
    for line in lines_array:
        if not isinstance(line, dict):
            continue
        notes = line.get("notes", [])
        if not isinstance(notes, list) or len(notes) == 0:
            continue
        for n in notes:
            if not isinstance(n, dict):
                continue
            n_type = n.get("type", "")
            n_time = n.get("time", "")
            try:
                tval = float(n_time)
            except Exception:
                continue
            try:
                ttype = int(n_type)
            except Exception:
                try:
                    ttype = str(n_type).strip()
                except Exception:
                    continue

            duration_value = note_duration_value(n, tval)
            for expanded in split_hold_note(tval, ttype, 0, duration_value):
                out.append((expanded[0], expanded[1], tval))
    return out

# -------------------------
# Parse rizcol ranges (start .. end)
# -------------------------
def parse_rizcol_ranges_from_lines(rizcol_lines: List[str]) -> List[Tuple[float, float]]:
    """
    Parse rizcol lines (including header) and return (start, end] ranges.
    """
    ranges: List[Tuple[float, float]] = []
    if not rizcol_lines:
        return ranges
    # find header index (first non-empty)
    header_idx = 0
    for i, line in enumerate(rizcol_lines):
        if line.strip() == "":
            continue
        header_idx = i
        break
    for line in rizcol_lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        raw_start = ""
        raw_end = ""
        if len(parts) >= 6:
            raw_start = parts[5].strip()
        if len(parts) >= 7:
            raw_end = parts[6].strip()
        try:
            start_val = float(raw_start) if raw_start != "" else None
        except Exception:
            start_val = None
        try:
            end_val = float(raw_end) if raw_end != "" else None
        except Exception:
            end_val = None
        if start_val is not None and end_val is not None:
            if start_val <= end_val:
                ranges.append((start_val, end_val))
            else:
                ranges.append((end_val, start_val))
    return ranges

def apply_rizcol_ranges_to_notes(rizcol_lines: List[str], notes: List[Tuple[float, int, int]]) -> List[Tuple[float, int, int]]:
    """
    Given rizcol lines and a list of notes (time, type, riz_flag),
    return a new notes list where riz_flag is set to 1 for any note whose time
    falls within any rizcol range (start, end], exclusive at start and inclusive at end.
    """
    if not rizcol_lines or not notes:
        return notes
    ranges = parse_rizcol_ranges_from_lines(rizcol_lines)
    if not ranges:
        return notes
    updated: List[Tuple[float, int, int]] = []
    for ttime, ttype, riz in notes:
        new_riz = riz
        if new_riz == 0:
            for start, end in ranges:
                try:
                    if start < ttime <= end:
                        new_riz = 1
                        break
                except Exception:
                    continue
        updated.append((ttime, ttype, new_riz))
    return updated

# -------------------------
# Process riz and notes using riz_color logic (integrated)
# -------------------------
def process_riz_and_notes(input_path: Path, use_hex: bool = False, cache_root: Path = CHARTS_INFO_ROOT, keep_info: bool = False):
    """
    Reads input JSON, writes <stem>_rizcol.txt and <stem>_notes.txt into cache_root/<stem>/,
    then updates notes_riz based on challengeTimes (start, end] ranges.
    Removes the cache folder after completion unless keep_info is True.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"{input_path} not found")

    stem = input_path.stem
    cache_dir = cache_root / stem
    cache_dir.mkdir(parents=True, exist_ok=True)

    out_rizcol = cache_dir / f"{stem}_rizcol.txt"
    out_notes = cache_dir / f"{stem}_notes.txt"

    raw = input_path.read_text(encoding="utf-8", errors="replace")
    if raw.startswith("\ufeff"):
        raw = raw.lstrip("\ufeff")

    themes = safe_load_array(raw, "themes")
    challenge_times = safe_load_array(raw, "challengeTimes")
    lines_array = safe_load_array(raw, "lines")

    # --- write rizcol file ---
    rizcol_header = "colorList_id\tBG\tNotes\tHit_Eff\tCP\tstart\tend\ttransTime"
    rizcol_lines: List[str] = [rizcol_header]
    for i, theme in enumerate(themes):
        colorList_id = i + 1
        colors = []
        if isinstance(theme, dict):
            colors = theme.get("colorsList", []) or []
            if not isinstance(colors, list):
                colors = []
        cp_index = i - 1
        cp_entry = challenge_times[cp_index] if 0 <= cp_index < len(challenge_times) else None
        rizcol_lines.append(format_rizcol_line(colorList_id, colors, cp_entry, use_hex))

    atomic_write_lines(out_rizcol, rizcol_lines)
    print(f"Wrote {len(themes)} theme lines to {out_rizcol}")

    # --- extract notes and write initial notes file (notes_riz default 0) ---
    notes_tuples = extract_notes_from_lines(lines_array)
    notes_tuples.sort(key=lambda x: x[0])  # sort by time

    counts_total: Dict[Any, int] = {}
    counts_riz1: Dict[Any, int] = {}

    for _, ttype, _ in notes_tuples:
        norm_t = normalize_note_type(ttype)
        counts_total[norm_t] = counts_total.get(norm_t, 0) + 1

    summary_lines = ["# Note type counts (total\triz1)"]
    for t in sorted(counts_total.keys(), key=note_type_sort_key):
        summary_lines.append(f"type_{t}\t{counts_total.get(t,0)}\t{0}")
    summary_lines.append("")
    note_rows = notes_with_hold_ids(
        [(time, ttype, 0) for (time, ttype, _) in notes_tuples]
    )
    notes_data_lines = [f"{ttype}\t{time}\t{note_id}\t{riz}" for time, ttype, note_id, riz in note_rows]
    notes_header = "notes/type\tnotes/time\tnotes/id\tnotes_riz"
    initial_notes_lines = summary_lines + [notes_header] + notes_data_lines

    atomic_write_lines(out_notes, initial_notes_lines)
    print(f"Wrote {len(notes_tuples)} note lines to {out_notes}")

    # --- update notes_riz based on rizcol ranges (start, end] ---
    ranges = parse_rizcol_ranges_from_lines(rizcol_lines)

    updated_notes: List[Tuple[float, Any, int]] = []

    for (time_val, ttype, orig_time) in notes_tuples:
        norm_t = normalize_note_type(ttype)
        riz_val = 0
        in_range = any(start < time_val <= end for (start, end) in ranges)
        if in_range:
            riz_val = 1
        updated_notes.append((time_val, norm_t, riz_val))

    updated_notes = synchronize_hold_riz_flags(updated_notes)
    counts_total = {}
    counts_riz1 = {}
    for time_val, norm_t, riz_val in updated_notes:
        counts_total[norm_t] = counts_total.get(norm_t, 0) + 1
        if riz_val == 1:
            counts_riz1[norm_t] = counts_riz1.get(norm_t, 0) + 1

    summary_lines = ["# Note type counts (total\triz1)"]
    all_types = sorted(set(list(counts_total.keys()) + list(counts_riz1.keys())), key=note_type_sort_key)
    for t in all_types:
        total = counts_total.get(t, 0)
        riz1 = counts_riz1.get(t, 0)
        summary_lines.append(f"type_{t}\t{total}\t{riz1}")

    t0 = counts_total.get(0, 0)
    t1 = counts_total.get(1, 0)
    t2 = counts_total.get("2a", 0) + counts_total.get("2b", 0)
    hit = t0 + t1 + t2
    combo = hit * 4 - 24
    riz1_t0 = counts_riz1.get(0, 0)
    riz1_t1 = counts_riz1.get(1, 0)
    riz1_t2 = counts_riz1.get("2a", 0) + counts_riz1.get("2b", 0)
    score = 1000000 + riz1_t0 * 100 + riz1_t1 * 100 + riz1_t2 * 200

    summary_lines.append("")  # blank line before aggregates
    summary_lines.append(f"Hit\t{hit}")
    summary_lines.append(f"Combo\t{combo}")
    summary_lines.append(f"Score\t{score}")
    summary_lines.append("")  # blank line before data header

    note_rows = notes_with_hold_ids(updated_notes)
    updated_data = [f"{ttype}\t{time_value}\t{note_id}\t{riz}" for time_value, ttype, note_id, riz in note_rows]
    final_notes_lines = summary_lines + [notes_header] + updated_data

    # Write updated notes atomically (overwrite)
    atomic_write_lines(out_notes, final_notes_lines)
    print(f"Updated notes written to {out_notes}")

    # Remove cache folder unless keep_info is True
    if not keep_info:
        try:
            # remove the entire stem directory
            if cache_dir.exists() and cache_dir.is_dir():
                shutil.rmtree(cache_dir)
                print(f"Removed cache folder {cache_dir}")
        except Exception as e:
            print(f"Warning: failed to remove cache folder {cache_dir}: {e}")
    else:
        print(f"Kept cache folder {cache_dir} (--keep-info specified)")

# -------------------------
# Other utilities and exporters (charts export, level export with stats)
# -------------------------
def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1

def find_case_insensitive(cwd: Path, name: str) -> Optional[Path]:
    lower = name.lower()
    for f in cwd.iterdir():
        if f.is_file() and f.name.lower() == lower:
            return f
    return None

def ensure_dirs(dirs: List[Path]):
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

def safe_relpath(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(str(path), str(start))
    except Exception:
        return str(path)

# --- Derive expected chart bundle names from chartId (handles SP and MR) ---
def derive_chart_bundle_candidates(chart_id: str) -> List[str]:
    candidates: List[str] = []
    if not isinstance(chart_id, str):
        return candidates
    parts = chart_id.split(".")
    if len(parts) >= 5 and parts[0] == "chart":
        song = parts[1]
        # MR form: chart.Song.Artist.0.mr.lv
        if parts[3] == "0" and parts[4] == "mr" and len(parts) >= 6:
            lv = parts[5]
            candidates.append(f"{song}_{lv}_mr.bundle")
            candidates.append(f"{song}_{lv}.bundle")
        # Normal 0 form: chart.Song.Artist.0.lv
        elif parts[3] == "0":
            lv = parts[4]
            candidates.append(f"{song}_{lv}.bundle")
            candidates.append(f"{song}_{lv}_mr.bundle")
        # SP form: chart.Song.Artist.1.lv  -> Song_lv.bundle (no duplicate _SP)
        elif parts[3] == "1":
            lv = parts[4]
            candidates.append(f"{song}_{lv}.bundle")
            candidates.append(f"{song}_{lv}_SP.bundle")  # fallback if explicit
    return candidates

# --- Finder that tries original name then derived chart names ---
def find_bundle_in_dir_with_chart_fallback(bundles_dir: Path, bundle_name: str, chart_id: str = None) -> Optional[Path]:
    candidate = bundles_dir / bundle_name
    if candidate.is_file():
        return candidate
    if not bundle_name.lower().endswith(".bundle"):
        candidate2 = bundles_dir / (bundle_name + ".bundle")
        if candidate2.is_file():
            return candidate2
    lower = bundle_name.lower()
    for f in bundles_dir.iterdir():
        if f.is_file() and f.name.lower() == lower:
            return f
    if not bundle_name.lower().endswith(".bundle"):
        lower2 = (bundle_name + ".bundle").lower()
        for f in bundles_dir.iterdir():
            if f.is_file() and f.name.lower() == lower2:
                return f
    if chart_id:
        for cand in derive_chart_bundle_candidates(chart_id):
            cpath = bundles_dir / cand
            if cpath.is_file():
                return cpath
            lower_c = cand.lower()
            for f in bundles_dir.iterdir():
                if f.is_file() and f.name.lower() == lower_c:
                    return f
            stem = Path(cand).stem
            for f in bundles_dir.iterdir():
                if f.is_file() and f.suffix.lower() == ".bundle" and f.stem.startswith(stem):
                    return f
    return None


def export_illustrations(filelist_path: Path,
                         bundles_dir: Path = BUNDLES_DIR,
                         output_dir: Path = OUT_ILLUST,
                         output_hires_dir: Path = OUT_ILLUST_HIRES) -> None:
    if not UNITYPY_AVAILABLE:
        print("UnityPy not available. Install with: pip install UnityPy")
        return
    if not filelist_path.exists():
        print(f"fileList.json not found at {filelist_path}; skipping illustration export")
        return

    try:
        filelist = load_json(filelist_path)
    except Exception as e:
        print(f"ERROR reading {filelist_path}: {e}")
        return
    if not isinstance(filelist, list):
        print(f"Unexpected fileList.json format at {filelist_path}; expected a list")
        return

    entries = []
    for entry in filelist:
        if not (isinstance(entry, list) and len(entry) >= 2
                and isinstance(entry[0], str) and isinstance(entry[1], str)):
            continue
        key = entry[0].strip()
        match = ILLUST_RE.match(key)
        if match:
            entries.append((key, entry[1].strip(), match.group(1), match.group(2)))

    if not entries:
        print("No illustration entries found in fileList.json")
        return

    exported = 0
    for key, bundle_name, song, hires in entries:
        destination = output_hires_dir if hires else output_dir
        destination.mkdir(parents=True, exist_ok=True)

        candidate_paths = [
            bundles_dir / bundle_name,
            DIR_ILLUST_HIRES / bundle_name,
            DIR_ILLUST / bundle_name,
        ]
        renamed_dir = DIR_ILLUST_HIRES if hires else DIR_ILLUST
        renamed_stem = f"{song}_illust_{hires}" if hires else f"{song}_illust"
        candidate_paths.append(renamed_dir / f"{renamed_stem}.bundle")
        bundle_file = next((path for path in candidate_paths if path.is_file()), None)
        if bundle_file is None:
            lower_name = bundle_name.lower()
            for search_dir in (renamed_dir, bundles_dir):
                if not search_dir.is_dir():
                    continue
                bundle_file = next(
                    (path for path in search_dir.iterdir()
                     if path.is_file() and path.name.lower() == lower_name),
                    None,
                )
                if bundle_file is None:
                    prefix = renamed_stem.lower()
                    bundle_file = next(
                        (path for path in search_dir.iterdir()
                         if path.is_file() and path.suffix.lower() == ".bundle"
                         and path.stem.lower().startswith(prefix)),
                        None,
                    )
                if bundle_file is not None:
                    break

        if bundle_file is None:
            print(f"Skipping {key}: illustration bundle '{bundle_name}' not found")
            continue

        try:
            env = UnityPy.load(str(bundle_file))
        except Exception as e:
            print(f"ERROR loading illustration bundle '{bundle_file.name}': {e}")
            continue

        base_name = re.sub(r'[<>:"/\\|?*]', "_", key)
        image_count = 0
        for obj in env.objects:
            if obj.type.name not in {"Sprite", "Texture2D"}:
                continue
            try:
                data = obj.read()
                image = getattr(data, "image", None)
                if image is None:
                    continue
                suffix = "" if image_count == 0 else f"_{image_count + 1}"
                image.save(destination / f"{base_name}{suffix}.png")
                image_count += 1
            except Exception as e:
                print(f"Warning: failed to export image from '{bundle_file.name}': {e}")

        if image_count:
            exported += 1
            print(f"Exported {key} -> {destination} ({image_count} image(s))")
        else:
            print(f"Skipping {key}: no Sprite or Texture2D images found in '{bundle_file.name}'")

    print(f"Done: exported illustrations for {exported}/{len(entries)} entries")


# --- Rename & move step ---
def rename_and_move(filelist_path: Path, bundles_dir: Path, dry_run: bool = False):
    cwd = Path.cwd()
    if not filelist_path.exists():
        print(f"Error: {filelist_path} not found in {cwd}")
        return

    try:
        data = load_json(filelist_path)
    except Exception as e:
        print(f"Error reading {filelist_path}: {e}")
        return

    if not isinstance(data, list):
        print("Error: fileList.json root is not a JSON array.")
        return

    try:
        shutil.copy2(filelist_path, BACKUP)
        print(f"Backup created: {BACKUP}")
    except Exception as e:
        print(f"Warning: could not create backup: {e}")

    ensure_dirs([DIR_CHARTS, DIR_ILLUST, DIR_ILLUST_HIRES])
    changed = False

    for idx, entry in enumerate(data):
        if not (isinstance(entry, list) and len(entry) >= 2 and
                isinstance(entry[0], str) and isinstance(entry[1], str)):
            continue

        key = entry[0].strip()
        bundle_name = entry[1].strip()

        m_chart_mr = CHART_MR_RE.match(key)
        m_chart = None if m_chart_mr else CHART_RE.match(key)
        m_chart_sp = None if (m_chart_mr or m_chart) else CHART_SP_RE.match(key)
        m_illust = None if (m_chart_mr or m_chart or m_chart_sp) else ILLUST_RE.match(key)

        if m_chart_mr:
            song = m_chart_mr.group(1)
            lv = m_chart_mr.group(2)
            desired_name = f"{song}_{lv}_mr.bundle"
            dest_dir = DIR_CHARTS
        elif m_chart:
            song = m_chart.group(1)
            lv = m_chart.group(2)
            desired_name = f"{song}_{lv}.bundle"
            dest_dir = DIR_CHARTS
        elif m_chart_sp:
            song = m_chart_sp.group(1)
            lv = m_chart_sp.group(2)
            desired_name = f"{song}_{lv}.bundle"
            dest_dir = DIR_CHARTS
        elif m_illust:
            song = m_illust.group(1)
            hires = m_illust.group(2)
            base = f"{song}_illust"
            desired_name = f"{base}_{hires}.bundle" if hires else f"{base}.bundle"
            dest_dir = DIR_ILLUST_HIRES if hires else DIR_ILLUST
        else:
            continue

        src_path = bundles_dir / bundle_name
        if not src_path.is_file():
            found = find_case_insensitive(bundles_dir, bundle_name)
            if found:
                src_path = found
            else:
                continue

        target_path = dest_dir / desired_name

        try:
            if target_path.exists() and src_path.resolve() == target_path.resolve():
                if entry[1] != target_path.name:
                    if not dry_run:
                        entry[1] = target_path.name
                    changed = True
                continue
        except Exception:
            pass

        if target_path.exists():
            target_path = unique_target(target_path)

        print(f"Action: move '{src_path.name}' -> '{safe_relpath(target_path, cwd)}'")
        if not dry_run:
            try:
                shutil.move(str(src_path), str(target_path))
            except Exception as e:
                print(f"ERROR moving '{src_path.name}' -> '{target_path}': {e}")
                continue
            entry[1] = target_path.name
            changed = True

    if changed and not dry_run:
        try:
            save_json(filelist_path, data)
            print(f"{filelist_path.name} updated. Backup saved as {BACKUP}")
        except Exception as e:
            print(f"ERROR writing {filelist_path}: {e}")
    elif changed and dry_run:
        print("Dry run complete. No files or JSON were modified.")
    else:
        print("Rename/move: no changes required.")

# --- Note extraction from chart JSON (robust) ---
def extract_notes_from_chart_obj(chart_obj: Any) -> List[Tuple[float, int, int]]:
    """
    Return list of tuples (time, type, riz_flag)
    - time: float
    - type: int (0/1/2)
    - riz_flag: 1 if note marked riz (riz, notes_riz, riz1, etc.), else 0
    """
    out: List[Tuple[float, int, int]] = []

    def parse_note(n: Any) -> List[Tuple[float, Any, int]]:
        if not isinstance(n, dict):
            return []
        # time
        t_raw = n.get("time", n.get("t", None))
        try:
            t = float(t_raw)
        except Exception:
            return []
        # type
        raw_type = n.get("type", n.get("noteType", n.get("tType", 0)))
        try:
            ttype = int(raw_type)
        except Exception:
            try:
                ttype = normalize_note_type(str(raw_type).strip())
            except Exception:
                return []
        # riz flag detection (several possible names)
        riz_val = 0
        for k in ("riz", "notes_riz", "riz1", "isRiz", "is_riz"):
            if k in n:
                try:
                    riz_val = 1 if int(n.get(k, 0)) else 0
                except Exception:
                    riz_val = 1 if bool(n.get(k)) else 0
                break
        duration_value = note_duration_value(n, t)
        return split_hold_note(t, ttype, riz_val, duration_value)

    # 1) If chart_obj has "lines" array like riz_color_combined expects
    if isinstance(chart_obj, dict):
        if "lines" in chart_obj and isinstance(chart_obj["lines"], list):
            for line in chart_obj["lines"]:
                if not isinstance(line, dict):
                    continue
                notes = line.get("notes", [])
                if isinstance(notes, list):
                    for n in notes:
                        for parsed in parse_note(n):
                            out.append(parsed)
            return out

        # 2) top-level "notes" array
        if "notes" in chart_obj and isinstance(chart_obj["notes"], list):
            for n in chart_obj["notes"]:
                for parsed in parse_note(n):
                    out.append(parsed)
            return out

    # 3) If chart_obj is a list of notes directly
    if isinstance(chart_obj, list):
        for n in chart_obj:
            for parsed in parse_note(n):
                out.append(parsed)
        return out

    # 4) Try to find any nested "lines" or "notes" keys by scanning values
    if isinstance(chart_obj, dict):
        for v in chart_obj.values():
            if isinstance(v, list):
                if v and isinstance(v[0], dict) and ("time" in v[0] or "notes" in v[0]):
                    # if it's a list of lines
                    if isinstance(v[0], dict) and "notes" in v[0]:
                        for line in v:
                            if not isinstance(line, dict):
                                continue
                            notes = line.get("notes", [])
                            if isinstance(notes, list):
                                for n in notes:
                                    for parsed in parse_note(n):
                                        out.append(parsed)
                        return out
                    # else treat as list of notes
                    for n in v:
                        for parsed in parse_note(n):
                            out.append(parsed)
                    return out

    return out

# --- Extract rizcol (themes + challengeTimes) from parsed chart object ---
def extract_rizcol_from_chart_obj(chart_obj: Any, use_hex: bool = False) -> Optional[List[str]]:
    """
    If chart_obj contains 'themes' and/or 'challengeTimes', build rizcol lines similar to riz_color.
    Returns list of lines including header, or None if nothing found.
    """
    if not isinstance(chart_obj, dict):
        return None

    themes = chart_obj.get("themes", None)
    challenge_times = chart_obj.get("challengeTimes", None)

    if not isinstance(themes, list) and not isinstance(challenge_times, list):
        return None

    # ensure lists
    themes_list = themes if isinstance(themes, list) else []
    challenge_list = challenge_times if isinstance(challenge_times, list) else []

    rizcol_header = "colorList_id\tBG\tNotes\tHit_Eff\tCP\tstart\tend\ttransTime"
    rizcol_lines: List[str] = [rizcol_header]

    for i, theme in enumerate(themes_list):
        colorList_id = i + 1
        colors = []
        if isinstance(theme, dict):
            colors = theme.get("colorsList", []) or []
            if not isinstance(colors, list):
                colors = []
        cp_index = i - 1
        cp_entry = challenge_list[cp_index] if 0 <= cp_index < len(challenge_list) else None
        rizcol_lines.append(format_rizcol_line(colorList_id, colors, cp_entry, use_hex))

    return rizcol_lines

# --- Compute Hit, Combo, Score from notes list (kept for compatibility) ---
def compute_hit_combo_score(notes: List[Tuple[float, Any, int]]) -> Tuple[int, int, int]:
    notes = synchronize_hold_riz_flags(notes)
    counts_total: Dict[Any, int] = {}
    counts_riz1: Dict[Any, int] = {}
    for _, ttype, riz in notes:
        normalized = normalize_note_type(ttype)
        counts_total[normalized] = counts_total.get(normalized, 0) + 1
        if riz:
            counts_riz1[normalized] = counts_riz1.get(normalized, 0) + 1

    t0 = counts_total.get(0, 0)
    t1 = counts_total.get(1, 0)
    t2a = counts_total.get("2a", 0)
    t2b = counts_total.get("2b", 0)
    hit = t0 + t1 + t2a + t2b
    combo = hit * 4 - 24
    riz1_t0 = counts_riz1.get(0, 0)
    riz1_t1 = counts_riz1.get(1, 0)
    riz1_hold_events = counts_riz1.get("2a", 0) + counts_riz1.get("2b", 0)
    score = 1000000 + 100 * (riz1_t0 + riz1_t1 + riz1_hold_events)
    return hit, combo, score

# --- Helpers for cache fallback (flat files under charts_info root) ---
def load_riz_notes_from_cache(cache_name: str, cache_root: Path = CHARTS_INFO_ROOT) -> Optional[List[Tuple[float, Any, int]]]:
    """
    Load notes from charts_info/<cache_name>_notes.txt and return list of (time, type, riz_flag).
    Returns None if file not found or parsing fails.
    """
    try:
        notes_file = cache_root / f"{cache_name}_notes.txt"
        if not notes_file.exists():
            return None
        lines = notes_file.read_text(encoding="utf-8", errors="replace").splitlines()
        data_idx = None
        riz_idx = 2
        for i, ln in enumerate(lines):
            if ln.strip().startswith("notes/type"):
                data_idx = i
                header = ln.split("\t")
                if "notes_riz" in header:
                    riz_idx = header.index("notes_riz")
                break
        if data_idx is None:
            return None
        notes_list: List[Tuple[float, Any, int]] = []
        for ln in lines[data_idx + 1:]:
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) < 3:
                continue
            try:
                ttype = normalize_note_type(parts[0])
                ttime = float(parts[1])
                riz = int(parts[riz_idx])
                notes_list.append((ttime, ttype, riz))
            except Exception:
                continue
        return notes_list
    except Exception:
        return None

def song_from_chart_id(chart_id: str) -> Optional[str]:
    """
    chartId format: chart.SongName.Artist.0.IN  -> returns SongName
    """
    if not isinstance(chart_id, str):
        return None
    parts = chart_id.split(".")
    if len(parts) >= 2 and parts[0] == "chart":
        return parts[1]
    return None

# --- Merge parsed notes with cache riz flags by matching time and type ---
def merge_parsed_notes_with_cache(parsed_notes: List[Tuple[float, int, int]],
                                  cache_notes: List[Tuple[float, int, int]],
                                  time_tolerance: float = 0.05) -> List[Tuple[float, int, int]]:
    """
    For each parsed note (time, type, riz_flag), if parsed riz_flag is 0 or missing,
    try to find a cache note with same type and time within time_tolerance seconds.
    If found, use cache riz flag for that note. Returns a new list of notes with riz flags applied.
    """
    if not parsed_notes:
        return []
    if not cache_notes:
        return parsed_notes

    cache_by_type: Dict[int, List[Tuple[float, int, int]]] = {}
    for ttime, ttype, riz in cache_notes:
        cache_by_type.setdefault(ttype, []).append((ttime, ttype, riz))

    for ttype in cache_by_type:
        cache_by_type[ttype].sort(key=lambda x: x[0])

    merged: List[Tuple[float, int, int]] = []
    for p_time, p_type, p_riz in parsed_notes:
        final_riz = p_riz if p_riz else 0
        if final_riz == 0:
            candidates = cache_by_type.get(p_type, [])
            lo = 0
            hi = len(candidates) - 1
            best_idx = None
            best_dt = None
            while lo <= hi:
                mid = (lo + hi) // 2
                mid_time = candidates[mid][0]
                if mid_time < p_time:
                    lo = mid + 1
                else:
                    hi = mid - 1
            for idx in (lo - 1, lo, lo + 1):
                if 0 <= idx < len(candidates):
                    c_time, c_type, c_riz = candidates[idx]
                    dt = abs(c_time - p_time)
                    if dt <= time_tolerance:
                        if best_dt is None or dt < best_dt:
                            best_dt = dt
                            best_idx = idx
            if best_idx is not None:
                final_riz = candidates[best_idx][2]
        merged.append((p_time, p_type, final_riz))
    return merged

# --- Write charts_info cache files (flat files under charts_info root) ---
def write_charts_info_cache(cache_name: str,
                            notes: List[Tuple[float, int, int]],
                            cache_root: Path = CHARTS_INFO_ROOT,
                            rizcol_lines: Optional[List[str]] = None) -> None:
    """
    Write two files into charts_info/:
      - <cache_name>_col.txt  (header + rizcol_lines if provided, otherwise minimal header)
      - <cache_name>_notes.txt (summary + notes/type\tnotes/time\tnotes_riz)
    'cache_name' should be SongName_lv (no extension).
    """
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        # write _col file
        col_path = cache_root / f"{cache_name}_col.txt"
        if rizcol_lines and isinstance(rizcol_lines, list) and len(rizcol_lines) > 0:
            atomic_write_lines(col_path, rizcol_lines)
        else:
            col_lines = ["colorList_id\tBG\tNotes\tHit_Eff\tCP\tstart\tend\ttransTime"]
            atomic_write_lines(col_path, col_lines)

        counts_total: Dict[Any, int] = {}
        counts_riz1: Dict[Any, int] = {}
        chronological_notes = synchronize_hold_riz_flags(notes)
        for ttime, ttype, riz in chronological_notes:
            norm_t = normalize_note_type(ttype)
            counts_total[norm_t] = counts_total.get(norm_t, 0) + 1
            if riz:
                counts_riz1[norm_t] = counts_riz1.get(norm_t, 0) + 1

        notes_path = cache_root / f"{cache_name}_notes.txt"
        lines: List[str] = []
        lines.append("# Note type counts (total\triz1)")
        for t in sorted(counts_total.keys(), key=note_type_sort_key):
            lines.append(f"type_{t}\t{counts_total.get(t,0)}\t{counts_riz1.get(t,0)}")
        lines.append("")
        lines.append("notes/type\tnotes/time\tnotes/id\tnotes_riz")
        note_rows = notes_with_hold_ids(chronological_notes)
        for ttime, ttype, note_id, riz in note_rows:
            lines.append(f"{ttype}\t{ttime}\t{note_id}\t{riz}")
        atomic_write_lines(notes_path, lines)
    except Exception as e:
        print(f"Warning: failed to write charts_info cache for '{cache_name}': {e}")

# --- Level table export with chart stats (reads charts_json/{chartId}.json) ---
SEP = "\t"

def diff_from_chart(chart):
    if not isinstance(chart, str):
        return ""
    parts = chart.split(".")
    return parts[-1] if parts else ""

def sanitize_music_name(name):
    if not isinstance(name, str):
        return ""
    return " ".join(name.replace("\r", " ").replace("\n", " ").split())

def normalize_disc_name(disc):
    if not isinstance(disc, str):
        return ""
    disc = disc.strip()
    m = re.match(r"^Disc\s+(\d+)$", disc, re.IGNORECASE)
    if m:
        return m.group(1)
    if disc == "EX - Single":
        return "EX-S"
    if disc == "EX - T.S.":
        return "EX-TS"
    return disc

def find_default_json_candidates(directory: Optional[Path] = None) -> List[Path]:
    if directory is not None:
        candidates = [directory / "Default.json", directory / "default.json"]
    else:
        candidates = [
            Path("Default.json"),
            Path("default.json"),
            Path("MonoBehaviour") / "Default.json",
            Path("MonoBehaviour") / "default.json",
            Path("download") / "Default.json",
            Path("download") / "default.json",
            Path("output") / "Default.json",
            Path("output") / "default.json",
            Path("download") / "output" / "Default.json",
            Path("download") / "output" / "default.json",
        ]
    return [p for p in candidates if p.is_file()]

def find_score_json_candidates(directory: Path) -> List[Path]:
    names = ("gameData_global.json", "gameData.json", "game_data.json")
    return [directory / name for name in names if (directory / name).is_file()]

def build_music_title_map(default_data: Dict[str, Any]) -> Dict[str, str]:
    music_map: Dict[str, str] = {}
    musics = default_data.get("musics", [])
    if isinstance(musics, list):
        for music in musics:
            if not isinstance(music, dict):
                continue
            music_id = music.get("id")
            music_name = music.get("musicName")
            if isinstance(music_id, str) and music_id and isinstance(music_name, str):
                music_map[music_id] = sanitize_music_name(music_name)

    for level_key in ("levels", "discOLevels"):
        levels = default_data.get(level_key, [])
        if not isinstance(levels, list):
            continue
        for level in levels:
            if not isinstance(level, dict):
                continue
            level_id = level.get("id")
            music_id = level.get("musicId")
            if isinstance(level_id, str) and isinstance(music_id, str):
                title = music_map.get(music_id)
                if title is not None:
                    music_map[level_id] = title
    return music_map


def export_rizb40_json(database_lines: List[str]) -> None:
    """Write songs.json and mapping.json in the format consumed by the B40 tool."""
    if not database_lines:
        raise ValueError("Database export is empty")

    header = database_lines[0].split(SEP)
    columns = {name: index for index, name in enumerate(header)}
    required = (
        "Trackid",
        "musics/musicName",
        "musics/ArtistName",
        "Diff",
        "charts/difficulty",
        "charts/Hit",
        "charts/Combo",
        "charts/Score",
    )
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(f"Database export is missing columns: {', '.join(missing)}")

    chart_difficulties = ("EZ", "HD", "IN", "AT")
    songs_by_track: Dict[str, Dict[str, str]] = {}
    mapping: Dict[str, str] = {}

    for line_number, line in enumerate(database_lines[1:], start=2):
        if not line:
            continue
        values = line.split(SEP)
        if len(values) < len(header):
            values.extend([""] * (len(header) - len(values)))

        def value(column: str) -> str:
            return values[columns[column]].strip()

        track_id = value("Trackid")
        title = value("musics/musicName")
        artist = value("musics/ArtistName")
        difficulty = value("Diff")
        disc_name = value("level/discName") if "level/discName" in columns else ""
        if not track_id:
            print(f"Warning: skipping Database.txt row {line_number}: missing Trackid")
            continue

        song = songs_by_track.setdefault(track_id, {
            "Page": title,
            "Title": title,
            "Artist": artist,
        })
        if disc_name:
            song["discName"] = normalize_disc_name(disc_name)
        if title:
            song["Page"] = title
            song["Title"] = title
            mapping[track_id] = title
        if artist:
            song["Artist"] = artist

        if difficulty not in chart_difficulties:
            continue

        song[f"{difficulty} Lv"] = value("charts/difficulty")
        song[f"{difficulty} Hit"] = value("charts/Hit")
        song[f"{difficulty} Combo"] = value("charts/Combo")
        score = value("charts/Score")
        song[f"{difficulty} Score"] = score
        try:
            riz_hit = str((Decimal(score) - Decimal(1_000_000)) / Decimal(100)) if score else ""
        except InvalidOperation:
            print(f"Warning: invalid score in Database.txt row {line_number}: {score!r}")
            riz_hit = ""
        if riz_hit and "." in riz_hit:
            riz_hit = riz_hit.rstrip("0").rstrip(".")
        song[f"{difficulty} RizHit"] = riz_hit

    for song in songs_by_track.values():
        for difficulty in chart_difficulties:
            for suffix in ("Lv", "Hit", "Combo", "Score", "RizHit"):
                song.setdefault(f"{difficulty} {suffix}", "")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SONGS_JSON_OUTPUT.write_text(
        json.dumps(list(songs_by_track.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    MAPPING_JSON_OUTPUT.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote B40 songs data to {SONGS_JSON_OUTPUT}")
    print(f"Wrote B40 track mapping to {MAPPING_JSON_OUTPUT}")
    export_additional_api_json()


def export_additional_api_json() -> None:
    if requests is None:
        raise RuntimeError("Exporting API metadata requires requests. Install it with: pip install requests")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    for action in ADDITIONAL_API_JSON:
        try:
            response = requests.get(
                B40_API_URL,
                params={"action": action},
                timeout=DOWNLOAD_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("expected a JSON object or array")
            output_path = DATA_DIR / f"{action}.json"
            output_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Wrote B40 API data to {output_path}")
        except (requests.exceptions.RequestException, ValueError, OSError) as exc:
            failures.append(f"{action}: {exc}")
            print(f"ERROR exporting API action {action}: {exc}")
    if failures:
        raise RuntimeError("Some API datasets could not be exported: " + "; ".join(failures))

def export_mybest_scores(
    score_json_path: Optional[Path],
    output_dir: Path,
    music_map: Dict[str, str],
    fallback_username: str = "",
) -> None:
    if score_json_path is None:
        candidates = find_score_json_candidates(output_dir)
        if not candidates:
            print(
                "Score export skipped: no gameData_global.json, gameData.json, or "
                "game_data.json found; specify --score-json <file>."
            )
            return
        score_json_path = candidates[0]
    elif not score_json_path.is_file():
        print(f"ERROR: score JSON not found: {score_json_path}")
        return

    try:
        with score_json_path.open("r", encoding="utf-8") as f:
            score_data = json.load(f)
    except Exception as e:
        print(f"ERROR reading score JSON {score_json_path}: {e}")
        return

    if not isinstance(score_data, dict):
        print(f"ERROR: score JSON must contain a JSON object: {score_json_path}")
        return

    my_best = score_data.get("myBest")
    if not isinstance(my_best, list):
        print(f"ERROR: 'myBest' array not found in score JSON: {score_json_path}")
        return

    username = score_data.get("username") or score_data.get("userName") or fallback_username
    if not isinstance(username, str) or not username.strip():
        print("ERROR: username is missing from both the score JSON and Default.json.")
        return
    safe_username = re.sub(r"[^\w.-]", "_", username.strip()).strip(".")
    if not safe_username:
        print(f"ERROR: username cannot be used for an output filename: {username!r}")
        return

    lines = ["Title\tDiff\tIs_AP\tscore\tAcc"]
    for index, record in enumerate(my_best, start=1):
        if not isinstance(record, dict):
            print(f"Warning: skipping invalid myBest entry #{index}: expected an object")
            continue

        track_asset_id = record.get("trackAssetId")
        if not isinstance(track_asset_id, str) or not track_asset_id:
            print(f"Warning: skipping myBest entry #{index}: missing trackAssetId")
            continue
        music_id = track_asset_id[6:] if track_asset_id.startswith("track.") else track_asset_id
        title = music_map.get(music_id)
        if title is None:
            title = music_id
            print(
                f"Warning: no music title found for trackAssetId {track_asset_id!r}; "
                "writing its ID instead."
            )

        difficulty = record.get("difficultyClassName", "")
        full_combo = record.get("isFullCombo", False)
        score = record.get("score", "")
        accuracy = record.get("completeRate", "")
        if isinstance(accuracy, (int, float)) and not isinstance(accuracy, bool):
            accuracy = f"{accuracy:.5f}"
        lines.append(SEP.join([
            sanitize_music_name(title),
            str(difficulty),
            "1" if full_combo is True else "0",
            str(score),
            str(accuracy),
        ]))

    output_path = output_dir / f"{safe_username}_Score.txt"
    try:
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote player scores to {output_path}")
    except Exception as e:
        print(f"ERROR writing score table to {output_path}: {e}")

def export_level_table_with_chart_stats(output_path: Path, charts_json_dir: Path, default_json_path: Optional[Path] = None, cache_root: Path = CHARTS_INFO_ROOT, keep_info: bool = False, score_json_path: Optional[Path] = None):
    """
    Export level table and for each chart attempt to gather notes info.
    Computes charts/Hit, charts/Combo, and charts/Score using cached or parsed notes.
    """
    # clear cache unless keep_info
    try:
        if cache_root.exists() and cache_root.is_dir() and not keep_info:
            shutil.rmtree(cache_root)
            cache_root.mkdir(parents=True, exist_ok=True)
            print(f"Cleared cache folder {cache_root}")
        else:
            cache_root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Warning: could not reset cache folder {cache_root}: {e}")

    # find Default.json
    def find_default():
        if default_json_path is not None:
            if default_json_path.is_dir():
                candidates = find_default_json_candidates(default_json_path)
            elif default_json_path.is_file():
                return default_json_path
            else:
                candidates = []
        else:
            candidates = find_default_json_candidates()
        return candidates[0] if candidates else None

    default_path = find_default()
    if not default_path:
        if default_json_path is not None:
            print(
                f"Default.json not found at {default_json_path}; "
                "provide a directory containing Default.json or default.json."
            )
        else:
            print("Default.json not found in expected locations.")
        return

    try:
        with default_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR reading {default_path}: {e}")
        return

    # Build music_map and chart_map
    music_map = build_music_title_map(data)
    music_details: Dict[str, Tuple[str, str]] = {}
    for music in data.get("musics", []):
        if not isinstance(music, dict):
            continue
        music_id = music.get("id")
        if isinstance(music_id, str) and music_id:
            title = music.get("musicName", "")
            artist = music.get("artist", music.get("artistName", ""))
            music_details[music_id] = (
                title if isinstance(title, str) else "",
                artist if isinstance(artist, str) else "",
            )

    chart_map = {}
    for c in data.get("charts", []):
        cid = c.get("id", "")
        difficulty = c.get("difficulty", "")
        designer = c.get("designer", "")
        if cid:
            chart_map[cid] = (difficulty, designer)

    header = SEP.join([
        "tracknum",
        "musics/musicName",
        "Diff",
        "level/discName",
        "charts/difficulty",
        "charts/Hit",
        "charts/Combo",
        "charts/Score",
        "charts/designer",
        "level/seriesIndex",
    ])

    lines = [header]
    database_lines = [SEP.join([
        "Trackid",
        "musics/musicName",
        "musics/ArtistName",
        "Diff",
        "charts/difficulty",
        "level/discName",
        "charts/Hit",
        "charts/Combo",
        "charts/Score",
        "charts/designer",
        "level/seriesIndex",
    ])]

    tracknum = 1
    prev_id = None

    if isinstance(data, dict):
        levels = data.get("levels", []) + data.get("discOLevels", [])
    else:
        print("Default.json format unexpected: expected an object with 'levels'")
        return

    for lvl in levels:
        lvl_id = lvl.get("id", "")
        chart_ids = lvl.get("chartIds", [])
        disc = lvl.get("discName", "")
        series = lvl.get("seriesIndex", "")

        if prev_id is not None and lvl_id != prev_id:
            tracknum += 1
        prev_id = lvl_id

        music_name = music_map.get(lvl_id, "")
        disc_norm = normalize_disc_name(disc)
        music_id = lvl.get("musicId", "")
        database_music_name, artist_name = music_details.get(music_id, ("", ""))
        if not database_music_name:
            database_music_name = music_name

        for chart in chart_ids:
            # skip SP charts
            if CHART_SP_RE.match(chart):
                continue

            chart_diff = diff_from_chart(chart)
            diff = chart_diff or ""
            difficulty_raw, designer = chart_map.get(chart, ("", ""))

            # format difficulty to one decimal place if numeric
            difficulty_str = ""
            if isinstance(difficulty_raw, (int, float)):
                difficulty_str = f"{float(difficulty_raw):.1f}"
            else:
                try:
                    num = float(str(difficulty_raw))
                    difficulty_str = f"{num:.1f}"
                except Exception:
                    difficulty_str = str(difficulty_raw)

            hit_str = ""
            combo_str = ""
            score_str = ""

            # 1) Try to parse chart JSON and extract notes + riz flags and rizcol
            chart_file = charts_json_dir / f"{chart}.json"
            notes_for_stats: Optional[List[Tuple[float, int, int]]] = None
            parsed_notes_have_riz = False
            parsed_notes_exist = False
            parsed_notes: List[Tuple[float, int, int]] = []
            parsed_rizcol_lines: Optional[List[str]] = None

            if chart_file.exists():
                try:
                    raw = chart_file.read_text(encoding="utf-8", errors="replace")
                    parsed = None
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        start_idx = None
                        for i, ch in enumerate(raw):
                            if ch in "{[":
                                start_idx = i
                                break
                        if start_idx is not None:
                            try:
                                parsed = json.loads(raw[start_idx:])
                            except Exception:
                                parsed = None
                    if parsed is not None:
                        parsed_notes = extract_notes_from_chart_obj(parsed)
                        parsed_rizcol_lines = extract_rizcol_from_chart_obj(parsed, use_hex=False)
                        if parsed_notes:
                            parsed_notes_exist = True
                            if any(riz for (_, _, riz) in parsed_notes):
                                parsed_notes_have_riz = True
                                notes_for_stats = parsed_notes
                            else:
                                notes_for_stats = parsed_notes
                except Exception:
                    # ignore parsing errors
                    pass

            # Determine song name and lv for cache file naming
            song = song_from_chart_id(chart)
            lv = diff_from_chart(chart) or ""
            # sanitize cache name to avoid problematic characters
            def _sanitize_cache_name(s: str) -> str:
                return re.sub(r'[^\w\-_\.]', '_', s) if s else s
            cache_name = _sanitize_cache_name(f"{song}_{lv}" if song else chart.replace(".", "_"))

            # If parsed rizcol_lines exist, apply them to parsed notes to flip riz flags
            if parsed_rizcol_lines and parsed_notes:
                # apply ranges to parsed notes (this will set riz=1 for notes inside ranges using start+trans .. end+trans)
                parsed_notes = apply_rizcol_ranges_to_notes(parsed_rizcol_lines, parsed_notes)
                parsed_notes_have_riz = any(riz for (_, _, riz) in parsed_notes)
                notes_for_stats = parsed_notes

            # 2) If parsed notes exist but no riz flags, try to load riz notes from cache by cache_name and merge
            if parsed_notes_exist and not parsed_notes_have_riz:
                cache_notes = load_riz_notes_from_cache(cache_name, cache_root=cache_root)
                if cache_notes:
                    merged = merge_parsed_notes_with_cache(parsed_notes, cache_notes, time_tolerance=0.05)
                    notes_for_stats = merged
                    write_charts_info_cache(cache_name, merged, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)
                else:
                    # no cache; write parsed notes as cache (no riz flags)
                    if parsed_notes:
                        write_charts_info_cache(cache_name, parsed_notes, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)

            # 3) If parsed notes missing entirely; try cache by cache_name
            if not parsed_notes_exist:
                cache_notes = load_riz_notes_from_cache(cache_name, cache_root=cache_root)
                if cache_notes:
                    notes_for_stats = cache_notes

            # 4) If parsed notes exist and already have riz flags, but some notes may still be missing riz flags,
            #    attempt to fill missing riz flags from cache as well
            if parsed_notes_exist and parsed_notes_have_riz:
                if any(riz == 0 for (_, _, riz) in parsed_notes):
                    cache_notes = load_riz_notes_from_cache(cache_name, cache_root=cache_root)
                    if cache_notes:
                        merged = merge_parsed_notes_with_cache(parsed_notes, cache_notes, time_tolerance=0.05)
                        notes_for_stats = merged
                        write_charts_info_cache(cache_name, merged, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)
                    else:
                        notes_for_stats = parsed_notes
                        write_charts_info_cache(cache_name, parsed_notes, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)
                else:
                    if parsed_notes:
                        notes_for_stats = parsed_notes
                        write_charts_info_cache(cache_name, parsed_notes, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)

            # 5) If we have notes_for_stats, ensure cache is written and compute stats
            if notes_for_stats:
                write_charts_info_cache(cache_name, notes_for_stats, cache_root=cache_root, rizcol_lines=parsed_rizcol_lines)
                try:
                    hit_val, combo_val, score_val = compute_hit_combo_score(notes_for_stats)
                    hit_str = str(hit_val)
                    combo_str = str(combo_val)
                    score_str = str(score_val)
                except Exception:
                    hit_str = ""
                    combo_str = ""
                    score_str = ""

            lines.append(SEP.join([
                str(tracknum),
                music_name,
                diff,
                disc_norm,
                difficulty_str,
                hit_str,
                combo_str,
                score_str,
                designer,
                str(series)
            ]))
            database_lines.append(SEP.join([
                str(lvl_id),
                database_music_name,
                artist_name,
                diff,
                difficulty_str,
                str(disc),
                hit_str,
                combo_str,
                score_str,
                str(designer),
                str(series),
            ]))

    try:
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote level table with chart info to {output_path}")
    except Exception as e:
        print(f"ERROR writing {output_path}: {e}")
    try:
        DATABASE_OUTPUT.write_text("\n".join(database_lines), encoding="utf-8")
        print(f"Wrote Rizline B40 database to {DATABASE_OUTPUT}")
    except Exception as e:
        print(f"ERROR writing {DATABASE_OUTPUT}: {e}")
    try:
        export_rizb40_json(database_lines)
    except Exception as e:
        print(f"ERROR exporting B40 songs/mapping JSON: {e}")
    export_mybest_scores(
        score_json_path,
        output_path.parent,
        music_map,
        fallback_username=data.get("username", ""),
    )

# --- Backwards-compatible export_level_table_search_default (wrapper) ---
def export_level_table_search_default(
    output_path: Path,
    keep_info: bool = False,
    default_json_path: Optional[Path] = None,
    score_json_path: Optional[Path] = None,
):
    export_level_table_with_chart_stats(
        output_path,
        OUT_CHARTS_JSON,
        default_json_path=default_json_path,
        cache_root=CHARTS_INFO_ROOT,
        keep_info=keep_info,
        score_json_path=score_json_path,
    )

# --- CLI and main ---
def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Rename/move bundles, export charts, export level table, and process riz/notes")
    p.add_argument("--download", action="store_true", help="Download the latest Rizline resources before running exports")
    p.add_argument("--clear-download", action="store_true", help="Clear the existing download/ directory before --download")
    p.add_argument("--rename", action="store_true", help="Run rename & move step")
    p.add_argument("--export-charts", action="store_true", help="Export charts and illustrations into output/")
    p.add_argument("--export-achievements", action="store_true", help="Export localized achievement JSON files from downloaded bundles")
    p.add_argument("--export-bios", action="store_true", help="Export localized bio JSON files from downloaded bundles")
    p.add_argument("--export-levels", action="store_true", help="Export level table from Default.json to output.txt (including chart stats)")
    p.add_argument("--default-json-dir", "-djd", type=Path, help="Directory containing Default.json (used with --export-levels; searches automatically if omitted)")
    p.add_argument("--score-json", type=Path, help="Player save JSON containing myBest (auto-detects common filenames in the output folder if omitted)")
    p.add_argument("--se", "--score-export", dest="score_export", action="store_true", help="Export only the player's myBest scores to <username>_Score.txt")
    p.add_argument("--dry-run", action="store_true", help="Dry run for rename step (no file moves or JSON writes)")
    p.add_argument("--riz", action="store_true", help="Run riz & notes extraction/update for a given input file (see --input)")
    p.add_argument("--input", type=str, help="Input JSON file for riz processing (used with --riz)")
    p.add_argument("--hex", action="store_true", help="When used with --riz, output colors as HEX")
    p.add_argument("--keep-info", action="store_true", help="When used with --riz or --export-levels, keep charts_info cache files after completion")
    return p.parse_args()

def main():
    args = parse_args()
    run_default_pipeline = len(sys.argv) == 1
    if run_default_pipeline:
        args.download = True
    if args.clear_download and not args.download:
        print("Error: --clear-download can only be used with --download")
        return
    if args.download:
        print("=== Download Rizline resources ===")
        try:
            download_all_game_data(clear_existing=args.clear_download)
        except Exception as exc:
            print(f"ERROR downloading Rizline resources: {exc}")
            print("Continuing to the requested export steps with any local data already available.")

    run_all_exports = run_default_pipeline or not (
        args.rename or args.export_charts or args.export_achievements or args.export_bios or args.export_levels or args.riz or args.score_export
    )
    run_rename = args.rename or run_all_exports
    run_export_charts = args.export_charts or run_all_exports
    run_export_achievements = args.export_achievements or run_all_exports
    run_export_bios = args.export_bios or run_all_exports
    run_export_levels = args.export_levels or run_all_exports

    if args.riz:
        if not args.input:
            print("Error: --input <file> is required when using --riz")
            return
        inp = Path(args.input)
        try:
            process_riz_and_notes(inp, use_hex=args.hex, cache_root=CHARTS_INFO_ROOT, keep_info=args.keep_info)
        except Exception as e:
            print(f"ERROR processing riz/notes: {e}")
        return

    if args.score_export:
        default_path = None
        if args.default_json_dir is not None:
            if args.default_json_dir.is_file():
                default_path = args.default_json_dir
            elif args.default_json_dir.is_dir():
                candidates = find_default_json_candidates(args.default_json_dir)
                default_path = candidates[0] if candidates else None
        else:
            candidates = find_default_json_candidates()
            default_path = candidates[0] if candidates else None

        if default_path is None:
            print("ERROR: Default.json not found; use --default-json-dir to specify its file or directory.")
            return
        try:
            with default_path.open("r", encoding="utf-8") as f:
                default_data = json.load(f)
        except Exception as e:
            print(f"ERROR reading Default.json {default_path}: {e}")
            return
        if not isinstance(default_data, dict) or not isinstance(default_data.get("musics"), list):
            print(f"ERROR: Default.json has no valid 'musics' array: {default_path}")
            return

        music_map = build_music_title_map(default_data)

        export_mybest_scores(
            args.score_json,
            Path("."),
            music_map,
            fallback_username=default_data.get("username", ""),
        )
        return

    if run_default_pipeline:
        print("=== Download finished; continuing with default exports ===")

    if run_rename:
        print("=== Rename & move step ===")
        try:
            rename_and_move(FILELIST, BUNDLES_DIR, dry_run=args.dry_run)
        except Exception as exc:
            print(f"ERROR during rename & move; continuing to exports: {exc}")

    if run_export_charts:
        print("=== Export charts step ===")
        charts_dir = DIR_CHARTS
        if not charts_dir.is_dir():
            print(f"Charts directory '{charts_dir}' not found; skipping export charts")
        else:
            # This script keeps the export_charts function available but it requires UnityPy.
            # If UnityPy is not available, the function will print a message.
            def extract_textasset_script(bundle_path: Path) -> Optional[bytes]:
                if not UNITYPY_AVAILABLE:
                    print("UnityPy not available. Install with: pip install UnityPy")
                    return None
                try:
                    env = UnityPy.load(str(bundle_path))
                except Exception as e:
                    print(f"ERROR: failed to load bundle '{bundle_path.name}': {e}")
                    return None

                for obj in env.objects:
                    try:
                        if obj.type.name == "TextAsset":
                            data = obj.read()
                            script = getattr(data, "m_Script", None)
                            if isinstance(script, str):
                                return script.encode("utf-8")
                            if isinstance(script, (bytes, bytearray)):
                                return bytes(script)
                    except Exception:
                        continue
                return None

            def try_pretty_json_bytes(raw_bytes: bytes) -> Optional[bytes]:
                try:
                    text = raw_bytes.decode("utf-8")
                except Exception:
                    try:
                        text = raw_bytes.decode("utf-8", errors="replace")
                    except Exception:
                        return None

                stripped = text.lstrip()
                if not stripped:
                    return None

                if not (stripped.startswith("{") or stripped.startswith("[")):
                    return None

                try:
                    parsed = json.loads(text)
                except Exception:
                    start_idx = None
                    for i, ch in enumerate(text):
                        if ch in "{[":
                            start_idx = i
                            break
                    if start_idx is None:
                        return None
                    sub = text[start_idx:]
                    try:
                        parsed = json.loads(sub)
                    except Exception:
                        return None

                try:
                    pretty = json.dumps(parsed, ensure_ascii=False, indent=4)
                    return pretty.encode("utf-8")
                except Exception:
                    return None

            def export_charts_from_charts_dir(filelist_path: Path, charts_dir: Path, out_dir: Path):
                if filelist_path.exists():
                    filelist = load_json(filelist_path)
                else:
                    print(f"fileList.json not found at {filelist_path}; aborting export charts")
                    return

                chart_entries = []
                for entry in filelist:
                    if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str) and isinstance(entry[1], str):
                        key = entry[0].strip()
                        if key.startswith("chart."):
                            chart_entries.append((key, entry[1].strip()))

                if not chart_entries:
                    print("No chart entries found in fileList.json")
                    return

                if not charts_dir.is_dir():
                    print(f"Charts directory not found: {charts_dir}")
                    return

                out_dir.mkdir(parents=True, exist_ok=True)
                total = len(chart_entries)
                success = 0
                for chartId, bundle_name in chart_entries:
                    bundle_file = find_bundle_in_dir_with_chart_fallback(charts_dir, bundle_name, chart_id=chartId)
                    if not bundle_file:
                        bundle_file = find_case_insensitive(charts_dir, bundle_name) or find_bundle_in_dir_with_chart_fallback(charts_dir, bundle_name, chart_id=chartId)
                    if not bundle_file:
                        print(f"Skipping {chartId}: bundle '{bundle_name}' not found in {charts_dir}")
                        continue

                    raw_bytes = extract_textasset_script(bundle_file)
                    if not raw_bytes:
                        print(f"Skipping {chartId}: no TextAsset.m_Script found in '{bundle_file.name}'")
                        continue

                    pretty_bytes = try_pretty_json_bytes(raw_bytes)
                    out_path = out_dir / f"{chartId}.json"
                    try:
                        if pretty_bytes:
                            with out_path.open("wb") as f:
                                f.write(pretty_bytes)
                        else:
                            # fallback: write raw bytes as-is
                            with out_path.open("wb") as f:
                                f.write(raw_bytes)
                        success += 1
                        print(f"Exported {chartId} -> {out_path}")
                    except Exception as e:
                        print(f"ERROR writing {out_path}: {e}")

                print(f"Done: exported {success}/{total} charts to {out_dir}")

            try:
                export_charts_from_charts_dir(FILELIST, charts_dir, OUT_CHARTS_JSON)
            except Exception as exc:
                print(f"ERROR exporting charts; continuing to illustrations and level table: {exc}")

        try:
            export_illustrations(FILELIST)
        except Exception as exc:
            print(f"ERROR exporting illustrations; continuing to level table: {exc}")

    if run_export_levels:
        print("=== Export level table step ===")
        try:
            export_level_table_search_default(
                LEVELS_OUTPUT,
                keep_info=args.keep_info,
                default_json_path=args.default_json_dir,
                score_json_path=args.score_json,
            )
        except Exception as exc:
            print(f"ERROR exporting level table: {exc}")

    if run_export_achievements:
        print("=== Export localized achievements step ===")
        try:
            export_localized_achievements()
        except Exception as exc:
            print(f"ERROR exporting localized achievements: {exc}")

    if run_export_bios:
        print("=== Export localized bios step ===")
        try:
            export_localized_bios()
        except Exception as exc:
            print(f"ERROR exporting localized bios: {exc}")

if __name__ == "__main__":
    main()
