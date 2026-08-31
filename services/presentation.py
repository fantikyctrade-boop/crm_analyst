"""Formatting and pagination for Telegram result messages."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from urllib.parse import urlparse

from .instagram_enrichment import InstagramStatus
from .lead_pipeline import SearchResult

PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class Page:
    text: str
    number: int
    total_pages: int


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _short(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _safe_link(url: str) -> str:
    value = _clean(url)
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed.geturl()


def _company_text(row: dict[str, str], number: int) -> str:
    name = html.escape(_short(_clean(row.get("name")) or "—", 100))
    country = html.escape(_short(_clean(row.get("country")) or "—", 40))
    region = html.escape(_short(_clean(row.get("region")) or "—", 60))
    city = html.escape(_short(_clean(row.get("city")) or "—", 60))
    phone = html.escape(_short(_clean(row.get("phone")) or "—", 100))
    email_value = _clean(row.get("email")).split(",", maxsplit=1)[0].strip()
    website_value = _clean(row.get("website")).split(",", maxsplit=1)[0].strip()
    score = html.escape(_clean(row.get("score")) or "0")
    lead_type = html.escape(_clean(row.get("lead_type")) or "UNKNOWN")
    recommended_offer = html.escape(
        _short(
            _clean(row.get("recommended_offer")) or "Потрібна ручна перевірка",
            120,
        )
    )
    reasons = html.escape(
        _short(_clean(row.get("score_reasons")) or "Немає факторів", 280)
    )

    email = html.escape(_short(email_value, 100) or "—")
    if email_value:
        email = f'<a href="mailto:{html.escape(email_value, quote=True)}">{email}</a>'

    website = html.escape(_short(website_value, 100) or "—")
    safe_website = _safe_link(website_value)
    if safe_website:
        website = f'<a href="{html.escape(safe_website, quote=True)}">{website}</a>'

    instagram = ""
    instagram_username = _clean(row.get("instagram_username"))
    if instagram_username:
        escaped_username = html.escape(instagram_username)
        profile_url = f"https://www.instagram.com/{instagram_username}/"
        instagram = (
            f'Instagram: <a href="{html.escape(profile_url, quote=True)}">'
            f"@{escaped_username}</a>"
        )
        if row.get("instagram_status") == InstagramStatus.FOUND.value:
            followers_value = _clean(row.get("instagram_followers"))
            try:
                followers_count = int(followers_value)
            except ValueError:
                followers_count = None
            if followers_count is not None and followers_count >= 0:
                formatted_followers = f"{followers_count:,}".replace(",", " ")
                instagram += f"\nПідписники: {formatted_followers}"

    return (
        f"<b>{number}. {name}</b>\n"
        f"Країна / регіон: {country} / {region}\n"
        f"Місто: {city}\n"
        f"Телефон: {phone}\n"
        f"Сайт: {website}\n"
        f"{instagram + chr(10) if instagram else ''}"
        f"Email: {email}\n"
        f"Score: <b>{score}</b>\n"
        f"Тип ліда: <code>{lead_type}</code>\n"
        f"Пропозиція: {recommended_offer}\n"
        f"Причини: {reasons}"
    )


def make_page(
    result: SearchResult,
    page: int,
    high_only: bool,
    lead_type: str | None = None,
) -> Page:
    rows = [
        row
        for row in result.rows
        if (not high_only or row["priority"] == "HIGH")
        and (lead_type is None or row.get("lead_type") == lead_type)
    ]
    total_pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = rows[start : start + PAGE_SIZE]
    priority_label = "HIGH" if high_only else "усі пріоритети"
    type_label = lead_type or "усі типи"

    header = (
        "<b>Результати пошуку</b>\n"
        f"Всього: <b>{result.total}</b> | HIGH: <b>{result.high}</b> | "
        f"MEDIUM: <b>{result.medium}</b> | LOW: <b>{result.low}</b>\n"
        f"Фільтр: {priority_label} · {type_label} | "
        f"Сторінка {page + 1}/{total_pages}"
    )
    if not chunk:
        return Page(f"{header}\n\nКомпаній за цим фільтром немає.", page, total_pages)

    companies = [
        _company_text(row, start + index + 1) for index, row in enumerate(chunk)
    ]
    return Page(f"{header}\n\n" + "\n\n".join(companies), page, total_pages)
