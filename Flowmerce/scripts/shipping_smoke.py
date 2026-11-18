"""Smoke test of the running API in-process (no browser, no server, no scheduler).

Opens the real local database, builds the app with the scheduler OFF, and calls a few SEO and Shipping
routes as this computer. Shipping calls go to the real Supabase (read-only GETs only). Prints status
codes and the Shipping data state; never prints keys or customer data.

Usage: .venv\\Scripts\\python.exe scripts\\shipping_smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SCHEDULER", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from flowmerce.modules.seo.app import startup  # noqa: E402


def main() -> int:
    app = startup(with_scheduler=False)
    c = TestClient(app, client=("127.0.0.1", 50000))
    checks = [
        ("SEO  /api/auth/me", "/api/auth/me"),
        ("SEO  /api/home", "/api/home"),
        ("SEO  /api/articles", "/api/articles?limit=5"),
        ("SEO  /api/topics", "/api/topics"),
        ("SHIP /api/shipping/summary", "/api/shipping/summary"),
        ("SHIP /api/shipping/shipments", "/api/shipping/shipments?size=5"),
        ("SHIP /api/shipping/diagnostics", "/api/shipping/diagnostics?size=5"),
        ("SHIP /api/shipping/carriers", "/api/shipping/carriers"),
    ]
    failures = 0
    for label, path in checks:
        r = c.get(path)
        note = ""
        if path.startswith("/api/shipping"):
            body = r.json()
            if "summary" in path:
                note = f"state={body.get('source', {}).get('state')}"
                if body.get("totals"):
                    t = body["totals"]
                    note += f" open={t['open_tracking']} exceptions={t['exceptions']} unverified={t['unverified']}"
            elif r.status_code >= 400:
                note = f"code={body.get('code')}"
            elif "total" in body:
                note = f"total={body.get('total')}"
            elif "carriers" in body:
                note = f"carriers={len(body['carriers'])}"
        ok = r.status_code < 500 or (path.startswith("/api/shipping") and r.status_code == 503)
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {r.status_code}  {label}  {note}")
    r = c.post("/api/shipping/refresh")   # no X-Requested-With header: must be refused
    print(f"{'ok  ' if r.status_code == 403 else 'FAIL'} {r.status_code}  CSRF guard on POST /api/shipping/refresh")
    failures += 0 if r.status_code == 403 else 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
