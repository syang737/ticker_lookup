"""Previous-close prices from Massive's grouped daily aggregates.

One call returns every US ticker's bar for a date, so pricing costs the same
for five rows or five thousand.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.massive.com"
EASTERN = ZoneInfo("America/New_York")


def last_session_candidates(now: datetime) -> list[date]:
    """Dates to try, newest first.

    Today counts only once the evening session is over, so a run during market
    hours never picks up a partial bar. Weekends and holidays come back empty
    and are walked past.
    """
    now = now.astimezone(EASTERN)
    start = now.date() if now.hour >= 20 else now.date() - timedelta(days=1)
    return [start - timedelta(days=i) for i in range(10)]


class Massive:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url=BASE,
            timeout=60,
            # Header auth, so the key never lands in a URL or a log line.
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._by_day: dict[date, dict[str, float]] = {}

    def grouped(self, day: date) -> dict[str, float]:
        if day not in self._by_day:
            resp = self.client.get(
                f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
                # Unadjusted: the price the security actually closed at.
                params={"adjusted": "false", "include_otc": "true"},
            )
            resp.raise_for_status()
            body = resp.json()
            closes = {r["T"]: r["c"] for r in body.get("results") or []}
            # An empty day may still fill in later; only cache real sessions.
            if not closes:
                return closes
            self._by_day[day] = closes
        return self._by_day[day]

    def previous_closes(self, now: datetime | None = None) -> tuple[date, dict[str, float]]:
        for day in last_session_candidates(now or datetime.now(EASTERN)):
            if closes := self.grouped(day):
                return day, closes
        raise RuntimeError("Massive returned no trading session in the last 10 days")
