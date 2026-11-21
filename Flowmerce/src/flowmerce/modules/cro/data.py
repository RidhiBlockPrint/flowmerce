"""Reads and writes of schema `cro` in Supabase, and the in-memory order snapshot the CRO pages use.

The snapshot holds the last SNAPSHOT_DAYS of one store's orders and line items. It is reloaded after
every sync. Once older than `snapshot_seconds` it is still served at once while a background thread
reloads it, so a page only waits when there is no copy yet (or it is older than MAX_STALE_SECONDS).
Small reads the pages repeat (sync state, settings, rules, alerts) are kept for READ_CACHE_SECONDS
and forgotten whenever this module writes to them.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..shipping.supabase import SupabaseClient, SupabaseError
from .config import SNAPSHOT_DAYS, cro_client, cro_config

ORDER_COLUMNS = (
    "id,name,placed_at,cancelled_at,financial_status,currency,total,subtotal,discounts,shipping,tax,"
    "refunded"
)
LINE_COLUMNS = "order_id,placed_at,product_id,title,product_type,tags,quantity,unit_price"
PAGE = 1000
MAX_STALE_SECONDS = 1800  # a copy older than this is reloaded before answering
READ_CACHE_SECONDS = 30.0

log = logging.getLogger(__name__)
# Separate pools so a task never waits on a task queued in its own pool: tables (orders, lines)
# submit to the page pool only.
_table_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cro-table")
_page_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="cro-page")


def parse_ts(value: Any) -> datetime | None:
    """An ISO timestamp from Supabase or Shopify as an aware UTC datetime."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except TypeError, ValueError:
        return 0.0


@dataclass(frozen=True)
class Order:
    """One order as the reports use it (no customer data)."""

    id: int
    name: str
    placed_at: datetime
    cancelled_at: datetime | None
    financial_status: str
    currency: str
    total: float
    subtotal: float
    discounts: float
    shipping: float
    tax: float
    refunded: float


@dataclass(frozen=True)
class Line:
    """One line item."""

    order_id: int
    placed_at: datetime
    product_id: int | None
    title: str
    product_type: str
    tags: str
    quantity: int
    unit_price: float


@dataclass(frozen=True)
class Snapshot:
    """A store's recent orders and line items, loaded at `loaded_at`."""

    store: str
    orders: tuple[Order, ...]
    lines: tuple[Line, ...]
    loaded_at: datetime
    since: datetime


def order_from_row(r: dict[str, Any]) -> Order:
    """A cro.orders row -> Order."""
    placed = parse_ts(r.get("placed_at"))
    if placed is None:
        raise ValueError("order row without placed_at")
    return Order(
        id=int(r["id"]),
        name=str(r.get("name") or ""),
        placed_at=placed,
        cancelled_at=parse_ts(r.get("cancelled_at")),
        financial_status=str(r.get("financial_status") or "").lower(),
        currency=str(r.get("currency") or "USD"),
        total=_num(r.get("total")),
        subtotal=_num(r.get("subtotal")),
        discounts=_num(r.get("discounts")),
        shipping=_num(r.get("shipping")),
        tax=_num(r.get("tax")),
        refunded=_num(r.get("refunded")),
    )


def line_from_row(r: dict[str, Any]) -> Line:
    """A cro.order_lines row -> Line."""
    placed = parse_ts(r.get("placed_at"))
    if placed is None:
        raise ValueError("line row without placed_at")
    pid = r.get("product_id")
    return Line(
        order_id=int(r["order_id"]),
        placed_at=placed,
        product_id=int(pid) if pid is not None else None,
        title=str(r.get("title") or ""),
        product_type=str(r.get("product_type") or ""),
        tags=str(r.get("tags") or ""),
        quantity=int(r.get("quantity") or 0),
        unit_price=_num(r.get("unit_price")),
    )


