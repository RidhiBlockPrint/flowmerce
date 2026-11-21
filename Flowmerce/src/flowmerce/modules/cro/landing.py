"""Landing pages, page types and bounce rate, from Shopify (ShopifyQL), bots left out.

Bounce is Shopify's definition: a visit that saw only one page; bounce rate = bounces / sessions.
ShopifyQL gives rates as decimals (0.25 = 25%); rows that collapse to one page (a trailing slash, a
query string) are merged, their rates weighted by sessions.

* landing_pages: per landing page its visits, bounce, add-to-cart and conversion rate, revenue and
  revenue per visit (ShopifyQL `sales` by the order's landing page), the top traffic source, and a
  flag when its bounce rate is 5+ points above the comparison period. Also page types, and bounce by
  traffic source and by device.
* grids: conversion of the top pages by traffic source, and of page types by device.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from . import shopify
from .conversion import HUMAN
from .traffic import Window, num, rate, required, run_many, since

SESSION_METRICS = "sessions, bounce_rate, added_to_cart_rate, conversion_rate"
BOUNCE_FLAG_PTS = 5.0  # a page's bounce rate this many points above its comparison is flagged
BOUNCE_DEFINITION = (
    "Shopify's definition: a bounce is a visit that saw only one page. Bounce rate = bounces / "
    "visits. Bots left out."
)


def min_sessions(days: int) -> int:
    """Below this a page's rates swing too much to judge (fewer visits on a single day)."""
    return 30 if days <= 1 else 100


def norm_path(value: Any) -> str:
    """'/products/x?variant=1' or 'https://shop.com/products/x/' -> '/products/x'."""
    s = str(value or "").strip()
    if "://" in s:
        s = urlparse(s).path
    s = s.split("?")[0].split("#")[0].rstrip("/").lower()
    return s or "/"


def rate_rows(rows: list[dict[str, Any]] | None, key: str) -> dict[str, dict[str, Any]]:
    """Rows grouped by `key` -> {label: {sessions, bounce_rate, added_to_cart_rate,
    conversion_rate}} with rates in % (pure)."""
    acc: dict[str, list[float]] = {}
    for r in rows or []:
        raw = r.get(key)
        if raw is None:
            continue  # a totals row
        label = norm_path(raw) if key == "landing_page_path" else (str(raw).strip() or "Unknown")
        s = num(r.get("sessions"))
        a = acc.setdefault(label, [0.0, 0.0, 0.0, 0.0])
        a[0] += s
        a[1] += num(r.get("bounce_rate")) * s
        a[2] += num(r.get("added_to_cart_rate")) * s
        a[3] += num(r.get("conversion_rate")) * s
    return {
        label: {
            "sessions": int(s),
            "bounce_rate": round(b / s * 100, 2) if s else None,
            "added_to_cart_rate": round(c / s * 100, 2) if s else None,
            "conversion_rate": round(v / s * 100, 2) if s else None,
        }
        for label, (s, b, c, v) in acc.items()
    }


def compare(
    cur: dict[str, dict[str, Any]], prev: dict[str, dict[str, Any]], least: int
) -> list[dict[str, Any]]:
    """Each label's rates with the comparison's and the change in points (pure). A change is only
    given when both periods have at least `least` visits."""
    out = []
    for label, v in sorted(cur.items(), key=lambda kv: -kv[1]["sessions"]):
        p = prev.get(label)
        enough = v["sessions"] >= least and p is not None and p["sessions"] >= least

        def change(key: str, v: dict[str, Any] = v, p: Any = p, enough: bool = enough) -> Any:
            if not enough or v[key] is None or p[key] is None:
                return None
            return round(v[key] - p[key], 2)

        out.append(
            {
                "label": label,
                **v,
                "previous_sessions": p["sessions"] if p else None,
                "previous_bounce_rate": p["bounce_rate"] if p else None,
                "bounce_change_pts": change("bounce_rate"),
                "previous_conversion_rate": p["conversion_rate"] if p else None,
                "conversion_change_pts": change("conversion_rate"),
                "too_few_sessions": v["sessions"] < least,
            }
        )
    return out


