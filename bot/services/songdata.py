"""Song index loaded from bot/static/songs_index.json."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bot.models import ChartInfo, Song


logger = logging.getLogger("rizline.bot")
_DIFFS = ("EZ", "HD", "IN", "AT")


def normalize(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


class SongIndex:
    def __init__(self, songs: list[Song], source: str) -> None:
        self.songs = songs
        self.source = source
        self.by_asset = {song.asset_id: song for song in songs}
        self.by_norm: dict[str, Song] = {}
        for song in songs:
            self.by_norm.setdefault(normalize(song.title), song)
            for alias in song.aliases:
                self.by_norm.setdefault(normalize(alias), song)

    @classmethod
    def load(cls, path: Path) -> SongIndex:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = str(payload.get("source") or "songs_index.json")
        songs: list[Song] = []
        for row in payload.get("songs") or []:
            charts: dict[str, ChartInfo] = {}
            for difficulty, chart in (row.get("charts") or {}).items():
                if difficulty not in _DIFFS or not isinstance(chart, dict):
                    continue
                charts[difficulty] = ChartInfo(
                    difficulty=difficulty,
                    level=float(chart.get("level") or 0),
                    hit=int(chart.get("hit") or 0),
                    combo=int(chart.get("combo") or 0),
                    score=int(chart.get("score") or 0),
                    riz_hit=int(chart.get("rizHit") or 0),
                    designer=str(chart.get("designer") or ""),
                )
            bpm = row.get("bpm")
            length = row.get("length")
            series = row.get("seriesIndex")
            songs.append(
                Song(
                    asset_id=str(row.get("assetId") or ""),
                    title=str(row.get("title") or ""),
                    artist=str(row.get("artist") or ""),
                    disc_name=str(row.get("discName") or ""),
                    illustration_id=str(row.get("illustrationId") or ""),
                    aliases=tuple(str(alias) for alias in row.get("aliases") or []),
                    charts=charts,
                    bpm=float(bpm) if isinstance(bpm, (int, float)) and float(bpm) > 0 else None,
                    length_seconds=float(length) if isinstance(length, (int, float)) and float(length) > 0 else None,
                    illustrator=str(row.get("illustrator") or ""),
                    series_index=int(series) if isinstance(series, int) and series != -1 else None,
                    series_name=str(row.get("seriesName") or ""),
                )
            )
        index = cls(songs, source)
        logger.info("Loaded %s songs (%s)", len(index.songs), source)
        return index

    def search(self, query: str, limit: int = 25) -> list[Song]:
        cleaned = query.strip()
        if not cleaned:
            return self.songs[:limit]
        if cleaned in self.by_asset:
            return [self.by_asset[cleaned]]
        needle = normalize(cleaned)
        if not needle:
            return []
        exact: list[Song] = []
        starts: list[Song] = []
        contains: list[Song] = []
        seen: set[str] = set()
        for song in self.songs:
            names = [normalize(song.title), *(normalize(alias) for alias in song.aliases)]
            names = [name for name in names if name]
            if song.asset_id in seen:
                continue
            if any(name == needle for name in names):
                exact.append(song)
                seen.add(song.asset_id)
            elif any(name.startswith(needle) for name in names):
                starts.append(song)
                seen.add(song.asset_id)
            elif any(needle in name for name in names):
                contains.append(song)
                seen.add(song.asset_id)
        return (exact + starts + contains)[:limit]

    def resolve(self, query: str) -> tuple[Song | None, list[Song]]:
        cleaned = query.strip()
        if cleaned in self.by_asset:
            return self.by_asset[cleaned], []
        hits = self.search(cleaned, limit=5)
        if len(hits) == 1:
            return hits[0], []
        needle = normalize(cleaned)
        exact = [
            song
            for song in hits
            if normalize(song.title) == needle or any(normalize(alias) == needle for alias in song.aliases)
        ]
        if len(exact) == 1:
            return exact[0], []
        return None, hits


def illustration_file(
    illustration_id: str,
    hires_dir: Path,
    low_dir: Path,
    *,
    prefer_low: bool = False,
) -> Path | None:
    stem = illustration_id.strip()
    if not stem:
        return None
    if not stem.startswith("illustration."):
        stem = f"illustration.{stem}"
    low = [low_dir / f"{stem}.png", low_dir / f"{stem}_2.png"]
    high = [hires_dir / f"{stem}.HiRes.png", hires_dir / f"{stem}.HiRes_2.png"]
    candidates = low + high if prefer_low else high + low
    for path in candidates:
        if path.is_file() and path.stat().st_size <= 8_000_000:
            return path
    return None


def illustration_path(
    song: Song,
    hires_dir: Path,
    low_dir: Path,
    *,
    prefer_low: bool = False,
) -> Path | None:
    return illustration_file(
        song.illustration_id or f"illustration.{song.asset_id}",
        hires_dir,
        low_dir,
        prefer_low=prefer_low,
    )


def attachment_name(song: Song) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", song.asset_id) or "song"
    return f"{safe[:80]}.png"
