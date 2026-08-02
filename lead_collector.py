"""Collect a small CSV lead list from Overture Maps Places.

Dependency:
    python -m pip install duckdb
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb

STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "minimal-overture-lead-collector/1.0"
UKRAINE_SCOPE_NAME = "Вся Україна"
UKRAINE_COUNTRY_CODE = "UA"
UKRAINE_BOUNDS = (22.0, 44.0, 40.5, 52.6)
UKRAINE_SCOPE_ALIASES = frozenset(
    {
        "вся україна",
        "україна",
        "по всій україні",
        "ukraine",
        "all ukraine",
    }
)

CSV_FIELDS = (
    "name",
    "city",
    "address",
    "phone",
    "website",
    "email",
    "category",
    "overture_id",
    "latitude",
    "longitude",
    "source_release",
)

CAR_SERVICE_CATEGORIES = (
    "automotive_services_and_repair",
    "automotive_repair",
    "auto_body_shop",
    "auto_electrical_repair",
    "auto_glass_service",
    "auto_restoration_services",
    "brake_service_and_repair",
    "car_inspection",
    "engine_repair_service",
    "exhaust_and_muffler_repair",
    "hybrid_car_repair",
    "oil_change_station",
    "tire_dealer_and_repair",
    "transmission_repair",
    "truck_repair",
    "wheel_and_rim_repair",
    "windshield_installation_and_repair",
)

# Local aliases translate common Ukrainian business niches into official
# Overture category codes. An English Overture code such as ``pharmacy`` or
# ``beauty_salon`` can also be passed directly.
NICHE_ALIASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "автосервіс": (CAR_SERVICE_CATEGORIES, ()),
    "автосервис": (CAR_SERVICE_CATEGORIES, ()),
    "сто": (CAR_SERVICE_CATEGORIES, ()),
    "car service": (CAR_SERVICE_CATEGORIES, ()),
    "auto repair": (CAR_SERVICE_CATEGORIES, ()),
    "кафе": (("cafe", "coffee_shop"), ()),
    "cafe": (("cafe", "coffee_shop"), ()),
    "кав'ярня": (("cafe", "coffee_shop"), ()),
    "кав’ярня": (("cafe", "coffee_shop"), ()),
    "ресторан": (("restaurant",), ("%restaurant%",)),
    "restaurant": (("restaurant",), ("%restaurant%",)),
    "готель": (("hotel", "motel", "hostel"), ()),
    "hotel": (("hotel", "motel", "hostel"), ()),
    "стоматологія": (("dentist", "dental_clinic"), ("%dental%",)),
    "dentist": (("dentist", "dental_clinic"), ("%dental%",)),
    "салон краси": (("beauty_salon",), ("%beauty_salon%",)),
    "beauty salon": (("beauty_salon",), ("%beauty_salon%",)),
    "аптека": (("pharmacy", "drugstore"), ()),
    "аптеки": (("pharmacy", "drugstore"), ()),
    "фармація": (("pharmacy", "drugstore"), ()),
    "перукарня": (("hair_salon",), ()),
    "перукар": (("hair_salon",), ()),
    "барбершоп": (("barber",), ()),
    "манікюр": (("nail_salon",), ()),
    "манікюрний салон": (("nail_salon",), ()),
    "масаж": (("massage", "massage_therapy"), ()),
    "масажний салон": (("massage", "massage_therapy"), ()),
    "медична клініка": (
        ("medical_center", "community_health_center", "storefront_clinic"),
        (),
    ),
    "медичний центр": (
        ("medical_center", "community_health_center", "storefront_clinic"),
        (),
    ),
    "клініка": (
        ("medical_center", "community_health_center", "storefront_clinic"),
        (),
    ),
    "лікарня": (("hospital",), ()),
    "лабораторія": (("laboratory_testing",), ()),
    "психолог": (("psychologist",), ()),
    "ветклініка": (("veterinarian",), ()),
    "ветеринарна клініка": (("veterinarian",), ()),
    "ветеринар": (("veterinarian",), ()),
    "спортзал": (("gym",), ()),
    "тренажерний зал": (("gym",), ()),
    "фітнес клуб": (("gym", "sports_and_fitness_instruction"), ()),
    "фітнес-клуб": (("gym", "sports_and_fitness_instruction"), ()),
    "фітнес": (("gym", "sports_and_fitness_instruction"), ()),
    "йога": (("yoga_studio",), ()),
    "продуктовий магазин": (
        ("grocery_store", "supermarket", "convenience_store"),
        (),
    ),
    "магазин продуктів": (
        ("grocery_store", "supermarket", "convenience_store"),
        (),
    ),
    "супермаркет": (("supermarket",), ()),
    "магазин одягу": (("clothing_store",), ()),
    "одяг": (("clothing_store",), ()),
    "меблевий магазин": (("furniture_store",), ()),
    "магазин меблів": (("furniture_store",), ()),
    "магазин техніки": (("electronics", "appliance_store"), ()),
    "магазин електроніки": (("electronics", "computer_store"), ()),
    "квітковий магазин": (("florist", "flowers_and_gifts_shop"), ()),
    "магазин квітів": (("florist", "flowers_and_gifts_shop"), ()),
    "зоомагазин": (("pet_store",), ()),
    "будівельний магазин": (
        ("building_supply_store", "hardware_store", "home_improvement_store"),
        (),
    ),
    "магазин": (("shopping",), ()),
    "автомийка": (("car_wash",), ()),
    "мийка авто": (("car_wash",), ()),
    "шиномонтаж": (
        ("tire_dealer_and_repair", "tire_shop", "tire_repair_shop"),
        (),
    ),
    "азс": (("gas_station",), ()),
    "заправка": (("gas_station",), ()),
    "автозаправка": (("gas_station",), ()),
    "автосалон": (("car_dealer", "used_car_dealer"), ()),
    "агентство нерухомості": (
        ("real_estate_agent", "real_estate_service"),
        (),
    ),
    "рієлтор": (("real_estate_agent",), ()),
    "юрист": (("lawyer",), ()),
    "адвокат": (("lawyer",), ()),
    "юридична компанія": (("lawyer",), ()),
    "бухгалтер": (("accountant",), ()),
    "бухгалтерські послуги": (("accountant",), ()),
    "страхова компанія": (("insurance_agency",), ()),
    "страхування": (("insurance_agency",), ()),
    "турагенція": (("travel_agents",), ()),
    "туристична агенція": (("travel_agents",), ()),
    "клінінг": (("home_cleaning", "b2b_cleaning_and_waste_management"), ()),
    "клінінгова компанія": (
        ("home_cleaning", "b2b_cleaning_and_waste_management"),
        (),
    ),
    "електрик": (("electrician",), ()),
    "будівельна компанія": (("construction_services", "builders"), ()),
    "ремонт квартир": (("construction_services",), ()),
    "рекламне агентство": (
        ("business_advertising", "marketing_agency"),
        (),
    ),
    "маркетингове агентство": (
        ("marketing_agency", "internet_marketing_service", "marketing_consultant"),
        (),
    ),
    "іт компанія": (("software_development",), ()),
    "it компанія": (("software_development",), ()),
    "мовна школа": (("language_school",), ()),
    "дитячий садок": (("preschool", "day_care_preschool"), ()),
    "садочок": (("preschool", "day_care_preschool"), ()),
    "школа": (("school",), ()),
    "пекарня": (("bakery",), ()),
    "піцерія": (("pizza_restaurant",), ()),
    "піца": (("pizza_restaurant",), ()),
    "суші": (("sushi_restaurant",), ()),
    "фастфуд": (("fast_food_restaurant",), ()),
    "бар": (("bar",), ()),
}

ADDITIONAL_NICHE_GROUPS: tuple[
    tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        ("private_tutor", "tutoring_center"),
        (),
        (
            "репетитор",
            "репетитори",
            "репетиторів",
            "приватний репетитор",
            "приватні репетитори",
            "приватний викладач",
            "приватна викладачка",
            "репетиторський центр",
            "центр репетиторів",
            "частный репетитор",
            "частные репетиторы",
            "центр репетиторов",
            "tutor",
            "tutors",
            "private tutor",
            "tutoring center",
        ),
    ),
    (
        ("dance_school",),
        (),
        (
            "школа танців",
            "школи танців",
            "танцювальна школа",
            "танцювальні школи",
            "студія танців",
            "студії танців",
            "танцювальна студія",
            "танцювальні студії",
            "школа танцев",
            "танцевальная школа",
            "студия танцев",
            "танцевальная студия",
            "dance school",
            "dance schools",
            "dance studio",
            "dance studios",
        ),
    ),
    (
        ("language_school",),
        (),
        (
            "мовна школа",
            "мовні школи",
            "школа англійської",
            "школи англійської",
            "курси англійської",
            "курс англійської",
            "школа іноземних мов",
            "школи іноземних мов",
            "курси іноземних мов",
            "языковая школа",
            "языковые школы",
            "школа английского",
            "курсы английского",
            "школа иностранных языков",
            "курсы иностранных языков",
            "language school",
            "language schools",
            "foreign language school",
            "english school",
            "english courses",
        ),
    ),
    (
        ("photographer",),
        (),
        (
            "фотограф",
            "фотографи",
            "фотографів",
            "фотостудія",
            "фотостудії",
            "весільний фотограф",
            "весільні фотографи",
            "фотограф на весілля",
            "послуги фотографа",
            "свадебный фотограф",
            "свадебные фотографы",
            "фотограф на свадьбу",
            "услуги фотографа",
            "фотостудия",
            "photographer",
            "photographers",
            "photography studio",
            "photo studio",
            "wedding photographer",
        ),
    ),
    (
        ("wedding_planning",),
        (),
        (
            "весільний організатор",
            "весільні організатори",
            "організатор весіль",
            "організатори весіль",
            "весільна агенція",
            "весільне агентство",
            "свадебный организатор",
            "организатор свадеб",
            "свадебное агентство",
            "wedding planner",
            "wedding planners",
            "wedding planning",
        ),
    ),
    (
        ("party_and_event_planning",),
        (),
        (
            "івент агенція",
            "івент-агенція",
            "івент агентство",
            "івент-агентство",
            "агенція подій",
            "організатор подій",
            "ивент агентство",
            "ивент-агентство",
            "организатор мероприятий",
            "event agency",
            "event planner",
            "event planning",
        ),
    ),
    (
        ("interior_design",),
        (),
        (
            "дизайнер інтер'єру",
            "дизайнери інтер'єру",
            "дизайнер інтер’єру",
            "дизайн інтер'єру",
            "дизайн інтер’єру",
            "студія дизайну",
            "студії дизайну",
            "студія дизайну інтер'єру",
            "архітектор інтер'єру",
            "архітектори інтер'єру",
            "дизайнер интерьера",
            "дизайн интерьера",
            "студия дизайна",
            "архитектор интерьера",
            "interior designer",
            "interior designers",
            "interior design",
            "interior design studio",
        ),
    ),
    (
        ("real_estate_agent",),
        (),
        (
            "ріелтор",
            "рієлтор",
            "ріелтори",
            "рієлтори",
            "ріелторів",
            "рієлторів",
            "приватний ріелтор",
            "приватний рієлтор",
            "ріелтор приватна практика",
            "рієлтор приватна практика",
            "агент з нерухомості",
            "агенти з нерухомості",
            "брокер з нерухомості",
            "брокери з нерухомості",
            "риелтор",
            "риэлтор",
            "частный риелтор",
            "частный риэлтор",
            "агент по недвижимости",
            "брокер по недвижимости",
            "real estate agent",
            "real estate agents",
            "realtor",
            "realtors",
            "private realtor",
        ),
    ),
    (
        ("fitness_trainer",),
        (),
        (
            "персональний тренер",
            "персональні тренери",
            "фітнес тренер",
            "фітнес-тренер",
            "фітнес тренери",
            "фитнес тренер",
            "фитнес-тренер",
            "персональный тренер",
            "персональные тренеры",
            "personal trainer",
            "personal trainers",
            "fitness trainer",
            "fitness trainers",
        ),
    ),
    (
        ("sports_and_fitness_instruction", "fitness_trainer"),
        (),
        (
            "спортивний тренер",
            "спортивні тренери",
            "спортивный тренер",
            "спортивные тренеры",
            "sports trainer",
            "sports trainers",
            "sports coach",
        ),
    ),
    (
        ("nutritionist", "dietitian"),
        (),
        (
            "нутриціолог",
            "нутриціологи",
            "дієтолог",
            "дієтологи",
            "консультант з харчування",
            "консультанти з харчування",
            "нутрициолог",
            "нутрициологи",
            "диетолог",
            "диетологи",
            "консультант по питанию",
            "консультанты по питанию",
            "nutritionist",
            "nutritionists",
            "dietitian",
            "dietitians",
            "nutrition consultant",
        ),
    ),
)

for _categories, _patterns, _aliases in ADDITIONAL_NICHE_GROUPS:
    for _alias in _aliases:
        NICHE_ALIASES[_alias] = (_categories, _patterns)

SUPPORTED_NICHE_OPTIONS = (
    "автосервіс",
    "стоматологія",
    "салон краси",
    "ветеринарна клініка",
    "мовна школа",
    "школа танців",
    "репетитор",
    "фотограф",
    "весільний організатор",
    "дизайнер інтер'єру",
    "ріелтор",
    "персональний тренер",
    "спортивний тренер",
    "нутриціолог",
    "клінінг",
    "юрист",
    "будівельна компанія",
    "агентство нерухомості",
)

NICHE_FILLER_WORDS = frozenset(
    {
        "приватний",
        "приватна",
        "приватне",
        "приватні",
        "студія",
        "студії",
        "школа",
        "школи",
        "центр",
        "центри",
        "послуга",
        "послуги",
        "практика",
        "частный",
        "частная",
        "частное",
        "частные",
        "студия",
        "студии",
        "школы",
        "услуга",
        "услуги",
        "private",
        "studio",
        "studios",
        "school",
        "schools",
        "center",
        "centers",
        "centre",
        "centres",
        "service",
        "services",
        "practice",
    }
)

PRIVATE_SPECIALIST_CATEGORIES = frozenset(
    {
        "private_tutor",
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


def fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def latest_release() -> str:
    release = fetch_json(STAC_CATALOG)["latest"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise RuntimeError(f"Unexpected Overture release name: {release!r}")
    return release


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"['’ʼ`]", "", normalized)
    normalized = re.sub(r"[-‐‑‒–—]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized)


class NicheSelectionRequiredError(ValueError):
    """Raised when a niche must be selected explicitly instead of guessed."""

    def __init__(self, message: str, suggestions: tuple[str, ...]) -> None:
        self.suggestions = suggestions
        choices = "; ".join(suggestions)
        super().__init__(f"{message} Оберіть і введіть один із варіантів: {choices}.")


def normalize_niche_key(value: str) -> str:
    words = (
        word
        for word in normalize_text(value).split()
        if word not in NICHE_FILLER_WORDS
    )
    return " ".join(words)


def _build_niche_indexes() -> tuple[
    dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
    dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
]:
    exact: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    simplified_buckets: dict[
        str, set[tuple[tuple[str, ...], tuple[str, ...]]]
    ] = {}

    for alias, mapping in NICHE_ALIASES.items():
        exact[normalize_text(alias)] = mapping
        simplified = normalize_niche_key(alias)
        if simplified:
            simplified_buckets.setdefault(simplified, set()).add(mapping)

    simplified = {
        key: next(iter(mappings))
        for key, mappings in simplified_buckets.items()
        if len(mappings) == 1
    }
    return exact, simplified


NORMALIZED_NICHE_ALIASES, SIMPLIFIED_NICHE_ALIASES = _build_niche_indexes()

_AMBIGUOUS_NICHE_OPTIONS = {
    "тренер": ("персональний тренер", "спортивний тренер", "школа танців"),
    "тренери": ("персональний тренер", "спортивний тренер", "школа танців"),
    "тренерка": ("персональний тренер", "спортивний тренер", "школа танців"),
    "тренерки": ("персональний тренер", "спортивний тренер", "школа танців"),
    "тренеры": ("персональний тренер", "спортивний тренер", "школа танців"),
    "trainer": ("персональний тренер", "спортивний тренер", "школа танців"),
    "coach": ("персональний тренер", "спортивний тренер", "школа танців"),
    "викладач": ("репетитор", "мовна школа", "школа танців"),
    "викладачка": ("репетитор", "мовна школа", "школа танців"),
    "викладачі": ("репетитор", "мовна школа", "школа танців"),
    "учитель": ("репетитор", "мовна школа", "школа танців"),
    "учителька": ("репетитор", "мовна школа", "школа танців"),
    "учителі": ("репетитор", "мовна школа", "школа танців"),
    "преподаватель": ("репетитор", "мовна школа", "школа танців"),
    "преподаватели": ("репетитор", "мовна школа", "школа танців"),
    "teacher": ("репетитор", "мовна школа", "школа танців"),
}
AMBIGUOUS_NICHE_OPTIONS = {
    normalize_text(alias): suggestions
    for alias, suggestions in _AMBIGUOUS_NICHE_OPTIONS.items()
}


def nearest_supported_niches(niche: str, limit: int = 3) -> tuple[str, ...]:
    normalized = normalize_text(niche)

    def similarity(option: str) -> float:
        option_normalized = normalize_text(option)
        sequence_score = SequenceMatcher(None, normalized, option_normalized).ratio()
        query_words = set(normalized.split())
        option_words = set(option_normalized.split())
        overlap_score = len(query_words & option_words) / max(
            len(query_words | option_words), 1
        )
        return max(sequence_score, overlap_score)

    ranked = sorted(
        SUPPORTED_NICHE_OPTIONS,
        key=lambda option: (-similarity(option), option),
    )
    return tuple(ranked[:limit])


def niche_filter(niche: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized = normalize_text(niche)
    if normalized in AMBIGUOUS_NICHE_OPTIONS:
        raise NicheSelectionRequiredError(
            "Запит надто широкий, тому категорію не вибрано автоматично.",
            AMBIGUOUS_NICHE_OPTIONS[normalized],
        )
    if normalized in NORMALIZED_NICHE_ALIASES:
        return NORMALIZED_NICHE_ALIASES[normalized]

    simplified = normalize_niche_key(niche)
    if simplified in AMBIGUOUS_NICHE_OPTIONS:
        raise NicheSelectionRequiredError(
            "Запит надто широкий, тому категорію не вибрано автоматично.",
            AMBIGUOUS_NICHE_OPTIONS[simplified],
        )
    if simplified in SIMPLIFIED_NICHE_ALIASES:
        return SIMPLIFIED_NICHE_ALIASES[simplified]

    category_code = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if not category_code:
        raise NicheSelectionRequiredError(
            "Точного локального зіставлення для цього запиту немає, "
            "тому збір не запущено.",
            nearest_supported_niches(niche),
        )
    return (category_code,), (f"%{category_code}%",)


def niche_coverage_warning(niche: str) -> str | None:
    try:
        exact_categories, _patterns = niche_filter(niche)
    except NicheSelectionRequiredError:
        return None
    if PRIVATE_SPECIALIST_CATEGORIES.intersection(exact_categories):
        return (
            "⚠️ Overture Maps краще покриває компанії та заклади, ніж "
            "приватних спеціалістів. Нульова або мала кількість результатів "
            "не означає, що таких спеціалістів у вибраному місті немає."
        )
    return None


def is_ukraine_scope(value: str) -> bool:
    return normalize_text(value) in UKRAINE_SCOPE_ALIASES


def parse_cities(value: str) -> list[str]:
    cities: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        city = item.strip()
        key = normalize_text(city)
        if is_ukraine_scope(city):
            return [UKRAINE_SCOPE_NAME]
        if city and key not in seen:
            cities.append(city)
            seen.add(key)
    if not cities:
        raise ValueError("Specify at least one city.")
    return cities


def geocode_city(city: str) -> tuple[float, float, float, float]:
    query = urlencode(
        {
            "q": city,
            "format": "jsonv2",
            "limit": 1,
            "featuretype": "city",
            "accept-language": "uk",
        }
    )
    results = fetch_json(f"{NOMINATIM_SEARCH}?{query}")
    if not results:
        raise RuntimeError(f"City not found: {city}")

    south, north, west, east = map(float, results[0]["boundingbox"])
    return west, south, east, north


def open_overture() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("INSTALL httpfs")
    connection.execute("LOAD httpfs")
    return connection


def fetch_places(
    connection: duckdb.DuckDBPyConnection,
    release: str,
    city: str,
    bounds: tuple[float, float, float, float],
    exact_categories: tuple[str, ...],
    category_patterns: tuple[str, ...],
    candidate_limit: int,
    country_code: str | None = None,
) -> list[dict[str, Any]]:
    parquet_path = (
        f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
    )
    category = "COALESCE(taxonomy.primary, basic_category, categories.primary)"
    category_parts: list[str] = []
    category_parameters: list[str] = []

    if exact_categories:
        placeholders = ", ".join("?" for _ in exact_categories)
        category_parts.append(
            f"({category} IN ({placeholders}) "
            "OR list_has_any("
            "COALESCE(taxonomy.hierarchy, []::VARCHAR[]), ?::VARCHAR[]"
            "))"
        )
        category_parameters.extend(exact_categories)
        category_parameters.append(list(exact_categories))
    for pattern in category_patterns:
        category_parts.append(f"{category} ILIKE ?")
        category_parameters.append(pattern)

    country_clause = ""
    country_parameters: list[str] = []
    if country_code:
        country_clause = "AND addresses[1].country = ?"
        country_parameters.append(country_code)
    city_expression = "COALESCE(addresses[1].locality, ?)" if country_code else "?"

    query = f"""
        SELECT
            names.primary AS name,
            {city_expression} AS city,
            addresses[1].freeform AS address,
            array_to_string(phones, ', ') AS phone,
            array_to_string(websites, ', ') AS website,
            array_to_string(emails, ', ') AS email,
            {category} AS category,
            id AS overture_id,
            bbox.ymin AS latitude,
            bbox.xmin AS longitude,
            ? AS source_release,
            confidence AS _confidence
        FROM read_parquet(?)
        WHERE bbox.xmin BETWEEN ? AND ?
          AND bbox.ymin BETWEEN ? AND ?
          {country_clause}
          AND ({" OR ".join(category_parts)})
          AND COALESCE(operating_status, 'open') <> 'permanently_closed'
          AND names.primary IS NOT NULL
          AND trim(names.primary) <> ''
        ORDER BY
            CASE WHEN
                COALESCE(array_length(phones), 0)
                + COALESCE(array_length(websites), 0)
                + COALESCE(array_length(emails), 0) > 0
            THEN 0 ELSE 1 END,
            confidence DESC NULLS LAST,
            names.primary
        LIMIT ?
    """

    west, south, east, north = bounds
    parameters = [
        city,
        release,
        parquet_path,
        west,
        east,
        south,
        north,
        *country_parameters,
        *category_parameters,
        candidate_limit,
    ]
    cursor = connection.execute(query, parameters)
    columns = [item[0] for item in cursor.description]
    return [
        {
            column: value if value is not None else ""
            for column, value in zip(columns, row)
        }
        for row in cursor.fetchall()
    ]


def has_contact(lead: dict[str, Any]) -> bool:
    return bool(lead["phone"] or lead["website"] or lead["email"])


def deduplicate(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    for lead in leads:
        overture_id = str(lead["overture_id"]).strip()
        if overture_id:
            key = ("id", overture_id)
        else:
            key = (
                "fallback",
                normalize_text(str(lead["name"])),
                normalize_text(str(lead["address"])),
                normalize_text(str(lead["phone"])),
            )
        if key not in seen:
            seen.add(key)
            unique.append(lead)
    return unique


def select_leads(leads: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    leads.sort(
        key=lambda lead: (
            not has_contact(lead),
            -float(lead["_confidence"] or 0),
            normalize_text(str(lead["name"])),
        )
    )
    return leads[:limit]


def write_csv(leads: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)


def print_statistics(leads: list[dict[str, Any]], output: Path, release: str) -> None:
    with_phone = sum(bool(lead["phone"]) for lead in leads)
    with_website = sum(bool(lead["website"]) for lead in leads)
    with_email = sum(bool(lead["email"]) for lead in leads)
    with_any_contact = sum(has_contact(lead) for lead in leads)

    print(f"\nOverture release: {release}")
    print(f"CSV: {output}")
    print("Статистика:")
    print(f"  Знайдено: {len(leads)}")
    print(f"  Із телефоном: {with_phone}")
    print(f"  Із сайтом: {with_website}")
    print(f"  Із email: {with_email}")
    print(f"  Із хоча б одним контактом: {with_any_contact}")


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("limit must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect company leads from Overture Maps Places into CSV."
    )
    parser.add_argument("--niche", required=True, help="Niche text or category code")
    parser.add_argument(
        "--cities",
        required=True,
        help='One city, comma-separated cities, or "Вся Україна"',
    )
    parser.add_argument("--limit", required=True, type=positive_int)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        cities = parse_cities(args.cities)
        exact_categories, category_patterns = niche_filter(args.niche)
        release = latest_release()
        candidate_limit = max(args.limit * 3, 100)
        all_leads: list[dict[str, Any]] = []

        connection = open_overture()
        try:
            for index, city in enumerate(cities):
                print(f"Пошук: {city}...")
                if is_ukraine_scope(city):
                    bounds = UKRAINE_BOUNDS
                    country_code = UKRAINE_COUNTRY_CODE
                else:
                    bounds = geocode_city(city)
                    country_code = None
                all_leads.extend(
                    fetch_places(
                        connection,
                        release,
                        city,
                        bounds,
                        exact_categories,
                        category_patterns,
                        candidate_limit,
                        country_code=country_code,
                    )
                )
                if index < len(cities) - 1:
                    time.sleep(1)
        finally:
            connection.close()

        leads = select_leads(deduplicate(all_leads), args.limit)
        write_csv(leads, args.output)
        print_statistics(leads, args.output, release)
        coverage_warning = niche_coverage_warning(args.niche)
        if coverage_warning:
            print(f"\n{coverage_warning}")
        return 0
    except (duckdb.Error, OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
