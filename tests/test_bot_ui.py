"""Smoke tests for aiogram keyboards and Telegram presentation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aiogram

from handlers.search import (
    ViewState,
    cities_keyboard,
    confirm_keyboard,
    main_keyboard,
    new_search_keyboard,
    results_keyboard,
)
from services.lead_pipeline import SearchResult
from services.presentation import make_page


class BotUiTest(unittest.TestCase):
    def test_aiogram_version_and_keyboards(self) -> None:
        self.assertEqual(str(aiogram.__version__), "3.30.0")
        self.assertEqual(main_keyboard().keyboard[0][0].text, "Новий пошук")
        self.assertEqual(cities_keyboard().keyboard[0][0].text, "Вся Україна")
        self.assertEqual(
            new_search_keyboard().inline_keyboard[0][0].callback_data,
            "search:new",
        )
        self.assertEqual(
            confirm_keyboard().inline_keyboard[0][0].callback_data,
            "search:run",
        )
        callbacks = {
            button.callback_data
            for row in results_keyboard().inline_keyboard
            for button in row
        }
        self.assertTrue(
            {
                "results:next",
                "results:previous",
                "results:high",
                "results:type:NO_WEBSITE",
                "results:csv",
                "search:new",
            }.issubset(callbacks)
        )

    def test_result_page_contains_stats_and_company_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = SearchResult(
                user_id=1,
                niche="автосервіс",
                cities=("Київ",),
                requested_limit=1,
                source_release="test",
                rows=(
                    {
                        "name": "Test Service",
                        "city": "Київ",
                        "phone": "+380001",
                        "website": "https://example.com",
                        "email": "test@example.com",
                        "score": "5",
                        "priority": "HIGH",
                        "score_reasons": "+5: test reason",
                        "lead_type": "MODERN_WEBSITE",
                        "recommended_offer": "Автоматизація запису або AI",
                        "instagram_username": "test.service",
                        "instagram_status": "found",
                        "instagram_followers": "4811",
                    },
                ),
                csv_path=Path(directory) / "scored_leads.csv",
                run_dir=Path(directory),
                high=1,
                medium=0,
                low=0,
            )
            page = make_page(result, page=0, high_only=True)
            self.assertIn("Test Service", page.text)
            self.assertIn("HIGH: <b>1</b>", page.text)
            self.assertIn("Score: <b>5</b>", page.text)
            self.assertIn("test reason", page.text)
            self.assertIn("MODERN_WEBSITE", page.text)
            self.assertIn("Автоматизація запису або AI", page.text)
            self.assertIn("Instagram:", page.text)
            self.assertIn("@test.service", page.text)
            self.assertIn("Підписники: 4 811", page.text)

            keyboard = results_keyboard(
                result,
                ViewState(lead_type="MODERN_WEBSITE"),
            )
            type_buttons = [
                button
                for row in keyboard.inline_keyboard
                for button in row
                if (button.callback_data or "").startswith("results:type:")
            ]
            self.assertTrue(
                any(
                    button.callback_data == "results:type:MODERN_WEBSITE"
                    and "✓" in button.text
                    and "1" in button.text
                    for button in type_buttons
                )
            )

            filtered = make_page(
                result,
                page=0,
                high_only=False,
                lead_type="NO_WEBSITE",
            )
            self.assertNotIn("Test Service", filtered.text)

            result.rows[0]["instagram_status"] = "unavailable"
            result.rows[0].pop("instagram_followers")
            unavailable = make_page(result, page=0, high_only=False)
            self.assertIn("Instagram:", unavailable.text)
            self.assertNotIn("Підписники:", unavailable.text)


if __name__ == "__main__":
    unittest.main()
