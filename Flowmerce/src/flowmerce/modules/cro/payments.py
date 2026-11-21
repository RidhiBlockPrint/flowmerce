"""Payment methods and payment success, from Shopify (ShopifyQL `payment_attempts`).

Success rate = successful payments / unique payment attempts (a shopper retrying the same purchase
counts once). Shopify is asked for daily rows over a slightly wider window and the wanted days are
picked here: asked for one day directly it can return nothing, while daily rows always match its
payment report.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import shopify
from .traffic import num, rate, required, run_many

METRICS = ("unique_payment_attempts", "successful_payments", "failed_payment_attempts")


def summed(rows: list[dict[str, Any]] | None, key: str, days: set[str]) -> list[dict[str, Any]]:
    """Daily rows added up per `key` over `days`, as display rows, biggest first (pure)."""
    acc: dict[str, list[int]] = {}
    for r in rows or []:
        if str(r.get("day") or "")[:10] not in days or r.get(key) is None:
            continue
        a = acc.setdefault(str(r[key]).strip() or "Other", [0, 0, 0])
        for i, m in enumerate(METRICS):
            a[i] += int(num(r.get(m)))
    out: list[dict[str, Any]] = [
        {
            "label": label,
            "attempts": attempts,
            "successful": ok,
            "failed_attempts": failed,
            "success_rate": rate(ok, attempts, 1),
        }
        for label, (attempts, ok, failed) in sorted(acc.items(), key=lambda kv: -kv[1][0])
    ]
    total = sum(x["successful"] for x in out)
    for x in out:
        x["share_of_payments"] = rate(x["successful"], total, 1)
    return out


def _days(first: date, last: date) -> set[str]:
    return {(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)}


def payments(
    store: str,
    cur: tuple[date, date],
    base: tuple[date, date] | None,
    gql: shopify.Gql | None = None,
) -> dict[str, Any]:
    """Payment methods and wallets for `cur`, with the comparison's success rate."""
    first = min(cur[0], base[0]) if base else cur[0]
    since, until = first - timedelta(days=2), cur[1] + timedelta(days=1)
    window = f"SINCE {since.isoformat()} UNTIL {until.isoformat()}"
    show = ", ".join(METRICS)
    rows, errors = run_many(
        store,
        {
            "method": f"FROM payment_attempts SHOW {show} GROUP BY payment_method "
            f"TIMESERIES day {window}",
            "wallet": f"FROM payment_attempts SHOW {show} GROUP BY payment_card_wallet "
            f"TIMESERIES day {window}",
        },
        gql,
    )
    method_rows = required(rows, errors, "method")
    methods = summed(method_rows, "payment_method", _days(*cur))
    attempts = sum(m["attempts"] for m in methods)
    ok = sum(m["successful"] for m in methods)
    before = summed(method_rows, "payment_method", _days(*base)) if base else []
    b_attempts = sum(m["attempts"] for m in before)
    b_ok = sum(m["successful"] for m in before)
    seen = sorted(
        str(r.get("day"))[:10]
        for r in method_rows
        if r.get("day") and num(r.get("unique_payment_attempts"))
    )
    return {
        "methods": methods,
        "wallets": summed(rows.get("wallet"), "payment_card_wallet", _days(*cur)),
        "attempts": attempts,
        "successful": ok,
        "failed_attempts": sum(m["failed_attempts"] for m in methods),
        "success_rate": rate(ok, attempts, 1),
        "previous_success_rate": rate(b_ok, b_attempts, 1) if base else None,
        "previous_attempts": b_attempts if base else None,
        "previous_failed_attempts": sum(m["failed_attempts"] for m in before) if base else None,
        "previous_methods": before,
        "previous_wallets": (
            summed(rows.get("wallet"), "payment_card_wallet", _days(*base)) if base else []
        ),
        "latest_day_with_data": seen[-1] if seen else None,
        "errors": errors,
    }
