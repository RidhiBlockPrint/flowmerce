"""Sessions, conversion rate, the cart/checkout funnel and device/channel splits, from Shopify
(ShopifyQL).

* Rates are computed here from session counts (completed checkouts / sessions, and so on), so they
  never depend on whether Shopify returns a percentage as 2.5 or 0.025.
* Days are the store's local days (Shopify applies the shop's timezone). Today is left out: it is
  not complete.
* Answers are cached per store and query for `cache_seconds` (default 10 minutes).
* Sessions are human sessions only (`human_or_bot_session = 'Human'`), as in Shopify Analytics'
  own reports, so sessions, conversion rate and the funnel match what Shopify shows.
* Money comes from Shopify's `sales` report, which books a refund on the day it is made (not on
  the day of the order), so a day's sales match Shopify's own reports.
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
HUMAN = "WHERE human_or_bot_session = 'Human' "  # bots left out, as in Shopify's own reports
SALES_FIELDS = (
    "orders, gross_sales, discounts, returns, net_sales, shipping_charges, taxes, total_sales"
)
SALES_KEYS = ("orders", "gross", "discounts", "returns", "net", "shipping", "tax", "total")
MIN_ALARM_SESSIONS = 30  # a day with fewer sessions gives no reliable conversion rate

_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return 0


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except TypeError, ValueError:
        return 0.0


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _rate(part: int, whole: int, digits: int = 2) -> float | None:
    return round(part / whole * 100, digits) if whole else None


# A page opened with nothing cached asks Shopify ~30 report queries at once. A query already being
# read is not asked again: a second caller waits for that answer (the Overview asks some twice). At
# most MAX_PARALLEL queries per store run at once, so a very large burst queues instead of all going
# out together (measured 2026-11-21: 6 slowed the cold Overview from 3.6 s to 5.8 s; Shopify still
# throttles many queries in a short time whatever the cap, so the cap is kept loose).
MAX_PARALLEL = 10
_slots: dict[str, threading.BoundedSemaphore] = {}
_key_locks: dict[tuple[str, str], threading.Lock] = {}


def _cached(key: tuple[str, str]) -> list[dict[str, Any]] | None:
    with _lock:
        hit = _cache.get(key)
        return hit[1] if hit and hit[0] > time.monotonic() else None


def _locks_for(key: tuple[str, str]) -> tuple[threading.Lock, threading.BoundedSemaphore]:
    with _lock:
        if len(_key_locks) > 5000:  # old dates' queries: drop the idle locks
            for k in [k for k, lk in _key_locks.items() if not lk.locked()]:
                del _key_locks[k]
        key_lock = _key_locks.setdefault(key, threading.Lock())
        slot = _slots.setdefault(key[0], threading.BoundedSemaphore(MAX_PARALLEL))
    return key_lock, slot


def run(store: str, query: str, gql: shopify.Gql | None = None) -> list[dict[str, Any]]:
    """Run a ShopifyQL query for a store, reusing a recent answer (and one being read now)."""
    key = (store, query)
    hit = _cached(key)
    if hit is not None:
        return hit
    key_lock, slot = _locks_for(key)
    with key_lock:
        hit = _cached(key)  # read by another caller while this one waited
        if hit is not None:
            return hit
        with slot:
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
        f"FROM sessions SHOW {FUNNEL_FIELDS} {HUMAN}TIMESERIES day "
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
        f"FROM sessions SHOW {FUNNEL_FIELDS} {HUMAN}TIMESERIES day "
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


def cvr_vs_weekday_average(
    rows: list[dict[str, Any]], today: date, weeks: int = 4
) -> dict[str, Any]:
    """Yesterday's conversion rate against the average of the same weekday in the `weeks` weeks
    before, and the % drop. Days with fewer than MIN_ALARM_SESSIONS sessions are left out of the
    average; drop_percent is None (with a `reason`) when yesterday has too few sessions or fewer
    than `weeks - 1` past weekdays are usable. `rows` are daily funnel rows (`daily()`)."""
    by_day = {r["date"]: r for r in rows}
    yesterday = today - timedelta(days=1)
    y_row = by_day.get(yesterday.isoformat()) or {}
    y_cvr = y_row.get("conversion_rate")
    y_sessions = int(y_row.get("sessions") or 0)
    baseline = []
    for w in range(1, weeks + 1):
        d = (yesterday - timedelta(days=7 * w)).isoformat()
        row = by_day.get(d)
        if (
            row
            and row.get("conversion_rate") is not None
            and int(row.get("sessions") or 0) >= MIN_ALARM_SESSIONS
        ):
            baseline.append(
                {"date": d, "cvr": row["conversion_rate"], "sessions": int(row["sessions"])}
            )
    avg = round(sum(b["cvr"] for b in baseline) / len(baseline), 2) if baseline else None
    drop = None
    reason = None
    if y_cvr is None or y_sessions < MIN_ALARM_SESSIONS:
        reason = "too_few_sessions_yesterday"
    elif len(baseline) < max(2, weeks - 1) or not avg:
        reason = "not_enough_past_weeks"
    else:
        drop = round((avg - y_cvr) / avg * 100, 2)
    return {
        "yesterday_date": yesterday.isoformat(),
        "yesterday_weekday": f"{yesterday:%A}",
        "yesterday_cvr": y_cvr,
        "yesterday_sessions": y_sessions,
        "baseline_weeks": weeks,
        "baseline_days": baseline,
        "baseline_cvr": avg,
        "drop_percent": drop,
        "reason": reason,
    }


def _money_row(row: dict[str, Any]) -> dict[str, float]:
    # Shopify gives discounts and returns as negative amounts; they are kept positive here (the
    # app shows them with a minus sign), as in the order-based figures.
    return {
        "orders": _int(row.get("orders")),
        "gross": round(_num(row.get("gross_sales")), 2),
        "discounts": round(abs(_num(row.get("discounts"))), 2),
        "returns": round(abs(_num(row.get("returns"))), 2),
        "net": round(_num(row.get("net_sales")), 2),
        "shipping": round(_num(row.get("shipping_charges")), 2),
        "tax": round(_num(row.get("taxes")), 2),
        "total": round(_num(row.get("total_sales")), 2),
    }


def sales_daily(
    store: str, start: date, end: date, gql: shopify.Gql | None = None
) -> dict[str, dict[str, float]]:
    """Shopify's own sales figures for each local day start..end (inclusive): orders, gross,
    discounts, returns, net, shipping, tax and total. Days without sales are zeros. Refunds count
    on the day they were made, as in Shopify's reports."""
    query = (
        f"FROM sales SHOW {SALES_FIELDS} TIMESERIES day "
        f"SINCE {start.isoformat()} UNTIL {end.isoformat()} ORDER BY day ASC"
    )
    out = {
        (start + timedelta(days=i)).isoformat(): _money_row({})
        for i in range((end - start).days + 1)
    }
    for row in run(store, query, gql):
        day = str(row.get("day") or "")[:10]
        if day in out:
            out[day] = _money_row(row)
    return out


