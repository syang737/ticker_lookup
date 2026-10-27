"""Append ticker and previous close to every row of an uploaded CSV.

The original columns pass through untouched; every row gets a status, so a
row that could not be priced says why instead of disappearing.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .cache import FigiCache
from .identifiers import CUSIP, classify
from .massive import Massive
from .openfigi import OpenFigi

ID_HEADERS = ("cusip", "isin", "ticker", "symbol", "identifier", "security id", "security")
OUT_COLUMNS = ["lookup_ticker", "close", "close_date", "lookup_status", "lookup_name", "lookup_figi"]


class InputError(ValueError):
    """The upload cannot be processed at all; the message is for the user."""


@dataclass
class Summary:
    rows: int
    priced: int
    column: str
    close_date: date
    statuses: Counter = field(default_factory=Counter)


def decode(data: bytes) -> str:
    # utf-8-sig: Excel's "CSV UTF-8" starts with a byte-order mark.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Plain "CSV" from Windows Excel.
        return data.decode("cp1252")


def detect_column(header: list[str], rows: list[list[str]]) -> int:
    lowered = [h.strip().lower() for h in header]
    for name in ID_HEADERS:
        for i, h in enumerate(lowered):
            if h == name or h.startswith(name):
                return i
    # No telling header: the column where most values look like identifiers.
    sample = rows[:200]
    scores = [sum(1 for r in sample if i < len(r) and classify(r[i])[1] not in (None, "TICKER")) for i in range(len(header))]
    if not scores or max(scores) == 0:
        raise InputError("No column of CUSIPs or ISINs found. Name the column 'CUSIP', 'ISIN' or 'Ticker'.")
    return scores.index(max(scores))


def massive_ticker(row: dict) -> str | None:
    # Massive prices equities only; a bond's FIGI "ticker" is a description.
    if row.get("marketSector") != "Equity" or not row.get("ticker"):
        return None
    # OpenFIGI writes share classes as BRK/B; Massive as BRK.B.
    return row["ticker"].replace("/", ".")


def choose(value: str, rows: list[dict], closes: dict[str, float]) -> tuple[dict | None, str | None, str]:
    """(chosen FIGI row, Massive ticker, status) for one identifier's matches."""
    if not rows:
        if value[3:6] in ("ESC", "CVR", "CNT"):
            return None, None, "not found (escrow / CVR placeholder)"
        return None, None, "not found"
    us = [r for r in rows if r.get("exchCode") == "US"]
    if not us:
        if len(rows) == 1 and not rows[0].get("exchCode"):
            r = rows[0]
            return r, None, f"not priceable ({r.get('marketSector')} {r.get('securityType')})"
        # Usually an old CUSIP after a corporate action: only foreign venues
        # remain, and their tickers (BZHGBP) would price something else.
        return rows[0], None, "no US listing"
    tradable = [(r, t) for r in us if (t := massive_ticker(r))]
    if not tradable:
        r = us[0]
        return r, None, f"not priceable ({r.get('marketSector')} {r.get('securityType')})"
    # A closed-end fund also maps to its NAV symbol, which never trades:
    # the candidate with a close is the listing.
    priced = [(r, t) for r, t in tradable if t in closes]
    if not priced:
        r, t = tradable[0]
        return r, t, "no close"
    r, t = priced[0]
    return r, t, "ok" if len(priced) == 1 else f"ok, ambiguous ({', '.join(t for _, t in priced)})"


def enrich(
    data: bytes,
    figi: OpenFigi,
    massive: Massive,
    cache: FigiCache | None = None,
) -> tuple[bytes, Summary]:
    rows = list(csv.reader(io.StringIO(decode(data))))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise InputError("The file needs a header row and at least one data row.")
    header, body = rows[0], rows[1:]
    col = detect_column(header, body)

    classified = [classify(r[col] if col < len(r) else "") for r in body]
    keys = list(dict.fromkeys((v, k) for v, k, _ in classified if k))

    found = cache.get_many(keys) if cache else {}
    missing = [k for k in keys if k not in found]
    if missing:
        fresh = figi.map(missing)
        if cache:
            cache.put_many(fresh)
        found.update(fresh)

    close_date, closes = massive.previous_closes()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header + OUT_COLUMNS)
    summary = Summary(rows=len(body), priced=0, column=header[col], close_date=close_date)
    for r, (value, kind, note) in zip(body, classified):
        if kind is None:
            match, ticker, status = None, None, f"invalid: {note}"
        else:
            match, ticker, status = choose(value if kind == CUSIP else "", found[(value, kind)], closes)
            if note:
                status += f", {note}"
        close = closes.get(ticker) if ticker else None
        summary.priced += close is not None
        summary.statuses[status.split(" (")[0].split(",")[0]] += 1
        w.writerow(r + [
            ticker or "",
            str(close) if close is not None else "",
            close_date.isoformat() if close is not None else "",
            status,
            (match or {}).get("name") or "",
            (match or {}).get("compositeFIGI") or "",
        ])
    # utf-8-sig so Excel reads the names correctly, on Windows too.
    return out.getvalue().encode("utf-8-sig"), summary
