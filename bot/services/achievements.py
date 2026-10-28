"""Achievement checklist data from the repository's localized achievement catalogs."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from bot.config import catalog_dir
from bot.services.language import normalize_language


@lru_cache(maxsize=8)
def _catalog(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def achievement_rows(repo_root: Path, language: str) -> list[dict[str, str]]:
    code = normalize_language(language)
    filenames = [f"achievement_{code}.json", "achievement_en.json", "achievement.json"]
    root = catalog_dir(repo_root)
    catalogs = [_catalog(root / filename) for filename in filenames]
    achievement_ids = dict.fromkeys(
        achievement_id for catalog in catalogs for achievement_id in catalog
    )

    rows = []
    for achievement_id in achievement_ids:
        # Merge individual fields so missing translations can use the English API catalog.
        entry: dict = {}
        for catalog in reversed(catalogs):
            localized_entry = catalog.get(achievement_id)
            if isinstance(localized_entry, dict):
                entry.update(localized_entry)
        title = " ".join(
            str(entry.get(key) or "").strip()
            for key in ("title1", "title2")
            if str(entry.get(key) or "").strip()
        )
        if title:
            achievement_id = str(achievement_id)
            rows.append({
                "id": achievement_id,
                "title": title,
                "name": str(entry.get("name") or achievement_id.replace("_", " ").title()),
                "unlock": str(entry.get("desc") or "Check the in-game achievement description."),
            })
    return rows


def unlocked_achievement_ids(cache: dict) -> set[str] | None:
    """Return unlocked IDs, or None when the cached save predates achievement support."""
    if "achievements" not in cache:
        return None
    result: set[str] = set()
    achievements = cache.get("achievements")
    if isinstance(achievements, list):
        for item in achievements:
            if isinstance(item, dict):
                achievement_id = str(item.get("id") or item.get("achievementId") or "")
            else:
                achievement_id = str(item or "")
            if achievement_id:
                result.add(achievement_id)
    return result
