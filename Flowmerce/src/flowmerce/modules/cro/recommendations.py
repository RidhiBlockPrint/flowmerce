"""Rule-based CRO recommendations (pure, no I/O).

A recommendation is only made when real figures support it; each one carries the evidence it is
based on. Sources that could not be read (for example ShopifyQL without the read_reports scope) are
simply skipped and listed in `skipped`, never guessed.

Every recommendation has a stable `key` (the team's status is saved against it), an `action`
(fix / promote / test), an `effort`, the `area` of the app it comes from, and, where the figures
allow, an estimated money `impact` over the window:
    visits x conversion gap (points) x average order value
the extra sales if that segment converted like the store average (or, for "promote", what its
above-average visits already add). It ranks the list; it is not a promise. Rules from the new CRO
prototype (landing pages, devices, traffic sources, payments, and leaky products: many GA4
product views but converting below their category, impact = the money left on the table)
carry an impact; the order-based
checks (stalled products, refunds, today's pace) do not, and rank after them by priority.
`evidence` stays one line (the Overview and Claude's plan read it); `evidence_list` has every line.
"""

from __future__ import annotations

from typing import Any

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
EFFORT = {
    "landing_fix": "Medium",
    "landing_bounce": "Medium",
    "landing_promote": "Low",
    "device_gap": "High",
    "source_test": "Medium",
    "source_promote": "Low",
    "cvr_drop": "Medium",
    "payment_method": "Low",
    "product_leaky": "Medium",
}
STATUSES = ("open", "in_progress", "done", "ignored")


def _rec(
    title: str,
    explanation: str,
    evidence: str,
    priority: str,
    action: str,
    metric: str,
    *,
    key: str,
    area: str,
    effort: str = "Medium",
    kind: str = "check",
    act: str = "fix",
    segment: str = "",
    evidence_list: list[str] | None = None,
    impact: float | None = None,
    formula: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "action": act,
        "effort": effort,
        "area": area,
        "segment": segment,
        "title": title,
        "explanation": explanation,
        "evidence": evidence,
        "evidence_list": evidence_list or [evidence],
        "priority": priority,
        "suggested_action": action,
        "affected_metric": metric,
        "impact": round(impact, 2) if impact is not None else None,
        "impact_formula": formula,
    }


def _product_gaps(alarms: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                key=f"product_gap:{str(a['keyword']).lower()}",
                area="Products",
                effort="Low",
                segment=f"Alarm · no '{a['keyword']}' order for {a['hours_elapsed']}h",
            )
        )
    return out


def _cvr(cmp: dict[str, Any] | None) -> list[dict[str, Any]]:
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
            key=f"cvr_day_drop:{cmp['yesterday_date']}",
            area="Conversion",
            segment="Whole store · yesterday",
        )
    ]


def _funnel(f: dict[str, Any] | None) -> list[dict[str, Any]]:
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
                key="funnel:cart_to_checkout",
                area="Cart & checkout",
                segment="Cart page",
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
                key="funnel:checkout_completion",
                area="Cart & checkout",
                segment="Checkout",
            )
        )
    return out


def _pacing(revenue: dict[str, Any] | None) -> list[dict[str, Any]]:
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
            key="pacing:today",
            area="Sales",
            effort="Low",
            segment="Today so far",
        )
    ]


def _declines(declines: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            key=f"product_decline:{str(d['name']).lower()}",
            area="Products",
            effort="Low",
            segment=f"Product · {d['name']}",
        )
        for d in declines
    ]


def _health(h: dict[str, Any] | None) -> list[dict[str, Any]]:
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
                    key=f"orders:{key}",
                    area="Overview",
                    segment="Orders",
                )
            )
    return out


# ----------------------------------------------------------------------------- impact-ranked rules
def money(v: float) -> str:
    """$1,234."""
    return f"${v:,.0f}"


