import csv
import io

import pytest
from conftest import FakeFigi

from ticker_lookup.cache import FigiCache
from ticker_lookup.enrich import InputError, enrich, to_csv

ROWS = [
    ("037833100", "100"),
    ("US0378331005", "5"),
    ("084670702", "10"),
    ("69355J104", "7"),
    ("91282CJL6", "1000"),
    ("46625H100", "3"),
    ("07556Q881", "1"),
    ("NVDA", "2"),
    ("37833100", "4"),
    ("037833101", "9"),
    ("7.8471E+109", "1"),
    ("682CVR055", "1"),
    ("12345678", "1"),
]


def run(figi, massive, rows=ROWS, header=("Security CUSIP", "Qty"), encoding="utf-8-sig", cache=None):
    buf = io.StringIO()
    csv.writer(buf).writerows([header, *rows])
    table, summary = enrich(buf.getvalue().encode(encoding), figi, massive, cache)
    return list(csv.DictReader(io.StringIO(to_csv(table).decode("utf-8-sig")))), summary


def test_every_row_comes_back_with_its_columns_and_a_status(figi, massive):
    rows, summary = run(figi, massive)
    by = {r["Security CUSIP"]: r for r in rows}
    assert len(rows) == len(ROWS)
    assert [r["Qty"] for r in rows] == [q for _, q in ROWS]

    assert (by["037833100"]["lookup_ticker"], by["037833100"]["close"]) == ("AAPL", "231.5")
    assert by["037833100"]["close_date"] == "2026-10-26"
    assert by["US0378331005"]["close"] == "231.5"
    assert (by["084670702"]["lookup_ticker"], by["084670702"]["close"]) == ("BRK.B", "470.12")
    assert by["NVDA"]["close"] == "180.0"
    assert by["37833100"]["lookup_status"] == "ok, zero-padded"

    assert summary.priced == 6
    assert summary.columns == ["Security CUSIP"]


def test_fund_resolves_to_the_listing_with_a_close_not_its_nav_symbol(figi, massive):
    rows, _ = run(figi, massive, rows=[("69355J104", "1")])
    assert (rows[0]["lookup_ticker"], rows[0]["lookup_status"]) == ("SDHY", "ok")


@pytest.mark.parametrize(
    "cusip, status",
    [
        ("91282CJL6", "not priceable (Govt US GOVERNMENT)"),
        ("46625H100", "not priceable (Pfd PUBLIC)"),
        ("07556Q881", "no US listing"),
        ("682CVR055", "not found (escrow / CVR placeholder)"),
        ("037833101", "invalid: bad CUSIP check digit"),
        ("7.8471E+109", "invalid: Excel scientific notation, re-export as text"),
    ],
)
def test_unpriced_rows_say_why(figi, massive, cusip, status):
    rows, _ = run(figi, massive)
    row = next(r for r in rows if r["Security CUSIP"] == cusip)
    assert row["lookup_status"] == status
    assert row["close"] == "" and row["lookup_ticker"] == ""


def test_identifiers_are_sent_once(figi, massive):
    run(figi, massive)
    sent = figi.calls[0]
    assert len(sent) == len(set(sent))
    assert ("037833100", "CUSIP") in sent


def test_column_found_by_content_when_the_header_says_nothing(figi, massive):
    rows, summary = run(figi, massive, rows=[("Apple", "037833100")], header=("Desc", "Code"))
    assert summary.columns == ["Code"]
    assert rows[0]["close"] == "231.5"


def test_windows_excel_csv_is_read(figi, massive):
    rows, _ = run(figi, massive, rows=[("037833100", "Société")], encoding="cp1252")
    assert rows[0]["Qty"] == "Société"


