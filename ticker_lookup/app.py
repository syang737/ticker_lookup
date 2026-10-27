"""The web app: a password page, a drop zone, and a download.

Auth is one shared password (APP_PASSWORD). A correct password sets a signed,
expiring cookie; nothing is stored server-side.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .cache import FigiCache
from .enrich import InputError, enrich
from .massive import Massive
from .openfigi import OpenFigi

load_dotenv()

STATIC = Path(__file__).parent / "static"
COOKIE = "tl_session"
SESSION_SECONDS = 12 * 3600
MAX_UPLOAD = 20 * 1024 * 1024


class Settings:
    def __init__(self) -> None:
        self.password = os.environ.get("APP_PASSWORD", "")
        # Without a fixed key, sessions end whenever the server restarts.
        self.secret = (os.environ.get("SECRET_KEY") or secrets.token_hex(32)).encode()
        self.secure_cookie = os.environ.get("SECURE_COOKIE", "false").lower() == "true"
        self.openfigi_key = os.environ.get("OPENFIGI_API_KEY") or None
        self.massive_key = os.environ.get("MASSIVE_API_KEY", "")
        self.cache_path = os.environ.get("CACHE_PATH", "./data/figi_cache.sqlite")


def _sign(secret: bytes, expires: int) -> str:
    mac = hmac.new(secret, str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def _valid(secret: bytes, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires, _ = token.split(".", 1)
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(token, _sign(secret, int(expires)))


def create_app(settings: Settings | None = None, figi=None, massive=None, cache=None) -> FastAPI:
    settings = settings or Settings()
    if not settings.password:
        raise RuntimeError("Set APP_PASSWORD")
    if massive is None and not settings.massive_key:
        raise RuntimeError("Set MASSIVE_API_KEY")
    figi = figi or OpenFigi(settings.openfigi_key)
    massive = massive or Massive(settings.massive_key)
    cache = cache or FigiCache(settings.cache_path)

    app = FastAPI(title="Ticker lookup", docs_url=None, redoc_url=None, openapi_url=None)

    def authed(request: Request) -> bool:
        return _valid(settings.secret, request.cookies.get(COOKIE))

    @app.get("/")
    def index(request: Request):
        if not authed(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC / "login.html")

    @app.post("/login")
    async def login(password: str = Form("")):
        if not hmac.compare_digest(password.encode(), settings.password.encode()):
            # Slows guessing; a shared password has no lockout to lean on.
            await asyncio.sleep(1)
            return RedirectResponse("/login?error=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        expires = int(time.time()) + SESSION_SECONDS
        resp.set_cookie(
            COOKIE,
            _sign(settings.secret, expires),
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookie,
        )
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # Sync on purpose: FastAPI runs it in a worker thread, so a 3,000-row
    # file does not block other requests while OpenFIGI is called.
    @app.post("/api/enrich")
    def enrich_upload(request: Request, file: UploadFile):
        if not authed(request):
            return JSONResponse({"error": "Signed out. Reload the page."}, status_code=401)
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            return JSONResponse({"error": "File is over 20 MB."}, status_code=413)
        try:
            out, summary = enrich(data, figi, massive, cache)
        except InputError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except httpx.HTTPError as e:
            return JSONResponse({"error": f"Data provider error: {e}"}, status_code=502)

        # The name goes into a header: keep it to characters that cannot break one.
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file.filename or "").stem)[:80].strip("_") or "lookup"
        name = f"{stem}_prices_{summary.close_date.isoformat()}.csv"
        info = {
            "rows": summary.rows,
            "priced": summary.priced,
            "column": summary.column,
            "close_date": summary.close_date.isoformat(),
            "statuses": summary.statuses.most_common(),
        }
        return Response(
            out,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Lookup-Summary": json.dumps(info),
            },
        )

    return app
