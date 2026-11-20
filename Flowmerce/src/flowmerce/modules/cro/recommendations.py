"""Rule-based CRO recommendations (pure, no I/O).

A recommendation is only made when real figures support it; each one carries the evidence it is
based on. Sources that could not be read (for example ShopifyQL without the read_reports scope) are
simply skipped and listed in `skipped`, never guessed.
"""

from __future__ import annotations

from typing import Any

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def _rec(
    title: str, explanation: str, evidence: str, priority: str, action: str, metric: str
) -> dict[str, str]:
    return {
        "title": title,
        "explanation": explanation,
        "evidence": evidence,
        "priority": priority,
        "suggested_action": action,
        "affected_metric": metric,
    }


def _product_gaps(alarms: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for a in alarms:
        if a.get("status") not in ("alarm_triggered", "alarm_active"):
            continue
        out.append(
            _rec(
                f"Orders for '{a['keyword']}' products have stalled",
                f"No order with a '{a['keyword']}' product in the last {a['hours_elapsed']} hours "
                f"(alarm at {a['threshold_hours']:g}h). This usually points to a traffic, pricing "
                "or stock problem.",
                f"Last such order: {a.get('last_order') or '-'}, {a['hours_elapsed']}h ago",
                "High",
                "Check availability, pricing and ads pointed at these products.",
                f"{a['keyword']} orders",
            )
        )
    return out


def _cvr(cmp: dict[str, Any] | None) -> list[dict[str, str]]:
    if not cmp or cmp.get("drop_percent") is None or cmp["drop_percent"] < 15:
        return []
    return [
        _rec(
            "Conversion rate dropped sharply",
            f"Yesterday's conversion rate ({cmp['yesterday_cvr']}%) is {cmp['drop_percent']}% "
            "lower than the day "
            f"before ({cmp['previous_cvr']}%). Check for a broken checkout step, a price change "
            "or a shift in "
            "traffic quality.",
            f"{cmp['previous_date']}: {cmp['previous_cvr']}% -> {cmp['yesterday_date']}: "
            f"{cmp['yesterday_cvr']}%",
            "High" if cmp["drop_percent"] >= 20 else "Medium",
            "Test the checkout end to end and review yesterday's traffic sources.",
            "Conversion rate",
        )
    ]


def _funnel(f: dict[str, Any] | None) -> list[dict[str, str]]:
    if not f or not f.get("sessions"):
        return []
    out = []
    cart, checkout = f.get("cart_rate"), f.get("checkout_rate")
    if cart is not None and checkout is not None and cart >= 15 and cart - checkout >= 15:
        out.append(
            _rec(
                "Shoppers add to cart but do not reach checkout",
                f"{cart}% of sessions added to cart but only {checkout}% reached checkout, a "
                f"{round(cart - checkout, 1)} point gap. This points to friction on the cart "
                "page: a shipping-cost "
                "surprise, a slow page or an unclear next step.",
                f"Added to cart: {f['added_to_cart']} sessions, reached checkout: "
                f"{f['reached_checkout']} ({f['date']})",
                "Medium",
                "Review the cart page for unexpected costs, speed and a clear checkout button.",
                "Cart to checkout",
            )
        )
    done = f.get("checkout_completion_rate")
    if done is not None and f.get("reached_checkout", 0) >= 10 and done <= 40:
        out.append(
            _rec(
                "Few checkouts are completed",
                f"Only {done}% of the sessions that reached checkout completed the purchase. This "
                "often means a "
                "payment, shipping-cost or trust issue at the last step.",
                f"Reached checkout: {f['reached_checkout']}, completed: {f['completed_checkout']} "
                f"({f['date']})",
                "High" if done <= 25 else "Medium",
                "Check payment methods, shipping-cost visibility and checkout load time.",
                "Checkout completion",
            )
        )
    return out


def _pacing(revenue: dict[str, Any] | None) -> list[dict[str, str]]:
    """Today so far against the same elapsed time on the same weekday last week."""
    if not revenue or revenue.get("too_early") or revenue.get("change_pct") is None:
        return []
    change = revenue["change_pct"]
    if change > -25:
        return []
    return [
        _rec(
            "Revenue is pacing well below last week",
            f"So far today revenue is {abs(change)}% lower than at the same time on the same "
            "weekday last week. "
            "It can be normal variation, or a traffic or availability problem.",
            f"Today so far: {revenue['value']}, same time last week: {revenue['baseline_value']}",
            "Medium",
            "Check that the store is up, ad spend is pacing and key products are in stock.",
            "Revenue",
        )
    ]


def _declines(declines: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        _rec(
            f"'{d['name']}' sales are declining",
            f"Revenue from this product fell {d['drop_percent']}% in the last 7 days against the "
            "7 days before.",
            f"Prior 7 days: {d['prior_revenue']} ({d.get('prior_units', '?')} sold) -> "
            f"last 7 days: {d['recent_revenue']} ({d.get('recent_units', '?')} sold)",
            "High" if d["drop_percent"] >= 60 else "Medium",
            "Check stock, price and the product page.",
            str(d["name"]),
        )
        for d in declines
    ]


def _health(h: dict[str, Any] | None) -> list[dict[str, str]]:
    if not h or h.get("total_orders", 0) < 10:
        return []
    out = []
    total = h["total_orders"]
    for key, title, why, action, metric in (
        (
            "refunded",
            "Refund rate is higher than usual",
            "This can point to product quality, size or description mismatches, or shipping "
            "damage.",
            "Read recent refund reasons and product reviews.",
            "Refund rate",
        ),
        (
            "cancelled",
            "Order cancellation rate is high",
            "Often linked to stock-outs after purchase, payment failures or slow fulfilment.",
            "Check inventory accuracy and fulfilment speed for recently cancelled orders.",
            "Cancellation rate",
        ),
    ):
        pct, count = h[key]["pct"], h[key]["count"]
        if pct >= 10:
            out.append(
                _rec(
                    title,
                    f"{pct}% of orders in the last {h['days']} days ({count} of {total}). {why}",
                    f"{key.capitalize()}: {count} of {total} orders (last {h['days']} days)",
                    "High" if pct >= 20 else "Medium",
                    action,
                    metric,
                )
            )
    return out


def build(
    *,
    product_alarms: list[dict[str, Any]],
    cvr: dict[str, Any] | None,
    funnel: dict[str, Any] | None,
    today_revenue: dict[str, Any] | None,
    declines: list[dict[str, Any]],
    health: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Every recommendation the figures support, most urgent first."""
    recs = (
        _product_gaps(product_alarms)
        + _cvr(cvr)
        + _funnel(funnel)
        + _pacing(today_revenue)
        + _declines(declines)
        + _health(health)
    )
    return sorted(recs, key=lambda r: PRIORITY_RANK.get(r["priority"], 3))
