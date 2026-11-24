"""Where visits come from and what changed, from Shopify (ShopifyQL), bots left out.

* where_changed: device and channel splits of a period against its comparison. Each segment's change
  in purchases is split into a traffic effect ((sessions now - sessions before) x conversion before)
  and a conversion effect (sessions now x (conversion now - conversion before)); the two add up to
  the change. The biggest effects become plain "top mover" sentences. Channels also get revenue per
  visit (ShopifyQL `sales` by the order's referrer source).
* geo: conversion by country and by US state.
* heatmap: conversion rate by weekday x hour in the store's time (Shopify's hour buckets are UTC).
* trends: average order value by day and sales by sales channel.
Every reader takes local-day windows (first, last), inclusive. `run_many` runs several queries at
once and reports the ones that failed instead of failing the whole answer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import shopify
from .config import cro_config
from .conversion import HUMAN, run

Window = tuple[date, date]
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SEGMENT_FIELDS = {"device": "session_device_type", "channel": "referrer_source"}
MIN_TOTAL_SESSIONS = 500  # below this the top movers are not worked out (same rule as the cards)
MIN_HEAT_SESSIONS = 20  # a weekday-hour cell with fewer visits gets no conversion rate


def since(w: Window) -> str:
    """ShopifyQL SINCE/UNTIL for a local-day window."""
    return f"SINCE {w[0].isoformat()} UNTIL {w[1].isoformat()}"


def num(value: Any) -> float:
    """A ShopifyQL value as a float (0 when missing)."""
    try:
        return float(value or 0)
    except TypeError, ValueError:
        return 0.0


def nice(label: Any) -> str:
    """'mobile' -> 'Mobile'; empty -> 'Unknown'."""
    s = str(label or "").strip() or "Unknown"
    return s[:1].upper() + s[1:]


def rate(part: float, whole: float, digits: int = 2) -> float | None:
    """part / whole as a percentage, None when whole is 0."""
    return round(part / whole * 100, digits) if whole else None


def run_many(
    store: str, queries: dict[str, str], gql: shopify.Gql | None = None
) -> tuple[dict[str, list[dict[str, Any]] | None], dict[str, str]]:
    """Run several ShopifyQL queries at once. Returns (rows by name, error message by name); a
    failed query's rows are None."""

    def one(item: tuple[str, str]) -> tuple[str, list[dict[str, Any]] | None, str | None]:
        name, query = item
        try:
            return name, run(store, query, gql), None
        except shopify.AnalyticsError as e:
            return name, None, e.message[:300]

    rows: dict[str, list[dict[str, Any]] | None] = {}
    errors: dict[str, str] = {}
    workers = max(1, min(cro_config().read_workers, len(queries) or 1))  # CRO_READ_WORKERS
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, result, err in pool.map(one, queries.items()):
            rows[name] = result
            if err:
                errors[name] = err
    return rows, errors


def required(
    rows: dict[str, list[dict[str, Any]] | None], errors: dict[str, str], name: str
) -> list[dict[str, Any]]:
    """The rows of a query the answer cannot do without; raises when it failed."""
    got = rows.get(name)
    if got is None:
        raise shopify.AnalyticsError("shopify_error", errors.get(name) or "Shopify did not answer.")
    return got


