"""Tests for local Ukrainian niche mappings."""

from __future__ import annotations

import unittest

import lead_collector


class NicheFilterTest(unittest.TestCase):
    def test_whole_ukraine_scope_aliases(self) -> None:
        for value in ("Вся Україна", "Україна", "Ukraine", "по всій Україні"):
            with self.subTest(value=value):
                self.assertEqual(
                    lead_collector.parse_cities(value),
                    [lead_collector.UKRAINE_SCOPE_NAME],
                )

        self.assertEqual(
            lead_collector.parse_cities("Київ, Вся Україна, Львів"),
            [lead_collector.UKRAINE_SCOPE_NAME],
        )

    def test_common_ukrainian_niches(self) -> None:
        cases = {
            "аптека": "pharmacy",
            "перукарня": "hair_salon",
            "магазин одягу": "clothing_store",
            "агентство нерухомості": "real_estate_agent",
            "клінінгова компанія": "home_cleaning",
        }

        for niche, expected_category in cases.items():
            with self.subTest(niche=niche):
                exact, _patterns = lead_collector.niche_filter(niche)
                self.assertIn(expected_category, exact)

    def test_english_category_code_remains_supported(self) -> None:
        exact, patterns = lead_collector.niche_filter("mobile phone store")
        self.assertEqual(exact, ("mobile_phone_store",))
        self.assertEqual(patterns, ("%mobile_phone_store%",))

    def test_unknown_cyrillic_niche_has_helpful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "локального зіставлення"):
            lead_collector.niche_filter("невідома тестова ніша")


if __name__ == "__main__":
    unittest.main()