def _all(c: SupabaseClient, table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every matching row. The first page also asks for the total; the other pages are then read
    at the same time (kept in order), so a large read costs about two round trips instead of one
    per page."""
    first = c.select(table, params, count=True, limit=PAGE)
    rows = list(first.rows)
    if len(first.rows) < PAGE:
        return rows
    if first.total is None:  # no total reported: read on page by page
        offset = PAGE
        while True:
            page = c.select(table, params, offset=offset, limit=PAGE).rows
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            offset += PAGE
    offsets = range(PAGE, first.total, PAGE)
    for page_rows in _page_pool.map(
        lambda o: c.select(table, params, offset=o, limit=PAGE).rows, offsets
    ):
        rows.extend(page_rows)
    return rows


def load_snapshot(
    store: str,
    now: datetime | None = None,
    c: SupabaseClient | None = None,
    since: datetime | None = None,
) -> Snapshot:
    """Read one store's orders and line items placed since `since` (default: the last
    SNAPSHOT_DAYS)."""
    c = c or cro_client()
    now = now or datetime.now(UTC)
    since = since or now - timedelta(days=SNAPSHOT_DAYS)
    filt = [("store", f"eq.{store}"), ("placed_at", f"gte.{since.isoformat()}")]
    orders_f = _table_pool.submit(
        _all, c, "orders", [("select", ORDER_COLUMNS), *filt, ("order", "placed_at.asc,id.asc")]
    )
    lines_f = _table_pool.submit(
        _all,
        c,
        "order_lines",
        [("select", LINE_COLUMNS), *filt, ("order", "placed_at.asc,order_id.asc,line_no.asc")],
    )
    orders, lines = orders_f.result(), lines_f.result()
    return Snapshot(
        store=store,
        orders=tuple(order_from_row(r) for r in orders),
        lines=tuple(line_from_row(r) for r in lines),
        loaded_at=now,
        since=since,
    )


_snapshots: dict[str, tuple[float, Snapshot]] = {}
_snap_lock = threading.Lock()  # guards the dictionaries below; never held during a load
_load_locks: dict[str, threading.Lock] = {}
_refreshing: set[str] = set()


def _load_lock(store: str) -> threading.Lock:
    with _snap_lock:
        return _load_locks.setdefault(store, threading.Lock())


def _reload(store: str, force: bool = False) -> Snapshot:
    """Load a store's snapshot, one load per store at a time. Unless forced, a caller that waited
    on another caller's load gets that result instead of loading again."""
    asked = datetime.now(UTC)
    with _load_lock(store):
        with _snap_lock:
            cached = _snapshots.get(store)
        if cached and not force and cached[1].loaded_at >= asked:
            return cached[1]
        snap = load_snapshot(store)
        with _snap_lock:
            _snapshots[store] = (time.monotonic() + cro_config().snapshot_seconds, snap)
        return snap


def _background_reload(store: str) -> None:
    try:
        _reload(store)
    except Exception:  # noqa: BLE001 - the old copy stays in use
        log.warning("CRO: background reload of the %s order copy failed", store, exc_info=True)
    finally:
        with _snap_lock:
            _refreshing.discard(store)


def snapshot(store: str, force: bool = False) -> Snapshot:
    """The store's snapshot. A copy older than `snapshot_seconds` is returned at once and reloaded
    in the background; without a copy, when the copy is older than MAX_STALE_SECONDS or when
    forced, it is loaded before returning."""
    if not force:
        with _snap_lock:
            cached = _snapshots.get(store)
            if cached:
                snap = cached[1]
                if cached[0] > time.monotonic():
                    return snap
                if (datetime.now(UTC) - snap.loaded_at).total_seconds() < MAX_STALE_SECONDS:
                    if store not in _refreshing:
                        _refreshing.add(store)
                        threading.Thread(
                            target=_background_reload, args=(store,), name="cro-reload", daemon=True
                        ).start()
                    return snap
    return _reload(store, force)


def warm(stores: list[str]) -> None:
    """Load the given stores' snapshots at the same time (start-up), logging failures."""
    futures = [(s, _table_pool.submit(snapshot, s)) for s in stores]
    for store, f in futures:
        try:
            f.result()
        except Exception:  # noqa: BLE001 - the first page visit will try again
            log.warning("CRO: could not load the %s order copy at start-up", store, exc_info=True)


