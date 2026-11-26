"""Reads and writes in schema `ads` (Supabase). Totals are added up in the database
(db/central/115_ads.sql), so the server never holds a long list of daily rows in memory.

Every function takes an optional client (tests pass a fake one) and raises SupabaseError on a
database problem.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

from ..shipping.supabase import SupabaseClient
from .config import ads_client

STRUCTURE_SECONDS = (
    300  # campaigns, ad sets and ads are kept in memory this long per account (a few hundred KB)
)
# Every Supabase round trip costs 0.3 to 0.9 s (measured 2026-11-24), so rows that rarely change
# (the account, the rules, the rupee rate, the newest saved day) are kept this long, and each
# finished page answer is kept ANSWER_SECONDS. Every write below and every Meta read clears both
# (forget), so a change shows at once. Answers are small (a few KB to a few hundred KB) and at most
# ANSWER_MAX are kept: Render's 512 MB limit (see docs/operations/hosting-render.md). Measured
# 2026-11-24: an Overview is 6 KB, Campaigns 30 KB, Creatives up to 300 KB as JSON, so 24 answers
# stay a few MB in normal use and about 30 MB at most.
SMALL_SECONDS = 300
ANSWER_SECONDS = 300
ANSWER_MAX = 24


def _c(c: SupabaseClient | None) -> SupabaseClient:
    return c or ads_client()


_small: dict[Hashable, tuple[float, Any]] = {}
_answers: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
_kept_lock = threading.Lock()


def _small_read[T](key: Hashable, c: SupabaseClient | None, read: Callable[[], T]) -> T:
    """`read()`, kept SMALL_SECONDS. A test's own client (c) is never served from or stored in
    memory."""
    if c is not None:
        return read()
    with _kept_lock:
        hit = _small.get(key)
        if hit and time.monotonic() - hit[0] < SMALL_SECONDS:
            return hit[1]  # type: ignore[no-any-return]
    out = read()
    with _kept_lock:
        _small[key] = (time.monotonic(), out)
    return out


def answer[T](key: Hashable, make: Callable[[], T]) -> T:
    """A page answer, kept ANSWER_SECONDS (the oldest dropped past ANSWER_MAX). Errors are not
    kept. Callers must not change what they get back: the next request is served the same object."""
    if ANSWER_SECONDS <= 0:
        return make()
    with _kept_lock:
        hit = _answers.get(key)
        if hit and time.monotonic() - hit[0] < ANSWER_SECONDS:
            _answers.move_to_end(key)
            return hit[1]  # type: ignore[no-any-return]
    out = make()
    with _kept_lock:
        _answers[key] = (time.monotonic(), out)
        _answers.move_to_end(key)
        while len(_answers) > ANSWER_MAX:
            _answers.popitem(last=False)
    return out


def _changed() -> None:
    """Something was written: drop the kept rows and answers (both brands; refilling is cheap)."""
    with _kept_lock:
        _small.clear()
        _answers.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _all(c: SupabaseClient, table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every row of a select, 1,000 at a time."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = c.select(table, params, offset=offset, limit=1000)
        out.extend(page.rows)
        if len(page.rows) < 1000:
            return out
        offset += 1000


# ------------------------------------------------------------------ accounts and sync state
def account(key: str, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """The account row (with its sync state), or None before its first sync."""

    def read() -> dict[str, Any] | None:
        rows = _c(c).select("accounts", [("select", "*"), ("key", f"eq.{key}")], limit=1).rows
        return rows[0] if rows else None

    row = _small_read(("account", key), c, read)
    return dict(row) if row is not None else None


def save_account(row: dict[str, Any], c: SupabaseClient | None = None) -> None:
    """Create or update the account's details (not its sync state)."""
    _c(c).upsert("accounts", [row], on_conflict="key")
    _changed()


def begin_sync(key: str, c: SupabaseClient | None = None) -> dict[str, Any] | None:
    """Take the account's sync lock. None when another sync holds it."""
    rows = _c(c).rpc("begin_sync", {"p_key": key}) or []
    _changed()
    return rows[0] if rows else None


def end_sync(
    key: str,
    ok: bool,
    error: str | None,
    full: bool,
    first_day: date | None,
    c: SupabaseClient | None = None,
) -> None:
    """Release the lock and record how the sync went."""
    _c(c).rpc(
        "end_sync",
        {
            "p_key": key,
            "p_ok": ok,
            "p_error": error,
            "p_full": full,
            "p_first_day": first_day.isoformat() if first_day else None,
        },
    )
    _changed()


def mark_loaded_from(key: str, day: date, c: SupabaseClient | None = None) -> None:
    """Record the oldest day loaded when a first load stopped part-way (only if none is set)."""
    _c(c).update(
        "accounts", [("key", f"eq.{key}"), ("first_day", "is.null")], {"first_day": day.isoformat()}
    )
    _changed()


