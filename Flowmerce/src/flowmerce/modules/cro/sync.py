"""Copy Shopify orders (money fields and line items) into cro.orders / cro.order_lines.

* First run per store: the orders updated in the last FIRST_RUN_DAYS (all a store app may read
  without read_all_orders). Later runs: orders updated since the last saved change, with a 10-minute
  overlap.
* The database lock (cro.begin_sync) stops two syncs of one store from overlapping, across
  processes. A running sync refreshes the lock after every batch; a lock not refreshed for
  LOCK_STALE_MINUTES belongs to a process that died and is cleared.
* Progress is saved after every batch (cro.sync_state.cursor), so an interrupted load continues
  where it stopped instead of starting over.
* Test orders are skipped. No customer data is requested or stored.
* One store failing never stops the other; each result is returned, nothing is raised.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ..shipping.supabase import SupabaseClient, SupabaseError
from . import shopify
from .config import FIRST_RUN_DAYS, STORE_BRAND, cro_client
from .data import forget_reads, parse_ts

log = logging.getLogger(__name__)

OVERLAP_MINUTES = 10
SAVE_BATCH = 50
LOCK_STALE_MINUTES = 10


def since_from_cursor(cursor: Any, now: datetime) -> tuple[datetime, bool]:
    """Where to start reading: (start time, is_first_run)."""
    last = parse_ts(cursor)
    if last is None:
        return now - timedelta(days=FIRST_RUN_DAYS), True
    return last - timedelta(minutes=OVERLAP_MINUTES), False


def _save(c: SupabaseClient, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    return int(c.rpc("save_orders", {"p_orders": rows}) or 0)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat()


def clear_abandoned_lock(c: SupabaseClient, store: str, now: datetime) -> bool:
    """Release a lock that has not been refreshed for LOCK_STALE_MINUTES (its process died).

    Compare-and-set on the old running_since value, so a sync that refreshes its lock at the same
    moment keeps it."""
    rows = c.select(
        "sync_state", [("select", "running_since"), ("store", f"eq.{store}")], limit=1
    ).rows
    held = parse_ts(rows[0].get("running_since")) if rows else None
    if held is None or now - held < timedelta(minutes=LOCK_STALE_MINUTES):
        return False
    c.update(
        "sync_state",
        [("store", f"eq.{store}"), ("running_since", f"eq.{rows[0]['running_since']}")],
        {"running_since": None},
    )
    log.warning("CRO order sync %s: cleared a lock abandoned since %s", store, _iso(held))
    return True


def _checkpoint(c: SupabaseClient, store: str, cursor: str | None, start: str | None) -> None:
    """Save progress and refresh the lock. The cursor only moves forward."""
    values: dict[str, Any] = {"running_since": _iso(datetime.now(UTC))}
    new, old = parse_ts(cursor), parse_ts(start)
    if new is not None and (old is None or new > old):
        values["cursor"] = _iso(new)
    c.update("sync_state", [("store", f"eq.{store}")], values)


def sync_store(
    store: str,
    c: SupabaseClient | None = None,
    gql: shopify.Gql | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sync one store. Returns {store, state: ok|already_running|not_configured|failed, ...}.
    Afterwards the pages read the new sync state instead of a cached one."""
    try:
        return _sync_store(store, c, gql, now)
    finally:
        forget_reads(store)


def _sync_store(
    store: str,
    c: SupabaseClient | None,
    gql: shopify.Gql | None,
    now: datetime | None,
) -> dict[str, Any]:
    c = c or cro_client()
    now = now or datetime.now(UTC)
    if gql is None and not shopify.configured(store):
        return {"store": store, "state": "not_configured"}
    gql = gql or shopify.gql_for(store)
    clear_abandoned_lock(c, store, now)
    lock = c.rpc("begin_sync", {"p_store": store}) or []
    if not lock:
        return {"store": store, "state": "already_running"}
    start_cursor = lock[0].get("since_cursor")
    since, first = since_from_cursor(start_cursor, now)
    read = written = 0
    newest: str | None = None
    try:
        pending: dict[int, dict[str, Any]] = {}
        for node in shopify.iter_orders(gql, since):
            read += 1
            updated = node.get("updatedAt")
            if updated and (newest is None or updated > newest):
                newest = updated
            row = shopify.order_row(store, node)
            if row is not None:
                pending[row["id"]] = row  # one row per order id: the latest copy wins
            if len(pending) >= SAVE_BATCH:
                written += _save(c, list(pending.values()))
                pending.clear()
                # every order updated before `newest` has been read and saved: safe to resume here
                _checkpoint(c, store, newest, start_cursor)
        written += _save(c, list(pending.values()))
    except Exception as e:  # noqa: BLE001 - recorded on the sync state; never stops the other store
        message = (getattr(e, "message", None) or str(e))[:1000]
        log.warning("CRO order sync %s failed: %s", store, message)
        try:
            c.rpc(
                "end_sync",
                {
                    "p_store": store,
                    "p_ok": False,
                    "p_cursor": None,
                    "p_orders": written,
                    "p_error": message,
                },
            )
        except SupabaseError:
            log.warning("CRO order sync %s: could not record the failure", store)
        return {"store": store, "state": "failed", "error": message[:300], "orders_read": read}
    c.rpc(
        "end_sync",
        {"p_store": store, "p_ok": True, "p_cursor": newest, "p_orders": written, "p_error": None},
    )
    return {
        "store": store,
        "state": "ok",
        "mode": "first load" if first else "changes",
        "orders_read": read,
        "orders_written": written,
    }


def sync_all() -> list[dict[str, Any]]:
    """Every store, one after the other. Never raises."""
    out = []
    for store in STORE_BRAND:
        try:
            out.append(sync_store(store))
        except SupabaseError as e:
            out.append({"store": store, "state": "failed", "error": e.message[:300]})
    return out
