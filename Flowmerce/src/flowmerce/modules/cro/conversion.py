"""Sessions, conversion rate, the cart/checkout funnel and device/channel splits, from Shopify
(ShopifyQL).

* Rates are computed here from session counts (completed checkouts / sessions, and so on), so they
  never depend on whether Shopify returns a percentage as 2.5 or 0.025.
* Days are the store's local days (Shopify applies the shop's timezone). Today is left out: it is
  not complete.
* Answers are cached per store and query for `cache_seconds` (default 10 minutes).
* Needs the read_reports scope and Level 2 protected customer data access; without them every
  function raises shopify.AnalyticsError('reports_access_missing').
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from typing import Any

from . import shopify
from .config import cro_config

FUNNEL_FIELDS = (
    "sessions, sessions_with_cart_additions, sessions_that_reached_checkout, "
    "sessions_that_completed_checkout"
)
DIMENSIONS = {"device": "session_device_type", "channel": "referrer_source"}

_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _rate(part: int, whole: int, digits: int = 2) -> float | None:
    return round(part / whole * 100, digits) if whole else None


def run(store: str, query: str, gql: shopify.Gql | None = None) -> list[dict[str, Any]]:
    """Run a ShopifyQL query for a store, reusing a recent answer."""
    key = (store, query)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    rows = shopify.shopifyql(gql or shopify.gql_for(store), query)
    with _lock:
        _cache[key] = (time.monotonic() + cro_config().cache_seconds, rows)
    return rows


def clear_cache() -> None:
    """Forget every cached ShopifyQL answer."""
    with _lock:
        _cache.clear()


def funnel_row(day: str, row: dict[str, Any]) -> dict[str, Any]:
    """One day (or period) of the funnel with its rates."""
    sessions = _int(row.get("sessions"))
    cart = _int(row.get("sessions_with_cart_additions"))
    checkout = _int(row.get("sessions_that_reached_checkout"))
    done = _int(row.get("sessions_that_completed_checkout"))
    return {
        "date": day,
        "sessions": sessions,
        "added_to_cart": cart,
        "reached_checkout": checkout,
        "completed_checkout": done,
        "cart_rate": _rate(cart, sessions, 1),
        "checkout_rate": _rate(checkout, sessions, 1),
        "conversion_rate": _rate(done, sessions),
        "cart_abandonment_rate": _rate(cart - done, cart, 1),
        "checkout_abandonment_rate": _rate(checkout - done, checkout, 1),
        "checkout_completion_rate": _rate(done, checkout, 1),
    }


def daily(
    store: str, today: date, days: int, gql: shopify.Gql | None = None
) -> list[dict[str, Any]]:
    """The funnel for each of the last `days` complete local days, oldest first."""
    query = (
        f"FROM sessions SHOW {FUNNEL_FIELDS} TIMESERIES day "
        f"SINCE -{days + 1}d UNTIL today ORDER BY day ASC"
    )
    out = []
    for row in run(store, query, gql):
        day = str(row.get("day") or "")[:10]
        if day and day < today.isoformat():
            out.append(funnel_row(day, row))
    return out[-days:]


def daily_between(
    store: str, start: date, end: date, today: date, gql: shopify.Gql | None = None
) -> list[dict[str, Any]]:
    """The funnel for each complete local day from start to end (inclusive), oldest first. Today is
    left out: Shopify's figures for it are not complete."""
    last = min(end, today - timedelta(days=1))
    if last < start:
        return []
    query = (
        f"FROM sessions SHOW {FUNNEL_FIELDS} TIMESERIES day "
        f"SINCE {start.isoformat()} UNTIL {last.isoformat()} ORDER BY day ASC"
    )
    out = []
    for row in run(store, query, gql):
        day = str(row.get("day") or "")[:10]
        if day and start.isoformat() <= day <= last.isoformat():
            out.append(funnel_row(day, row))
    return out


