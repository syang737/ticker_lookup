"""Classify and validate CUSIPs, ISINs and tickers.

Requests arrive from spreadsheets, so the damage Excel does is handled here:
leading zeros stripped from CUSIPs (repaired when the check digit agrees) and
CUSIPs turned into scientific notation (unrecoverable, and named as such).
"""

from __future__ import annotations

import re

CUSIP_RE = re.compile(r"^[0-9A-Z*@#]{8}[0-9]$")
ISIN_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{9}[0-9]$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")
SCI_RE = re.compile(r"^\d(\.\d+)?E\+\d+$")

CUSIP, ISIN, TICKER = "CUSIP", "ISIN", "TICKER"


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - ord("A") + 10
    return {"*": 36, "@": 37, "#": 38}[c]


def cusip_valid(s: str) -> bool:
    total = 0
    for i, c in enumerate(s[:8]):
        v = _char_value(c)
        if i % 2:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(s[8])


def isin_valid(s: str) -> bool:
    # Letters expand to two digits, then Luhn over the whole string.
    digits = "".join(str(_char_value(c)) for c in s[:11]) + s[11]
    total = 0
    for i, d in enumerate(reversed(digits)):
        v = int(d)
        if i % 2:
            v *= 2
        total += v // 10 + v % 10
    return total % 10 == 0


def classify(raw: str) -> tuple[str, str | None, str]:
    """(normalised id, kind or None if unusable, note for the status column)."""
    s = raw.strip().upper()
    # Excel drops a CUSIP's leading zeros; the check digit says when padding is right.
    if s.isdigit() and 6 <= len(s) < 9 and cusip_valid(s.zfill(9)):
        return s.zfill(9), CUSIP, "zero-padded"
    if ISIN_RE.match(s):
        return (s, ISIN, "") if isin_valid(s) else (s, None, "bad ISIN check digit")
    if CUSIP_RE.match(s):
        return (s, CUSIP, "") if cusip_valid(s) else (s, None, "bad CUSIP check digit")
    if SCI_RE.match(s):
        # 78471E109 opened in Excel; the digits are gone for good.
        return s, None, "Excel scientific notation, re-export as text"
    if TICKER_RE.match(s):
        return s, TICKER, ""
    return s, None, "not a CUSIP, ISIN or ticker" if s else "blank"
