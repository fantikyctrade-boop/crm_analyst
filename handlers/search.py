"""FSM and result navigation for lead searches."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import Counter
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import lead_collector as collector
from lead_scorer import LEAD_TYPES
from services.instagram_enrichment import InstagramEnrichmentService
from services.lead_pipeline import (
    LeadPipeline,
    SearchAlreadyRunningError,
    SearchResult,
)
from services.presentation import make_page

router = Router(name=__name__)
logger = logging.getLogger(__name__)
background_tasks: set[asyncio.Task[None]] = set()
NEW_SEARCH_DEBOUNCE_SECONDS = 2.0

LEAD_TYPE_LABELS = {
    "NO_WEBSITE": "Без сайту",
    "INSTAGRAM_ONLY": "Instagram",
    "GOOGLE_MAPS_ONLY": "Google Maps",
    "BUSINESS_SITE": "Business Site",
    "SOCIAL_ONLY": "Соцмережі",
    "HTTP_WEBSITE": "HTTP",
    "MODERN_WEBSITE": "HTTPS",
    "UNKNOWN": "Невідомо",
}


class SearchForm(StatesGroup):
    country = State()
    region = State()
    cities = State()
    niche = State()
    limit = State()
    confirm = State()


@dataclass(slots=True)
class ViewState:
    page: int = 0
    high_only: bool = False
    lead_type: str | None = None


view_states: dict[int, ViewState] = {}


class NewSearchDebouncer:
    def __init__(self, cooldown_seconds: float) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_click: dict[int, float] = {}

    def accept(self, user_id: int, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        previous = self._last_click.get(user_id)
        if previous is not None and current - previous < self.cooldown_seconds:
            return False
        self._last_click[user_id] = current
        return True

    def reset(self, user_id: int) -> None:
        self._last_click.pop(user_id, None)


new_search_debouncer = NewSearchDebouncer(NEW_SEARCH_DEBOUNCE_SECONDS)


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Новий пошук")]],
        resize_keyboard=True,
    )


def cities_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=collector.UKRAINE_SCOPE_NAME)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def country_keyboard() -> ReplyKeyboardMarkup:
    countries = [KeyboardButton(text=name) for name in collector.country_options()]
    return ReplyKeyboardMarkup(
        keyboard=[
            countries[index : index + 2] for index in range(0, len(countries), 2)
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def region_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустити регіон")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Запустити", callback_data="search:run")],
            [InlineKeyboardButton(text="Новий пошук", callback_data="search:new")],
        ]
    )


def new_search_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новий пошук", callback_data="search:new")]
        ]
    )


def results_keyboard(
    result: SearchResult | None = None,
    view: ViewState | None = None,
) -> InlineKeyboardMarkup:
    current_view = view or ViewState()
    counts = (
        Counter(row.get("lead_type", "UNKNOWN") for row in result.rows)
        if result
        else Counter()
    )
    type_buttons = [
        InlineKeyboardButton(
            text=(
                f"{'✓ ' if current_view.lead_type is None else ''}"
                f"Усі типи{f' · {result.total}' if result else ''}"
            ),
            callback_data="results:type:ALL",
        )
    ]
    for lead_type in LEAD_TYPES:
        count = counts[lead_type]
        if result is not None and count == 0:
            continue
        marker = "✓ " if current_view.lead_type == lead_type else ""
        suffix = f" · {count}" if result is not None else ""
        type_buttons.append(
            InlineKeyboardButton(
                text=f"{marker}{LEAD_TYPE_LABELS[lead_type]}{suffix}",
                callback_data=f"results:type:{lead_type}",
            )
        )

    type_rows = [
        type_buttons[index : index + 2] for index in range(0, len(type_buttons), 2)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Попередні 10", callback_data="results:previous"
                ),
                InlineKeyboardButton(text="Наступні 10", callback_data="results:next"),
            ],
            [
                InlineKeyboardButton(
                    text="Усі priority" if current_view.high_only else "Тільки HIGH",
                    callback_data="results:high",
                )
            ],
            *type_rows,
            [InlineKeyboardButton(text="Завантажити CSV", callback_data="results:csv")],
            [InlineKeyboardButton(text="Новий пошук", callback_data="search:new")],
        ]
    )


async def begin_search(
    message: Message,
    state: FSMContext,
    pipeline: LeadPipeline,
    user_id: int | None = None,
) -> None:
    effective_user_id = user_id or (message.from_user.id if message.from_user else None)
    if effective_user_id is not None and await pipeline.is_running(effective_user_id):
        await message.answer("Поточний пошук ще виконується. Дочекайтеся завершення.")
        return
    await state.clear()
    await state.set_state(SearchForm.country)
    await message.answer("Оберіть країну.", reply_markup=country_keyboard())


@router.message(CommandStart())
async def command_start(message: Message) -> None:
    await message.answer(
        "Бот збирає компанії через Overture Maps і виконує локальний скоринг.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "Новий пошук")
async def new_search_message(
    message: Message, state: FSMContext, pipeline: LeadPipeline
) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is not None and not new_search_debouncer.accept(user_id):
        await message.answer("Новий пошук уже відкрито.")
        return
    await begin_search(message, state, pipeline, user_id=user_id)


@router.callback_query(F.data == "search:new")
async def new_search_callback(
    callback: CallbackQuery, state: FSMContext, pipeline: LeadPipeline
) -> None:
    user_id = callback.from_user.id
    if not new_search_debouncer.accept(user_id):
        await callback.answer("Новий пошук уже відкрито.")
        return
    await callback.answer()
    if callback.message:
        await begin_search(
            callback.message,
            state,
            pipeline,
            user_id=user_id,
        )


@router.message(SearchForm.country)
async def receive_country(message: Message, state: FSMContext) -> None:
    try:
        country = collector.parse_country(message.text or "")
    except ValueError as error:
        await message.answer(f"Некоректна країна: {error}")
        return
    await state.update_data(country_code=country.code, country_name=country.name)
    await state.set_state(SearchForm.region)
    await message.answer(
        "Введіть штат або регіон (наприклад, California). "
        "Або натисніть «Пропустити регіон».",
        reply_markup=region_keyboard(),
    )


@router.message(SearchForm.region)
async def receive_region(message: Message, state: FSMContext) -> None:
    region = (message.text or "").strip()
    if region == "Пропустити регіон":
        region = ""
    await state.update_data(region=region)
    await state.set_state(SearchForm.cities)
    await message.answer(
        "Введіть одне або кілька міст через кому.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(SearchForm.cities)
async def receive_cities(message: Message, state: FSMContext) -> None:
    raw_cities = (message.text or "").strip()
    try:
        cities = collector.parse_cities(raw_cities)
    except ValueError as error:
        await message.answer(f"Некоректний список міст: {error}")
        return
    await state.update_data(cities=cities)
    await state.set_state(SearchForm.niche)
    await message.answer("Введіть нішу, наприклад: Dental або автосервіс.")


@router.message(SearchForm.niche)
async def receive_niche(message: Message, state: FSMContext) -> None:
    niche = (message.text or "").strip()
    if not niche:
        await message.answer("Ніша не може бути порожньою. Спробуйте ще раз.")
        return
    try:
        collector.niche_filter(niche)
    except ValueError as error:
        await message.answer(f"Не вдалося розпізнати нішу: {error}")
        return
    await state.update_data(niche=niche)
    await state.set_state(SearchForm.limit)
    await message.answer("Введіть потрібну кількість компаній.")


@router.message(SearchForm.limit)
async def receive_limit(message: Message, state: FSMContext) -> None:
    try:
        limit = collector.positive_int((message.text or "").strip())
    except (ValueError, TypeError):
        await message.answer("Ліміт має бути цілим числом, більшим за нуль.")
        return

    await state.update_data(limit=limit)
    data = await state.get_data()
    await state.set_state(SearchForm.confirm)
    await message.answer(
        "<b>Перевірте параметри</b>\n"
        f"Країна: {html.escape(data['country_name'])}\n"
        f"Регіон: {html.escape(data['region'] or '—')}\n"
        f"Міста: {html.escape(', '.join(data['cities']))}\n"
        f"Ніша: {html.escape(data['niche'])}\n"
        f"Ліміт: {limit}",
        reply_markup=confirm_keyboard(),
    )


async def refresh_instagram_enrichment(
    result_message: Message,
    result: SearchResult,
    instagram_enrichment: InstagramEnrichmentService,
) -> None:
    try:
        await instagram_enrichment.enrich_rows(result.rows)
        view = view_states.get(result.user_id, ViewState())
        page = make_page(result, view.page, view.high_only, view.lead_type)
        await result_message.edit_text(
            page.text,
            reply_markup=results_keyboard(result, view),
        )
    except Exception:
        logger.exception("Could not refresh Instagram enrichment")


async def send_search_result(
    message: Message,
    result: SearchResult,
    instagram_enrichment: InstagramEnrichmentService,
) -> None:
    view = ViewState()
    view_states[result.user_id] = view
    instagram_profiles = instagram_enrichment.prepare_rows(result.rows)
    page = make_page(result, page=0, high_only=False, lead_type=None)
    coverage_warning = collector.niche_coverage_warning(result.niche)
    if coverage_warning:
        await message.answer(coverage_warning)
    result_message = await message.answer(
        page.text,
        reply_markup=results_keyboard(result, view),
    )
    await message.answer_document(
        FSInputFile(result.csv_path, filename="scored_leads.csv"),
        caption="Повний scored_leads.csv",
        reply_markup=new_search_keyboard(),
    )
    if instagram_profiles and instagram_enrichment.enabled:
        task = asyncio.create_task(
            refresh_instagram_enrichment(
                result_message,
                result,
                instagram_enrichment,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)


async def run_search_in_background(
    message: Message,
    pipeline: LeadPipeline,
    user_id: int,
    niche: str,
    cities: list[str],
    limit: int,
    instagram_enrichment: InstagramEnrichmentService,
    country_code: str | None = None,
    country_name: str = "",
    region: str = "",
) -> None:
    try:
        result = await pipeline.run(
            user_id,
            niche,
            cities,
            limit,
            country_code=country_code,
            country_name=country_name,
            region=region,
        )
        await send_search_result(message, result, instagram_enrichment)
    except SearchAlreadyRunningError:
        await message.answer(
            "Пошук уже виконується. Дочекайтеся завершення.",
            reply_markup=new_search_keyboard(),
        )
    except Exception:
        logger.exception("Lead search failed for user %s", user_id)
        await message.answer(
            "Не вдалося завершити пошук. Перевірте мережу та параметри й спробуйте ще раз.",
            reply_markup=new_search_keyboard(),
        )


@router.callback_query(SearchForm.confirm, F.data == "search:run")
async def run_search(
    callback: CallbackQuery,
    state: FSMContext,
    pipeline: LeadPipeline,
    instagram_enrichment: InstagramEnrichmentService,
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    if await pipeline.is_running(callback.from_user.id):
        await callback.answer("Пошук уже виконується.", show_alert=True)
        return

    data = await state.get_data()
    required = {"country_code", "country_name", "region", "niche", "cities", "limit"}
    if not required.issubset(data):
        await callback.answer(
            "Параметри застаріли. Почніть новий пошук.", show_alert=True
        )
        return

    await callback.answer()
    await state.clear()
    await callback.message.answer("Пошук запущено. Це може зайняти кілька хвилин.")
    task = asyncio.create_task(
        run_search_in_background(
            callback.message,
            pipeline,
            callback.from_user.id,
            data["niche"],
            data["cities"],
            data["limit"],
            instagram_enrichment,
            country_code=data["country_code"],
            country_name=data["country_name"],
            region=data["region"],
        )
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def update_result_message(
    callback: CallbackQuery, pipeline: LeadPipeline, action: str
) -> None:
    user_id = callback.from_user.id
    result = pipeline.get_result(user_id)
    if result is None or not callback.message:
        await callback.answer("Немає активного результату.", show_alert=True)
        return

    view = view_states.setdefault(user_id, ViewState())
    previous_page = view.page
    previous_high_only = view.high_only
    previous_lead_type = view.lead_type
    if action == "next":
        view.page += 1
    elif action == "previous":
        view.page -= 1
    elif action == "high":
        view.high_only = not view.high_only
        view.page = 0
    elif action.startswith("type:"):
        selected_type = action.partition(":")[2]
        view.lead_type = None if selected_type == "ALL" else selected_type
        view.page = 0

    page = make_page(result, view.page, view.high_only, view.lead_type)
    view.page = page.number
    if (
        view.page == previous_page
        and view.high_only == previous_high_only
        and view.lead_type == previous_lead_type
    ):
        await callback.answer("Інших сторінок немає.")
        return
    await callback.message.edit_text(
        page.text,
        reply_markup=results_keyboard(result, view),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"results:next", "results:previous", "results:high"}))
async def navigate_results(callback: CallbackQuery, pipeline: LeadPipeline) -> None:
    action = (callback.data or "").partition(":")[2]
    await update_result_message(callback, pipeline, action)


@router.callback_query(F.data.startswith("results:type:"))
async def filter_results_by_type(
    callback: CallbackQuery, pipeline: LeadPipeline
) -> None:
    action = (callback.data or "").partition("results:")[2]
    selected_type = action.partition(":")[2]
    if selected_type != "ALL" and selected_type not in LEAD_TYPES:
        await callback.answer("Невідомий тип ліда.", show_alert=True)
        return
    await update_result_message(callback, pipeline, action)


@router.callback_query(F.data == "results:csv")
async def download_csv(callback: CallbackQuery, pipeline: LeadPipeline) -> None:
    result = pipeline.get_result(callback.from_user.id)
    if result is None or not result.csv_path.exists() or not callback.message:
        await callback.answer(
            "CSV більше недоступний. Запустіть новий пошук.", show_alert=True
        )
        return
    await callback.answer()
    await callback.message.answer_document(
        FSInputFile(result.csv_path, filename="scored_leads.csv")
    )
