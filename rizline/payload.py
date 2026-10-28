"""Card-art shape helpers shared by the HTTP and socket clients."""

from __future__ import annotations


_ALIASES = {
    "avatarId": ("avatarId", "avatarID", "avatar"),
    "avatarPos": ("avatarPos", "avatarPosition"),
    "bioId1": ("bioId1", "bio1", "titleId"),
    "bioId2": ("bioId2", "bio2", "subtitleId"),
    "backgroundId": ("backgroundId", "bannerId", "background"),
    "layoutId": ("layoutId", "layout"),
    "username": ("username", "userName", "name", "playerName"),
    "totalRks": ("totalRks", "rks"),
}


_LIST_KEYS = ("ownRizcards", "rizcards", "cards")
_NEST_KEYS = ("result", "data", "rizcard", "card", "staticCard", "profile", "ownRizcard")
_ART_KEYS = ("avatarId", "avatarID", "avatar", "backgroundId", "bannerId", "background", "layoutId", "layout")


def _row_has_art(row: dict) -> bool:
    blobs = [row]
    for key in _NEST_KEYS:
        child = row.get(key)
        if isinstance(child, dict):
            blobs.append(child)
    return any(blob.get(key) not in (None, "") for blob in blobs for key in _ART_KEYS)


def _sources(payload: dict) -> list[dict]:
    found: list[dict] = []
    pending = [payload]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        marker = id(current)
        if marker in seen or not isinstance(current, dict):
            continue
        seen.add(marker)
        found.append(current)
        for key in _NEST_KEYS:
            child = current.get(key)
            if isinstance(child, dict):
                pending.append(child)
        fallback = None
        chosen = None
        for key in _LIST_KEYS:
            rows = current.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if fallback is None:
                    fallback = row
                if _row_has_art(row):
                    chosen = row
                    break
            if chosen is not None:
                break
        picked = chosen or fallback
        if picked is not None:
            pending.append(picked)
    return found


def has_card_art(payload: dict) -> bool:
    card = normalize_rizcard(payload if isinstance(payload, dict) else {})
    return any(card.get(key) not in (None, "") for key in ("avatarId", "backgroundId", "layoutId"))


def normalize_rizcard(payload: dict) -> dict:
    """Pull card art fields from a live payload. Missing fields stay absent."""
    card: dict = {}
    if not isinstance(payload, dict):
        return card
    for source in _sources(payload):
        for dest, keys in _ALIASES.items():
            if card.get(dest) not in (None, ""):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    card[dest] = value
                    break
    return card
