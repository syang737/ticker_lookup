import io
from datetime import date, datetime

from openpyxl import load_workbook

from ticker_lookup.enrich import enrich, to_xlsx

# Shaped like the CUSIPs Excel turns into scientific notation when it opens a CSV.
CSV = (
    "Account,CUSIP,Qty,Price,Note\n"
    "0012,037833100,100,1.5,=HYPERLINK(\"http://x\")\n"
    "0013,78471E109,7,2,1E5\n"
).encode()


def sheet(figi, massive):
    table, _ = enrich(CSV, figi, massive)
    ws = load_workbook(io.BytesIO(to_xlsx(table))).active
    return [[c for c in row] for row in ws.iter_rows()]


def test_identifiers_stay_text_so_excel_cannot_mangle_them(figi, massive):
    rows = sheet(figi, massive)
    aapl, spy = rows[1][1], rows[2][1]
    assert (aapl.value, aapl.data_type, aapl.number_format) == ("037833100", "s", "@")
    assert (spy.value, spy.data_type) == ("78471E109", "s")


def test_numbers_become_numbers_only_when_nothing_is_lost(figi, massive):
    rows = sheet(figi, massive)
    account, qty, price, note = (rows[1][i].value for i in (0, 2, 3, 4))
    assert account == "0012"  # leading zero kept
    assert (qty, price) == (100, 1.5)
    assert rows[2][4].value == "1E5"


def test_formula_text_from_the_upload_is_not_a_live_formula(figi, massive):
    cell = sheet(figi, massive)[1][4]
    assert (cell.value, cell.data_type) == ('=HYPERLINK("http://x")', "s")


def test_close_is_a_number_and_close_date_a_date(figi, massive):
    head, aapl = sheet(figi, massive)[:2]
    names = [c.value for c in head]
    close, close_date = aapl[names.index("close")], aapl[names.index("close_date")]
    assert close.value == 231.5
    assert close_date.value in (date(2026, 10, 26), datetime(2026, 10, 26))
    assert close_date.number_format == "yyyy-mm-dd"