def _sum_by(
    rows: list[dict[str, Any]] | None, field: str, keys: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in rows or []:
        if r.get(field) is None:
            continue  # a totals row
        k = str(r[field]).strip().lower() or "unknown"
        acc = out.setdefault(k, dict.fromkeys(keys, 0.0))
        for key in keys:
            acc[key] += num(r.get(key))
    return out


def _min_segment(days: int) -> int:
    return 100 if days <= 1 else (300 if days <= 7 else 800)


def changes(
    dim: str,
    cur: dict[str, dict[str, float]],
    prev: dict[str, dict[str, float]],
    days: int,
    sales_now: dict[str, dict[str, float]] | None = None,
    sales_before: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rows, movers) for one dimension (pure). `cur`/`prev`: label -> {sessions,
    sessions_that_completed_checkout}; `sales_*`: label -> {total_sales, orders} (channels)."""
    min_seg = _min_segment(days)
    rows: list[dict[str, Any]] = []
    movers: list[dict[str, Any]] = []
    for k in sorted(set(cur) | set(prev), key=lambda x: -cur.get(x, {}).get("sessions", 0)):
        s1 = int(cur.get(k, {}).get("sessions", 0))
        b1 = int(cur.get(k, {}).get("sessions_that_completed_checkout", 0))
        s0 = int(prev.get(k, {}).get("sessions", 0))
        b0 = int(prev.get(k, {}).get("sessions_that_completed_checkout", 0))
        if not s1 and not s0:
            continue
        c1 = b1 / s1 if s1 else None
        c0 = b0 / s0 if s0 else None
        traffic = (s1 - s0) * c0 if c0 is not None else None
        conv = s1 * (c1 - c0) if c1 is not None and c0 is not None else None
        row: dict[str, Any] = {
            "key": k,
            "label": nice(k),
            "sessions": s1,
            "previous_sessions": s0,
            "sessions_change_pct": round((s1 - s0) / s0 * 100, 1) if s0 else None,
            "conversion_rate": round(c1 * 100, 2) if c1 is not None else None,
            "previous_conversion_rate": round(c0 * 100, 2) if c0 is not None else None,
            "conversion_change_pts": (
                round((c1 - c0) * 100, 2) if c1 is not None and c0 is not None else None
            ),
            "purchases": b1,
            "previous_purchases": b0,
            "traffic_effect": round(traffic, 1) if traffic is not None else None,
            "conversion_effect": round(conv, 1) if conv is not None else None,
            "enough_data": s1 >= min_seg and s0 >= min_seg,
        }
        if sales_now is not None:
            r1 = (sales_now.get(k) or {}).get("total_sales")
            r0 = ((sales_before or {}).get(k) or {}).get("total_sales")
            row["revenue"] = round(r1, 2) if r1 is not None else 0.0
            row["revenue_per_session"] = round(r1 / s1, 2) if r1 is not None and s1 else None
            row["previous_revenue_per_session"] = (
                round(r0 / s0, 2) if r0 is not None and s0 else None
            )
            rps1, rps0 = row["revenue_per_session"], row["previous_revenue_per_session"]
            row["revenue_per_session_change_pct"] = (
                round((rps1 - rps0) / rps0 * 100, 1) if rps1 is not None and rps0 else None
            )
        rows.append(row)
        if not row["enough_data"]:
            continue
        label = row["label"]
        if conv is not None:
            subject = f"{label} conversion" if dim == "device" else f"Conversion from {label}"
            movers.append(
                {
                    "dimension": dim,
                    "segment": label,
                    "kind": "conversion",
                    "effect": conv,
                    "text": (
                        f"{subject} {'rose' if conv > 0 else 'fell'} from "
                        f"{row['previous_conversion_rate']}% to {row['conversion_rate']}% "
                        f"({row['conversion_change_pts']:+.2f} pts): about {abs(round(conv))} "
                        f"{'more' if conv > 0 else 'fewer'} purchases."
                    ),
                }
            )
        if traffic is not None:
            subject = f"{label} visits" if dim == "device" else f"Visits from {label}"
            movers.append(
                {
                    "dimension": dim,
                    "segment": label,
                    "kind": "traffic",
                    "effect": traffic,
                    "text": (
                        f"{subject} {'rose' if s1 > s0 else 'fell'} "
                        f"{abs(row['sessions_change_pct'] or 0):.0f}% ({s0:,} to {s1:,}): "
                        f"about {abs(round(traffic))} {'more' if traffic > 0 else 'fewer'} "
                        "purchases."
                    ),
                }
            )
    return rows, movers


def top_movers(movers: list[dict[str, Any]], total_sessions: int) -> list[dict[str, Any]]:
    """The 3 biggest effects (at least one purchase), none when there are too few visits."""
    if total_sessions < MIN_TOTAL_SESSIONS:
        return []
    picked = [m for m in sorted(movers, key=lambda m: -abs(m["effect"])) if abs(m["effect"]) >= 1]
    return [{**m, "effect": round(m["effect"], 1), "good": m["effect"] > 0} for m in picked[:3]]


def where_changed(
    store: str, cur: Window, base: Window, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Device and channel tables of `cur` against `base`, with the top movers."""
    queries: dict[str, str] = {}
    for dim, field in SEGMENT_FIELDS.items():
        for tag, w in (("cur", cur), ("prev", base)):
            queries[f"{dim}_{tag}"] = (
                f"FROM sessions SHOW sessions, sessions_that_completed_checkout {HUMAN}"
                f"GROUP BY {field} {since(w)} ORDER BY sessions DESC"
            )
    for tag, w in (("cur", cur), ("prev", base)):
        queries[f"sales_{tag}"] = (
            f"FROM sales SHOW total_sales, orders GROUP BY order_referrer_source {since(w)}"
        )
    rows, errors = run_many(store, queries, gql)
    days = (cur[1] - cur[0]).days + 1
    keys = ("sessions", "sessions_that_completed_checkout")
    sales_ok = rows.get("sales_cur") is not None
    tables: dict[str, list[dict[str, Any]]] = {}
    movers: list[dict[str, Any]] = []
    total = 0
    for dim, field in SEGMENT_FIELDS.items():
        now = _sum_by(required(rows, errors, f"{dim}_cur"), field, keys)
        before = _sum_by(rows.get(f"{dim}_prev"), field, keys)
        if dim == "device":
            total = int(sum(v["sessions"] for v in now.values()))
        sales = (
            (
                _sum_by(rows["sales_cur"], "order_referrer_source", ("total_sales", "orders")),
                _sum_by(rows.get("sales_prev"), "order_referrer_source", ("total_sales", "orders")),
            )
            if dim == "channel" and sales_ok
            else (None, None)
        )
        tables[dim], found = changes(dim, now, before, days, *sales)
        movers += found
    return {
        "total_sessions": total,
        "too_early": total < MIN_TOTAL_SESSIONS,
        "min_segment_sessions": _min_segment(days),
        "device": tables["device"],
        "channel": tables["channel"],
        "movers": top_movers(movers, total),
        "revenue_available": sales_ok,
        "errors": errors,
    }


GEO_SHOW = "sessions, sessions_with_cart_additions, sessions_that_completed_checkout"


def _geo_rows(
    now: list[dict[str, Any]], before: list[dict[str, Any]] | None, field: str, min_sessions: int
) -> list[dict[str, Any]]:
    keys = ("sessions", "sessions_with_cart_additions", "sessions_that_completed_checkout")
    cur = _sum_by(now, field, keys)
    prev = _sum_by(before, field, keys)
    labels = {
        str(r[field]).strip().lower() or "unknown": nice(r[field]) for r in now if r.get(field)
    }
    out: list[dict[str, Any]] = []
    for k, v in sorted(cur.items(), key=lambda kv: -kv[1]["sessions"]):
        s = int(v["sessions"])
        p = prev.get(k)
        cvr = rate(v["sessions_that_completed_checkout"], s)
        p_cvr = rate(p["sessions_that_completed_checkout"], p["sessions"]) if p else None
        enough = s >= min_sessions and p is not None and p["sessions"] >= min_sessions
        out.append(
            {
                "label": labels.get(k, nice(k)),
                "sessions": s,
                "share_pct": None,
                "cart_rate": rate(v["sessions_with_cart_additions"], s, 1),
                "conversion_rate": cvr,
                "orders": int(v["sessions_that_completed_checkout"]),
                "previous_sessions": int(p["sessions"]) if p else None,
                "previous_conversion_rate": p_cvr,
                "conversion_change_pts": (
                    round(cvr - p_cvr, 2)
                    if enough and cvr is not None and p_cvr is not None
                    else None
                ),
                "too_few_sessions": s < min_sessions,
            }
        )
    total = sum(r["sessions"] for r in out)
    for r in out:
        r["share_pct"] = rate(r["sessions"], total, 1)
    return out


def geo(
    store: str, cur: Window, base: Window | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Conversion by country and by US state, against the comparison window."""
    us = "WHERE human_or_bot_session = 'Human' AND session_country_code = 'US' "
    queries = {
        "countries": f"FROM sessions SHOW {GEO_SHOW} {HUMAN}GROUP BY session_country "
        f"{since(cur)} ORDER BY sessions DESC LIMIT 60",
        "states": f"FROM sessions SHOW {GEO_SHOW} {us}GROUP BY session_region "
        f"{since(cur)} ORDER BY sessions DESC LIMIT 70",
    }
    if base:
        queries["countries_prev"] = (
            f"FROM sessions SHOW {GEO_SHOW} {HUMAN}GROUP BY session_country "
            f"{since(base)} ORDER BY sessions DESC LIMIT 60"
        )
        queries["states_prev"] = (
            f"FROM sessions SHOW {GEO_SHOW} {us}GROUP BY session_region "
            f"{since(base)} ORDER BY sessions DESC LIMIT 70"
        )
    rows, errors = run_many(store, queries, gql)
    days = (cur[1] - cur[0]).days + 1
    min_sessions = 30 if days <= 1 else 100
    return {
        "min_sessions": min_sessions,
        "countries": _geo_rows(
            required(rows, errors, "countries"),
            rows.get("countries_prev"),
            "session_country",
            min_sessions,
        ),
        "us_states": _geo_rows(
            rows.get("states") or [], rows.get("states_prev"), "session_region", min_sessions
        ),
        "errors": errors,
    }


def local_hour(value: Any, tz: ZoneInfo) -> datetime | None:
    """A ShopifyQL hour bucket ('2026-11-19T05:00:00Z') in the store's time."""
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(tz) if at.tzinfo else None


def heat_grid(rows: list[dict[str, Any]], tz: ZoneInfo, first: date, last: date) -> dict[str, Any]:
    """Weekday x hour cells (store time) from hourly session rows (pure)."""
    grid = {(w, h): [0, 0] for w in range(7) for h in range(24)}
    seen: set[str] = set()
    for r in rows:
        key = str(r.get("hour"))
        t = local_hour(r.get("hour"), tz)
        if t is None or key in seen or not first <= t.date() <= last:
            continue
        seen.add(key)
        cell = grid[(t.weekday(), t.hour)]
        cell[0] += int(num(r.get("sessions")))
        cell[1] += int(num(r.get("sessions_that_completed_checkout")))
    cells: list[dict[str, Any]] = [
        {
            "weekday": w,
            "hour": h,
            "sessions": s,
            "orders": o,
            "cvr": rate(o, s) if s >= MIN_HEAT_SESSIONS else None,
        }
        for (w, h), (s, o) in sorted(grid.items())
    ]
    sessions = sum(c["sessions"] for c in cells)
    return {
        "metric": "cvr",
        "weekdays": list(WEEKDAYS),
        "cells": cells,
        "hours_with_data": len(seen),
        "average_cvr": rate(sum(c["orders"] for c in cells), sessions),
    }


def heatmap(
    store: str, first: date, last: date, tz: ZoneInfo, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Conversion by weekday x hour over local days first..last. Asked in 7-day pieces (Shopify
    refuses long hourly queries), each a day wider on both sides because UTC hours spill over local
    days."""
    pieces: list[Window] = []
    a = first
    while a <= last:
        b = min(a + timedelta(days=6), last)
        pieces.append((a, b))
        a = b + timedelta(days=1)

    def one(w: Window) -> list[dict[str, Any]]:
        return run(
            store,
            f"FROM sessions SHOW sessions, sessions_that_completed_checkout {HUMAN}"
            f"TIMESERIES hour {since((w[0] - timedelta(days=1), w[1] + timedelta(days=1)))}",
            gql,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(one, pieces))
    out = heat_grid([r for part in parts for r in part], tz, first, last)
    if not out["hours_with_data"]:
        raise shopify.AnalyticsError("shopify_error", "Shopify returned no hourly visits.")
    return out


def trends(
    store: str, cur: Window, base: Window | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Average order value by day (and of the comparison days) and sales by sales channel."""
    queries = {
        "aov": f"FROM sales SHOW average_order_value, orders TIMESERIES day {since(cur)} "
        "ORDER BY day ASC",
        "channels": f"FROM sales SHOW total_sales, orders GROUP BY sales_channel {since(cur)} "
        "ORDER BY total_sales DESC",
    }
    if base:
        queries["aov_prev"] = (
            f"FROM sales SHOW average_order_value, orders TIMESERIES day {since(base)} "
            "ORDER BY day ASC"
        )
    rows, errors = run_many(store, queries, gql)

    def series(got: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [
            {
                "date": str(r.get("day"))[:10],
                "aov": round(num(r.get("average_order_value")), 2),
                "orders": int(num(r.get("orders"))),
            }
            for r in got or []
            if r.get("day")
        ]

    channels: list[dict[str, Any]] = [
        {
            "label": str(r.get("sales_channel")).strip() or "Other",
            "total_sales": round(num(r.get("total_sales")), 2),
            "orders": int(num(r.get("orders"))),
        }
        for r in rows.get("channels") or []
        if r.get("sales_channel") is not None
    ]
    total = sum(c["total_sales"] for c in channels)
    for c in channels:
        c["share_pct"] = rate(c["total_sales"], total, 1)
    return {
        "aov": series(rows.get("aov")),
        "previous_aov": series(rows.get("aov_prev")),
        "channels": channels,
        "errors": errors,
    }
