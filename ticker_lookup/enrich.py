"""Append ticker and previous close to every row of an uploaded CSV or .xlsx.

The original columns pass through untouched; every row gets a status, so a
row that could not be priced says why instead of disappearing. The result is
written as .xlsx by default: opened in Excel, a CSV loses CUSIPs to scientific
notation (78471E109) and leading zeros, and only a typed cell prevents that.

A file that went through Excel before it reached us may already be damaged,
and scientific notation cannot be undone: Excel keeps only the digits it
displays, so 9.29E+211 fits a dozen valid CUSIPs. When the row also has an
ISIN, a US or Canadian one carries the CUSIP intact in characters 3-11 -- and
only those CUSIPs are all digits but for an E, so only those are ever damaged.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .cache import FigiCache
from .identifiers import CUSIP, ISIN, TICKER, classify, cusip_valid
from .massive import Massive
from .openfigi import OpenFigi

# Identifier columns by header, in the order a row's values are tried.
ID_HEADERS = (("cusip",), ("isin",), ("ticker", "symbol"), ("identifier", "security id", "security"))
OUT_COLUMNS = ["lookup_cusip", "lookup_ticker", "close", "close_date", "lookup_status", "lookup_name", "lookup_figi"]

MAX_ROWS = 100_000


class InputError(ValueError):
    """The upload cannot be processed at all; the message is for the user."""


@dataclass
class Table:
    header: list[str]
    # Original cells are strings; close is a float and close_date a date.
    rows: list[list]
    id_cols: list[int]


@dataclass
class Summary:
    rows: int
    priced: int
    columns: list[str]
    close_date: date
    statuses: Counter = field(default_factory=Counter)
    # Notes on identifiers that were looked up anyway: repairs and warnings.
    repairs: Counter = field(default_factory=Counter)


def decode(data: bytes) -> str:
    # utf-8-sig: Excel's "CSV UTF-8" starts with a byte-order mark.
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Plain "CSV" from Windows Excel.
        return data.decode("cp1252")


def read_rows(data: bytes) -> list[list[str]]:
    if data[:4] == b"PK\x03\x04":
        return _xlsx_rows(data)
    return list(csv.reader(io.StringIO(decode(data))))


def _xlsx_rows(data: bytes) -> list[list[str]]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise InputError(f"Could not read the Excel file ({e.__class__.__name__}).") from e
    try:
        # The first sheet; a workbook of several is usually one list plus notes.
        ws = wb.worksheets[0]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([_text(v) for v in row])
            if len(rows) > MAX_ROWS + 1:
                break
        return rows
    finally:
        wb.close()


def _text(v) -> str:
    """A cell as the text it would have in a CSV."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        # A CUSIP Excel took for a number: 20398707 (zeros lost, padded back
        # later) or 4.701e+112 (scientific notation, reported as such).
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0) else v.isoformat(sep=" ")
    if isinstance(v, (date, time)):
        return v.isoformat()
    return str(v)


def detect_columns(header: list[str], rows: list[list[str]]) -> list[int]:
    """Identifier columns, in the order to try them for each row."""
    lowered = [h.strip().lower() for h in header]
    cols: list[int] = []
    for names in ID_HEADERS:
        cols += [i for i, h in enumerate(lowered) if i not in cols and any(h.startswith(n) for n in names)]
    if cols:
        return cols
    # No telling header: the column where most values look like identifiers.
    sample = rows[:200]
    scores = [sum(1 for r in sample if i < len(r) and classify(r[i])[1] not in (None, TICKER)) for i in range(len(header))]
    if not scores or max(scores) == 0:
        raise InputError("No column of CUSIPs or ISINs found. Name the column 'CUSIP', 'ISIN' or 'Ticker'.")
    return [scores.index(max(scores))]


@dataclass
class RowId:
    """What one row is looked up by, and the CUSIP it turns out to have."""

    value: str | None
    kind: str | None
    cusip: str | None
    notes: list[str]


