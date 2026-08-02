"""Tests for local Ukrainian niche mappings."""

from __future__ import annotations

import unittest

import lead_collector


class NicheFilterTest(unittest.TestCase):
    VERIFIED_CATEGORIES = frozenset(
        {
            "private_tutor",
            "tutoring_center",
            "dance_school",
            "language_school",
            "photographer",
            "wedding_planning",
            "party_and_event_planning",
            "interior_design",
            "real_estate_agent",
            "fitness_trainer",
            "sports_and_fitness_instruction",
            "nutritionist",
            "dietitian",
        }
    )

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

    def test_requested_niches_use_verified_overture_categories(self) -> None:
        cases = {
            "репетитор": {"private_tutor", "tutoring_center"},
            "Репетитор": {"private_tutor", "tutoring_center"},
            "приватний репетитор": {"private_tutor", "tutoring_center"},
            "школа танців": {"dance_school"},
            "танцювальна студія": {"dance_school"},
            "школа англійської": {"language_school"},
            "школа іноземних мов": {"language_school"},
            "фотограф": {"photographer"},
            "весільний фотограф": {"photographer"},
            "весільний організатор": {"wedding_planning"},
            "дизайнер інтер'єру": {"interior_design"},
            "ріелтор": {"real_estate_agent"},
            "приватний ріелтор": {"real_estate_agent"},
            "ріелтор приватна практика": {"real_estate_agent"},
            "персональний тренер": {"fitness_trainer"},
            "фітнес-тренер": {"fitness_trainer"},
            "нутриціолог": {"nutritionist", "dietitian"},
            "дієтолог": {"nutritionist", "dietitian"},
        }

        for niche, expected in cases.items():
            with self.subTest(niche=niche):
                exact, patterns = lead_collector.niche_filter(niche)
                self.assertEqual(set(exact), expected)
                self.assertFalse(patterns)
                self.assertLessEqual(set(exact), self.VERIFIED_CATEGORIES)

    def test_russian_and_english_aliases(self) -> None:
        cases = {
            "частный репетитор": "private_tutor",
            "танцевальная школа": "dance_school",
            "курсы английского": "language_school",
            "свадебный фотограф": "photographer",
            "организатор свадеб": "wedding_planning",
            "ивент-агентство": "party_and_event_planning",
            "дизайнер интерьера": "interior_design",
            "частный риэлтор": "real_estate_agent",
            "фитнес-тренер": "fitness_trainer",
            "спортивный тренер": "sports_and_fitness_instruction",
            "консультант по питанию": "nutritionist",
            "dance studio": "dance_school",
            "language school": "language_school",
            "photography studio": "photographer",
            "event planner": "party_and_event_planning",
            "interior design studio": "interior_design",
            "realtor": "real_estate_agent",
            "fitness trainer": "fitness_trainer",
            "dietitian": "dietitian",
        }

        for niche, expected in cases.items():
            with self.subTest(niche=niche):
                exact, _patterns = lead_collector.niche_filter(niche)
                self.assertIn(expected, exact)

    def test_normalization_is_safe_and_handles_common_variants(self) -> None:
        cases = {
            "  ШКОЛА     ТАНЦІВ  ": "dance_school",
            "фітнес--тренер": "fitness_trainer",
            "дизайнер інтер’єру": "interior_design",
            "дизайнер інтерєру": "interior_design",
            "приватна практика ріелтор": "real_estate_agent",
            "студія   танців": "dance_school",
            "репетитори": "private_tutor",
            "фотографи": "photographer",
            "нутриціологи": "nutritionist",
        }

        for niche, expected in cases.items():
            with self.subTest(niche=niche):
                exact, _patterns = lead_collector.niche_filter(niche)
                self.assertIn(expected, exact)

    def test_broad_trainer_and_teacher_require_selection(self) -> None:
        cases = {
            "тренер": (
                "персональний тренер",
                "спортивний тренер",
                "школа танців",
            ),
            "викладач": ("репетитор", "мовна школа", "школа танців"),
            "учитель": ("репетитор", "мовна школа", "школа танців"),
        }

        for niche, expected_suggestions in cases.items():
            with self.subTest(niche=niche):
                with self.assertRaises(
                    lead_collector.NicheSelectionRequiredError
                ) as raised:
                    lead_collector.niche_filter(niche)
                self.assertEqual(raised.exception.suggestions, expected_suggestions)
                self.assertIn("Оберіть", str(raised.exception))

    def test_unknown_niche_only_suggests_and_does_not_map(self) -> None:
        with self.assertRaises(
            lead_collector.NicheSelectionRequiredError
        ) as raised:
            lead_collector.niche_filter("невідома тестова ніша")

        self.assertEqual(len(raised.exception.suggestions), 3)
        self.assertIn("збір не запущено", str(raised.exception))

        with self.assertRaises(
            lead_collector.NicheSelectionRequiredError
        ) as typo:
            lead_collector.niche_filter("фотграф")
        self.assertEqual(typo.exception.suggestions[0], "фотограф")

    def test_private_specialist_coverage_warning(self) -> None:
        warning = lead_collector.niche_coverage_warning("приватний репетитор")
        self.assertIsNotNone(warning)
        self.assertIn("приватних спеціалістів", warning or "")
        self.assertIsNone(lead_collector.niche_coverage_warning("школа танців"))

    def test_english_category_code_remains_supported(self) -> None:
        exact, patterns = lead_collector.niche_filter("mobile phone store")
        self.assertEqual(exact, ("mobile_phone_store",))
        self.assertEqual(patterns, ("%mobile_phone_store%",))

    def test_unknown_cyrillic_niche_has_helpful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "локального зіставлення"):
            lead_collector.niche_filter("невідома тестова ніша")


if __name__ == "__main__":
    unittest.main()