def landing_pages(
    store: str, cur: Window, base: Window | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """The landing page report for `cur`, compared with `base` when given."""
    c = since(cur)
    queries = {
        "pages": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}"
        f"GROUP BY landing_page_path, landing_page_type {c} ORDER BY sessions DESC LIMIT 200",
        "page_sources": f"FROM sessions SHOW sessions {HUMAN}"
        f"GROUP BY landing_page_path, referrer_source {c} ORDER BY sessions DESC LIMIT 1000",
        "page_sales": "FROM sales SHOW total_sales, orders GROUP BY order_landing_page_path "
        f"{c} ORDER BY total_sales DESC LIMIT 1000",
        "types": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}GROUP BY landing_page_type {c} "
        "ORDER BY sessions DESC",
        "sources": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}GROUP BY referrer_source {c} "
        "ORDER BY sessions DESC",
        "devices": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}GROUP BY session_device_type "
        f"{c} ORDER BY sessions DESC",
    }
    if base:
        b = since(base)
        queries |= {
            "pages_prev": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}"
            f"GROUP BY landing_page_path {b} ORDER BY sessions DESC LIMIT 1000",
            "types_prev": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}"
            f"GROUP BY landing_page_type {b} ORDER BY sessions DESC",
            "sources_prev": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}"
            f"GROUP BY referrer_source {b} ORDER BY sessions DESC",
            "devices_prev": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}"
            f"GROUP BY session_device_type {b} ORDER BY sessions DESC",
        }
    rows, errors = run_many(store, queries, gql)
    page_rows = required(rows, errors, "pages")
    least = min_sessions((cur[1] - cur[0]).days + 1)

    page_type: dict[str, str] = {}
    for r in page_rows:
        if r.get("landing_page_path") is not None:
            page_type.setdefault(
                norm_path(r["landing_page_path"]),
                str(r.get("landing_page_type") or "").strip() or "Other",
            )
    top_source: dict[str, tuple[str, int]] = {}
    for r in rows.get("page_sources") or []:
        if r.get("landing_page_path") is None or r.get("referrer_source") is None:
            continue
        path, s = norm_path(r["landing_page_path"]), int(num(r.get("sessions")))
        if s > top_source.get(path, ("", -1))[1]:
            top_source[path] = (str(r["referrer_source"]).strip() or "Unknown", s)
    sales_ok = rows.get("page_sales") is not None
    sales: dict[str, list[float]] = {}
    for r in rows.get("page_sales") or []:
        if r.get("order_landing_page_path") is None:
            continue
        got = sales.setdefault(norm_path(r["order_landing_page_path"]), [0.0, 0.0])
        got[0] += num(r.get("total_sales"))
        got[1] += num(r.get("orders"))

    pages = []
    for row in compare(
        rate_rows(page_rows, "landing_page_path"),
        rate_rows(rows.get("pages_prev"), "landing_page_path"),
        least,
    ):
        path = row.pop("label")
        sale = sales.get(path)
        revenue = round(sale[0], 2) if sale else (0.0 if sales_ok else None)
        src = top_source.get(path)
        pages.append(
            {
                "path": path,
                "page_type": page_type.get(path, "Other"),
                **row,
                "revenue": revenue,
                "orders": int(sale[1]) if sale else (0 if sales_ok else None),
                "revenue_per_session": (
                    round(revenue / row["sessions"], 2)
                    if revenue is not None and row["sessions"]
                    else None
                ),
                "top_source": src[0] if src else None,
                "top_source_share": rate(src[1], row["sessions"], 1) if src else None,
                "bounce_flag": (
                    row["bounce_change_pts"] is not None
                    and row["bounce_change_pts"] >= BOUNCE_FLAG_PTS
                ),
            }
        )
    total = sum(p["sessions"] for p in pages)
    types = compare(
        rate_rows(rows.get("types"), "landing_page_type"),
        rate_rows(rows.get("types_prev"), "landing_page_type"),
        least,
    )
    for t in types:
        t["share_of_sessions"] = rate(t["sessions"], total, 1)
    return {
        "bounce_definition": BOUNCE_DEFINITION,
        "min_sessions": least,
        "bounce_flag_pts": BOUNCE_FLAG_PTS,
        "revenue_available": sales_ok,
        "revenue_note": (
            "Revenue = total sales of orders whose visit started on this page."
            if sales_ok
            else "Shopify did not answer revenue by landing page, so it is left blank."
        ),
        "pages": pages,
        "page_types": types,
        "by_source": compare(
            rate_rows(rows.get("sources"), "referrer_source"),
            rate_rows(rows.get("sources_prev"), "referrer_source"),
            least,
        ),
        "by_device": compare(
            rate_rows(rows.get("devices"), "session_device_type"),
            rate_rows(rows.get("devices_prev"), "session_device_type"),
            least,
        ),
        "errors": errors,
    }


