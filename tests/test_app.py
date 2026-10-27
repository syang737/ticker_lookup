import json

import pytest
from fastapi.testclient import TestClient

from ticker_lookup.app import COOKIE, Settings, create_app
from ticker_lookup.cache import FigiCache

CSV = b"CUSIP,Qty\n037833100,100\n084670702,5\n"


@pytest.fixture
def client(figi, massive, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "hunter2")
    monkeypatch.setenv("SECRET_KEY", "s" * 64)
    app = create_app(Settings(), figi=figi, massive=massive, cache=FigiCache(tmp_path / "c.sqlite"))
    return TestClient(app)


def login(client, password="hunter2"):
    return client.post("/login", data={"password": password}, follow_redirects=False)


def test_pages_need_a_login(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    r = client.post("/api/enrich", files={"file": ("a.csv", CSV)})
    assert r.status_code == 401


def test_wrong_password_is_refused(client):
    r = login(client, "nope")
    assert r.headers["location"] == "/login?error=1"
    assert COOKIE not in r.cookies


def test_forged_or_expired_cookie_is_refused(client):
    client.cookies.set(COOKIE, "9999999999.deadbeef")
    assert client.get("/", follow_redirects=False).status_code == 303
    client.cookies.set(COOKIE, "1.abc")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_upload_returns_the_priced_file(client):
    assert login(client).headers["location"] == "/"
    assert "Drop a CSV" in client.get("/").text

    r = client.post("/api/enrich", files={"file": ("positions (1).csv", CSV, "text/csv")})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="positions_1_prices_2026-10-26.csv"'
    summary = json.loads(r.headers["x-lookup-summary"])
    assert (summary["rows"], summary["priced"], summary["column"]) == (2, 2, "CUSIP")
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "CUSIP,Qty,lookup_ticker,close,close_date,lookup_status,lookup_name,lookup_figi"
    assert lines[1].startswith("037833100,100,AAPL,231.5,2026-10-26,ok,")


def test_bad_file_is_a_400_with_a_message(client):
    login(client)
    r = client.post("/api/enrich", files={"file": ("a.csv", b"just a header\n")})
    assert r.status_code == 400
    assert "header row" in r.json()["error"]


def test_logout_clears_the_session(client):
    login(client)
    client.post("/logout", follow_redirects=False)
    client.cookies.clear()
    assert client.get("/", follow_redirects=False).status_code == 303
