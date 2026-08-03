"""Regression tests for Overture category matching and zero-result diagnostics."""

from __future__ import annotations

import unittest

import lead_collector


def make_lead(overture_id: str, category: str) -> dict[str, object]:
    return {
        "name": "Photo Studio",
        "city": "Чернігів",
        "address": "Test address",
        "phone": "+380000000000",
        "website": "",
        "email": "",
        "category": category,
        "overture_id": overture_id,
        "latitude": 51.49,
        "longitude": 31.29,
        "source_release": "test-release",
        "_confidence": 0.9,
    }


class SearchDiagnosticsTest(unittest.TestCase):
    def test_recognized_category_but_overture_returns_zero(self) -> None:
        exact, patterns = lead_collector.niche_filter("фотограф")
        self.assertIn("photography_service", exact)
        self.assertFalse(patterns)

        diagnostics = lead_collector.PlaceFilterDiagnostics(0, 0, 0, 0, 0, 0)
        with self.assertLogs("lead_collector", level="INFO") as captured:
            lead_collector.log_place_diagnostics("Тестове місто", diagnostics)

        log = "\n".join(captured.output)
        self.assertIn("before_filters=0", log)
        self.assertIn("before category, status, and name filters", log)

    def test_overture_records_all_rejected_by_a_later_filter(self) -> None:
        diagnostics = lead_collector.PlaceFilterDiagnostics(3, 3, 3, 0, 0, 0)
        with self.assertLogs("lead_collector", level="INFO") as captured:
            lead_collector.log_place_diagnostics("Тестове місто", diagnostics)

        log = "\n".join(captured.output)
        self.assertIn("after_category=3 after_status=0", log)
        self.assertIn("operating-status filter rejected all", log)

    def test_one_niche_resolves_to_multiple_real_categories(self) -> None:
        exact, patterns = lead_collector.niche_filter("фотограф")

        self.assertGreater(len(exact), 1)
        self.assertIn("photography_service", exact)
        self.assertIn("event_photography_service", exact)
        self.assertIn("session_photography_service", exact)
        self.assertFalse(patterns)

    def test_empty_first_category_does_not_hide_second_category_results(self) -> None:
        values = {
            "taxonomy_primary": "event_photography_service",
            "taxonomy_hierarchy": (
                "services_and_business",
                "media_service",
                "photography_service",
                "event_photography_service",
            ),
        }

        self.assertFalse(
            lead_collector.matches_overture_categories(
                ("photographer",), (), **values
            )
        )
        self.assertTrue(
            lead_collector.matches_overture_categories(
                ("photographer", "photography_service"), (), **values
            )
        )

    def test_duplicates_from_different_categories_are_removed(self) -> None:
        leads = [
            make_lead("same-id", "photography_service"),
            make_lead("same-id", "event_photography_service"),
        ]

        unique = lead_collector.deduplicate(leads)

        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["overture_id"], "same-id")

    def test_final_result_survives_the_correct_hierarchy_filter(self) -> None:
        categories, patterns = lead_collector.niche_filter("фотограф")
        matches = lead_collector.matches_overture_categories(
            categories,
            patterns,
            taxonomy_primary="event_photography_service",
            taxonomy_hierarchy=(
                "services_and_business",
                "media_service",
                "photography_service",
                "event_photography_service",
            ),
            legacy_primary="event_photography",
        )

        leads = [make_lead("photo-1", "event_photography_service")] if matches else []
        selected = lead_collector.select_leads(leads, 10)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["overture_id"], "photo-1")

    def test_sql_filter_checks_current_and_legacy_alternates(self) -> None:
        sql, _parameters = lead_collector._category_filter_sql(
            ("photography_service",), ()
        )

        self.assertIn("taxonomy.alternates", sql)
        self.assertIn("categories.alternate", sql)


if __name__ == "__main__":
    unittest.main()
