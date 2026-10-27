import pytest

from ticker_lookup.identifiers import CUSIP, ISIN, TICKER, classify


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("037833100", ("037833100", CUSIP, "")),
        ("78462F103", ("78462F103", CUSIP, "")),
        (" us0378331005 ", ("US0378331005", ISIN, "")),
        ("NVDA", ("NVDA", TICKER, "")),
        ("BRK/B", ("BRK/B", TICKER, "")),
        # Excel stripped the leading zero; the check digit confirms the repair.
        ("37833100", ("037833100", CUSIP, "zero-padded")),
        ("037833101", ("037833101", None, "bad CUSIP check digit")),
        ("US0378331006", ("US0378331006", None, "bad ISIN check digit")),
        ("7.8471E+109", ("7.8471E+109", None, "Excel scientific notation, re-export as text")),
        ("", ("", None, "blank")),
    ],
)
def test_classify(raw, expected):
    assert classify(raw) == expected


def test_digits_that_do_not_pad_to_a_valid_cusip_stay_invalid():
    assert classify("37833101")[1] is None