_wide: dict[tuple[str, str], tuple[float, Snapshot]] = {}


def snapshot_since(store: str, since: datetime) -> Snapshot:
    """Orders since `since`: the cached snapshot when it reaches back far enough, otherwise a wider
    read (cached per store and start day for `snapshot_seconds`, at most 4 kept)."""
    snap = snapshot(store)
    if since >= snap.since:
        return snap
    key = (store, since.date().isoformat())
    with _snap_lock:
        hit = _wide.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    wide = load_snapshot(store, since=datetime.combine(since.date(), datetime.min.time(), UTC))
    with _snap_lock:
        if len(_wide) >= 4:
            _wide.pop(next(iter(_wide)))
        _wide[key] = (time.monotonic() + cro_config().snapshot_seconds, wide)
    return wide


_first: dict[str, tuple[float, str | None]] = {}


def first_order_day(store: str, c: SupabaseClient | None = None) -> str | None:
    """The day (YYYY-MM-DD, UTC) of the oldest order in CRO's copy, cached for an hour."""
    hit = _first.get(store)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    rows = (
        (c or cro_client())
        .select(
            "orders",
            [("select", "placed_at"), ("store", f"eq.{store}"), ("order", "placed_at.asc")],
            limit=1,
        )
        .rows
    )
    day = str(rows[0]["placed_at"])[:10] if rows else None
    _first[store] = (time.monotonic() + 3600, day)
    return day


def forget_snapshots() -> None:
    """Drop every cached snapshot (tests, or after a failed reload)."""
    with _snap_lock:
        _snapshots.clear()
        _wide.clear()
    forget_reads()


# ------------------------------------------------------------------------------------------ short
# cache of the small reads the pages repeat
_reads: dict[tuple[str, ...], tuple[float, Any]] = {}
_reads_lock = threading.Lock()


def recent[T](key: tuple[str, ...], load: Callable[[], T]) -> T:
    """`load()`, reused for READ_CACHE_SECONDS. For page reads only: alarm checks and the sync
    lock always read the database."""
    with _reads_lock:
        hit = _reads.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]  # type: ignore[no-any-return]
    value = load()
    with _reads_lock:
        _reads[key] = (time.monotonic() + READ_CACHE_SECONDS, value)
    return value


def forget_reads(store: str | None = None) -> None:
    """Forget the cached small reads (of one store, or all) after a write."""
    with _reads_lock:
        for k in [k for k in _reads if store is None or store in k]:
            _reads.pop(k, None)


