#!/usr/bin/env python3
"""Write a score-only fixture. Drops mails, purchases, ids, and every other save field."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rizline_client import derive_minimal_cache  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Strip a Rizline save down to score fields.")
    parser.add_argument("--input", type=Path, default=ROOT / "NightXWind_gameData.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "fixtures" / "sanitized_save.json")
    args = parser.parse_args()
    if not args.input.is_file():
        print("Input save was not found.", file=sys.stderr)
        return 1
    save = json.loads(args.input.read_text(encoding="utf-8"))
    minimal = derive_minimal_cache(save)
    forbidden = {"mails", "userId", "_id", "mailSyncId", "getProducts", "password", "token", "email"}
    if forbidden & set(minimal):
        print("Sanitizer kept a forbidden field.", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(minimal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(minimal['myBest'])} bests and {len(minimal['levelsRks'])} ranked rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
