"""New vs returning customers (batch 5 of the new CRO prototype).

Shopify's sales report by `new_or_returning_customer` (orders, net sales, average order) and its
returning customer rate, for the range and its comparison. Shopify decides who is new or returning;
Flowmerce reads nothing about the customer (owner decision 2026-11-21: no read_customers scope and
no customer identity anywhere).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import shopify
from .traffic import num, rate, required, run_many, since

Days = tuple[date, date]
NEW_RET_SHOW = "orders, net_sales, average_order_value"


def nr_summary(rows: list[dict[str, Any]], rate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """New and returning customers' orders, share, net sales and average order (pure)."""
    by = {str(r.get("new_or_returning_customer") or "").strip().lower(): r for r in rows}
    total = sum(num(by.get(k, {}).get("orders")) for k in ("new", "returning"))
    out: dict[str, Any] = {"orders": int(total)}
    for key in ("new", "returning"):
        r = by.get(key, {})
        orders = num(r.get("orders"))
        out[key] = {
            "orders": int(orders),
            "share_of_orders": rate(orders, total, 1),
            "net_sales": round(num(r.get("net_sales")), 2),
            "aov": round(num(r.get("average_order_value")), 2) if orders else None,
        }
    raw = rate_rows[0].get("returning_customer_rate") if rate_rows else None
    out["returning_customer_rate"] = round(num(raw) * 100, 1) if raw is not None else None
    return out


def new_vs_returning(
    store: str, cur: Days, base: Days | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """New vs returning customers for `cur`, with the comparison's figures when Shopify gives
    them."""
    queries = {
        "cur": f"FROM sales SHOW {NEW_RET_SHOW} GROUP BY new_or_returning_customer {since(cur)}",
        "cur_rate": f"FROM sales SHOW returning_customer_rate {since(cur)}",
    }
    if base:
        queries["base"] = (
            f"FROM sales SHOW {NEW_RET_SHOW} GROUP BY new_or_returning_customer {since(base)}"
        )
        queries["base_rate"] = f"FROM sales SHOW returning_customer_rate {since(base)}"
    rows, errors = run_many(store, queries, gql)
    out = nr_summary(required(rows, errors, "cur"), rows.get("cur_rate") or [])
    prev = None
    if base and rows.get("base") is not None:
        prev = nr_summary(rows["base"] or [], rows.get("base_rate") or [])
    return {**out, "previous": prev, "skipped": sorted(errors)}
