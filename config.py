"""Settings from environment / .env. Credentials are read here and nowhere else."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    mode: str = os.getenv("MARKET_MODE", "demo").strip().lower()
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8010)
    api_key: str = os.getenv("KITE_API_KEY", "").strip()
    access_token: str = os.getenv("KITE_ACCESS_TOKEN", "").strip()
    board_size: int = _int("BOARD_SIZE", 10)
    picks: int = _int("PICKS", 3)
    sector_cap: int = _int("SECTOR_CAP", 2)
    publish_seconds: float = _float("PUBLISH_SECONDS", 2.0)
    history_rate: float = _float("HISTORY_RATE_PER_SEC", 2.5)
    demo_seconds_per_minute: float = _float("DEMO_SECONDS_PER_MINUTE", 2.0)
    demo_start_minute: int = _int("DEMO_START_MINUTE", 150)
    cache_dir: Path = Path(os.getenv("CACHE_DIR") or (ROOT / ".cache"))


def redact(text: str, cfg: Config) -> str:
    """Never let a credential reach logs or the browser."""
    out = str(text)
    for secret in (cfg.api_key, cfg.access_token):
        if secret:
            out = out.replace(secret, "***")
    return out[:300]
