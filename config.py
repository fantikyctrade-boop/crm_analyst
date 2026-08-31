"""Environment-based bot configuration."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class InstagramConfig:
    enabled: bool
    provider: str
    api_key: str
    account_id: str
    graph_api_version: str
    timeout_seconds: float
    max_concurrency: int
    cache_ttl_seconds: int
    cache_path: Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]
    instagram: InstagramConfig

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        raw_user_ids = os.getenv("ALLOWED_USER_IDS", "").strip()

        if not token:
            raise ValueError("BOT_TOKEN is missing in .env.")
        if not raw_user_ids:
            raise ValueError("ALLOWED_USER_IDS is missing in .env.")

        if raw_user_ids == "*":
            user_ids = frozenset()
        else:
            try:
                user_ids = frozenset(
                    int(item.strip())
                    for item in raw_user_ids.split(",")
                    if item.strip()
                )
            except ValueError as error:
                raise ValueError(
                    "ALLOWED_USER_IDS must be '*' or a comma-separated "
                    "list of integers."
                ) from error

            if not user_ids:
                raise ValueError(
                    "ALLOWED_USER_IDS must contain at least one user ID."
                )
        cache_path_value = os.getenv("INSTAGRAM_ENRICHMENT_CACHE_PATH", "").strip()
        cache_path = (
            Path(cache_path_value)
            if cache_path_value
            else Path(tempfile.gettempdir()) / "overture_instagram_cache.json"
        )
        instagram = InstagramConfig(
            enabled=_env_bool("INSTAGRAM_ENRICHMENT_ENABLED"),
            provider=os.getenv(
                "INSTAGRAM_ENRICHMENT_PROVIDER", "meta_graph"
            ).strip(),
            api_key=os.getenv("INSTAGRAM_ENRICHMENT_API_KEY", "").strip(),
            account_id=os.getenv("INSTAGRAM_ENRICHMENT_ACCOUNT_ID", "").strip(),
            graph_api_version=os.getenv(
                "INSTAGRAM_GRAPH_API_VERSION", "v21.0"
            ).strip(),
            timeout_seconds=_env_positive_float(
                "INSTAGRAM_ENRICHMENT_TIMEOUT_SECONDS", 3.0
            ),
            max_concurrency=_env_positive_int(
                "INSTAGRAM_ENRICHMENT_MAX_CONCURRENCY", 3
            ),
            cache_ttl_seconds=max(
                _env_positive_int("INSTAGRAM_ENRICHMENT_CACHE_TTL_SECONDS", 86400),
                86400,
            ),
            cache_path=cache_path,
        )
        return cls(
            bot_token=token,
            allowed_user_ids=user_ids,
            instagram=instagram,
        )
