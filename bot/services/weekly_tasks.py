"""Map a GetWeeklyTasks payload into progress rows. Never claims rewards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from bot.config import catalog_dir
from bot.services.language import normalize_language


# English weeklyTask.* strings from the mobile client. Used if the catalog file is missing.
TITLES = {
    "100101": "Log in 3 days total",
    "100201": "Log in 2 consecutive days",
    "100301": "Play any track 5 times",
    "100401": "Clear any track 5 times",
    "100502": "Play Asyncombat 5 times",
    "100601": "Play any track with any MOD 2 times",
    "100701": "Accumulate 100 Dots",
    "100801": "Clear 3 different tracks in Main Discs",
    "100901": "Clear 3 different tracks in EX Discs",
    "101001": "Accumulate 3000000 score",
    "101101": "Accumulate 3000 Hits",
    "101201": "Total level of cleared charts reaches 15",
    "101301": "Win 3 times in Asyncombat",
    "101401": "Get a 2-win Streak in Asyncombat",
}

STATUS_LABELS = {
    "en": {
        "incomplete": "Incomplete",
        "complete": "Complete",
        "claimable": "Claimable",
        "claimed": "Claimed",
    },
    "zh-Hans": {
        "incomplete": "未完成",
        "complete": "已完成",
        "claimable": "可领取",
        "claimed": "已领取",
    },
    "zh-Hant": {
        "incomplete": "未完成",
        "complete": "已完成",
        "claimable": "可領取",
        "claimed": "已領取",
    },
    "ja": {
        "incomplete": "未完了",
        "complete": "完了",
        "claimable": "受取可",
        "claimed": "受取済",
    },
}


@dataclass(frozen=True)
class WeeklyTask:
    task_id: str
    title: str
    progress: int
    target: int
    status: str
    desc: str = ""


@dataclass(frozen=True)
class WeeklyBoard:
    week_index: str
    next_refresh: str
    tasks: tuple[WeeklyTask, ...]


def _unwrap(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("result", "data"):
        child = payload.get(key)
        if isinstance(child, dict) and _rows(child):
            return child
    return payload


def _rows(payload: dict) -> list:
    for key in ("tasks", "weeklyTasks", "items", "list", "taskList"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _status(item: dict, progress: int, target: int) -> str:
    raw = str(item.get("status") or item.get("state") or "").strip().lower()
    if (
        item.get("rewarded") is True
        or item.get("claimed") is True
        or item.get("rewardClaimed") is True
        or raw in {"claimed", "received", "rewarded"}
    ):
        return "claimed"
    if item.get("claimable") is True or item.get("canClaim") is True or raw in {"claimable", "canclaim"}:
        return "claimable"
    if item.get("completed") is True:
        return "claimable"
    if raw in {"complete", "completed", "finished", "done"} or (target > 0 and progress >= target):
        return "complete"
    if raw in {"incomplete", "progress", "ongoing"}:
        return "incomplete"
    return "incomplete"


def _title(item: dict, task_id: str, catalog_title: str, *, catalog_loaded: bool) -> str:
    if catalog_title:
        return catalog_title
    for key in ("title", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if not catalog_loaded:
        fallback = TITLES.get(task_id)
        if fallback:
            return fallback
    return f"weeklyTask.{task_id}" if task_id else "Weekly task"


def _desc(item: dict, catalog_desc: str) -> str:
    if catalog_desc:
        return catalog_desc
    for key in ("description", "desc"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@lru_cache(maxsize=8)
def _read_catalog(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _catalog_entry(task_id: str, language: str, catalog_root: Path) -> tuple[dict[str, str], bool]:
    code = normalize_language(language)
    found: dict[str, str] = {}
    loaded = False
    for filename in (f"weekly_tasks_{code}.json", "weekly_tasks_en.json"):
        path = catalog_root / filename
        if path.is_file():
            loaded = True
        catalog = _read_catalog(str(path))
        entry = catalog.get(task_id)
        if not isinstance(entry, dict):
            continue
        for field in ("title", "desc"):
            if found.get(field):
                continue
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                found[field] = value.strip()
    return found, loaded


def map_weekly_tasks(
    payload: dict,
    language: str = "en",
    repo_root: Path | None = None,
) -> WeeklyBoard:
    root = catalog_dir(repo_root or Path(__file__).resolve().parents[2])
    body = _unwrap(payload if isinstance(payload, dict) else {})
    tasks: list[WeeklyTask] = []
    for item in _rows(body):
        task_id = str(item.get("id") or item.get("taskId") or item.get("taskID") or "").strip()
        progress = _int(item.get("progress", item.get("current", item.get("value"))))
        target = _int(item.get("target", item.get("goal", item.get("need", item.get("max")))))
        entry, catalog_loaded = _catalog_entry(task_id, language, root)
        tasks.append(
            WeeklyTask(
                task_id=task_id,
                title=_title(item, task_id, entry.get("title", ""), catalog_loaded=catalog_loaded),
                progress=progress,
                target=target,
                status=_status(item, progress, target),
                desc=_desc(item, entry.get("desc", "")),
            )
        )
    week = body.get("weekIndex")
    refresh = body.get("nextRefreshAt")
    return WeeklyBoard(
        week_index="" if week is None else str(week),
        next_refresh="" if refresh is None else str(refresh),
        tasks=tuple(tasks),
    )


def _int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return 0


def status_label(status: str, language: str) -> str:
    table = STATUS_LABELS.get(language) or STATUS_LABELS["en"]
    return table.get(status, STATUS_LABELS["en"].get(status, status))
