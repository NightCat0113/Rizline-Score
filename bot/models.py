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


@dataclass(frozen=True)
class Song:
    asset_id: str
    title: str
    artist: str
    disc_name: str
    illustration_id: str
    aliases: tuple[str, ...] = ()
    charts: dict[str, ChartInfo] = field(default_factory=dict)


@dataclass
class Session:
    email: str
    token: str
    device_id: str

    def __repr__(self) -> str:
        return "Session(email='<redacted>', token='<redacted>', device_id='<redacted>')"
