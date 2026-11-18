"""Copy the Amazon MCF tracking sheet into Supabase (ops.amazon_mcf_sheet, 111) once a day.

The sheet is refreshed from Amazon every morning around 04:30-05:00 IST, so Flowmerce copies it at 09:00 IST
(AMAZON_MCF_SYNC_AT, "HH:MM" India time). If the server was off at 09:00, it copies as soon as it starts and finds
that today's copy is missing. "Sync now" on the Shipping page runs the same copy at once.

* Reads the sheet with the Google service account (read-only); writes with the Supabase service key (server only).
* Upserts every row by MCF id + parcel; never deletes. Each run is logged in ops.sync_runs (source 'amazon',
  kind 'import'); the database refuses two runs at once.
* The Shipping page itself only ever reads Supabase (ops.amazon_mcf_packages).
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import mcf_sheet
from .config import shipping_config
from .supabase import SupabaseError, client

log = logging.getLogger("flowmerce.shipping")
IST = timedelta(hours=5, minutes=30)          # India has no daylight saving time
BATCH = 500
TRIGGER_JOB = "job:amazon_mcf_sheet"
_stop = threading.Event()
_thread: threading.Thread | None = None


def sync_time() -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", os.environ.get("AMAZON_MCF_SYNC_AT") or "09:00")
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)), int(m.group(2))
    return 9, 0


def row_for_db(p: dict[str, Any], now: datetime) -> dict[str, Any]:
    """One sheet package -> one ops.amazon_mcf_sheet row (no names, no links)."""
    return {"sfo_id": p["sfo_id"][:200], "package_key": p.get("package_number") or "", "store": p.get("store"),
            "order_number": p.get("displayable_order_id"), "order_status": p.get("order_status"),
            "received_on": p.get("received_at"), "speed": p.get("speed"), "tracking_number": p.get("tracking_number"),
            "carrier": p.get("carrier_code"), "shipped_on": p.get("shipped_at"), "arrives_by": p.get("estimated_arrival"),
            "tracking_status": p.get("tracking_status"), "tracking_status_text": p.get("tracking_status_text"),
            "delivered_at": p.get("delivered_at"), "last_event_at": p.get("last_event_at"),
            "last_event_city": p.get("last_event_city"), "last_event_state": p.get("last_event_state"),
            "sheet_flag": p.get("sheet_flag"), "checked_at": p.get("fetched_at"),
            "synced_at": now.isoformat(timespec="seconds")}


def sync(triggered_by: str) -> dict[str, Any]:
    """Read the sheet and upsert it into Supabase. Returns {state, rows, error}; never raises for a sheet problem."""
    c = client()
    now = datetime.now(UTC)
    new_run = {"source": "amazon", "kind": "import", "triggered_by": triggered_by[:120], "cursor": "mcf_sheet"}
    try:
        run = c.insert_returning("sync_runs", new_run)
    except SupabaseError as e:
        if e.state != "conflict":
            raise
        # a run left "running" by a server that stopped mid-copy would block every later copy: end it after 30 min
        stale = (now - timedelta(minutes=30)).isoformat(timespec="seconds")
        c.update("sync_runs", [("source", "eq.amazon"), ("kind", "eq.import"), ("status", "eq.running"),
                               ("started_at", f"lt.{stale}")],
                 {"status": "failed", "finished_at": now.isoformat(timespec="seconds"), "error": "Interrupted (server stopped)."})
        try:
            run = c.insert_returning("sync_runs", new_run)
        except SupabaseError as e2:
            if e2.state == "conflict":
                return {"state": "already_running", "rows": 0, "error": "A copy of the MCF sheet is already running."}
            raise
    run_id = run.get("id")

    def finish(status: str, read: int = 0, written: int = 0, error: str | None = None) -> None:
        c.update("sync_runs", [("id", f"eq.{run_id}")],
                 {"status": status, "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
                  "rows_read": read, "rows_written": written, "error": (error or None) and error[:500]})

    try:
        packages = mcf_sheet.load()
        if packages is None:
            err = mcf_sheet.status().get("error") or "The MCF sheet could not be read."
            finish("failed", error=err)
            return {"state": "failed", "rows": 0, "error": err}
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for p in packages:                       # one row per MCF id + parcel (the last one wins if the sheet repeats)
            r = row_for_db(p, now)
            rows[(r["sfo_id"], r["package_key"])] = r
        out = list(rows.values())
        for i in range(0, len(out), BATCH):
            c.upsert("amazon_mcf_sheet", out[i:i + BATCH], "sfo_id,package_key")
        finish("ok", len(packages), len(out))
        log.info("Amazon MCF sheet copied to Supabase: %s rows", len(out))
        return {"state": "ok", "rows": len(out), "error": None}
    except SupabaseError as e:
        finish("failed", error=e.message)
        return {"state": "failed", "rows": 0, "error": e.message}
    except Exception as e:   # never leave the run "running" (that would block every later copy)
        finish("failed", error=str(e))
        raise


def last_ok(c=None) -> datetime | None:
    try:
        rows = (c or client()).select("sync_runs", [("select", "finished_at"), ("source", "eq.amazon"), ("kind", "eq.import"),
                                                    ("cursor", "eq.mcf_sheet"), ("status", "eq.ok"),
                                                    ("order", "finished_at.desc")], limit=1).rows
    except SupabaseError:
        return None
    t = rows[0]["finished_at"] if rows else None
    return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None


def due_at(day: date) -> datetime:
    """Today's (IST) sync moment, in UTC."""
    h, m = sync_time()
    return datetime(day.year, day.month, day.day, h, m, tzinfo=UTC) - IST


def next_run(now: datetime, last: datetime | None) -> datetime:
    """Now, when today's IST sync moment has passed and no copy was made since; otherwise the next sync moment."""
    today = (now + IST).date()
    due = due_at(today)
    if now >= due and (last is None or last < due):
        return now
    return due if now < due else due_at(today + timedelta(days=1))


def _loop() -> None:
    if _stop.wait(60):                           # let the server finish starting first
        return
    while not _stop.is_set():
        now = datetime.now(UTC)
        when = next_run(now, last_ok())
        if when > now:
            if _stop.wait(min((when - now).total_seconds(), 3600)):   # wake hourly to re-check (sleep, clock changes)
                return
            continue
        try:
            res = sync(TRIGGER_JOB)
            log.info("Amazon MCF sheet sync: %s", res)
            if res["state"] == "ok":
                from . import board
                board.snapshot(force=True)
            elif res["state"] == "failed":
                _stop.wait(3600)                 # sheet not readable: try again in an hour, not in a tight loop
        except Exception:
            log.exception("Amazon MCF sheet sync crashed")
            _stop.wait(3600)


def start() -> bool:
    global _thread
    flag = (os.environ.get("AMAZON_MCF_SYNC") or "on").strip().lower()
    if not shipping_config().configured or flag in ("0", "off", "false", "no") or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="amazon-mcf-sheet-sync", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
