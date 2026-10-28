# Ticker Lookup

Drop a CSV of CUSIPs, ISINs or tickers on a web page; get the same file back
with the ticker and previous close appended. Behind one shared password.

## Run it

```
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e .
copy .env.example .env            # then fill in APP_PASSWORD, SECRET_KEY, MASSIVE_API_KEY
python -m ticker_lookup           # http://127.0.0.1:8000
```

`--host 0.0.0.0` to serve others on the network. Over HTTPS, set
`SECURE_COOKIE=true`.

To host it on a server behind Caddy, see [deploy/DEPLOY.md](deploy/DEPLOY.md).

## What comes back

An Excel file by default (CSV on request). Excel opens a CSV by guessing types,
which turns CUSIPs like `12345E107` into scientific notation and drops leading
zeros; in the .xlsx the identifier column is stored as text, so it cannot.

Every original row and column, plus:

| Column | |
|---|---|
| `lookup_ticker` | The US ticker priced |
| `close` | Unadjusted close of the last completed session |
| `close_date` | That session's date |
| `lookup_status` | `ok`, or why the row has no price |
| `lookup_name`, `lookup_figi` | What the identifier resolved to, to check against |

The identifier column is found by its header (`CUSIP`, `ISIN`, `Ticker`,
`Symbol`...) or, failing that, by which column holds identifiers.

## How it works

1. **Classify** each value and check its check digit. CUSIPs Excel stripped
   of leading zeros are repaired when the check digit confirms it; ones it
   turned into scientific notation are reported as unrecoverable.
2. **Resolve** through [OpenFIGI](https://www.openfigi.com/api): 100
   identifiers per request with a free key, CINS (non-US issuer CUSIPs)
   retried as such. Answers are cached in SQLite for a week (misses for a day).
3. **Price** from Massive's grouped daily aggregates: one call returns every
   US close for the date, so a 3,000-row file costs one request. Before 8pm
   Eastern, "previous close" means the prior session's.

When an identifier maps to several US listings -- a closed-end fund and its
NAV symbol -- the one with a close wins.

Not priceable by design: bonds, preferreds (no Massive ticker), escrow and
CVR placeholders, and old CUSIPs whose only listings are foreign.

## Tests

```
pip install -e ".[dev]"
pytest
```
