"""Tests for optional Instagram follower enrichment."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from services.instagram_enrichment import (
    InstagramEnrichmentService,
    InstagramStatus,
    extract_instagram_username,
)


class ValueProvider:
    def __init__(self, value: int | None) -> None:
        self.value = value
        self.calls = 0

    async def get_followers(self, username: str) -> int | None:
        del username
        self.calls += 1
        return self.value


class SlowProvider:
    async def get_followers(self, username: str) -> int | None:
        del username
        await asyncio.sleep(0.2)
        return 1


class ErrorProvider:
    async def get_followers(self, username: str) -> int | None:
        del username
        raise RuntimeError("provider failed")


class InstagramEnrichmentTest(unittest.IsolatedAsyncioTestCase):
    def test_extracts_profiles_but_not_posts(self) -> None:
        self.assertEqual(
            extract_instagram_username("https://www.instagram.com/example.profile/"),
            "example.profile",
        )
        self.assertIsNone(
            extract_instagram_username("https://instagram.com/p/ABC123/")
        )

    async def test_profile_with_followers(self) -> None:
        provider = ValueProvider(4811)
        service = InstagramEnrichmentService(provider, enabled=True)

        lookup = await service.lookup_username("example")

        self.assertEqual(lookup.followers_count, 4811)
        self.assertEqual(lookup.status, InstagramStatus.FOUND)
        self.assertEqual(provider.calls, 1)

    async def test_profile_without_available_count(self) -> None:
        provider = ValueProvider(None)
        service = InstagramEnrichmentService(provider, enabled=True)

        lookup = await service.lookup_username("example")

        self.assertIsNone(lookup.followers_count)
        self.assertEqual(lookup.status, InstagramStatus.UNAVAILABLE)

    async def test_timeout_becomes_error_without_raising(self) -> None:
        service = InstagramEnrichmentService(
            SlowProvider(),
            enabled=True,
            timeout_seconds=0.01,
        )

        lookup = await service.lookup_username("slow_profile")

        self.assertIsNone(lookup.followers_count)
        self.assertEqual(lookup.status, InstagramStatus.ERROR)

    async def test_successful_result_is_cached_for_24_hours(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "instagram-cache.json"
            provider = ValueProvider(4811)
            service = InstagramEnrichmentService(
                provider,
                enabled=True,
                cache_ttl_seconds=60,
                cache_path=cache_path,
            )

            first = await service.lookup_username("cached_profile")
            second = await service.lookup_username("cached_profile")

            self.assertEqual(first, second)
            self.assertEqual(provider.calls, 1)
            self.assertTrue(cache_path.exists())
            self.assertGreaterEqual(service.cache_ttl_seconds, 86400)

            replacement_provider = ValueProvider(999)
            replacement = InstagramEnrichmentService(
                replacement_provider,
                enabled=True,
                cache_path=cache_path,
            )
            persisted = await replacement.lookup_username("cached_profile")
            self.assertEqual(persisted.followers_count, 4811)
            self.assertEqual(replacement_provider.calls, 0)

    async def test_provider_error_is_stored_as_status_only(self) -> None:
        service = InstagramEnrichmentService(ErrorProvider(), enabled=True)

        lookup = await service.lookup_username("broken_profile")

        self.assertIsNone(lookup.followers_count)
        self.assertEqual(lookup.status, InstagramStatus.ERROR)

    async def test_disabled_service_marks_profile_not_checked(self) -> None:
        rows = [
            {
                "website": "https://instagram.com/example/",
                "name": "Example",
            }
        ]
        service = InstagramEnrichmentService.disabled()

        await service.enrich_rows(rows)

        self.assertEqual(rows[0]["instagram_username"], "example")
        self.assertEqual(
            rows[0]["instagram_status"],
            InstagramStatus.NOT_CHECKED.value,
        )
        self.assertNotIn("instagram_followers", rows[0])


if __name__ == "__main__":
    unittest.main()
