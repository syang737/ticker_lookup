from datetime import date

import pytest

AAPL = {"exchCode": "US", "ticker": "AAPL", "marketSector": "Equity", "securityType": "Common Stock",
        "name": "APPLE INC", "compositeFIGI": "BBG000B9XRY4"}
BRKB = {"exchCode": "US", "ticker": "BRK/B", "marketSector": "Equity", "securityType": "Common Stock",
        "name": "BERKSHIRE HATHAWAY INC-CL B", "compositeFIGI": "BBG000DWG505"}
FUND = {"exchCode": "US", "ticker": "SDHY", "marketSector": "Equity", "securityType": "Closed-End Fund",
        "name": "PGIM SHRT DURAT HI YLD"}
FUND_NAV = {**FUND, "ticker": "XSDHX"}
TREASURY = {"ticker": "T 4.875 11/30/25", "marketSector": "Govt", "securityType": "US GOVERNMENT",
            "name": "US TREASURY N/B"}
PFD = {"exchCode": "US", "ticker": "JPM 6 PERP EE", "marketSector": "Pfd", "securityType": "PUBLIC",
       "name": "JPMORGAN CHASE & CO"}
FOREIGN = {"exchCode": "LN", "ticker": "BZHGBP", "marketSector": "Equity", "name": "BEAZER HOMES USA INC"}

MATCHES = {
    ("037833100", "CUSIP"): [AAPL],
    ("US0378331005", "ISIN"): [AAPL],
    ("084670702", "CUSIP"): [BRKB],
    # NAV symbol first, so picking by close is what gets the listing.
    ("69355J104", "CUSIP"): [FUND_NAV, FUND],
    ("91282CJL6", "CUSIP"): [TREASURY],
    ("46625H100", "CUSIP"): [PFD],
    ("07556Q881", "CUSIP"): [FOREIGN, {**FOREIGN, "exchCode": "GR"}],
    ("NVDA", "TICKER"): [{**AAPL, "ticker": "NVDA", "name": "NVIDIA CORP"}],
}
CLOSES = {"AAPL": 231.5, "BRK.B": 470.12, "SDHY": 8.31, "NVDA": 180.0}
CLOSE_DATE = date(2026, 10, 26)


class FakeFigi:
    def __init__(self):
        self.calls = []

    def map(self, ids):
        self.calls.append(list(ids))
        return {k: MATCHES.get(k, []) for k in ids}


class FakeMassive:
    def previous_closes(self, now=None):
        return CLOSE_DATE, CLOSES


@pytest.fixture
def figi():
    return FakeFigi()


@pytest.fixture
def massive():
    return FakeMassive()
