"""Render /rizcard from a Socket.IO payload, not the score cache."""

from __future__ import annotations

from pathlib import Path

from bot.services.rizcard import normalize_rizcard
from bot.ui.b40_image import render_rizcard


def render_live_rizcard(
    payload: dict,
    *,
    username: str,
    total_rks: float,
    illust_hires_dir: Path,
    illust_dir: Path,
    font_path: Path,
    repo_root: Path | None = None,
    language: str = "en",
) -> bytes:
    card = normalize_rizcard(payload)
    name = str(card.pop("username", "") or username or "Player")
    raw_rks = card.pop("totalRks", None)
    try:
        rks = float(raw_rks) if raw_rks is not None else float(total_rks)
    except (TypeError, ValueError):
        rks = float(total_rks or 0)
    return render_rizcard(
        username=name,
        total_rks=rks,
        illust_hires_dir=illust_hires_dir,
        illust_dir=illust_dir,
        font_path=font_path,
        repo_root=repo_root,
        card=card,
        language=language,
    )