def identify(row: list[str], cols: list[int], header: list[str]) -> RowId:
    found, problems = [], []
    for i in cols:
        value, kind, note = classify(row[i])
        if kind:
            found.append((value, kind, note, header[i]))
        elif row[i].strip():
            problems.append(f"{header[i]}: {note}" if len(cols) > 1 else note)

    cusips = [(v, n) for v, k, n, _ in found if k == CUSIP]
    # US and Canadian ISINs carry the CUSIP in characters 3-11.
    from_isin = next((v[2:11] for v, k, _, _ in found if k == ISIN and v[:2] in ("US", "CA") and cusip_valid(v[2:11])), None)

    if cusips:
        value, note = cusips[0]
        notes = [note] if note else []
        if from_isin and from_isin != value:
            notes.append(f"CUSIP and ISIN disagree (ISIN has {from_isin})")
        return RowId(value, CUSIP, value, notes)
    if from_isin:
        return RowId(from_isin, CUSIP, from_isin, ["CUSIP from ISIN"] if problems else [])
    if found:
        value, kind, note, column = found[0]
        notes = [note] if note else []
        if problems:
            # Say what it fell back to and why, or a miss looks like a bad symbol.
            notes.append(f"by {column} ({'; '.join(problems)})")
        return RowId(value, kind, None, notes)
    return RowId(None, None, None, problems or ["blank"])


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
) -> tuple[Table, Summary]:
    rows = [r for r in read_rows(data) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise InputError("The file needs a header row and at least one data row.")
    if len(rows) > MAX_ROWS + 1:
        raise InputError(f"The file has over {MAX_ROWS:,} rows; split it up.")
    width = max(len(r) for r in rows)
    # Pad ragged rows, so the appended columns line up under their headers.
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, body = rows[0], rows[1:]
    cols = detect_columns(header, body)

    ids = [identify(r, cols, header) for r in body]
    keys = list(dict.fromkeys((i.value, i.kind) for i in ids if i.kind))

    found = cache.get_many(keys) if cache else {}
    missing = [k for k in keys if k not in found]
    if missing:
        fresh = figi.map(missing)
        if cache:
            cache.put_many(fresh)
        found.update(fresh)

    close_date, closes = massive.previous_closes()

    table = Table(header=header + OUT_COLUMNS, rows=[], id_cols=cols)
    summary = Summary(rows=len(body), priced=0, columns=[header[c] for c in cols], close_date=close_date)
    for r, rid in zip(body, ids):
        if rid.kind is None:
            match, ticker, status = None, None, f"invalid: {'; '.join(rid.notes)}"
        else:
            match, ticker, status = choose(rid.value if rid.kind == CUSIP else "", found[(rid.value, rid.kind)], closes)
            if rid.notes:
                status += ", " + ", ".join(rid.notes)
                summary.repairs.update(n.split(" (")[0] for n in rid.notes)
        close = closes.get(ticker) if ticker else None
        summary.priced += close is not None
        summary.statuses[status.split(" (")[0].split(",")[0]] += 1
        table.rows.append(r + [
            rid.cusip or "",
            ticker or "",
            close,
            close_date if close is not None else None,
            status,
            (match or {}).get("name") or "",
            (match or {}).get("compositeFIGI") or "",
        ])
    return table, summary


def to_csv(table: Table) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(table.header)
    for r in table.rows:
        w.writerow(["" if v is None else v.isoformat() if isinstance(v, date) else str(v) for v in r])
    # utf-8-sig so Excel reads the names correctly, on Windows too.
    return out.getvalue().encode("utf-8-sig")


# Only values that survive the trip to a number and back unchanged become
# numbers: 0123 (an account), 1E5 or 12345678901234567 (past float precision)
# stay text.
NUMBER_RE = re.compile(r"^-?(0|[1-9]\d{0,14})(\.\d{1,15})?$")


def _cell(ws, value, text: bool = False) -> WriteOnlyCell:
    if isinstance(value, str) and not text and NUMBER_RE.match(value) and len(value) <= 16:
        value = float(value) if "." in value else int(value)
    cell = WriteOnlyCell(ws, value=value)
    if isinstance(value, str):
        # Without this, a value starting with "=" is written as a live formula.
        cell.data_type = "s"
        if text:
            cell.number_format = "@"
    elif isinstance(value, date):
        cell.number_format = "yyyy-mm-dd"
    return cell


def to_xlsx(table: Table) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Prices")
    ws.freeze_panes = "A2"
    for i, name in enumerate(table.header):
        width = max([len(name), *(len(str(r[i])) for r in table.rows[:200] if i < len(r))])
        ws.column_dimensions[get_column_letter(i + 1)].width = min(max(width + 2, 8), 45)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(table.header))}{len(table.rows) + 1}"

    bold = Font(bold=True)
    head = []
    for name in table.header:
        c = _cell(ws, name, text=True)
        c.font = bold
        head.append(c)
    ws.append(head)

    n_orig = len(table.header) - len(OUT_COLUMNS)
    # Text columns among those appended: everything but close and close_date.
    text_cols = set(table.id_cols) | {n_orig + i for i, c in enumerate(OUT_COLUMNS) if c not in ("close", "close_date")}
    for r in table.rows:
        ws.append([_cell(ws, v, text=i in text_cols) for i, v in enumerate(r)])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