# ------------------------------------------------------------------ structure
def save_structure(table: str, rows: list[dict[str, Any]], c: SupabaseClient | None = None) -> None:
    """Upsert campaigns, ad sets or ads, 500 rows per request. Rows of one call must have the same
    keys."""
    for i in range(0, len(rows), 500):
        _c(c).upsert(table, rows[i : i + 500], on_conflict="id")


def budgets(key: str, c: SupabaseClient | None = None) -> dict[str, dict[str, Any]]:
    """{campaign id: {daily_budget, budget_changed_at}} as stored, to notice a budget change."""
    rows = _all(
        _c(c),
        "campaigns",
        [("select", "id,daily_budget,budget_changed_at"), ("account_key", f"eq.{key}")],
    )
    return {r["id"]: r for r in rows}


def save_lifetime(
    key: str, rows: list[dict[str, Any]], at: datetime, c: SupabaseClient | None = None
) -> int:
    """Store each ad's lifetime totals in one database call. Ads Meta no longer lists (deleted) are
    skipped. Returns the ads updated."""
    n = _c(c).rpc("save_lifetime", {"p_key": key, "p_at": at.isoformat(), "p_rows": rows})
    return int(n or 0)


def replace_daily(
    key: str, since: date, until: date, rows: list[dict[str, Any]], c: SupabaseClient | None = None
) -> int:
    """Replace the account's daily rows for since..until (one transaction). Returns the rows
    written."""
    n = _c(c).rpc(
        "replace_daily",
        {"p_key": key, "p_from": since.isoformat(), "p_to": until.isoformat(), "p_rows": rows},
    )
    return int(n or 0)


# ------------------------------------------------------------------ structure for the page (kept a
# few minutes)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def structure(key: str, c: SupabaseClient | None = None, *, fresh: bool = False) -> dict[str, Any]:
    """The account's campaigns, ad sets and ads ({campaigns, ad_sets, ads} lists), kept
    STRUCTURE_SECONDS."""
    with _lock:
        hit = _cache.get(key)
        if hit and not fresh and time.monotonic() - hit[0] < STRUCTURE_SECONDS:
            return hit[1]
    cl = _c(c)
    queries = {
        "campaigns": [
            ("select", "id,name,objective,status,daily_budget,budget_changed_at"),
            ("account_key", f"eq.{key}"),
        ],
        "ad_sets": [
            ("select", "id,campaign_id,name,status,daily_budget"),
            ("account_key", f"eq.{key}"),
        ],
        "ads": [
            (
                "select",
                "id,campaign_id,ad_set_id,name,status,created_time,post_id,format,"
                "video_length_s,lt_spend,lt_purchases,lt_value",
            ),
            ("account_key", f"eq.{key}"),
        ],
    }
    # The three lists at the same time (each round trip costs 0.3 to 0.9 s).
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {t: pool.submit(_all, cl, t, q) for t, q in queries.items()}
        out = {t: f.result() for t, f in futures.items()}
    with _lock:
        _cache[key] = (time.monotonic(), out)
    return out


def forget(key: str | None = None) -> None:
    """Drop the kept structure (after a sync or a change of rules), for one account or all, and
    every kept row and answer."""
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)
    _changed()


# ------------------------------------------------------------------ report functions (added up in
# the database)
def account_days(
    key: str, since: date, until: date, c: SupabaseClient | None = None
) -> list[dict[str, Any]]:
    """Per day totals of the account in US dollars, oldest first; a day without spend has no row."""
    return list(
        _c(c).rpc(
            "account_days", {"p_key": key, "p_from": since.isoformat(), "p_to": until.isoformat()}
        )
        or []
    )


def ad_windows(
    key: str,
    since: date,
    until: date,
    prev_from: date,
    prev_to: date,
    c: SupabaseClient | None = None,
) -> list[dict[str, Any]]:
    """Per ad totals in US dollars for the windows cur, prev, d3, d7 and d14 (see 115_ads.sql)."""
    return list(
        _c(c).rpc(
            "ad_windows",
            {
                "p_key": key,
                "p_from": since.isoformat(),
                "p_to": until.isoformat(),
                "p_prev_from": prev_from.isoformat(),
                "p_prev_to": prev_to.isoformat(),
            },
        )
        or []
    )


def store_days(
    store: str, tz: str, since: date, until: date, bulk_min: float, c: SupabaseClient | None = None
) -> list[dict[str, Any]]:
    """Store orders and sales per store-local day (cro.orders), with bulk orders counted apart."""
    return list(
        _c(c).rpc(
            "store_days",
            {
                "p_store": store,
                "p_tz": tz,
                "p_from": since.isoformat(),
                "p_to": until.isoformat(),
                "p_bulk_min": bulk_min,
            },
        )
        or []
    )


