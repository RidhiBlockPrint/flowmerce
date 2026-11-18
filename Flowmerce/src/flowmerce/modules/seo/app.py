"""FastAPI application: the local-only guard, security headers, the local operator identity, the CSRF
guard and the /api router. This is the backend API only; the Next.js frontend (frontend/) renders the pages
and forwards /api/* here.

Local operator mode: every request is refused with 403 unless it comes from a loopback address. The single exception is POST /api/hooks/workflow, which has its
own X-Workflow-Secret check. Requests that pass act as the local administrator record; there is no sign-in."""
from __future__ import annotations

import secrets
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import api
from .audit import audit
from .auth import LOCAL_OPERATOR_PASSWORD_HASH, is_loopback_client, local_operator
from .config import config
from .db import get, now, open_db, run
from .integrations.status import sweep_stuck_syncs
from .services import ai_jobs
from .services.runs import sweep_interrupted_runs
from .services.scheduler import start_scheduler
from .util import HttpError

# The backend only returns JSON (and the /api/docs page, which is exempt below), so nothing may load or embed.
CSP = "default-src 'none'; frame-ancestors 'none'"


def create_app() -> FastAPI:
    app = FastAPI(title="Blog Ops", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        # The workflow webhook is the only thing reachable from other computers: it checks its own secret.
        # The match is exact (method and path); no other path is exempt.
        is_webhook = request.method == "POST" and path == "/api/hooks/workflow"
        if not is_webhook and not is_loopback_client(request):
            resp = JSONResponse({"error": "Flowmerce is in local operator mode and only answers requests from this computer.",
                                 "code": "local_only"}, status_code=403)
        elif path.startswith("/api"):
            request.state.user = None if is_webhook else local_operator()
            if request.method not in ("GET", "HEAD", "OPTIONS") and not path.startswith("/api/hooks/") \
                    and request.headers.get("X-Requested-With") != "blog-ops":
                resp = JSONResponse({"error": "Missing request header.", "code": "csrf"}, status_code=403)
            else:
                resp = await call_next(request)
        else:
            resp = await call_next(request)
        if path.startswith("/api"):
            resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not path.startswith("/api/docs"):
            resp.headers["Content-Security-Policy"] = CSP
        return resp

    @app.exception_handler(HttpError)
    async def http_error(_request: Request, e: HttpError):
        return JSONResponse({"error": e.message, "code": e.code, "details": e.details}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request: Request, e: RequestValidationError):
        return JSONResponse({"error": "The request body is not valid JSON.", "code": "bad_request"}, status_code=400)

    @app.exception_handler(Exception)
    async def server_error(request: Request, e: Exception):
        ref = secrets.token_hex(4)
        print(f"[{ref}] {request.method} {request.url.path}\n{traceback.format_exc()}")
        return JSONResponse({"error": f"Something went wrong on the server (ref {ref}). {str(e)[:300]}".strip(), "code": "server_error"}, status_code=500)

    app.include_router(api)
    _include_shipping(app)   # must come before the /api catch-all below

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    def api_not_found(rest: str):
        raise HttpError(404, "Not found.")

    return app


def _include_shipping(app: FastAPI) -> None:
    """Mount the Shipping module's /api/shipping routes. Kept independent: if the module cannot load,
    SEO still starts and the Shipping pages report the problem."""
    try:
        from ..shipping.api import shipping
    except Exception:  # noqa: BLE001 - a broken optional module must never stop SEO
        print(f"Shipping module not loaded:\n{traceback.format_exc()}")
        return
    app.include_router(shipping)


def _start_shipping_refresher() -> None:
    try:
        from ..shipping.scheduler import start_refresher
        if start_refresher():
            print("Shipping: refreshing data from Supabase in the background.")
    except Exception:  # noqa: BLE001
        print(f"Shipping refresher not started:\n{traceback.format_exc()}")
    try:
        from ..shipping import mcf_sync
        if mcf_sync.start():
            h, m = mcf_sync.sync_time()
            print(f"Shipping: copying the Amazon MCF sheet into Supabase daily at {h:02d}:{m:02d} IST.")
    except Exception:  # noqa: BLE001
        print(f"Amazon MCF sheet sync not started:\n{traceback.format_exc()}")


def bootstrap_admin() -> None:
    """Make sure an active administrator record exists, because every local request acts as one.

    This runs even when other users already exist. No password is generated, shown, logged or written to a
    file: the record gets a hash that can never verify (LOCAL_OPERATOR_PASSWORD_HASH). ADMIN_PASSWORD is
    ignored. Existing users, any old data/initial-admin.txt and existing sessions are left untouched."""
    if get("SELECT 1 FROM users WHERE role = 'admin' AND active = 1 LIMIT 1"):
        return
    wanted = (config.admin_email or "admin@blog-ops.local").lower()
    email, n = wanted, 1
    while get("SELECT 1 FROM users WHERE email = ?", email):  # emails are unique; never touch an existing record
        n += 1
        email = f"local-operator{'' if n == 2 else n - 1}@flowmerce.local"
    run("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
        email, "Local operator" if email != wanted else "Administrator", "admin", LOCAL_OPERATOR_PASSWORD_HASH, now())
    audit(None, "user.bootstrap_admin", "user", summary=f"{email} (local operator record, no password)")
    print(f"Created the local operator administrator record ({email}). Flowmerce opens without sign-in on this computer.")


def startup(with_scheduler: bool = True) -> FastAPI:
    open_db()
    bootstrap_admin()
    swept = sweep_interrupted_runs()
    if swept:
        print(f"Marked {swept} interrupted workflow run(s) as failed.")
    stuck = sweep_stuck_syncs()
    if stuck:
        print(f"Marked {stuck} integration sync(s) left 'syncing' by an earlier server as interrupted.")
    if with_scheduler and config.scheduler:
        start_scheduler()
    app = create_app()
    if with_scheduler:
        ai_jobs.start_runner()   # recovers interrupted AI jobs, then works through the queue; does nothing when AI execution is disabled
        app.router.add_event_handler("shutdown", ai_jobs.stop_runner)   # graceful: finish or hand back running jobs
        _start_shipping_refresher()
    return app
