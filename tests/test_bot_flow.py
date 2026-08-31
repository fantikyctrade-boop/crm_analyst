"""Mocked end-to-end test of collection, scoring, and run cleanup."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.lead_pipeline import (
    LeadPipeline,
    SearchAlreadyRunningError,
    SearchResult,
)


class FakeConnection:
    def close(self) -> None:
        pass


def fake_places(city: str) -> list[dict[str, object]]:
    return [
        {
            "name": f"No Site {city}",
            "city": city,
            "address": "Address 1",
            "phone": "+380001",
            "website": "",
            "email": "owner@gmail.com",
            "category": "automotive_repair",
            "overture_id": f"{city}-1",
            "latitude": 50.0,
            "longitude": 30.0,
            "source_release": "mock-release",
            "_confidence": 0.9,
        },
        {
            "name": f"HTTP Site {city}",
            "city": city,
            "address": "Address 2",
            "phone": "+380002",
            "website": "http://example.com",
            "email": "office@example.com",
            "category": "automotive_repair",
            "overture_id": f"{city}-2",
            "latitude": 50.1,
            "longitude": 30.1,
            "source_release": "mock-release",
            "_confidence": 0.8,
        },
        {
            "name": f"Normal Site {city}",
            "city": city,
            "address": "Address 3",
            "phone": "+380003",
            "website": "https://example.org",
            "email": "office@example.org",
            "category": "automotive_repair",
            "overture_id": f"{city}-3",
            "latitude": 50.2,
            "longitude": 30.2,
            "source_release": "mock-release",
            "_confidence": 0.7,
        },
    ]


class BotFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_whole_ukraine_skips_geocoding_and_filters_country(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = LeadPipeline(Path(directory))
            captured_kwargs: dict[str, object] = {}

            def fetch_places(
                *args: object, **kwargs: object
            ) -> list[dict[str, object]]:
                captured_kwargs.update(kwargs)
                return fake_places(str(args[2]))[:1]

            with (
                patch(
                    "services.lead_pipeline.collector.latest_release",
                    return_value="mock-release",
                ),
                patch(
                    "services.lead_pipeline.collector.niche_filter",
                    return_value=(("automotive_repair",), ()),
                ),
                patch(
                    "services.lead_pipeline.collector.open_overture",
                    return_value=FakeConnection(),
                ),
                patch("services.lead_pipeline.collector.geocode_city") as geocode_city,
                patch(
                    "services.lead_pipeline.collector.fetch_places",
                    side_effect=fetch_places,
                ),
            ):
                result = await pipeline.run(
                    1002,
                    "автосервіс",
                    ["Вся Україна"],
                    1,
                )

            self.assertEqual(result.cities, ("Вся Україна",))
            self.assertEqual(result.total, 1)
            self.assertEqual(captured_kwargs["country_code"], "UA")
            geocode_city.assert_not_called()
            pipeline.cleanup_all()

    async def test_international_search_geocodes_and_filters_selected_country(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = LeadPipeline(Path(directory))
            captured_kwargs: dict[str, object] = {}

            def fetch_places(
                *args: object, **kwargs: object
            ) -> list[dict[str, object]]:
                captured_kwargs.update(kwargs)
                return fake_places(str(args[2]))[:1]

            with (
                patch(
                    "services.lead_pipeline.collector.latest_release",
                    return_value="mock-release",
                ),
                patch(
                    "services.lead_pipeline.collector.niche_filter",
                    return_value=(("dentist",), ()),
                ),
                patch(
                    "services.lead_pipeline.collector.open_overture",
                    return_value=FakeConnection(),
                ),
                patch(
                    "services.lead_pipeline.collector.geocode_city",
                    return_value=(-122.6, 37.0, -121.9, 38.0),
                ) as geocode_city,
                patch(
                    "services.lead_pipeline.collector.fetch_places",
                    side_effect=fetch_places,
                ),
            ):
                result = await pipeline.run(
                    1003,
                    "Dental",
                    ["San Francisco"],
                    1,
                    country_code="US",
                    country_name="USA",
                    region="California",
                )

            self.assertEqual(result.country_code, "US")
            self.assertEqual(result.region, "California")
            self.assertEqual(captured_kwargs["country_code"], "US")
            self.assertEqual(captured_kwargs["region"], "California")
            geocode_city.assert_called_once_with(
                "San Francisco",
                country_code="US",
                country_name="USA",
                region="California",
            )
            pipeline.cleanup_all()

    async def test_region_only_search_geocodes_region_and_skips_city_requirement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = LeadPipeline(Path(directory))
            captured_kwargs: dict[str, object] = {}

            def fetch_places(
                *args: object, **kwargs: object
            ) -> list[dict[str, object]]:
                captured_kwargs.update(kwargs)
                return fake_places(str(args[2]))[:1]

            with (
                patch(
                    "services.lead_pipeline.collector.latest_release",
                    return_value="mock-release",
                ),
                patch(
                    "services.lead_pipeline.collector.niche_filter",
                    return_value=(("dentist",), ()),
                ),
                patch(
                    "services.lead_pipeline.collector.open_overture",
                    return_value=FakeConnection(),
                ),
                patch(
                    "services.lead_pipeline.collector.geocode_city",
                    return_value=(-106.7, 25.8, -93.5, 36.6),
                ) as geocode_city,
                patch(
                    "services.lead_pipeline.collector.fetch_places",
                    side_effect=fetch_places,
                ),
            ):
                result = await pipeline.run(
                    1004,
                    "Dental",
                    [],
                    1,
                    country_code="US",
                    country_name="USA",
                    region="Texas",
                )

            self.assertEqual(result.cities, ())
            self.assertEqual(captured_kwargs["region"], "Texas")
            geocode_city.assert_called_once_with(
                "Texas",
                country_code="US",
                country_name="USA",
                region="Texas",
            )
            pipeline.cleanup_all()

    async def test_mocked_search_scores_and_replaces_old_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = LeadPipeline(Path(directory))

            def fetch_places(
                *args: object, **kwargs: object
            ) -> list[dict[str, object]]:
                del kwargs
                return fake_places(str(args[2]))

            patches = (
                patch(
                    "services.lead_pipeline.collector.latest_release",
                    return_value="mock-release",
                ),
                patch(
                    "services.lead_pipeline.collector.niche_filter",
                    return_value=(("automotive_repair",), ()),
                ),
                patch(
                    "services.lead_pipeline.collector.open_overture",
                    return_value=FakeConnection(),
                ),
                patch(
                    "services.lead_pipeline.collector.geocode_city",
                    return_value=(30.0, 50.0, 31.0, 51.0),
                ),
                patch(
                    "services.lead_pipeline.collector.fetch_places",
                    side_effect=fetch_places,
                ),
            )

            for active_patch in patches:
                active_patch.start()
                self.addCleanup(active_patch.stop)

            first = await pipeline.run(1001, "автосервіс", ["Київ"], 10)
            self.assertEqual(first.total, 3)
            self.assertEqual((first.high, first.medium, first.low), (1, 1, 1))
            self.assertTrue(first.csv_path.exists())
            self.assertFalse((first.run_dir / "leads.csv").exists())

            second = await pipeline.run(1001, "автосервіс", ["Львів"], 10)
            self.assertTrue(second.csv_path.exists())
            self.assertFalse(first.run_dir.exists())
            self.assertEqual(second.rows[0]["priority"], "HIGH")

            pipeline.cleanup_all()
            self.assertFalse(Path(directory).exists())

    async def test_same_user_cannot_start_two_searches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = LeadPipeline(Path(directory))
            started = threading.Event()
            finish = threading.Event()
            run_dir = Path(directory) / "1001" / "run"
            run_dir.mkdir(parents=True)
            csv_path = run_dir / "scored_leads.csv"
            csv_path.write_text("name,priority\n", encoding="utf-8")

            def slow_run(*args: object) -> SearchResult:
                del args
                started.set()
                finish.wait(timeout=5)
                return SearchResult(
                    user_id=1001,
                    niche="test",
                    cities=("Київ",),
                    requested_limit=1,
                    source_release="test",
                    rows=(),
                    csv_path=csv_path,
                    run_dir=run_dir,
                    high=0,
                    medium=0,
                    low=0,
                )

            with patch.object(pipeline, "_run_sync", side_effect=slow_run):
                first = asyncio.create_task(pipeline.run(1001, "test", ["Київ"], 1))
                await asyncio.to_thread(started.wait, 2)
                with self.assertRaises(SearchAlreadyRunningError):
                    await pipeline.run(1001, "test", ["Київ"], 1)
                finish.set()
                await first

            pipeline.cleanup_all()


if __name__ == "__main__":
    unittest.main()
