"""Small Overture Places data-quality test for car services in Chernihiv.

Dependency:
    python -m pip install duckdb
"""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

import duckdb

STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"

# A compact bounding box around Chernihiv, including the city's industrial edges.
WEST, SOUTH, EAST, NORTH = 31.20, 51.43, 31.40, 51.57

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


def latest_release() -> str:
    request = Request(STAC_CATALOG, headers={"User-Agent": "overture-chernihiv-test/1.0"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)["latest"]

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise RuntimeError(f"Unexpected Overture release name: {release!r}")
    return release


def fetch_places(release: str) -> list[dict[str, str]]:
    parquet_path = (
        "s3://overturemaps-us-west-2/release/"
        f"{release}/theme=places/type=place/*"
    )
    placeholders = ", ".join("?" for _ in CAR_SERVICE_CATEGORIES)

    query = f"""
        SELECT
            names.primary AS name,
            addresses[1].freeform AS address,
            array_to_string(phones, ', ') AS phone,
            array_to_string(websites, ', ') AS website,
            array_to_string(emails, ', ') AS email,
            COALESCE(categories.primary, basic_category) AS category,
            id AS overture_id
        FROM read_parquet(?)
        WHERE bbox.xmin BETWEEN ? AND ?
          AND bbox.ymin BETWEEN ? AND ?
          AND COALESCE(categories.primary, basic_category) IN ({placeholders})
          AND COALESCE(operating_status, 'open') <> 'permanently_closed'
          AND names.primary IS NOT NULL
        ORDER BY confidence DESC NULLS LAST, names.primary
        LIMIT 20
    """

    connection = duckdb.connect()
    try:
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        parameters = [
            parquet_path,
            WEST,
            EAST,
            SOUTH,
            NORTH,
            *CAR_SERVICE_CATEGORIES,
        ]
        cursor = connection.execute(query, parameters)
        columns = [item[0] for item in cursor.description]
        return [
            {column: value or "" for column, value in zip(columns, row)}
            for row in cursor.fetchall()
        ]
    finally:
        connection.close()


def print_places(places: list[dict[str, str]], release: str) -> None:
    print(f"Overture release: {release}")
    print(f"Знайдено автосервісів: {len(places)}\n")

    for number, place in enumerate(places, start=1):
        print(f"{number}. {place['name']}")
        print(f"   Адреса: {place['address'] or '—'}")
        print(f"   Телефон: {place['phone'] or '—'}")
        print(f"   Сайт: {place['website'] or '—'}")
        print(f"   Email: {place['email'] or '—'}")
        print(f"   Категорія: {place['category'] or '—'}")
        print(f"   Overture ID: {place['overture_id']}")

    with_phone = sum(bool(place["phone"]) for place in places)
    with_website = sum(bool(place["website"]) for place in places)
    with_any_contact = sum(
        bool(place["phone"] or place["website"] or place["email"])
        for place in places
    )

    print("\nСтатистика:")
    print(f"  Компаній знайдено: {len(places)}")
    print(f"  Є телефон: {with_phone}")
    print(f"  Є сайт: {with_website}")
    print(f"  Є хоча б один контакт: {with_any_contact}")


def main() -> None:
    release = latest_release()
    places = fetch_places(release)
    print_places(places, release)


if __name__ == "__main__":
    main()