FUNNEL_STEPS = (
    ("sessions", "sessions"),
    ("added_to_cart", "sessions_with_cart_additions"),
    ("reached_checkout", "sessions_that_reached_checkout"),
    ("completed_checkout", "sessions_that_completed_checkout"),
)


def device_funnel(row: dict[str, Any]) -> dict[str, Any]:
    """One device's (or all devices') funnel counts with each step's share of sessions and its
    share of the step before."""
    sessions = int(row.get("sessions") or 0)
    viewed = row.get("viewed_product")
    steps = [
        ("viewed_product", viewed),
        *((k, int(row.get(k) or 0)) for k, _ in FUNNEL_STEPS[1:]),
    ]
    out: dict[str, Any] = {"sessions": sessions, "steps": []}
    before: int | None = sessions
    for key, count in steps:
        out["steps"].append(
            {
                "key": key,
                "count": count,
                "pct_of_sessions": _rate(count, sessions, 1) if count is not None else None,
                "pct_of_previous": (
                    _rate(count, before, 1) if count is not None and before else None
                ),
            }
        )
        if count is not None:
            before = count
    out["conversion_rate"] = _rate(int(row.get("completed_checkout") or 0), sessions)
    return out


def funnel_by_device(
    store: str, start: date, end: date, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """The funnel for local days start..end (inclusive), for all devices and for each device,
    with a "viewed a product" step between sessions and cart. When Shopify does not answer the
    product-view split, the funnel is returned without that step (`viewed_product` None)."""
    window = f"SINCE {start.isoformat()} UNTIL {end.isoformat()}"
    shown = ", ".join(f for _, f in FUNNEL_STEPS)
    devices: dict[str, dict[str, Any]] = {}

    def bucket(label: Any) -> dict[str, Any]:
        name = str(label or "").strip().title() or "Unknown"
        return devices.setdefault(name, {**{k: 0 for k, _ in FUNNEL_STEPS}, "viewed_product": None})

    views = True
    try:
        rows = run(
            store,
            f"FROM sessions SHOW {shown} {HUMAN}"
            f"GROUP BY session_device_type, session_viewed_product {window}",
            gql,
        )
    except shopify.AnalyticsError as e:
        if e.state != "query_error":
            raise
        views = False
        rows = run(
            store, f"FROM sessions SHOW {shown} {HUMAN}GROUP BY session_device_type {window}", gql
        )
    for row in rows:
        if row.get("session_device_type") is None:
            continue  # a totals row
        d = bucket(row.get("session_device_type"))
        for key, field in FUNNEL_STEPS:
            d[key] += _int(row.get(field))
        if views:
            d["viewed_product"] = (d["viewed_product"] or 0) + (
                _int(row.get("sessions")) if _is_true(row.get("session_viewed_product")) else 0
            )
    total: dict[str, Any] = {k: sum(d[k] for d in devices.values()) for k, _ in FUNNEL_STEPS}
    total["viewed_product"] = (
        sum(d["viewed_product"] or 0 for d in devices.values()) if views else None
    )
    ordered = sorted(devices.items(), key=lambda kv: -int(kv[1]["sessions"]))
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "product_views_available": views,
        "all": device_funnel(total),
        "devices": [{"label": k, **device_funnel(v)} for k, v in ordered],
    }


def _segment(
    store: str, field: str, since: str, until: str, gql: shopify.Gql | None
) -> list[dict[str, Any]]:
    query = (
        "FROM sessions SHOW sessions, sessions_with_cart_additions, "
        f"sessions_that_completed_checkout {HUMAN}"
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
