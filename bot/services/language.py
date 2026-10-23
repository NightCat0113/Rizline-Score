"""Saved display language. It changes series art and text drawn inside card images only."""

from __future__ import annotations


DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "zh-Hans", "zh-Hant", "ja")
LANGUAGE_NAMES = {
    "en": "English",
    "zh-Hans": "简体中文",
    "zh-Hant": "繁體中文",
    "ja": "日本語",
}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "track_series": "Track Series",
        "preorder_ends": "Preorder ends",
        "volume": "Volume",
        "score": "Score",
        "accuracy": "Accuracy",
        "no_record": "No record",
        "clear": "Clear",
        "not_cleared": "Not cleared",
        "illustrator": "Illustrator",
        "length": "Length",
        "disc": "Disc",
        "hit": "Hit",
        "riz_hit": "RizHit",
        "combo": "Combo",
        "charter": "Charter",
        "no_chart_details": "No chart details are in the local song index.",
        "no_charts_group": "No charts in this group.",
    },
    "zh-Hans": {
        "track_series": "曲目系列",
        "preorder_ends": "预购截止",
        "volume": "卷",
        "score": "分数",
        "accuracy": "准确率",
        "no_record": "无记录",
        "clear": "已通关",
        "not_cleared": "未通关",
        "illustrator": "画师",
        "length": "时长",
        "disc": "碟片",
        "hit": "Hit",
        "riz_hit": "RizHit",
        "combo": "连击",
        "charter": "谱师",
        "no_chart_details": "本地歌曲索引中没有谱面详情。",
        "no_charts_group": "该分组没有谱面。",
    },
    "zh-Hant": {
        "track_series": "曲目系列",
        "preorder_ends": "預購截止",
        "volume": "卷",
        "score": "分數",
        "accuracy": "準確率",
        "no_record": "無記錄",
        "clear": "已通關",
        "not_cleared": "未通關",
        "illustrator": "畫師",
        "length": "時長",
        "disc": "碟片",
        "hit": "Hit",
        "riz_hit": "RizHit",
        "combo": "連擊",
        "charter": "譜師",
        "no_chart_details": "本地歌曲索引中沒有譜面詳情。",
        "no_charts_group": "該分組沒有譜面。",
    },
    "ja": {
        "track_series": "トラックシリーズ",
        "preorder_ends": "予約終了",
        "volume": "ボリューム",
        "score": "スコア",
        "accuracy": "精度",
        "no_record": "記録なし",
        "clear": "クリア",
        "not_cleared": "未クリア",
        "illustrator": "イラストレーター",
        "length": "長さ",
        "disc": "ディスク",
        "hit": "Hit",
        "riz_hit": "RizHit",
        "combo": "コンボ",
        "charter": "譜面作者",
        "no_chart_details": "ローカルの曲索引に譜面情報がありません。",
        "no_charts_group": "このグループに譜面はありません。",
    },
}


def normalize_language(value: object) -> str:
    text = str(value or "").strip()
    return text if text in _STRINGS else DEFAULT_LANGUAGE


def strings(language: object) -> dict[str, str]:
    return _STRINGS[normalize_language(language)]


def user_language(database: object, discord_id: int) -> str:
    """Read the saved language; any storage problem means English."""
    getter = getattr(database, "get_language", None)
    if getter is None:
        return DEFAULT_LANGUAGE
    try:
        return normalize_language(getter(discord_id))
    except Exception:
        return DEFAULT_LANGUAGE
