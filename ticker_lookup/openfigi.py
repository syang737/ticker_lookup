"""Batched identifier mapping through OpenFIGI's /v3/mapping."""

from __future__ import annotations

import time

import httpx

MAPPING_URL = "https://api.openfigi.com/v3/mapping"

ID_TYPES = {"CUSIP": "ID_CUSIP", "ISIN": "ID_ISIN", "TICKER": "TICKER", "CINS": "ID_CINS"}


def _job(value: str, kind: str) -> dict:
    j = {"idType": ID_TYPES[kind], "idValue": value}
    if kind == "TICKER":
        # Bare tickers are ambiguous worldwide; we only price US listings.
        j["exchCode"] = "US"
    return j


class OpenFigi:
    def __init__(self, api_key: str | None, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        # 100 jobs per request with a key, 10 without.
        self.batch = 100 if api_key else 10
        self.client = client or httpx.Client(timeout=60)

    def _post(self, jobs: list[dict]) -> list[dict]:
        headers = {"X-OPENFIGI-APIKEY": self.api_key} if self.api_key else {}
        for attempt in range(5):
            resp = self.client.post(MAPPING_URL, json=jobs, headers=headers)
            if resp.status_code != 429 or attempt == 4:
                resp.raise_for_status()
                return resp.json()
            time.sleep(int(resp.headers.get("ratelimit-reset") or 2**attempt * 3))
        raise AssertionError("unreachable")

    def map(self, ids: list[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
        """{(value, kind): matching rows}; an empty list means not found."""
        out: dict[tuple[str, str], list[dict]] = {}
        for start in range(0, len(ids), self.batch):
            chunk = ids[start : start + self.batch]
            for key, res in zip(chunk, self._post([_job(*k) for k in chunk])):
                out[key] = res.get("data") or []
            if not self.api_key and start + self.batch < len(ids):
                time.sleep(2.5)  # 25 requests/minute unauthenticated

        # CINS -- a CUSIP for a non-US issuer, starting with a letter -- is its
        # own idType at OpenFIGI, and comes back not found as a CUSIP.
        cins = [v for (v, k), rows in out.items() if k == "CUSIP" and not rows and v[0].isalpha()]
        if cins:
            for (v, _), rows in self.map([(v, "CINS") for v in cins]).items():
                out[(v, "CUSIP")] = rows
        return out
