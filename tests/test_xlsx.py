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


def xlsx_upload(rows):
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_upload_reads_cells_excel_turned_into_numbers(figi, massive):
    data = xlsx_upload([
        ("Symbol", "ISIN", "CUSIP", "Trade Date", "Qty"),
        # Leading zero lost: stored as the number 84670702.
        ("BRK B", "US0846707026", 84670702, datetime(2026, 6, 1), 3),
        # Scientific notation stored as a number; the ISIN rescues it.
        ("AAPL", "US0378331005", 4.701e112, datetime(2026, 6, 2, 9, 30), 1.5),
    ])
    table, summary = enrich(data, figi, massive)
    head = table.header
    brk, aapl = (dict(zip(head, r)) for r in table.rows)
    assert (brk["CUSIP"], brk["lookup_cusip"], brk["lookup_ticker"]) == ("84670702", "084670702", "BRK.B")
    assert brk["lookup_status"] == "ok, zero-padded"
    assert brk["Trade Date"] == "2026-06-01" and brk["Qty"] == "3"
    assert (aapl["lookup_cusip"], aapl["lookup_status"]) == ("037833100", "ok, CUSIP from ISIN")
    assert aapl["Trade Date"] == "2026-06-02 09:30:00" and aapl["Qty"] == "1.5"
    assert summary.priced == 2


def test_a_broken_xlsx_is_a_user_error(figi, massive):
    import pytest
    from ticker_lookup.enrich import InputError
    with pytest.raises(InputError):
        enrich(b"PK\x03\x04 not really a zip", figi, massive)