def latest_day(key: str, c: SupabaseClient | None = None) -> date | None:
    """The newest account day with saved figures, or None before the first read."""

    def read() -> date | None:
        rows = (
            _c(c)
            .select(
                "daily",
                [("select", "day"), ("account_key", f"eq.{key}"), ("order", "day.desc")],
                limit=1,
            )
            .rows
        )
        return date.fromisoformat(str(rows[0]["day"])) if rows else None

    return _small_read(("latest", key), c, read)


def fx_rate(currency: str, on: date, c: SupabaseClient | None = None) -> float:
    """Units of `currency` for one US dollar on a day (1 for USD)."""
    if currency == "USD":
        return 1.0

    def read() -> float:
        rows = (
            _c(c)
            .select(
                "fx_rates",
                [
                    ("select", "rate"),
                    ("currency", f"eq.{currency}"),
                    ("valid_from", f"lte.{on.isoformat()}"),
                    ("order", "valid_from.desc"),
                ],
                limit=1,
            )
            .rows
        )
        return float(rows[0]["rate"]) if rows else 1.0

    return _small_read(("fx", currency, on), c, read)


def fx_since(currency: str, c: SupabaseClient | None = None) -> str | None:
    """The day the current rate started."""

    def read() -> str | None:
        rows = (
            _c(c)
            .select(
                "fx_rates",
                [
                    ("select", "valid_from"),
                    ("currency", f"eq.{currency}"),
                    ("order", "valid_from.desc"),
                ],
                limit=1,
            )
            .rows
        )
        return str(rows[0]["valid_from"]) if rows else None

    return _small_read(("fx_since", currency), c, read)


def set_fx_rate(
    currency: str, on: date, rate: float, by: str, c: SupabaseClient | None = None
) -> None:
    """A new rate from `on` on (replacing one set earlier the same day). Earlier days keep their
    rate."""
    _c(c).upsert(
        "fx_rates",
        [{"currency": currency, "valid_from": on.isoformat(), "rate": rate, "set_by": by}],
        on_conflict="currency,valid_from",
    )
    _changed()


# ------------------------------------------------------------------ rules and actions
def rules(brand: str, c: SupabaseClient | None = None) -> dict[str, Any]:
    """The values the team changed for the brand ({} when none)."""

    def read() -> dict[str, Any]:
        rows = _c(c).select("rules", [("select", "rules"), ("brand", f"eq.{brand}")], limit=1).rows
        return dict(rows[0]["rules"]) if rows else {}

    return dict(_small_read(("rules", brand), c, read))


def save_rules(
    brand: str, values: dict[str, Any], by: str, c: SupabaseClient | None = None
) -> None:
    """Store the brand's changed values (the whole set)."""
    _c(c).upsert(
        "rules",
        [{"brand": brand, "rules": values, "updated_by": by, "updated_at": _now()}],
        on_conflict="brand",
    )
    _changed()


def action_status(brand: str, c: SupabaseClient | None = None) -> dict[str, str]:
    """{action id: 'done' | 'skipped'} for the brand."""
    rows = _all(_c(c), "action_status", [("select", "action_id,status"), ("brand", f"eq.{brand}")])
    return {r["action_id"]: r["status"] for r in rows}


def set_action_status(
    brand: str, action: dict[str, Any], status: str, by: str, c: SupabaseClient | None = None
) -> None:
    """Mark a suggestion done, skipped or open again, and add the change to the history."""
    cl = _c(c)
    if status == "open":
        cl.rpc("reopen_action", {"p_brand": brand, "p_action_id": action["id"]})
    else:
        cl.upsert(
            "action_status",
            [
                {
                    "brand": brand,
                    "action_id": action["id"],
                    "status": status,
                    "updated_by": by,
                    "updated_at": _now(),
                }
            ],
            on_conflict="brand,action_id",
        )
    cl.insert(
        "action_history",
        {
            "brand": brand,
            "action_id": action["id"],
            "title": action.get("title", ""),
            "grp": action.get("group", ""),
            "status": status,
            "by_user": by,
        },
    )
    _changed()


def action_history(
    brand: str, limit: int = 30, c: SupabaseClient | None = None
) -> list[dict[str, Any]]:
    """The brand's latest marks, newest first."""
    return (
        _c(c)
        .select(
            "action_history",
            [
                ("select", "id,action_id,title,grp,status,by_user,at"),
                ("brand", f"eq.{brand}"),
                ("order", "at.desc"),
            ],
            limit=limit,
        )
        .rows
    )
