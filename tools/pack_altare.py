"""Build a zip suitable for uploading to Altare's file manager.

Usage (from the repo root):
  python tools/pack_altare.py
  python tools/pack_altare.py --hires
  python tools/pack_altare.py --code-only --out deploy.zip
  python tools/pack_altare.py --art-only --out art.zip
  python tools/pack_altare.py --out dist/rizline-altare.zip

The default pack includes code, locale catalogs, the song index, the
font, and ``output/illust`` + ``output/series`` + ``output/layouts``.
High-res jackets are optional. Bake layouts first with
``python tools/bake_layouts.py`` so collection cards are real art, not
color swatches. ``--code-only`` is the GitHub Actions payload: code and
catalogs only, so a deploy does not replace art, the font, ``.env``,
or ``var/`` already on the server. ``--art-only`` packs
``output/illust``, ``output/illust_HiRes``, ``output/series``, and
``output/layouts`` so ``/arts`` can send the high-resolution jackets.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Full first-upload pack (art and font included).
INCLUDE_PATHS = (
    "main.py",
    "requirements-altare.txt",
    "bot",
    "rizline",
    "tools",
    "locale",
    "assets",
    "songs.json",
    "mapping.json",
    "TERMS.md",
    "PRIVACY.md",
)

# CI deploy pack. Art, font, secrets, and the score cache stay on the server.
# ``tools/`` is included so missing-script errors are clear; the download
# pipeline still needs a full local tree (UnityPy, ``download/``, disk).
CODE_ONLY_PATHS = (
    "main.py",
    "requirements-altare.txt",
    "bot",
    "rizline",
    "tools",
    "locale",
    "songs.json",
    "mapping.json",
    "TERMS.md",
    "PRIVACY.md",
)

SKIP_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
    ".venv",
    "venv",
    "tests",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".pyd"}

_ART_FOLDERS = ("output/illust", "output/series", "output/layouts")
_HIRES_FOLDER = "output/illust_HiRes"


def _should_skip(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def _add_path(zf: zipfile.ZipFile, path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    if path.is_file():
        if _should_skip(path.relative_to(ROOT)):
            return 0
        zf.write(path, path.relative_to(ROOT).as_posix())
        return 1
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        rel = child.relative_to(ROOT)
        if _should_skip(rel):
            continue
        zf.write(child, rel.as_posix())
        count += 1
    return count


def pack(out: Path, *, include_hires: bool, code_only: bool, art_only: bool = False) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if art_only:
            for folder in (*_ART_FOLDERS, _HIRES_FOLDER):
                count = _add_path(zf, ROOT / folder)
                if count == 0:
                    raise SystemExit(f"art-only pack missing files in {folder}")
                added += count
        else:
            names = CODE_ONLY_PATHS if code_only else INCLUDE_PATHS
            for name in names:
                added += _add_path(zf, ROOT / name)
            # Runtime requirements.txt expected by Altare's Python template.
            req = (ROOT / "requirements-altare.txt").read_bytes()
            zf.writestr("requirements.txt", req)
            added += 1
            if not code_only:
                for folder in _ART_FOLDERS:
                    added += _add_path(zf, ROOT / folder)
                if include_hires:
                    added += _add_path(zf, ROOT / _HIRES_FOLDER)
                # Empty writable cache dir for a first install. Later deploys
                # must not touch var/ (the live score cache lives there).
                zf.writestr("var/.gitkeep", b"")
                added += 1
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Wrote {out} ({size_mb:.1f} MB, {added} entries)")
    if art_only:
        print("Art-only pack: output/illust, output/illust_HiRes, output/series, output/layouts")
    elif code_only:
        print("Code-only pack: does not include output/, assets/, .env, or var/")
    else:
        print("On Altare: extract at server root, create .env, set main file to main.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist" / "rizline-altare.zip",
        help="Zip path (default: dist/rizline-altare.zip)",
    )
    parser.add_argument(
        "--hires",
        action="store_true",
        help="Also pack output/illust_HiRes (~680 MB uncompressed)",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Pack code and catalogs only (GitHub Actions deploy)",
    )
    parser.add_argument(
        "--art-only",
        action="store_true",
        help="Pack output/illust, output/series, and output/layouts only",
    )
    args = parser.parse_args()
    if args.code_only and args.hires:
        parser.error("--code-only cannot be combined with --hires")
    if args.art_only and (args.code_only or args.hires):
        parser.error("--art-only cannot be combined with --code-only or --hires")
    pack(
        args.out.resolve(),
        include_hires=args.hires,
        code_only=args.code_only,
        art_only=args.art_only,
    )


if __name__ == "__main__":
    main()
