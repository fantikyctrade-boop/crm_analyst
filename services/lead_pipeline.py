"""Non-blocking orchestration of the existing collector and scorer modules."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lead_collector as collector
import lead_scorer as scorer


class SearchAlreadyRunningError(RuntimeError):
    """Raised when a user attempts to start a second simultaneous search."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    user_id: int
    niche: str
    cities: tuple[str, ...]
    requested_limit: int
    source_release: str
    rows: tuple[dict[str, str], ...]
    csv_path: Path
    run_dir: Path
    high: int
    medium: int
    low: int

    @property
    def total(self) -> int:
        return len(self.rows)


class LeadPipeline:
    """Run collection and scoring in a worker thread and manage run files."""

    def __init__(self, temp_root: Path | None = None) -> None:
        self.temp_root = temp_root or (
            Path(tempfile.gettempdir()) / "overture_lead_bot_runs"
        )
        self._running_users: set[int] = set()
        self._sessions: dict[int, SearchResult] = {}
        self._state_lock = asyncio.Lock()
        self._geocode_lock = threading.Lock()
        self._last_geocode_at = 0.0

    async def is_running(self, user_id: int) -> bool:
        async with self._state_lock:
            return user_id in self._running_users

    def get_result(self, user_id: int) -> SearchResult | None:
        return self._sessions.get(user_id)

    async def run(
        self, user_id: int, niche: str, cities: list[str], limit: int
    ) -> SearchResult:
        async with self._state_lock:
            if user_id in self._running_users:
                raise SearchAlreadyRunningError(
                    "Для цього користувача пошук уже виконується."
                )
            self._running_users.add(user_id)

        try:
            result = await asyncio.to_thread(
                self._run_sync, user_id, niche, cities, limit
            )
            previous = self._sessions.get(user_id)
            self._sessions[user_id] = result
            if previous and previous.run_dir != result.run_dir:
                shutil.rmtree(previous.run_dir, ignore_errors=True)
            return result
        finally:
            async with self._state_lock:
                self._running_users.discard(user_id)

    def _geocode_city(self, city: str) -> tuple[float, float, float, float]:
        # The public Nominatim policy permits at most one request per second.
        with self._geocode_lock:
            delay = 1.0 - (time.monotonic() - self._last_geocode_at)
            if delay > 0:
                time.sleep(delay)
            bounds = collector.geocode_city(city)
            self._last_geocode_at = time.monotonic()
            return bounds

    def _run_sync(
        self, user_id: int, niche: str, cities: list[str], limit: int
    ) -> SearchResult:
        run_dir = self.temp_root / str(user_id) / uuid.uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        raw_csv = run_dir / "leads.csv"
        scored_csv = run_dir / "scored_leads.csv"

        try:
            parsed_cities = collector.parse_cities(",".join(cities))
            exact_categories, category_patterns = collector.niche_filter(niche)
            release = collector.latest_release()
            candidate_limit = max(limit * 3, 100)
            all_leads: list[dict[str, Any]] = []

            connection = collector.open_overture()
            try:
                for city in parsed_cities:
                    if collector.is_ukraine_scope(city):
                        bounds = collector.UKRAINE_BOUNDS
                        country_code = collector.UKRAINE_COUNTRY_CODE
                    else:
                        bounds = self._geocode_city(city)
                        country_code = None
                    all_leads.extend(
                        collector.fetch_places(
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
            finally:
                connection.close()

            leads = collector.select_leads(
                collector.deduplicate(all_leads), limit
            )
            collector.write_csv(leads, raw_csv)

            scored_rows, fieldnames = scorer.read_and_score(raw_csv)
            scorer.write_scored(scored_csv, scored_rows, fieldnames)
            raw_csv.unlink(missing_ok=True)

            counts = Counter(row["priority"] for row in scored_rows)
            return SearchResult(
                user_id=user_id,
                niche=niche,
                cities=tuple(parsed_cities),
                requested_limit=limit,
                source_release=release,
                rows=tuple(scored_rows),
                csv_path=scored_csv,
                run_dir=run_dir,
                high=counts["HIGH"],
                medium=counts["MEDIUM"],
                low=counts["LOW"],
            )
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise

    def cleanup_all(self) -> None:
        self._sessions.clear()
        shutil.rmtree(self.temp_root, ignore_errors=True)
