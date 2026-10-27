import json
from datetime import datetime

import httpx

from ticker_lookup.massive import EASTERN, Massive
from ticker_lookup.openfigi import OpenFigi


def test_openfigi_batches_and_retries_cins():
    seen = []

    def handler(request):
        jobs = json.loads(request.content)
        seen.append(jobs)
        out = []
        for j in jobs:
            if j["idType"] == "ID_CINS":
                out.append({"data": [{"ticker": "BORR", "exchCode": "US"}]})
            else:
                out.append({"warning": "No identifier found."})
        return httpx.Response(200, json=out)

    figi = OpenFigi("key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    ids = [(f"{i:08d}0", "CUSIP") for i in range(150)] + [("G1466R173", "CUSIP")]
    res = figi.map(ids)

    assert [len(b) for b in seen] == [100, 51, 1]
    assert seen[-1] == [{"idType": "ID_CINS", "idValue": "G1466R173"}]
    assert res[("G1466R173", "CUSIP")][0]["ticker"] == "BORR"
    assert res[("000000000", "CUSIP")] == []


def test_massive_walks_back_past_empty_days_and_skips_today_during_market_hours():
    seen = []

    def handler(request):
        seen.append(request.url.path.rsplit("/", 1)[1])
        assert request.headers["authorization"] == "Bearer k"
        assert request.url.params["adjusted"] == "false"
        if seen[-1] == "2026-10-23":
            return httpx.Response(200, json={"resultsCount": 1, "results": [{"T": "AAPL", "c": 230.0}]})
        return httpx.Response(200, json={"resultsCount": 0})

    m = Massive("k", client=httpx.Client(
        base_url="https://x", headers={"Authorization": "Bearer k"},
        transport=httpx.MockTransport(handler)))
    # Monday 26 Oct, mid-session: Sunday and Saturday are empty, Friday is it.
    day, closes = m.previous_closes(datetime(2026, 10, 26, 11, 0, tzinfo=EASTERN))
    assert seen == ["2026-10-25", "2026-10-24", "2026-10-23"]
    assert (day.isoformat(), closes) == ("2026-10-23", {"AAPL": 230.0})