def totals(rows: list[dict[str, Any]], day: str = "") -> dict[str, Any]:
    """Several days of the funnel added up into one row with its rates."""
    keys = ("sessions", "added_to_cart", "reached_checkout", "completed_checkout")
    t = {k: sum(int(r.get(k) or 0) for r in rows) for k in keys}
    return funnel_row(
        day,
        {
            "sessions": t["sessions"],
            "sessions_with_cart_additions": t["added_to_cart"],
            "sessions_that_reached_checkout": t["reached_checkout"],
            "sessions_that_completed_checkout": t["completed_checkout"],
        },
    )


def cvr_comparison(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Yesterday's conversion rate against the day before, and the % drop (None when not
    computable).
    """
    by_day = {r["date"]: r for r in rows}
    y_day = (today - timedelta(days=1)).isoformat()
    p_day = (today - timedelta(days=2)).isoformat()
    y = (by_day.get(y_day) or {}).get("conversion_rate")
    p = (by_day.get(p_day) or {}).get("conversion_rate")
    drop = round((p - y) / p * 100, 2) if y is not None and p else None
    return {
        "yesterday_date": y_day,
        "yesterday_cvr": y,
        "previous_date": p_day,
        "previous_cvr": p,
        "drop_percent": drop,
    }


def _segment(
    store: str, field: str, since: str, until: str, gql: shopify.Gql | None
) -> list[dict[str, Any]]:
    query = (
        "FROM sessions SHOW sessions, sessions_with_cart_additions, "
        "sessions_that_completed_checkout "
        f"GROUP BY {field} WITH TOTALS SINCE {since} UNTIL {until} ORDER BY sessions DESC"
    )
    out = []
    for row in run(store, query, gql):
        label = row.get(field)
        if label is None:
            continue  # the WITH TOTALS row
        sessions = _int(row.get("sessions"))
        done = _int(row.get("sessions_that_completed_checkout"))
        out.append(
            {
                "label": str(label).strip() or "Unknown",
                "sessions": sessions,
                "orders": done,
                "added_to_cart_rate": _rate(
                    _int(row.get("sessions_with_cart_additions")), sessions
                ),
                "conversion_rate": _rate(done, sessions),
            }
        )
    return out


def segments(
    store: str, dimension: str, days: int, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Device or channel split of the last `days` days against the `days` before them."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown dimension {dimension!r}; expected device or channel.")
    field = DIMENSIONS[dimension]
    current = _segment(store, field, f"-{days}d", "today", gql)
    base_rows = _segment(store, field, f"-{days * 2}d", f"-{days}d", gql)
    return {**_split(dimension, current, base_rows), "days": days}


def segments_between(
    store: str,
    dimension: str,
    current: tuple[date, date],
    baseline: tuple[date, date] | None,
    gql: shopify.Gql | None = None,
) -> dict[str, Any]:
    """Device or channel split of a date range, against an optional earlier range."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown dimension {dimension!r}; expected device or channel.")
    field = DIMENSIONS[dimension]
    rows = _segment(store, field, current[0].isoformat(), current[1].isoformat(), gql)
    base_rows = (
        _segment(store, field, baseline[0].isoformat(), baseline[1].isoformat(), gql)
        if baseline
        else []
    )
    return {**_split(dimension, rows, base_rows), "days": (current[1] - current[0]).days + 1}


def _split(
    dimension: str, current: list[dict[str, Any]], base_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    base = {r["label"]: r for r in base_rows}
    rows = []
    for r in current:
        b = base.get(r["label"])
        rows.append(
            {
                **r,
                "baseline_sessions": b["sessions"] if b else None,
                "baseline_conversion_rate": b["conversion_rate"] if b else None,
                "sessions_change_pct": (
                    round((r["sessions"] - b["sessions"]) / b["sessions"] * 100, 1)
                    if b and b["sessions"]
                    else None
                ),
                "conversion_rate_change_pts": (
                    round(r["conversion_rate"] - b["conversion_rate"], 2)
                    if b and b["conversion_rate"] is not None and r["conversion_rate"] is not None
                    else None
                ),
            }
        )
    return {
        "dimension": dimension,
        "rows": rows,
        "revenue_available": False,
        "revenue_note": (
            "AOV and revenue per session are not split by device or channel: Shopify does not "
            "link order revenue to the session's device or channel in this data."
        ),
    }
