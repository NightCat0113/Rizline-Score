"""Bake collection layout cards into output/layouts for production (no Unity bundles).

Usage (from the repo root):
  python tools/bake_layouts.py
  python tools/bake_layouts.py --only layout.00031 layout.00036
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.ui.layout_card import bake_collection_layouts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="LAYOUT_ID",
        help="Bake only these layout ids (default: every catalog layout)",
    )
    args = parser.parse_args()
    ok, failed = bake_collection_layouts(ROOT, args.only)
    print(f"Baked {ok} layout(s) → output/layouts/ ({failed} failed)")
    if ok == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