def test_cache_spares_openfigi_on_the_second_run(figi, massive, tmp_path):
    cache = FigiCache(tmp_path / "c.sqlite")
    run(figi, massive, cache=cache)
    again = FakeFigi()
    rows, _ = run(again, massive, cache=cache)
    # Only the misses, which expire sooner, may be asked again -- and they
    # have not expired yet.
    assert again.calls == []
    assert rows[0]["close"] == "231.5"


def test_no_identifier_column_is_a_user_error(figi, massive):
    with pytest.raises(InputError):
        run(figi, massive, rows=[("hello", "world")], header=("a", "b"))


# -- several identifier columns, as in a broker's order list -----------------

ORDERS_HEADER = ("Symbol", "ISIN", "CUSIP", "Qty")


def by_symbol(rows):
    return {r["Symbol"]: r for r in rows}


def test_cusip_excel_destroyed_is_taken_from_the_isin(figi, massive):
    # 037833100 shown as Excel would show a CUSIP like 47010E108: rounded.
    rows, summary = run(figi, massive, header=ORDERS_HEADER, rows=[("AAPL", "US0378331005", "4.70E+112", "5")])
    row = rows[0]
    assert (row["lookup_cusip"], row["lookup_ticker"], row["close"]) == ("037833100", "AAPL", "231.5")
    assert row["lookup_status"] == "ok, CUSIP from ISIN"
    assert row["CUSIP"] == "4.70E+112"  # the original column is left as it came
    assert summary.columns == ["CUSIP", "ISIN", "Symbol"]
    assert summary.repairs["CUSIP from ISIN"] == 1


def test_good_cusip_is_used_and_a_disagreeing_isin_flagged(figi, massive):
    rows, summary = run(figi, massive, header=ORDERS_HEADER, rows=[("AAPL", "US0846707026", "037833100", "1")])
    assert rows[0]["lookup_cusip"] == "037833100"
    assert rows[0]["lookup_status"] == "ok, CUSIP and ISIN disagree (ISIN has 084670702)"
    assert summary.repairs["CUSIP and ISIN disagree"] == 1


def test_foreign_isin_is_not_a_cusip_but_is_looked_up(figi, massive):
    figi_rows = {("GB0005405286", "ISIN"): [{"exchCode": "US", "ticker": "AAPL", "marketSector": "Equity"}]}
    figi.map = lambda ids: {k: figi_rows.get(k, []) for k in ids}
    rows, _ = run(figi, massive, header=ORDERS_HEADER, rows=[("HBCYF", "GB0005405286", "", "1")])
    assert rows[0]["lookup_cusip"] == ""
    assert rows[0]["lookup_status"] == "ok"


def test_symbol_is_the_last_resort(figi, massive):
    rows, _ = run(figi, massive, header=ORDERS_HEADER, rows=[("NVDA", "", "", "1")])
    assert (rows[0]["lookup_ticker"], rows[0]["close"]) == ("NVDA", "180.0")


def test_every_column_unusable_says_why_for_each(figi, massive):
    rows, _ = run(figi, massive, header=ORDERS_HEADER, rows=[("", "US0378331006", "9.29E+211", "1")])
    assert rows[0]["lookup_status"] == (
        "invalid: CUSIP: Excel scientific notation, re-export as text; ISIN: bad ISIN check digit")


def test_short_rows_keep_the_appended_columns_in_line(figi, massive):
    rows, _ = run(figi, massive, header=("CUSIP", "Qty", "Note"), rows=[("037833100",)])
    assert rows[0]["Note"] == "" and rows[0]["close"] == "231.5"


def test_falling_back_to_the_symbol_says_why(figi, massive):
    rows, summary = run(figi, massive, header=ORDERS_HEADER, rows=[("NVDA", "US0378331006", "9.29E+211", "1")])
    assert rows[0]["close"] == "180.0"
    assert rows[0]["lookup_status"] == (
        "ok, by Symbol (CUSIP: Excel scientific notation, re-export as text; ISIN: bad ISIN check digit)")
    assert summary.repairs["by Symbol"] == 1