GRID_METRICS = ("conversion_rate", "added_to_cart_rate", "bounce_rate")
GRID_MIN = 30  # a cell with fewer visits gets no rates


def _cell(acc: list[float] | None) -> dict[str, Any]:
    visits = acc[0] if acc else 0.0
    out: dict[str, Any] = {"sessions": int(visits)}
    for i, m in enumerate(GRID_METRICS, 1):
        out[m] = round(acc[i] / visits * 100, 2) if acc and visits >= GRID_MIN else None
    return out


def _grid(
    rows: list[dict[str, Any]] | None, row_key: str, col_key: str, max_rows: int, max_cols: int
) -> dict[str, Any]:
    """The busiest rows x columns of visits and rates, each row with its "All" cell (every column,
    shown or not) and an "All" row (pure). Rates are weighted by visits."""
    cells: dict[tuple[str, str], list[float]] = {}
    for r in rows or []:
        if r.get(row_key) is None or r.get(col_key) is None:
            continue
        rk = norm_path(r[row_key]) if row_key == "landing_page_path" else str(r[row_key]).strip()
        ck = str(r[col_key]).strip() or "Unknown"
        s = num(r.get("sessions"))
        c = cells.setdefault((rk or "Other", ck), [0.0] * (len(GRID_METRICS) + 1))
        c[0] += s
        for i, m in enumerate(GRID_METRICS, 1):
            c[i] += num(r.get(m)) * s

    def ranked(index: int, limit: int) -> list[str]:
        totals: dict[str, float] = {}
        for k, acc in cells.items():
            totals[k[index]] = totals.get(k[index], 0.0) + acc[0]
        return [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:limit]]

    def total(match: int, label: str | None) -> list[float]:
        acc = [0.0] * (len(GRID_METRICS) + 1)
        for k, v in cells.items():
            if label is None or k[match] == label:
                acc = [a + b for a, b in zip(acc, v, strict=True)]
        return acc

    row_labels, col_labels = ranked(0, max_rows), ranked(1, max_cols)
    return {
        "rows": row_labels,
        "columns": col_labels,
        "cells": [[_cell(cells.get((rk, ck))) for ck in col_labels] for rk in row_labels],
        "row_totals": [_cell(total(0, rk)) for rk in row_labels],
        "column_totals": [_cell(total(1, ck)) for ck in col_labels],
        "total": _cell(total(0, None)),
    }


def grids(store: str, cur: Window, gql: shopify.Gql | None = None) -> dict[str, Any]:
    """Top landing pages x traffic source, and page types x device: visits, conversion, add to cart
    and bounce per cell, against the grid's "All" figures. A cell with fewer than 30 visits gets
    no rates."""
    c = since(cur)
    shown = "sessions, " + ", ".join(GRID_METRICS)
    rows, errors = run_many(
        store,
        {
            "page_source": f"FROM sessions SHOW {shown} {HUMAN}"
            f"GROUP BY landing_page_path, referrer_source {c} ORDER BY sessions DESC LIMIT 1000",
            "type_device": f"FROM sessions SHOW {shown} {HUMAN}"
            f"GROUP BY landing_page_type, session_device_type {c} ORDER BY sessions DESC LIMIT 200",
        },
        gql,
    )
    return {
        "page_by_source": _grid(
            required(rows, errors, "page_source"), "landing_page_path", "referrer_source", 10, 5
        ),
        "type_by_device": _grid(
            rows.get("type_device"), "landing_page_type", "session_device_type", 8, 3
        ),
        "errors": errors,
    }
