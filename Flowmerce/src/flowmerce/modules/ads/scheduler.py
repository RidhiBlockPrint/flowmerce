"""Background job: every ADS_SYNC_MINUTES (default 60) read each brand's Meta ad account into schema
`ads` (sync.py decides how many days to re-read).

* One daemon thread per process, never inside a request. It waits a minute after start-up so the
  server and the other modules' first rounds start first.
* Two processes never sync one account at once (database lock in ads.begin_sync).
* Any error is logged; the thread keeps going and SEO, Shipping and CRO are unaffected.
* Memory: a sync holds one 7-day span of daily rows at a time (a few thousand small rows), then
  sends it on.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from ..shipping.config import shipping_config
from ..shipping.supabase import SupabaseError
from . import sync
from .config import BRANDS, ads_config, check_brand, meta_account

log = logging.getLogger(__name__)
_stop = threading.Event()
_thread: threading.Thread | None = None
_running = threading.Lock()
last_run: dict[str, Any] = {"state": "not_run_yet"}
RETRY_MINUTES = 5


def sync_one(brand: str) -> dict[str, Any]:
    """Read one brand's Meta account now. Raises SupabaseError if the database cannot be reached."""
    try:
        check_brand(brand)
    except ValueError as e:
        from .service import InputError

        raise InputError(str(e)) from None
    return sync.sync_brand(brand)


def run_once() -> dict[str, Any]:
    """One round for every brand with a Meta account. Never raises."""
    global last_run
    out: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "brands": {}}
    if not _running.acquire(blocking=False):
        return {**out, "state": "already_running"}
    try:
        for brand in BRANDS:
            if meta_account(brand) is None:
                out["brands"][brand] = {"state": "not_configured"}
                continue
            try:
                out["brands"][brand] = sync.sync_brand(brand)
            except SupabaseError as e:
                out["brands"][brand] = {"state": "failed", "error": e.message[:300]}
            except Exception as e:  # noqa: BLE001 - never let the thread die
                log.exception("Ads round for %s crashed", brand)
                out["brands"][brand] = {"state": "failed", "error": str(e)[:300]}
    finally:
        _running.release()
    last_run = out
    return out


def _loop(minutes: int) -> None:
    if _stop.wait(60):
        return
    while not _stop.is_set():
        res = run_once()
        states = {b: r.get("state") for b, r in res.get("brands", {}).items()}
        log.info("Ads round: %s", states)
        # A failed or blocked account is tried again soon (a network blip, a lock left by a
        # stopped server) instead of waiting the full interval.
        wait = RETRY_MINUTES if {"failed", "locked"} & set(states.values()) else minutes
        if _stop.wait(min(wait, minutes) * 60):
            return


def enabled() -> bool:
    """Whether this process may run the job: SCHEDULER is not false, ADS_SYNC_MINUTES > 0, Supabase
    is configured and at least one brand has a Meta account set."""
    from ..seo.config import config

    return (
        bool(config.scheduler)
        and ads_config().sync_minutes > 0
        and shipping_config().configured
        and any(meta_account(b) for b in BRANDS)
    )


def start() -> bool:
    """Start the background job when enabled() and it is not already running."""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(
        target=_loop, args=(ads_config().sync_minutes,), name="ads-sync", daemon=True
    )
    _thread.start()
    return True


def stop() -> None:
    """Ask the background job to stop."""
    _stop.set()
