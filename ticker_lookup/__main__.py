"""Run the app: python -m ticker_lookup [--host 0.0.0.0] [--port 8000]"""

import argparse

import uvicorn

ap = argparse.ArgumentParser(description="Run Ticker Lookup")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8000)
args = ap.parse_args()
uvicorn.run("ticker_lookup.app:create_app", factory=True, host=args.host, port=args.port)
