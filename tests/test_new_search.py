"""Tests for the inline new-search flow and terminal action buttons."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from handlers.search import (
    NewSearchDebouncer,
    SearchForm,
    begin_search,
    new_search_callback,
    new_search_debouncer,
    run_search_in_background,
    send_search_result,
)
from services.instagram_enrichment import InstagramEnrichmentService
from services.lead_pipeline import SearchResult


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {"stale": True}
        self.state: object | None = None
        self.clear_count = 0

    async def clear(self) -> None:
        self.data.clear()
        self.state = None
        self.clear_count += 1

    async def set_state(self, state: object) -> None:
        self.state = state


class FakeResultMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[tuple[str, dict[str, object]]] = []

    async def edit_text(self, text: str, **kwargs: object) -> None:
        self.text = text
        self.edits.append((text, kwargs))


class FakeMessage:
    def __init__(self, user_id: int = 1001) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[tuple[str, dict[str, object], FakeResultMessage]] = []
        self.documents: list[tuple[object, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> FakeResultMessage:
        result = FakeResultMessage(text)
        self.answers.append((text, kwargs, result))
        return result

    async def answer_document(self, document: object, **kwargs: object) -> None:
        self.documents.append((document, kwargs))


class FakeCallback:
    def __init__(self, message: FakeMessage, user_id: int = 1001) -> None:
        self.message = message
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[tuple[str | None, dict[str, object]]] = []

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


class FakePipeline:
    def __init__(self, old_result: object | None = None) -> None:
        self.old_result = old_result

    async def is_running(self, user_id: int) -> bool:
        del user_id
        return False

    def get_result(self, user_id: int) -> object | None:
        del user_id
        return self.old_result


class FailingPipeline(FakePipeline):
    async def run(self, *args: object, **kwargs: object) -> SearchResult:
        del args, kwargs
        raise RuntimeError("collection failed")


def make_result(directory: str, *, rows: tuple[dict[str, str], ...]) -> SearchResult:
    run_dir = Path(directory)
    csv_path = run_dir / "scored_leads.csv"
    csv_path.write_text("name,priority\n", encoding="utf-8")
    return SearchResult(
        user_id=1001,
        niche="автосервіс",
        cities=("Київ",),
        requested_limit=10,
        source_release="test",
        rows=rows,
        csv_path=csv_path,
        run_dir=run_dir,
        high=sum(row.get("priority") == "HIGH" for row in rows),
        medium=sum(row.get("priority") == "MEDIUM" for row in rows),
        low=sum(row.get("priority") == "LOW" for row in rows),
    )


def keyboard_callbacks(markup: Any) -> set[str | None]:
    return {button.callback_data for row in markup.inline_keyboard for button in row}


class NewSearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_result_has_new_search_on_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_result(
                directory,
                rows=(
                    {
                        "name": "Test",
                        "city": "Київ",
                        "phone": "",
                        "website": "",
                        "email": "",
                        "score": "5",
                        "priority": "HIGH",
                        "score_reasons": "test",
                        "lead_type": "NO_WEBSITE",
                        "recommended_offer": "Новий сайт",
                    },
                ),
            )
            message = FakeMessage()

            await send_search_result(
                message,
                result,
                InstagramEnrichmentService.disabled(),
            )

            self.assertTrue(message.documents)
            markup = message.documents[-1][1]["reply_markup"]
            self.assertIn("search:new", keyboard_callbacks(markup))

    async def test_empty_result_has_new_search_button(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = make_result(directory, rows=())
            message = FakeMessage()

            await send_search_result(
                message,
                result,
                InstagramEnrichmentService.disabled(),
            )

            self.assertIn("Компаній за цим фільтром немає", message.answers[-1][0])
            markup = message.documents[-1][1]["reply_markup"]
            self.assertIn("search:new", keyboard_callbacks(markup))

    async def test_error_message_has_new_search_button(self) -> None:
        message = FakeMessage()

        await run_search_in_background(
            message,
            FailingPipeline(),
            1001,
            "автосервіс",
            ["Київ"],
            10,
            InstagramEnrichmentService.disabled(),
        )

        markup = message.answers[-1][1]["reply_markup"]
        self.assertIn("search:new", keyboard_callbacks(markup))

    async def test_begin_search_clears_fsm_but_preserves_old_result(self) -> None:
        old_result = object()
        pipeline = FakePipeline(old_result)
        state = FakeState()
        message = FakeMessage()

        await begin_search(message, state, pipeline, user_id=1001)

        self.assertEqual(state.clear_count, 1)
        self.assertEqual(state.state, SearchForm.country)
        self.assertIs(pipeline.get_result(1001), old_result)
        self.assertIn("Оберіть країну", message.answers[-1][0])

    async def test_callback_starts_repeat_search_and_rejects_double_click(self) -> None:
        new_search_debouncer.reset(1001)
        pipeline = FakePipeline(old_result=object())
        state = FakeState()
        message = FakeMessage()
        callback = FakeCallback(message)

        await new_search_callback(callback, state, pipeline)
        await new_search_callback(callback, state, pipeline)

        self.assertEqual(state.clear_count, 1)
        self.assertEqual(state.state, SearchForm.country)
        self.assertEqual(callback.answers[-1][0], "Новий пошук уже відкрито.")
        new_search_debouncer.reset(1001)

    def test_debouncer_allows_a_later_repeat(self) -> None:
        debouncer = NewSearchDebouncer(cooldown_seconds=2.0)
        self.assertTrue(debouncer.accept(1, now=10.0))
        self.assertFalse(debouncer.accept(1, now=11.0))
        self.assertTrue(debouncer.accept(1, now=12.0))


if __name__ == "__main__":
    unittest.main()
