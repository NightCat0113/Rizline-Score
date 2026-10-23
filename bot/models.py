"""Shared data shapes for songs and cached scores."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChartInfo:
    difficulty: str
    level: float
    hit: int
    combo: int
    score: int
    riz_hit: int
    designer: str
    level_text: str = ""
    track_id: str = ""


@dataclass(frozen=True)
class SeriesVolume:
    label: str
    preorder_ends: str
    song_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrackSeries:
    series_index: int
    name: str
    bio_id: str = ""
    volumes: tuple[SeriesVolume, ...] = ()


@dataclass(frozen=True)
class Song:
    asset_id: str
    title: str
    artist: str
    disc_name: str
    illustration_id: str
    aliases: tuple[str, ...] = ()
    charts: dict[str, ChartInfo] = field(default_factory=dict)
    bpm: float | None = None
    length_seconds: float | None = None
    illustrator: str = ""
    series_index: int | None = None
    series_name: str = ""
    original: str = ""
    original_with: str = ""


@dataclass
class Session:
    email: str
    token: str
    device_id: str

    def __repr__(self) -> str:
        return "Session(email='<redacted>', token='<redacted>', device_id='<redacted>')"
