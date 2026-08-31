"""Score leads from a CSV file using simple, deterministic rules."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

SOCIAL_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "t.me",
    "telegram.me",
    "telegram.org",
)

INSTAGRAM_DOMAINS = ("instagram.com",)
SOCIAL_ONLY_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.com",
    "fb.me",
    "tiktok.com",
    "t.me",
    "telegram.me",
    "telegram.org",
)

LEAD_TYPES = (
    "NO_WEBSITE",
    "INSTAGRAM_ONLY",
    "GOOGLE_MAPS_ONLY",
    "BUSINESS_SITE",
    "SOCIAL_ONLY",
    "HTTP_WEBSITE",
    "MODERN_WEBSITE",
    "UNKNOWN",
)

RECOMMENDED_OFFERS = {
    "NO_WEBSITE": "Новий сайт із онлайн-записом",
    "INSTAGRAM_ONLY": "Сайт як доповнення до Instagram",
    "GOOGLE_MAPS_ONLY": "Лендінг + онлайн-запис",
    "BUSINESS_SITE": "Перехід на повноцінний сайт",
    "SOCIAL_ONLY": "Сайт із SEO та формою запису",
    "HTTP_WEBSITE": "Оновлення сайту та HTTPS",
    "MODERN_WEBSITE": "Автоматизація запису або AI",
    "UNKNOWN": "Потрібна ручна перевірка",
}

FREE_SITE_DOMAINS = (
    "business.site",
    "wixsite.com",
    "wordpress.com",
    "weebly.com",
    "webnode.com",
    "webnode.page",
    "ucoz.com",
    "ucoz.net",
    "jimdosite.com",
    "strikingly.com",
    "tilda.ws",
    "site123.me",
)

PERSONAL_EMAIL_DOMAINS = ("gmail.com", "ukr.net", "i.ua", "outlook.com")
LARGE_BUSINESS_MARKERS = (
    "VIDI",
    "Toyota",
    "Renault",
    "Hyundai",
    "Mazda",
    "Bosch",
    "Goodyear",
    "Volkswagen",
    "ATL",
    "Oiler",
)
PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def split_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;\n]+", value) if item.strip()]


def hostname(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.hostname or "").casefold().removeprefix("www.")


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def is_google_maps_url(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()
    if host == "maps.app.goo.gl" or host == "maps.google.com":
        return True
    if host == "goo.gl" and path.startswith("/maps"):
        return True
    return domain_matches(host, "google.com") and path.startswith("/maps")


def lead_type_for(website: str) -> str:
    websites = split_values(website)
    if not websites:
        return "NO_WEBSITE"

    hosts = [hostname(url) for url in websites]
    if all(
        any(domain_matches(host, domain) for domain in INSTAGRAM_DOMAINS)
        for host in hosts
    ):
        return "INSTAGRAM_ONLY"
    if all(is_google_maps_url(url) for url in websites):
        return "GOOGLE_MAPS_ONLY"
    if any(domain_matches(host, "business.site") for host in hosts):
        return "BUSINESS_SITE"

    social_domains = (*INSTAGRAM_DOMAINS, *SOCIAL_ONLY_DOMAINS)
    if all(
        any(domain_matches(host, domain) for domain in social_domains) for host in hosts
    ):
        return "SOCIAL_ONLY"
    if any(url.casefold().startswith("http://") for url in websites):
        return "HTTP_WEBSITE"

    has_normal_https = any(
        url.casefold().startswith("https://")
        and not is_google_maps_url(url)
        and not any(domain_matches(hostname(url), domain) for domain in social_domains)
        for url in websites
    )
    if has_normal_https:
        return "MODERN_WEBSITE"
    return "UNKNOWN"


def is_social_or_maps(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()

    if any(domain_matches(host, domain) for domain in SOCIAL_DOMAINS):
        return True
    if host == "maps.app.goo.gl" or host == "maps.google.com":
        return True
    return domain_matches(host, "google.com") and path.startswith("/maps")


def is_free_site_builder(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"//{url}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if any(domain_matches(host, domain) for domain in FREE_SITE_DOMAINS):
        return True
    return host == "sites.google.com"


def has_personal_email(value: str) -> bool:
    for email in split_values(value):
        _, separator, domain = email.rpartition("@")
        if separator and domain.casefold() in PERSONAL_EMAIL_DOMAINS:
            return True
    return False


def find_large_business_marker(name: str) -> str | None:
    for marker in LARGE_BUSINESS_MARKERS:
        pattern = rf"(?<!\w){re.escape(marker)}(?!\w)"
        if re.search(pattern, name, flags=re.IGNORECASE):
            return marker
    return None


def priority_for(score: int) -> str:
    if score >= 5:
        return "HIGH"
    if score >= 2:
        return "MEDIUM"
    return "LOW"


def score_lead(row: dict[str, str]) -> dict[str, str]:
    score = 0
    reasons: list[str] = []
    websites = split_values(row.get("website", "") or "")
    email = row.get("email", "") or ""
    name = row.get("name", "") or ""

    if not websites:
        score += 5
        reasons.append("+5: немає website")
    else:
        if any(is_social_or_maps(url) for url in websites):
            score += 4
            reasons.append("+4: website веде на соцмережу або Google Maps")
        if any(url.casefold().startswith("http://") for url in websites):
            score += 2
            reasons.append("+2: website використовує http://")
        if any(is_free_site_builder(url) for url in websites):
            score += 3
            reasons.append("+3: сайт на безкоштовному конструкторі")

    if has_personal_email(email):
        score += 1
        reasons.append("+1: email на загальнодоступному сервісі")

    marker = find_large_business_marker(name)
    if marker:
        score -= 5
        reasons.append(f"-5: ознака великого бізнесу ({marker})")

    scored = dict(row)
    lead_type = lead_type_for(row.get("website", "") or "")
    scored["score"] = str(score)
    scored["priority"] = priority_for(score)
    scored["score_reasons"] = " | ".join(reasons) if reasons else "Немає факторів"
    scored["lead_type"] = lead_type
    scored["recommended_offer"] = RECOMMENDED_OFFERS[lead_type]
    return scored


def read_and_score(input_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header.")
        fieldnames = list(reader.fieldnames)
        rows = [score_lead(dict(row)) for row in reader]

    for field in (
        "score",
        "priority",
        "score_reasons",
        "lead_type",
        "recommended_offer",
    ):
        if field not in fieldnames:
            fieldnames.append(field)

    rows.sort(
        key=lambda row: (
            PRIORITY_ORDER[row["priority"]],
            -int(row["score"]),
            (row.get("name") or "").casefold(),
        )
    )
    return rows, fieldnames


def write_scored(
    output_path: Path, rows: list[dict[str, str]], fieldnames: list[str]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_results(rows: list[dict[str, str]], output_path: Path) -> None:
    counts = Counter(row["priority"] for row in rows)
    print(f"Створено: {output_path}")
    print("Статистика:")
    print(f"  HIGH: {counts['HIGH']}")
    print(f"  MEDIUM: {counts['MEDIUM']}")
    print(f"  LOW: {counts['LOW']}")

    lead_type_counts = Counter(row["lead_type"] for row in rows)
    print("\nСтатистика за lead_type:")
    for lead_type in LEAD_TYPES:
        print(f"  {lead_type}: {lead_type_counts[lead_type]}")

    print("\nПерші 15 компаній із HIGH:")
    high_rows = [row for row in rows if row["priority"] == "HIGH"][:15]
    if not high_rows:
        print("  Немає компаній із пріоритетом HIGH.")
        return

    for number, row in enumerate(high_rows, start=1):
        print(
            f"  {number}. {row.get('name') or '—'} "
            f"({row.get('city') or '—'}) — score {row['score']}"
        )
        print(f"     {row['score_reasons']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score an existing lead CSV using deterministic rules."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output files must be different.")
        rows, fieldnames = read_and_score(args.input)
        write_scored(args.output, rows, fieldnames)
        print_results(rows, args.output)
        return 0
    except (OSError, ValueError, csv.Error) as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
