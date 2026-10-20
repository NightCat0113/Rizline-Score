"""Environment and path configuration. Paths are relative to the repo root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_API_BASE = "https://service.rhyths.net"


class ConfigError(Exception):
    pass


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _parse_ids(raw: str) -> frozenset[int]:
    if not raw.strip():
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError("ALLOWED_USER_IDS must be comma-separated numeric Discord ids")
        ids.add(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    discord_token: str
    encryption_key: str
    allowed_user_ids: frozenset[int]
    cache_ttl_hours: float
    owner_id: int | None
    repo_root: Path
    var_dir: Path
    db_path: Path
    songs_index_path: Path
    illust_hires_dir: Path
    illust_dir: Path

    @property
    def cache_ttl(self) -> timedelta:
        return timedelta(hours=self.cache_ttl_hours)

    @classmethod
    def from_mapping(cls, env: dict[str, str], repo_root: Path = REPO_ROOT) -> Settings:
        def need(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise ConfigError(f"Missing required environment variable {name}")
            return value

        ttl_raw = env.get("CACHE_TTL_HOURS", "24").strip() or "24"
        try:
            ttl = float(ttl_raw)
        except ValueError as exc:
            raise ConfigError("CACHE_TTL_HOURS must be a number") from exc
        if ttl <= 0:
            raise ConfigError("CACHE_TTL_HOURS must be greater than zero")
        owner_raw = env.get("OWNER_ID", "").strip()
        owner_id = None
        if owner_raw:
            if not owner_raw.isdigit():
                raise ConfigError("OWNER_ID must be a numeric Discord user id")
            owner_id = int(owner_raw)
        var_dir = repo_root / "var"
        return cls(
            discord_token=need("DISCORD_TOKEN"),
            encryption_key=need("BOT_ENCRYPTION_KEY"),
            allowed_user_ids=_parse_ids(env.get("ALLOWED_USER_IDS", "")),
            cache_ttl_hours=ttl,
            owner_id=owner_id,
            repo_root=repo_root,
            var_dir=var_dir,
            db_path=var_dir / "bot.db",
            songs_index_path=repo_root / "bot" / "static" / "songs_index.json",
            illust_hires_dir=repo_root / "output" / "illust_HiRes",
            illust_dir=repo_root / "output" / "illust",
        )

    @classmethod
    def load(cls) -> Settings:
        load_env_file(REPO_ROOT / ".env")
        return cls.from_mapping(dict(os.environ), REPO_ROOT)