# ------------------------------------------------------------------------------------------ sync
# state
def sync_state(store: str, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """The store's cro.sync_state row, or None before the first sync."""
    rows = (
        (c or cro_client())
        .select("sync_state", [("select", "*"), ("store", f"eq.{store}")], limit=1)
        .rows
    )
    return rows[0] if rows else None


# ------------------------------------------------------------------------------------------
# settings
def alarms_enabled(store: str, c: SupabaseClient | None = None) -> bool:
    """Whether CRO alarms run for this store. A store without a settings row has them on."""
    rows = (
        (c or cro_client())
        .select("store_settings", [("select", "alarms_enabled"), ("store", f"eq.{store}")], limit=1)
        .rows
    )
    return bool(rows[0]["alarms_enabled"]) if rows else True


def set_alarms_enabled(store: str, enabled: bool, by: str, c: SupabaseClient | None = None) -> None:
    """Switch CRO alarms on or off for a store."""
    forget_reads(store)
    (c or cro_client()).upsert(
        "store_settings",
        [{"store": store, "alarms_enabled": enabled, "updated_by": by[:200]}],
        on_conflict="store",
    )


# ------------------------------------------------------------------------------------------ alarm
# rules
RULE_COLUMNS = (
    "id,store,kind,title,threshold,product_keyword,is_active,last_checked_at,updated_by,updated_at"
)


def alarm_rules(store: str, c: SupabaseClient | None = None) -> list[dict[str, Any]]:
    """Every alarm rule of a store, oldest first."""
    return (
        (c or cro_client())
        .select(
            "alarm_rules", [("select", RULE_COLUMNS), ("store", f"eq.{store}"), ("order", "id.asc")]
        )
        .rows
    )


def alarm_rule(store: str, rule_id: int, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """One rule of this store, or None."""
    rows = (
        (c or cro_client())
        .select(
            "alarm_rules",
            [("select", RULE_COLUMNS), ("store", f"eq.{store}"), ("id", f"eq.{rule_id}")],
            limit=1,
        )
        .rows
    )
    return rows[0] if rows else None


def create_rule(row: dict[str, Any], c: SupabaseClient | None = None) -> dict[str, Any]:
    """Insert a rule; returns the stored row. A duplicate (store, kind, keyword) raises
    SupabaseError 'conflict'.
    """
    forget_reads(str(row.get("store")))
    return (c or cro_client()).insert_returning("alarm_rules", row)


def update_rule(
    store: str, rule_id: int, values: dict[str, Any], c: SupabaseClient | None = None
) -> None:
    """Change a rule of this store."""
    forget_reads(store)
    (c or cro_client()).update(
        "alarm_rules", [("id", f"eq.{rule_id}"), ("store", f"eq.{store}")], values
    )


def mark_checked(rule_id: int, at: datetime, c: SupabaseClient | None = None) -> None:
    """Record when a rule was last evaluated."""
    (c or cro_client()).update(
        "alarm_rules", [("id", f"eq.{rule_id}")], {"last_checked_at": at.isoformat()}
    )


# ------------------------------------------------------------------------------------------ alerts
ALERT_COLUMNS = "id,rule_id,store,period_date,message,details,triggered_at,resolved_at"


def open_alert(rule_id: int, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """The rule's open alert, if any (the database allows at most one)."""
    rows = (
        (c or cro_client())
        .select(
            "alerts",
            [("select", ALERT_COLUMNS), ("rule_id", f"eq.{rule_id}"), ("resolved_at", "is.null")],
            limit=1,
        )
        .rows
    )
    return rows[0] if rows else None


def alerts(store: str, limit: int = 50, c: SupabaseClient | None = None) -> list[dict[str, Any]]:
    """The store's most recent alerts."""
    return (
        (c or cro_client())
        .select(
            "alerts",
            [("select", ALERT_COLUMNS), ("store", f"eq.{store}"), ("order", "triggered_at.desc")],
            limit=limit,
        )
        .rows
    )


def insert_alert(row: dict[str, Any], c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """Insert an alert; None when the database refuses it as a duplicate (already open, or already
    raised that day).
    """
    forget_reads(str(row.get("store")))
    try:
        return (c or cro_client()).insert_returning("alerts", row)
    except SupabaseError as e:
        if e.state == "conflict":
            return None
        raise


def resolve_alert(alert_id: int, at: datetime, c: SupabaseClient | None = None) -> None:
    """Close an open alert."""
    forget_reads()
    (c or cro_client()).update(
        "alerts",
        [("id", f"eq.{alert_id}"), ("resolved_at", "is.null")],
        {"resolved_at": at.isoformat()},
    )


# ------------------------------------------------------------------------------------------ change
# log
CHANGE_COLUMNS = "id,store,entry_date,change,area,owner,created_by,created_at"


def change_log(store: str, since: str, c: SupabaseClient | None = None) -> list[dict[str, Any]]:
    """Change-log entries of a store on or after `since` (YYYY-MM-DD), newest first."""
    return (
        (c or cro_client())
        .select(
            "change_log",
            [
                ("select", CHANGE_COLUMNS),
                ("store", f"eq.{store}"),
                ("entry_date", f"gte.{since}"),
                ("order", "entry_date.desc,id.desc"),
            ],
        )
        .rows
    )


def add_change(row: dict[str, Any], c: SupabaseClient | None = None) -> dict[str, Any]:
    """Insert a change-log entry; returns the stored row."""
    forget_reads(str(row.get("store")))
    return (c or cro_client()).insert_returning("change_log", row)


def delete_change(store: str, entry_id: int, c: SupabaseClient | None = None) -> bool:
    """Remove one entry of this store (via cro.delete_change_log). True when a row was deleted."""
    forget_reads(store)
    return bool((c or cro_client()).rpc("delete_change_log", {"p_store": store, "p_id": entry_id}))


# ------------------------------------------------------------------------------------------ 114:
# free-shipping amount, recommendation status, experiments
def free_shipping(store: str, c: SupabaseClient | None = None) -> float | None:
    """The store's free-shipping amount (cro.store_settings), or None: not set, or 114 not run."""
    try:
        rows = (
            (c or cro_client())
            .select(
                "store_settings",
                [("select", "free_shipping_threshold"), ("store", f"eq.{store}")],
                limit=1,
            )
            .rows
        )
    except SupabaseError:
        return None
    value = rows[0].get("free_shipping_threshold") if rows else None
    return float(value) if value is not None else None


def set_free_shipping(
    store: str, amount: float | None, by: str, c: SupabaseClient | None = None
) -> None:
    """Save (or clear, with None) the store's free-shipping amount."""
    forget_reads(store)
    (c or cro_client()).upsert(
        "store_settings",
        [{"store": store, "free_shipping_threshold": amount, "updated_by": by[:200]}],
        on_conflict="store",
    )


def rec_statuses(store: str, c: SupabaseClient | None = None) -> dict[str, dict[str, Any]]:
    """The team's status per recommendation key for a store (keys without a row are open)."""
    rows = (
        (c or cro_client())
        .select(
            "recommendation_status",
            [("select", "rec_key,status,updated_by,updated_at"), ("store", f"eq.{store}")],
        )
        .rows
    )
    return {str(r["rec_key"]): r for r in rows}


def set_rec_status(
    store: str, key: str, status: str, by: str, c: SupabaseClient | None = None
) -> None:
    """Save the status of one recommendation."""
    forget_reads(store)
    (c or cro_client()).upsert(
        "recommendation_status",
        [
            {
                "store": store,
                "rec_key": key[:300],
                "status": status,
                "updated_by": by[:200],
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ],
        on_conflict="store,rec_key",
    )


EXPERIMENT_COLUMNS = (
    "id,store,name,hypothesis,metric,page_path,start_date,end_date,owner,rec_key,created_by,"
    "created_at,updated_at"
)


def experiments(store: str, c: SupabaseClient | None = None) -> list[dict[str, Any]]:
    """A store's experiments, newest start first."""
    return (
        (c or cro_client())
        .select(
            "experiments",
            [
                ("select", EXPERIMENT_COLUMNS),
                ("store", f"eq.{store}"),
                ("order", "start_date.desc,id.desc"),
            ],
        )
        .rows
    )


def experiment(store: str, exp_id: int, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """One experiment of this store, or None."""
    rows = (
        (c or cro_client())
        .select(
            "experiments",
            [("select", EXPERIMENT_COLUMNS), ("id", f"eq.{exp_id}"), ("store", f"eq.{store}")],
            limit=1,
        )
        .rows
    )
    return rows[0] if rows else None


def add_experiment(row: dict[str, Any], c: SupabaseClient | None = None) -> dict[str, Any]:
    """Insert an experiment; returns the stored row."""
    forget_reads(str(row.get("store")))
    return (c or cro_client()).insert_returning("experiments", row)


def update_experiment(
    store: str, exp_id: int, values: dict[str, Any], c: SupabaseClient | None = None
) -> None:
    """Change an experiment of this store."""
    forget_reads(store)
    (c or cro_client()).update(
        "experiments", [("id", f"eq.{exp_id}"), ("store", f"eq.{store}")], values
    )


def delete_experiment(store: str, exp_id: int, c: SupabaseClient | None = None) -> bool:
    """Remove one experiment of this store (cro.delete_experiment). True when one was deleted."""
    forget_reads(store)
    return bool((c or cro_client()).rpc("delete_experiment", {"p_store": store, "p_id": exp_id}))