def weighted_cvr(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Conversion of several segments together, weighted by visits, and their visits."""
    usable = [r for r in rows if r.get("conversion_rate") is not None]
    visits = sum(int(r.get("sessions") or 0) for r in usable)
    if not visits:
        return None, 0
    return sum(int(r.get("sessions") or 0) * r["conversion_rate"] for r in usable) / visits, visits


def gap_impact(visits: int, gap_pts: float, aov: float) -> float:
    """Extra sales if `visits` converted `gap_pts` points better, at `aov` per order."""
    return visits * gap_pts / 100 * aov


def _formula(visits: int, gap_pts: float, aov: float, extra: str = "") -> str:
    return f"{visits:,} visits × {gap_pts:.2f} pts conversion gap × {money(aov)} average order" + (
        f" ({extra})" if extra else ""
    )


def _impact_rec(
    kind: str,
    act: str,
    key: str,
    title: str,
    area: str,
    segment: str,
    evidence: list[str | None],
    impact: float,
    formula: str,
) -> dict[str, Any]:
    lines = [e for e in evidence if e]
    return _rec(
        title,
        lines[0] if lines else title,
        lines[0] if lines else "",
        "High" if act == "fix" else "Medium",
        lines[-1] if lines else "",
        area,
        key=key,
        area=area,
        effort=EFFORT[kind],
        kind=kind,
        act=act,
        segment=segment,
        evidence_list=lines,
        impact=impact,
        formula=formula,
    )


def _landing_items(
    landing: dict[str, Any], store_cvr: float, aov: float, compare_label: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pages = landing.get("pages") or []
    flagged: set[str] = set()
    for p in pages:  # 1. pages converting well below the store: fix
        cvr = p.get("conversion_rate")
        if p.get("too_few_sessions") or cvr is None or cvr >= store_cvr * 0.7:
            continue
        gap = store_cvr - cvr
        flagged.add(p["path"])
        out.append(
            _impact_rec(
                "landing_fix",
                "fix",
                f"landing_fix:{p['path']}",
                f"Fix landing page {p['path']}: converts {cvr:.2f}% vs {store_cvr:.2f}% store",
                "Landing pages",
                f"{p.get('page_type') or 'Page'} · {p['path']}",
                [
                    f"{p['sessions']:,} visits, conversion {cvr:.2f}% vs store {store_cvr:.2f}%",
                    (
                        f"Bounce {p['bounce_rate']:.1f}%, "
                        f"add to cart {p['added_to_cart_rate']:.1f}%"
                        if p.get("bounce_rate") is not None
                        and p.get("added_to_cart_rate") is not None
                        else None
                    ),
                    (
                        f"Main traffic: {p['top_source']} ({p['top_source_share']}% of visits)"
                        if p.get("top_source")
                        else None
                    ),
                ],
                gap_impact(p["sessions"], gap, aov),
                _formula(p["sessions"], gap, aov),
            )
        )
    flag_pts = float(landing.get("bounce_flag_pts") or 5)
    for p in pages:  # 2. bounce jumped and conversion fell: fix
        b, c = p.get("bounce_change_pts"), p.get("conversion_change_pts")
        if p["path"] in flagged or b is None or c is None or b < flag_pts or c >= 0:
            continue
        out.append(
            _impact_rec(
                "landing_bounce",
                "fix",
                f"landing_bounce:{p['path']}",
                f"Bounce jumped on {p['path']} (+{b:.1f} pts) and conversion fell",
                "Landing pages",
                f"{p.get('page_type') or 'Page'} · {p['path']}",
                [
                    f"Bounce {p['previous_bounce_rate']:.1f}% → {p['bounce_rate']:.1f}% "
                    f"({compare_label} → now)",
                    f"Conversion {p['previous_conversion_rate']:.2f}% → "
                    f"{p['conversion_rate']:.2f}% on {p['sessions']:,} visits",
                    "Check the change log for what changed on this page",
                ],
                gap_impact(p["sessions"], -c, aov),
                _formula(p["sessions"], -c, aov),
            )
        )
    by_visits = sorted(pages, key=lambda x: -int(x["sessions"]))
    median = by_visits[len(by_visits) // 2]["sessions"] if by_visits else 0
    least = int(landing.get("min_sessions") or 100)
    for p in pages:  # 3. pages converting far above the store with modest traffic: promote
        cvr = p.get("conversion_rate")
        if (
            p.get("too_few_sessions")
            or cvr is None
            or cvr < store_cvr * 1.5
            or p["sessions"] > max(median, least) * 4
        ):
            continue
        gap = cvr - store_cvr
        out.append(
            _impact_rec(
                "landing_promote",
                "promote",
                f"landing_promote:{p['path']}",
                f"Send more traffic to {p['path']}: converts {cvr:.2f}% vs {store_cvr:.2f}% store",
                "Landing pages",
                f"{p.get('page_type') or 'Page'} · {p['path']}",
                [
                    f"{p['sessions']:,} visits, conversion {cvr:.2f}%",
                    (
                        f"Revenue {money(p['revenue'])} from {p['orders']} orders"
                        if p.get("revenue")
                        else None
                    ),
                ],
                gap_impact(p["sessions"], gap, aov),
                _formula(
                    p["sessions"], gap, aov, "extra earned by these visits vs an average page"
                ),
            )
        )
    return out


def _segment_items(
    landing: dict[str, Any], store_cvr: float, visits: int, aov: float, compare_label: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in landing.get("by_device") or []:  # 4. a device converting below the store: fix
        cvr = d.get("conversion_rate")
        if d.get("too_few_sessions") or cvr is None or cvr >= store_cvr * 0.85:
            continue
        gap = store_cvr - cvr
        out.append(
            _impact_rec(
                "device_gap",
                "fix",
                f"device_gap:{d['label']}",
                f"{d['label'].title()} converts {cvr:.2f}% vs {store_cvr:.2f}% store",
                "Conversion",
                f"Device · {d['label'].title()}",
                [
                    f"{d['sessions']:,} visits ({d['sessions'] / visits * 100:.0f}% of visits)"
                    if visits
                    else None,
                    "Check page speed, a sticky add-to-cart button and checkout on this device",
                ],
                gap_impact(d["sessions"], gap, aov),
                _formula(d["sessions"], gap, aov),
            )
        )
    for s in landing.get("by_source") or []:  # 5. traffic sources: test the weak, grow the strong
        cvr = s.get("conversion_rate")
        if s.get("too_few_sessions") or cvr is None:
            continue
        label = str(s["label"]).title()
        if cvr < store_cvr * 0.6:
            gap = store_cvr - cvr
            out.append(
                _impact_rec(
                    "source_test",
                    "test",
                    f"source_test:{s['label']}",
                    f"Test a better landing page or offer for {label} traffic "
                    f"({cvr:.2f}% conversion)",
                    "Landing pages",
                    f"Traffic source · {label}",
                    [
                        f"{s['sessions']:,} visits, conversion {cvr:.2f}% "
                        f"vs store {store_cvr:.2f}%",
                        f"Bounce {s['bounce_rate']:.1f}%"
                        if s.get("bounce_rate") is not None
                        else None,
                    ],
                    gap_impact(s["sessions"], gap, aov),
                    _formula(s["sessions"], gap, aov),
                )
            )
        elif cvr > store_cvr * 1.5:
            gap = cvr - store_cvr
            out.append(
                _impact_rec(
                    "source_promote",
                    "promote",
                    f"source_promote:{s['label']}",
                    f"Grow {label} traffic: converts {cvr:.2f}% vs {store_cvr:.2f}% store",
                    "Landing pages",
                    f"Traffic source · {label}",
                    [f"{s['sessions']:,} visits, conversion {cvr:.2f}%"],
                    gap_impact(s["sessions"], gap, aov),
                    _formula(s["sessions"], gap, aov, "extra earned by these visits vs average"),
                )
            )
    prev_cvr, prev_visits = weighted_cvr(  # 6. the store converting less than before: fix
        [
            {
                "sessions": d.get("previous_sessions") or 0,
                "conversion_rate": d.get("previous_conversion_rate"),
            }
            for d in landing.get("by_device") or []
        ]
    )
    least = int(landing.get("min_sessions") or 100)
    if prev_cvr and prev_visits >= least and store_cvr < prev_cvr * 0.9:
        gap = prev_cvr - store_cvr
        out.append(
            _impact_rec(
                "cvr_drop",
                "fix",
                "cvr_drop:store",
                f"Store conversion fell to {store_cvr:.2f}% from {prev_cvr:.2f}%",
                "Conversion",
                "Whole store",
                [
                    f"{compare_label}: {prev_cvr:.2f}% on {prev_visits:,} visits",
                    f"Now: {store_cvr:.2f}% on {visits:,} visits",
                    "Check the change log and the device and source items",
                ],
                gap_impact(visits, gap, aov),
                _formula(visits, gap, aov),
            )
        )
    return out


def _payment_items(pay: dict[str, Any], aov: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    overall = pay.get("success_rate")
    if not overall:
        return out
    for m in [*(pay.get("methods") or []), *(pay.get("wallets") or [])]:
        rate = m.get("success_rate")
        if rate is None or m["attempts"] < 30 or rate >= overall - 3:
            continue
        lost = m["attempts"] * (overall - rate) / 100
        label = str(m["label"]).replace("_", " ")
        out.append(
            _impact_rec(
                "payment_method",
                "fix",
                f"payment_method:{m['label']}",
                f"Payments via {label} succeed only {rate}% (store {overall}%)",
                "Cart & checkout",
                f"Payment · {label}",
                [
                    f"{m['attempts']:,} purchase attempts, "
                    f"{m['failed_attempts']:,} failed attempts",
                    "Check the gateway or wallet setup and its error messages",
                ],
                lost * aov,
                f"{m['attempts']:,} attempts × {overall - rate:.1f} pts success gap × "
                f"{money(aov)} average order",
            )
        )
    return out


LEAKY_ITEMS = 5  # the leakiest products become recommendations; the rest stay on the Products tab
LEAKY_MIN_IMPACT = 50.0


def leaky_items(leaky: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Leaky products from the Products tab's fix-first list: many product views (GA4) but
    converting below their category. Impact = views x conversion gap x price."""
    out: list[dict[str, Any]] = []
    if not leaky:
        return out
    days = leaky.get("days") or 0
    for p in leaky.get("fix_first") or []:
        if len(out) >= LEAKY_ITEMS or (p.get("left_on_table") or 0) < LEAKY_MIN_IMPACT:
            break
        cvr, cat = float(p["conversion_rate"] or 0), float(p["category_rate"] or 0)
        peers = str(p.get("compared_with") or p["category"]).lower()
        atc = p.get("add_to_cart_rate")
        out.append(
            _impact_rec(
                "product_leaky",
                "fix",
                f"product_leaky:{p['product_id']}",
                f"Fix product page {p['name']}: converts {cvr:.2f}% vs {cat:.2f}% for {peers}",
                "Products",
                f"Product · {p['name']}",
                [
                    f"{int(p['views']):,} product views in {days} days (GA4), conversion "
                    f"{cvr:.2f}% vs {cat:.2f}% for {peers}",
                    f"Added to cart on {atc}% of views" if atc is not None else None,
                    "Check the photos, price, reviews, delivery promise and stock on this page",
                ],
                float(p["left_on_table"]),
                f"{int(p['views']):,} views × {cat - cvr:.2f} pts conversion gap × "
                f"{money(float(p['price'] or 0))} price",
            )
        )
    return out


def impact_items(
    *,
    landing: dict[str, Any] | None,
    payments: dict[str, Any] | None,
    aov: float | None,
    compare_label: str,
) -> tuple[list[dict[str, Any]], float | None, int]:
    """(recommendations with an estimated impact, store conversion, visits) from the landing-page
    report, the payment report and the average order value. Nothing when a source is missing."""
    if not landing or not aov:
        return [], None, 0
    store_cvr, visits = weighted_cvr(landing.get("by_device") or [])
    if not store_cvr:
        return [], None, visits
    out = _landing_items(landing, store_cvr, aov, compare_label)
    out += _segment_items(landing, store_cvr, visits, aov, compare_label)
    if payments:
        out += _payment_items(payments, aov)
    return out, round(store_cvr, 2), visits


def rank(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Impact first (largest first), then the checks without an estimate by priority; numbered."""
    ordered = sorted(
        recs,
        key=lambda r: (
            r["impact"] is None,
            -(r["impact"] or 0),
            PRIORITY_RANK.get(r["priority"], 3),
        ),
    )
    return [{**r, "rank": i} for i, r in enumerate(ordered, 1)]


def build(
    *,
    product_alarms: list[dict[str, Any]],
    cvr: dict[str, Any] | None,
    funnel: dict[str, Any] | None,
    today_revenue: dict[str, Any] | None,
    declines: list[dict[str, Any]],
    health: dict[str, Any] | None,
    extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every recommendation the figures support: the impact-ranked ones (`extra`) first, then the
    rest, most urgent first. A key appears once."""
    recs = (
        (extra or [])
        + _product_gaps(product_alarms)
        + _cvr(cvr)
        + _funnel(funnel)
        + _pacing(today_revenue)
        + _declines(declines)
        + _health(health)
    )
    seen: set[str] = set()
    unique = []
    for r in recs:
        if r["key"] not in seen:
            seen.add(r["key"])
            unique.append(r)
    return rank(unique)
