"""Optional, bounded Instagram follower enrichment.

The core search never depends on this module. The official Meta Graph provider
is disabled unless it is explicitly configured with professional-account
credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

MIN_CACHE_TTL_SECONDS = 24 * 60 * 60
INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com", "instagr.am"})
RESERVED_PATHS = frozenset(
    {
        "accounts",
        "direct",
        "explore",
        "p",
        "reel",
        "reels",
        "share",
        "stories",
    }
)
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._]{1,30}")


class InstagramStatus(StrEnum):
    FOUND = "found"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    NOT_CHECKED = "not_checked"


@dataclass(frozen=True, slots=True)
class InstagramLookup:
    username: str
    followers_count: int | None
    status: InstagramStatus


class InstagramProvider(Protocol):
    async def get_followers(self, username: str) -> int | None:
        """Return the follower count, or None when the metric is unavailable."""


class InstagramProviderError(RuntimeError):
    """Raised when an external provider fails."""


class MetaGraphInstagramProvider:
    """Official Meta Business Discovery provider for professional accounts."""

    def __init__(
        self,
        access_token: str,
        instagram_account_id: str,
        graph_api_version: str = "v21.0",
    ) -> None:
        self.access_token = access_token
        self.instagram_account_id = instagram_account_id
        self.graph_api_version = graph_api_version.strip("/")

    async def get_followers(self, username: str) -> int | None:
        endpoint = (
            f"https://graph.facebook.com/{self.graph_api_version}/"
            f"{self.instagram_account_id}"
        )
        params = {
            "fields": (
                f"business_discovery.username({username})"
                "{followers_count}"
            ),
            "access_token": self.access_token,
        }
        async with (
            aiohttp.ClientSession() as session,
            session.get(endpoint, params=params) as response,
        ):
            payload = await response.json(content_type=None)
            if response.status >= 400:
                message = "Meta Graph API request failed"
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict) and error.get("message"):
                        message = str(error["message"])
                raise InstagramProviderError(message)

        if not isinstance(payload, dict):
            return None
        business = payload.get("business_discovery")
        if not isinstance(business, dict):
            return None
        followers = business.get("followers_count")
        if isinstance(followers, bool) or not isinstance(followers, int):
            return None
        return followers if followers >= 0 else None


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    lookup: InstagramLookup
    expires_at: float


def extract_instagram_username(value: str | None) -> str | None:
    """Extract a profile username without treating posts or reels as profiles."""

    for raw_part in re.split(r"[\s,]+", (value or "").strip()):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith("@"):
            username = part[1:]
        else:
            candidate = part if "://" in part else f"https://{part}"
            parsed = urlparse(candidate)
            if parsed.netloc.casefold() not in INSTAGRAM_HOSTS:
                continue
            path_parts = [item for item in parsed.path.split("/") if item]
            if not path_parts or path_parts[0].casefold() in RESERVED_PATHS:
                continue
            username = path_parts[0].lstrip("@")

        if USERNAME_PATTERN.fullmatch(username):
            return username
    return None


class InstagramEnrichmentService:
    """Apply optional provider lookups with timeout, concurrency and 24h cache."""

    def __init__(
        self,
        provider: InstagramProvider | None = None,
        *,
        enabled: bool = False,
        timeout_seconds: float = 3.0,
        max_concurrency: int = 3,
        cache_ttl_seconds: int = MIN_CACHE_TTL_SECONDS,
        cache_path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.provider = provider
        self.enabled = enabled and provider is not None
        self.timeout_seconds = max(float(timeout_seconds), 0.01)
        self.cache_ttl_seconds = max(
            int(cache_ttl_seconds), MIN_CACHE_TTL_SECONDS
        )
        self.cache_path = cache_path
        self._clock = clock
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._cache_lock = asyncio.Lock()
        self._cache = self._load_cache()

    @classmethod
    def disabled(cls) -> InstagramEnrichmentService:
        return cls(enabled=False)

    def _load_cache(self) -> dict[str, _CacheEntry]:
        if self.cache_path is None or not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            logger.warning("Could not read Instagram enrichment cache")
            return {}

        cache: dict[str, _CacheEntry] = {}
        now = self._clock()
        if not isinstance(payload, dict):
            return cache
        for username, item in payload.items():
            if not isinstance(username, str) or not isinstance(item, dict):
                continue
            try:
                status = InstagramStatus(item["status"])
                expires_at = float(item["expires_at"])
            except (KeyError, TypeError, ValueError):
                continue
            followers = item.get("followers_count")
            if followers is not None and (
                isinstance(followers, bool) or not isinstance(followers, int)
            ):
                continue
            if expires_at <= now or status not in {
                InstagramStatus.FOUND,
                InstagramStatus.UNAVAILABLE,
            }:
                continue
            lookup = InstagramLookup(username, followers, status)
            cache[username.casefold()] = _CacheEntry(lookup, expires_at)
        return cache

    def _write_cache(self) -> None:
        if self.cache_path is None:
            return
        payload = {
            username: {
                "followers_count": entry.lookup.followers_count,
                "status": entry.lookup.status.value,
                "expires_at": entry.expires_at,
            }
            for username, entry in self._cache.items()
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)

    async def _cached(self, username: str) -> InstagramLookup | None:
        key = username.casefold()
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > self._clock():
                return entry.lookup
            if entry:
                self._cache.pop(key, None)
        return None

    async def _store(self, lookup: InstagramLookup) -> None:
        if lookup.status not in {
            InstagramStatus.FOUND,
            InstagramStatus.UNAVAILABLE,
        }:
            return
        entry = _CacheEntry(
            lookup=lookup,
            expires_at=self._clock() + self.cache_ttl_seconds,
        )
        async with self._cache_lock:
            self._cache[lookup.username.casefold()] = entry
            try:
                await asyncio.to_thread(self._write_cache)
            except OSError:
                logger.warning("Could not write Instagram enrichment cache")

    async def lookup_username(self, username: str) -> InstagramLookup:
        if not self.enabled or self.provider is None:
            return InstagramLookup(username, None, InstagramStatus.NOT_CHECKED)

        cached = await self._cached(username)
        if cached is not None:
            return cached

        try:
            async with self._semaphore:
                followers = await asyncio.wait_for(
                    self.provider.get_followers(username),
                    timeout=self.timeout_seconds,
                )
        except TimeoutError:
            return InstagramLookup(username, None, InstagramStatus.ERROR)
        except Exception:
            logger.exception("Instagram enrichment failed for @%s", username)
            return InstagramLookup(username, None, InstagramStatus.ERROR)

        status = (
            InstagramStatus.FOUND
            if followers is not None
            else InstagramStatus.UNAVAILABLE
        )
        lookup = InstagramLookup(username, followers, status)
        await self._store(lookup)
        return lookup

    def prepare_rows(self, rows: Iterable[dict[str, str]]) -> int:
        prepared = 0
        for row in rows:
            username = extract_instagram_username(row.get("website"))
            if not username:
                continue
            row["instagram_username"] = username
            row.setdefault("instagram_status", InstagramStatus.NOT_CHECKED.value)
            prepared += 1
        return prepared

    async def enrich_rows(self, rows: Iterable[dict[str, str]]) -> None:
        row_list = list(rows)
        self.prepare_rows(row_list)
        by_username: dict[str, list[dict[str, str]]] = {}
        for row in row_list:
            username = row.get("instagram_username")
            if username:
                by_username.setdefault(username.casefold(), []).append(row)

        async def enrich(username: str, matching_rows: list[dict[str, str]]) -> None:
            lookup = await self.lookup_username(username)
            for row in matching_rows:
                row["instagram_username"] = lookup.username
                row["instagram_status"] = lookup.status.value
                if lookup.followers_count is None:
                    row.pop("instagram_followers", None)
                else:
                    row["instagram_followers"] = str(lookup.followers_count)

        await asyncio.gather(
            *(
                enrich(rows_for_user[0]["instagram_username"], rows_for_user)
                for rows_for_user in by_username.values()
            )
        )


def build_instagram_enrichment(
    *,
    enabled: bool,
    provider_name: str,
    api_key: str,
    account_id: str,
    graph_api_version: str,
    timeout_seconds: float,
    max_concurrency: int,
    cache_ttl_seconds: int,
    cache_path: Path | None = None,
) -> InstagramEnrichmentService:
    """Build a configured service without making enrichment a startup dependency."""

    if not enabled:
        return InstagramEnrichmentService.disabled()
    if provider_name != "meta_graph":
        logger.warning("Unknown Instagram enrichment provider: %s", provider_name)
        return InstagramEnrichmentService.disabled()
    if not api_key or not account_id:
        logger.warning(
            "Instagram enrichment is enabled but API key/account ID is missing"
        )
        return InstagramEnrichmentService.disabled()

    provider = MetaGraphInstagramProvider(
        access_token=api_key,
        instagram_account_id=account_id,
        graph_api_version=graph_api_version,
    )
    return InstagramEnrichmentService(
        provider,
        enabled=True,
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
        cache_ttl_seconds=cache_ttl_seconds,
        cache_path=cache_path
        or Path(tempfile.gettempdir()) / "overture_instagram_cache.json",
    )
