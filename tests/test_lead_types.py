"""Tests for deterministic lead classification and viewer integration."""

from __future__ import annotations

import unittest

import lead_scorer
import lead_viewer


class LeadTypeTest(unittest.TestCase):
    def test_all_lead_types_and_offers(self) -> None:
        cases = (
            ("", "NO_WEBSITE", 5),
            ("https://instagram.com/example", "INSTAGRAM_ONLY", 4),
            ("https://maps.google.com/maps?q=test", "GOOGLE_MAPS_ONLY", 4),
            ("https://example.business.site", "BUSINESS_SITE", 3),
            (
                "https://facebook.com/example, https://youtube.com/example",
                "SOCIAL_ONLY",
                4,
            ),
            ("http://example.com", "HTTP_WEBSITE", 2),
            ("https://example.com", "MODERN_WEBSITE", 0),
            ("example.com", "UNKNOWN", 0),
        )

        for website, expected_type, expected_score in cases:
            with self.subTest(website=website):
                row = lead_scorer.score_lead(
                    {"name": "Test company", "website": website, "email": ""}
                )
                self.assertEqual(row["lead_type"], expected_type)
                self.assertEqual(
                    row["recommended_offer"],
                    lead_scorer.RECOMMENDED_OFFERS[expected_type],
                )
                self.assertEqual(int(row["score"]), expected_score)

    def test_normal_site_overrides_instagram_only(self) -> None:
        website = "https://instagram.com/example, https://example.com"
        self.assertEqual(lead_scorer.lead_type_for(website), "MODERN_WEBSITE")

    def test_short_google_maps_url(self) -> None:
        self.assertEqual(
            lead_scorer.lead_type_for("https://goo.gl/maps/example"),
            "GOOGLE_MAPS_ONLY",
        )

    def test_viewer_contains_type_filter_and_offer_column(self) -> None:
        columns = ["name", "lead_type", "recommended_offer"]
        rows = [
            {
                "name": "Test company",
                "lead_type": "NO_WEBSITE",
                "recommended_offer": "Новий сайт із онлайн-записом",
            }
        ]
        html = lead_viewer.build_html(columns, rows)
        self.assertIn('id="leadTypeFilter"', html)
        self.assertIn('id="leadTypeStats"', html)
        self.assertIn("recommended_offer", html)
        self.assertIn("NO_WEBSITE", html)


if __name__ == "__main__":
    unittest.main()
