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

Deep checks (owner request 2026-11-23, "recommendations too generic"): every recommendation also
has a `diagnosis` (where the loss is and its likely cause, worked out from the figures: for a
landing page, whether visitors leave at once, browse without adding to cart, or add to cart and
stop), `steps` that name the page, product, device or term and where to change it, a `measure`
(metric, value now, goal) and the `experiment_metric` / `page_path` the Experiments tab should
follow. The deep checks add the funnel step that breaks per device, orders just under the
free-shipping amount, site searches that find nothing or get few clicks, slow page types,
discounts given without a code, products bought together and products with many refunds.
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
    "funnel_step": "Medium",
    "free_shipping": "Low",
    "search_none": "Low",
    "search_clicks": "Low",
    "page_speed": "High",
    "discount_rise": "Low",
    "bundle": "Low",
    "refunds": "Medium",
}
STATUSES = ("open", "in_progress", "done", "ignored")


def _measure(metric: str, now: str, goal: str, days: int = 14) -> dict[str, Any]:
    return {"metric": metric, "baseline": now, "goal": goal, "check_after_days": days}


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
    steps: list[str] | None = None,
    measure: dict[str, Any] | None = None,
    experiment_metric: str = "conversion_rate",
    page_path: str = "",
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
        "diagnosis": explanation,
        "evidence": evidence,
        "evidence_list": evidence_list or [evidence],
        "priority": priority,
        "suggested_action": action,
        "steps": steps or ([action] if action else []),
        "affected_metric": metric,
        "measure": measure,
        "experiment_metric": experiment_metric,
        "page_path": page_path,
        "impact": round(impact, 2) if impact is not None else None,
        "impact_formula": formula,
    }


def _pct(v: float | None, digits: int = 2) -> str:
    return "-" if v is None else f"{v:.{digits}f}%"


def _product_gaps(alarms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in alarms:
        if a.get("status") not in ("alarm_triggered", "alarm_active"):
            continue
        word = a["keyword"]
        out.append(
            _rec(
                f"Orders for '{word}' products have stalled",
                f"No order with a '{word}' product in the last {a['hours_elapsed']} hours "
                f"(alarm at {a['threshold_hours']:g}h). This usually points to a traffic, pricing "
                "or stock problem.",
                f"Last such order: {a.get('last_order') or '-'}, {a['hours_elapsed']}h ago",
                "High",
                "Check availability, pricing and ads pointed at these products.",
                f"{word} orders",
                key=f"product_gap:{str(word).lower()}",
                area="Products",
                effort="Low",
                segment=f"Alarm · no '{word}' order for {a['hours_elapsed']}h",
                steps=[
                    f"In Products, search '{word}' and check every matching product is Active, on "
                    "the "
                    "Online Store channel and in stock in its main sizes.",
                    f"Open a '{word}' product on a phone and add it to the cart to make sure the "
                    "button and checkout work.",
                    f"Check the ads and posts that send traffic to '{word}' products are still "
                    "running.",
                    "Look in the Change log for a price or theme change around the time orders "
                    "stopped.",
                ],
                measure=_measure(f"Orders with a '{word}' product", "0", "orders again", 2),
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
            steps=[
                "Place a test order on a phone and on desktop from a top landing page to the "
                "thank-you page.",
                "On the Conversion tab, pick yesterday and compare devices and channels with the "
                "day before to see which one fell.",
                "Check the Change log for anything changed yesterday (theme, app, price, "
                "discount).",
            ],
            measure=_measure(
                "Daily conversion rate", f"{cmp['yesterday_cvr']}%", f"{cmp['previous_cvr']}%", 3
            ),
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
                steps=[
                    "Add a best seller to the cart on a phone and note anything above the checkout "
                    "button that is not the items, subtotal or checkout buttons.",
                    "Show the shipping cost or the free-shipping amount in the cart.",
                    "Put the express checkout buttons (Shop Pay, Apple Pay) right under the "
                    "subtotal.",
                ],
                measure=_measure(
                    "Reached checkout ÷ added to cart",
                    _pct(checkout / cart * 100 if cart else None, 1),
                    "+10 pts",
                ),
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
                steps=[
                    "Go through checkout on a phone with each payment method you offer and note "
                    "errors or slow steps.",
                    "Compare the shipping cost shown at checkout with what the product page "
                    "promises.",
                    "Read the payment section of the Cart & checkout tab for a method that fails "
                    "more than the rest.",
                ],
                measure=_measure("Checkout completion", f"{done}%", f"{min(done + 10, 75):.0f}%"),
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
            steps=[
                "Open the store on a phone and place a test order to check it works.",
                "Check today's ad spend and that the main campaigns are running.",
                "On the Overview, compare today's visits with last week's to see if traffic or "
                "conversion is behind.",
            ],
        )
    ]


def _declines(declines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in declines:
        name = d["name"]
        out.append(
            _rec(
                f"'{name}' sales are declining",
                f"Revenue from {name} fell {d['drop_percent']}% in the last 7 days against the 7 "
                "days before. A sudden drop in a product that sold steadily usually means a "
                "sold-out "
                "size, a hidden or changed listing, or an ad that stopped.",
                f"Prior 7 days: {d['prior_revenue']} ({d.get('prior_units', '?')} sold) -> "
                f"last 7 days: {d['recent_revenue']} ({d.get('recent_units', '?')} sold)",
                "High" if d["drop_percent"] >= 60 else "Medium",
                "Check stock, price and the product page.",
                str(name),
                key=f"product_decline:{str(name).lower()}",
                area="Products",
                effort="Low",
                segment=f"Product · {name}",
                steps=[
                    f"In Products, open {name}: check status, the Online Store channel and stock "
                    "for "
                    "every size and colour.",
                    "Check the Change log and the product's history for a price or photo change in "
                    "the "
                    "last two weeks.",
                    "If a size is sold out and stock is coming, say when on the page; if not, "
                    "move "
                    f"{name} down its collections so a product in stock takes its place.",
                    "Check whether an ad or post that featured it stopped.",
                ],
                measure=_measure(
                    f"Weekly units of {name}",
                    str(d.get("recent_units", "?")),
                    str(d.get("prior_units", "?")),
                ),
            )
        )
    return out


def _health(h: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not h or h.get("total_orders", 0) < 10:
        return []
    out = []
    total = h["total_orders"]
    for key, title, why, action, metric, steps in (
        (
            "refunded",
            "Refund rate is higher than usual",
            "This can point to product quality, size or description mismatches, or shipping "
            "damage.",
            "Read recent refund reasons and product reviews.",
            "Refund rate",
            [
                "In Orders, filter by Refunded for these days and note the products and reasons.",
                "On the Products tab, sort refunds by rate to see which products drive them.",
                "Fix the product page of the worst one first (size details, colour photos).",
            ],
        ),
        (
            "cancelled",
            "Order cancellation rate is high",
            "Often linked to stock-outs after purchase, payment failures or slow fulfilment.",
            "Check inventory accuracy and fulfilment speed for recently cancelled orders.",
            "Cancellation rate",
            [
                "In Orders, filter by Cancelled for these days and note the cancel reason of each.",
                "If the reason is stock, check inventory tracking is on for those products.",
                "If customers cancel, check the delivery time promised on the product page.",
            ],
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
                    steps=steps,
                    measure=_measure(metric, f"{pct}%", "under 10%", 30),
                )
            )
    return out


# ----------------------------------------------------------------------------- impact-ranked rules
def money(v: float) -> str:
    """$1,234."""
    return f"${v:,.0f}"


def weighted_cvr(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Conversion of several segments together, weighted by visits, and their visits."""
    return weighted(rows, "conversion_rate")


def weighted(rows: list[dict[str, Any]], field: str) -> tuple[float | None, int]:
    """One rate of several segments together, weighted by visits, and their visits."""
    usable = [r for r in rows if r.get(field) is not None]
    visits = sum(int(r.get("sessions") or 0) for r in usable)
    if not visits:
        return None, 0
    return sum(int(r.get("sessions") or 0) * r[field] for r in usable) / visits, visits


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
    *,
    diagnosis: str = "",
    steps: list[str] | None = None,
    measure: dict[str, Any] | None = None,
    experiment_metric: str = "conversion_rate",
    page_path: str = "",
) -> dict[str, Any]:
    lines = [e for e in evidence if e]
    clean_steps = [s for s in steps or [] if s]
    return _rec(
        title,
        diagnosis or (lines[0] if lines else title),
        lines[0] if lines else "",
        "High" if act == "fix" else "Medium",
        clean_steps[0] if clean_steps else (lines[-1] if lines else ""),
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
        steps=clean_steps or None,
        measure=measure,
        experiment_metric=experiment_metric,
        page_path=page_path,
    )


NOT_FOR_SALE = (
    "/pages/contact",
    "/pages/faq",
    "/pages/track",
    "/pages/shipping",
    "/pages/return",
    "/pages/refund",
    "/pages/privacy",
    "/pages/terms",
    "/policies/",
    "/account",
    "/cart",
    "/checkout",
    "/search",
    "/apps/",
    "/tools/",
)


def _not_for_sale(path: str) -> bool:
    """Contact, help, policy, account and cart pages: visitors there are not shopping, so a low
    conversion rate is expected and is not a finding."""
    p = str(path or "").lower()
    return any(p.startswith(x) for x in NOT_FOR_SALE)


def _is_content(p: dict[str, Any]) -> bool:
    kind = str(p.get("page_type") or "").lower()
    return str(p["path"]).startswith("/blogs/") or "blog" in kind or "article" in kind


def _page_name(path: str) -> str:
    return "/ (home page)" if path == "/" else path


def _page_cause(p: dict[str, Any], store: dict[str, float | None]) -> str:
    """Where a landing page loses its visitors, from its own rates against the store's:
    'content' (a blog page with no route to products), 'bounce' (they leave at once), 'browse'
    (they stay but do not add to cart) or 'cart' (they add to cart but do not buy)."""
    if _is_content(p):
        return "content"
    bounce, atc = p.get("bounce_rate"), p.get("added_to_cart_rate")
    s_bounce, s_atc = store.get("bounce"), store.get("atc")
    if bounce is not None and s_bounce is not None and bounce >= s_bounce + 8:
        return "bounce"
    if atc is not None and s_atc and atc < s_atc * 0.75:
        return "browse"
    return "cart"


def _page_story(
    p: dict[str, Any], cause: str, store: dict[str, float | None], store_cvr: float
) -> tuple[str, list[str], dict[str, Any], str]:
    """(diagnosis, steps, measure, experiment metric) for a landing page that converts poorly."""
    path, name = str(p["path"]), _page_name(str(p["path"]))
    src = str(p.get("top_source") or "").lower() or None
    share = p.get("top_source_share")
    came = f" {share:.0f}% of them from {src}," if src and share is not None else ""
    bounce, atc, cvr = p.get("bounce_rate"), p.get("added_to_cart_rate"), p.get("conversion_rate")
    s_bounce, s_atc = store.get("bounce"), store.get("atc")
    goal = cvr + (store_cvr - cvr) / 2 if cvr is not None else None
    page_type = str(p.get("page_type") or "").lower()
    if cause == "content":
        return (
            f"{name} is a content page: {p['sessions']:,} visits,{came} but only "
            f"{_pct(atc, 2)} add to cart and {_pct(cvr)} buy. Readers get no clear route from the "
            "article to the products it talks about.",
            [
                "Edit the post in Online Store > Blog posts and add a button to the matching "
                "collection after each main section.",
                "Add a product block with the 3-4 products the post is about near the top, so "
                "phone readers see it before scrolling.",
                "Link each product photo in the post to that product's page.",
                "Log the change in the Change log, then check this page's add-to-cart rate after "
                "3 weeks.",
            ],
            _measure(
                f"Add-to-cart rate of visits landing on {name}",
                _pct(atc, 2),
                _pct(max((atc or 0) * 3, 1.0), 1),
                21,
            ),
            "added_to_cart_rate",
        )
    if cause == "bounce":
        origin = (
            f" {share:.0f}% of its visits come from {src}, so"
            if src and share is not None
            else " So"
        )
        return (
            f"{_pct(bounce, 1)} of visits to {name} leave without a second page, against "
            f"{_pct(s_bounce, 1)} for the store.{origin} the first screen probably does not show "
            "what that traffic expected.",
            [
                f"Open {name} on a phone the way a {src or 'typical'} visitor arrives and check "
                "the first screen shows the product or offer the post or ad promised.",
                "Put the best-selling items with their prices in the first screen; move banners "
                "and long text below them.",
                f"Check that the {src or 'ads and posts'} links pointing here go to the matching "
                "collection or product, not a general page.",
                "Log the change in the Change log so its effect can be read.",
            ],
            _measure(
                f"Bounce rate of visits landing on {name}", _pct(bounce, 1), _pct(s_bounce, 1)
            ),
            "bounce_rate",
        )
    if cause == "browse":
        steps = (
            [
                f"In Products > Collections, set this collection ({name}) to manual sort and put "
                "the best-converting products (Products tab) in the first two rows.",
                "Move sold-out and low-converting products to the end of the collection.",
                "Make sure each product tile shows the price, and the colours or sizes it comes "
                "in.",
            ]
            if "collection" in page_type
            or (path.startswith("/collections/") and "/products/" not in path)
            else [
                f"Open {name} on a phone and check every size and colour is in stock and the price "
                "and add-to-cart button show without scrolling.",
                "Compare it with a product of the same category that converts better (Products "
                "tab) and copy what differs: photos, size guide, delivery promise.",
                "Make the default variant the size most people buy.",
            ]
        )
        return (
            f"Visitors to {name} stay ({_pct(bounce, 1)} bounce) but only {_pct(atc, 2)} add to "
            f"cart, against {_pct(s_atc, 2)} for the store: what they see first is not what they "
            "want to buy.",
            [*steps, "Log the change in the Change log."],
            _measure(
                f"Add-to-cart rate of visits landing on {name}",
                _pct(atc, 2),
                _pct((atc or 0) + ((s_atc or 0) - (atc or 0)) / 2, 2),
            ),
            "added_to_cart_rate",
        )
    return (
        f"Visitors to {name} add to cart ({_pct(atc, 2)}, store {_pct(s_atc, 2)}) but only "
        f"{_pct(cvr)} buy, against {_pct(store_cvr)} for the store: carts started here stall at "
        "the cart or checkout (price, shipping cost or the size picked).",
        [
            f"Add a product from {name} to the cart on a phone and go to checkout; note any "
            "surprise "
            "(shipping cost, delivery time, missing payment option).",
            "Show the shipping cost or the free-shipping amount on the product page and in the "
            "cart.",
            "Put the express checkout buttons (Shop Pay, Apple Pay) right under the cart subtotal.",
            "Log the change in the Change log.",
        ],
        _measure(f"Conversion of visits landing on {name}", _pct(cvr), _pct(goal)),
        "conversion_rate",
    )


def _landing_items(
    landing: dict[str, Any], store_cvr: float, aov: float, compare_label: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pages = landing.get("pages") or []
    devices = landing.get("by_device") or []
    store = {
        "bounce": weighted(devices, "bounce_rate")[0],
        "atc": weighted(devices, "added_to_cart_rate")[0],
    }
    flagged: set[str] = set()
    for p in pages:  # 1. pages converting well below the store: fix
        cvr = p.get("conversion_rate")
        if (
            p.get("too_few_sessions")
            or cvr is None
            or cvr >= store_cvr * 0.7
            or _not_for_sale(p["path"])
        ):
            continue
        gap = store_cvr - cvr
        flagged.add(p["path"])
        cause = _page_cause(p, store)
        diagnosis, steps, measure, metric = _page_story(p, cause, store, store_cvr)
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
                        f"Bounce {p['bounce_rate']:.1f}%"
                        + (
                            f" vs store {store['bounce']:.1f}%"
                            if store["bounce"] is not None
                            else ""
                        )
                        + f", add to cart {p['added_to_cart_rate']:.1f}%"
                        + (f" vs store {store['atc']:.1f}%" if store["atc"] is not None else "")
                        if p.get("bounce_rate") is not None
                        and p.get("added_to_cart_rate") is not None
                        else None
                    ),
                    (
                        f"Main traffic: {p['top_source']} ({p['top_source_share']}% of visits)"
                        if p.get("top_source")
                        else None
                    ),
                    (
                        f"Revenue {money(p['revenue'])} from {p['orders']} orders"
                        if p.get("revenue")
                        else None
                    ),
                ],
                gap_impact(p["sessions"], gap, aov),
                _formula(p["sessions"], gap, aov),
                diagnosis=diagnosis,
                steps=steps,
                measure=measure,
                experiment_metric=metric,
                page_path=str(p["path"]),
            )
        )
    flag_pts = float(landing.get("bounce_flag_pts") or 5)
    for p in pages:  # 2. bounce jumped and conversion fell: fix
        b, c = p.get("bounce_change_pts"), p.get("conversion_change_pts")
        if p["path"] in flagged or b is None or c is None or b < flag_pts or c >= 0:
            continue
        name = _page_name(str(p["path"]))
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
                diagnosis=f"More visitors now leave {name} at once "
                f"({p['previous_bounce_rate']:.1f}% "
                f"→ {p['bounce_rate']:.1f}%) and fewer buy. A change on the page or in the traffic "
                "sent to it is the likely cause: sold-out items at the top, a new banner, or ads "
                "pointing here for something else.",
                steps=[
                    f"Check the Change log and the theme history for what changed on {name} since "
                    f"{compare_label or 'the last period'}.",
                    f"Open {name} on a phone: look for sold-out items in the first rows, a new "
                    "banner, or a slower first screen.",
                    "Check which ads or posts now link here and whether they promise what the page "
                    "shows.",
                    "Undo or fix the change and log it.",
                ],
                measure=_measure(
                    f"Bounce rate of visits landing on {name}",
                    _pct(p["bounce_rate"], 1),
                    _pct(p["previous_bounce_rate"], 1),
                ),
                experiment_metric="bounce_rate",
                page_path=str(p["path"]),
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
        name = _page_name(str(p["path"]))
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
                diagnosis=f"{name} turns {cvr:.2f}% of its visitors into buyers, against "
                f"{store_cvr:.2f}% for the store, but gets only {p['sessions']:,} visits. Each "
                "extra visit sent here is worth more than one sent to an average page.",
                steps=[
                    f"Use {name} as the landing page of the next social post, ad or email instead "
                    "of a general collection.",
                    f"Link {name} from the home page and the main menu.",
                    "Keep its first rows in stock so the extra traffic finds what converts.",
                ],
                measure=_measure(
                    f"Visits to {name}", f"{p['sessions']:,}", f"{int(p['sessions'] * 1.5):,}", 21
                ),
                page_path=str(p["path"]),
            )
        )
    return out


STEP_NAMES = {
    "added_to_cart": ("visit", "add to cart"),
    "reached_checkout": ("cart", "checkout"),
    "completed_checkout": ("checkout", "order"),
}
STEP_FIX = {
    "added_to_cart": "Make the price, sizes and add-to-cart button visible without scrolling on "
    "{device} product pages, and check they load fast.",
    "reached_checkout": "Simplify the {device} cart: express checkout buttons right under the "
    "subtotal, the shipping cost shown, nothing covering the checkout button.",
    "completed_checkout": "Go through checkout on {device} with each payment method and compare "
    "the shipping cost and options with desktop.",
}


def _step_rates(d: dict[str, Any]) -> dict[str, tuple[int, int, float | None]]:
    """{step: (count before, count, rate from the step before)} of one device's funnel."""
    counts = {s.get("key"): s.get("count") for s in d.get("steps") or []}
    before = {
        "added_to_cart": d.get("sessions") or 0,
        "reached_checkout": counts.get("added_to_cart") or 0,
        "completed_checkout": counts.get("reached_checkout") or 0,
    }
    out = {}
    for step, prev in before.items():
        count = int(counts.get(step) or 0)
        out[step] = (int(prev), count, round(count / prev * 100, 1) if prev else None)
    return out


def _segment_items(
    landing: dict[str, Any],
    store_cvr: float,
    visits: int,
    aov: float,
    compare_label: str,
    funnel: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rates = {
        str(d.get("label", "")).lower(): _step_rates(d) for d in (funnel or {}).get("devices") or []
    }
    for d in landing.get("by_device") or []:  # 4. a device converting below the store: fix
        cvr = d.get("conversion_rate")
        if d.get("too_few_sessions") or cvr is None or cvr >= store_cvr * 0.85:
            continue
        gap = store_cvr - cvr
        device = str(d["label"]).lower()
        mine = rates.get(device)
        others = [r for k, r in rates.items() if k != device]
        worst = None
        if mine and others:
            gaps = {
                s: max((o[s][2] or 0) for o in others) - (mine[s][2] or 0)
                for s in STEP_NAMES
                if mine[s][2] is not None
            }
            worst = max(gaps, key=lambda s: gaps[s]) if gaps else None
        where = (
            f" The biggest loss is from {STEP_NAMES[worst][0]} to {STEP_NAMES[worst][1]}: "
            f"{mine[worst][2]}% on {device}."
            if worst and mine
            else ""
        )
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
                    *(
                        f"{STEP_NAMES[s][0].title()} to {STEP_NAMES[s][1]}: {mine[s][2]}% on "
                        f"{device}"
                        for s in STEP_NAMES
                        if mine and mine[s][2] is not None
                    ),
                    "Check page speed, a sticky add-to-cart button and checkout on this device",
                ],
                gap_impact(d["sessions"], gap, aov),
                _formula(d["sessions"], gap, aov),
                diagnosis=f"{d['label'].title()} visits convert at {cvr:.2f}%, against "
                f"{store_cvr:.2f}% for the store.{where}",
                steps=[
                    f"On a {device}, go from a top landing page to a finished checkout and note "
                    "every slow or awkward step.",
                    STEP_FIX[worst].format(device=device)
                    if worst
                    else f"Check page speed and a sticky add-to-cart button on {device}.",
                    f"Check the Site health tab for slow {device} page types and fix the slowest.",
                ],
                measure=_measure(
                    f"{d['label'].title()} conversion rate", _pct(cvr), _pct(cvr + gap / 2)
                ),
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
                    diagnosis=f"{label} visits convert at {cvr:.2f}%, well under the store's "
                    f"{store_cvr:.2f}%: the pages they land on or the offer they see do not match "
                    "what brought them.",
                    steps=[
                        f"On the Landing pages tab, open the Pages × traffic source grid and find "
                        f"the {label} landing pages with the most visits.",
                        f"For the biggest one, test sending {label} links to a product or "
                        "collection that converts better for the same theme.",
                        "Run it as an experiment for two weeks and compare.",
                    ],
                    measure=_measure(
                        f"{label} conversion rate", _pct(cvr), _pct(cvr + gap / 2), 21
                    ),
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
                    diagnosis=f"{label} visitors buy at {cvr:.2f}%, against {store_cvr:.2f}% for "
                    f"the store, but bring only {s['sessions']:,} visits.",
                    steps=[
                        f"Put more effort into {label}: post or send more often, with links "
                        "straight to the best-converting collections.",
                        f"Check which {label} links brought the most orders and repeat that kind "
                        "of message.",
                    ],
                    measure=_measure(
                        f"{label} visits", f"{s['sessions']:,}", f"{int(s['sessions'] * 1.3):,}", 30
                    ),
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
                diagnosis=f"The store converts {store_cvr:.2f}% now against {prev_cvr:.2f}% "
                f"before ({compare_label}). The device, source and page items in this list show "
                "where the drop sits.",
                steps=[
                    "On the Conversion tab, compare devices and channels with the period before to "
                    "find the segment that fell most.",
                    "Check the Change log for theme, app, price or discount changes in this "
                    "period.",
                    "Fix the biggest device or page item in this list first.",
                ],
                measure=_measure("Store conversion rate", _pct(store_cvr), _pct(prev_cvr), 21),
            )
        )
    return out


def funnel_step_items(funnel: dict[str, Any] | None, aov: float) -> list[dict[str, Any]]:
    """A funnel step that breaks on one device: its rate from the step before is 8+ points under
    the best device's, with 100+ shoppers at that step. Impact = shoppers x gap x (for the cart
    step) the device's checkout completion x average order."""
    out: list[dict[str, Any]] = []
    devices = [d for d in (funnel or {}).get("devices") or [] if (d.get("sessions") or 0) >= 300]
    if len(devices) < 2 or not aov:
        return out
    rates = {str(d["label"]): _step_rates(d) for d in devices}
    for step in ("reached_checkout", "completed_checkout"):
        usable = {
            k: r[step] for k, r in rates.items() if r[step][2] is not None and r[step][0] >= 100
        }
        if len(usable) < 2:
            continue
        best = max(usable, key=lambda k: usable[k][2] or 0)
        for device, (before, count, rate) in usable.items():
            gap = (usable[best][2] or 0) - (rate or 0)
            if device == best or gap < 8:
                continue
            finish = (
                (rates[device]["completed_checkout"][2] or 0) / 100
                if step == ("reached_checkout")
                else 1.0
            )
            impact = before * gap / 100 * finish * aov
            a, b = STEP_NAMES[step]
            out.append(
                _impact_rec(
                    "funnel_step",
                    "fix",
                    f"funnel_step:{device.lower()}:{step}",
                    f"Fix the {device.lower()} {a} step: {rate}% go on to {b} vs "
                    f"{usable[best][2]}% "
                    f"on {best.lower()}",
                    "Cart & checkout",
                    f"Device · {device} · {a} to {b}",
                    [
                        f"{device}: {before:,} at {a} → {count:,} at {b} ({rate}%)",
                        f"{best}: {usable[best][0]:,} → {usable[best][1]:,} ({usable[best][2]}%)",
                        f"{device} checkout to order: {rates[device]['completed_checkout'][2]}%"
                        if step == "reached_checkout"
                        else None,
                    ],
                    impact,
                    f"{before:,} {a}s × {gap:.1f} pts gap"
                    + (f" × {finish * 100:.1f}% checkout completion" if finish != 1.0 else "")
                    + f" × {money(aov)} average order",
                    diagnosis=f"On {device.lower()}, only {rate}% of shoppers who reach the {a} go "
                    f"on to {b}, against {usable[best][2]}% on {best.lower()}. The loss sits at "
                    f"this step, not in the traffic.",
                    steps=[
                        f"On a {device.lower()}, add a best seller to the cart and go to {b}; note "
                        "every element that slows you down or hides the next button.",
                        STEP_FIX[step].format(device=device.lower()),
                        "Remove one obstacle at a time and log each change in the Change log.",
                    ],
                    measure=_measure(
                        f"{device} {a} to {b} rate", f"{rate}%", f"{(rate or 0) + gap / 2:.1f}%"
                    ),
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
                diagnosis=f"{rate}% of {label} payments go through, against {overall}% for all "
                "methods: shoppers who chose it and wanted to buy are being turned away at the "
                "last step.",
                steps=[
                    f"In Settings > Payments, open {label} and check its status and any notices.",
                    f"Place a small test order with {label} on a phone and on desktop.",
                    f"Ask the {label} provider for the decline reasons in these days.",
                    "If it keeps failing, show a method that works better above it.",
                ],
                measure=_measure(f"{label} payment success rate", f"{rate}%", f"{overall}%"),
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
        name = p["name"]
        out.append(
            _impact_rec(
                "product_leaky",
                "fix",
                f"product_leaky:{p['product_id']}",
                f"Fix product page {name}: converts {cvr:.2f}% vs {cat:.2f}% for {peers}",
                "Products",
                f"Product · {name}",
                [
                    f"{int(p['views']):,} product views in {days} days (GA4), conversion "
                    f"{cvr:.2f}% vs {cat:.2f}% for {peers}",
                    f"Added to cart on {atc}% of views" if atc is not None else None,
                    "Check the photos, price, reviews, delivery promise and stock on this page",
                ],
                float(p["left_on_table"]),
                f"{int(p['views']):,} views × {cat - cvr:.2f} pts conversion gap × "
                f"{money(float(p['price'] or 0))} price",
                diagnosis=f"{name} is seen often ({int(p['views']):,} views) but only {cvr:.2f}% "
                f"of views end in an order, against {cat:.2f}% for {peers}. Shoppers want this "
                "kind of product; something on this page puts them off.",
                steps=[
                    f"Open {name} on a phone next to the best seller in {peers}: compare photos, "
                    "price, sizes shown, delivery promise and reviews.",
                    "Check every size and colour is in stock and the default variant is the one "
                    "most people buy.",
                    "Change the one thing that differs most, and log it in the Change log.",
                    f"If it still converts under {cat:.2f}% after three weeks, move it down its "
                    "collections.",
                ],
                measure=_measure(
                    f"Conversion of {name} views",
                    f"{cvr:.2f}%",
                    f"{cvr + (cat - cvr) / 2:.2f}%",
                    21,
                ),
            )
        )
    return out


# ----------------------------------------------------------------------------- deep checks
def free_shipping_items(values: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Orders just under the free-shipping amount: if a third of them added a small item to reach
    it. Impact = orders just under x 1/3 x the average amount they were short."""
    v = values or {}
    threshold, near = v.get("threshold"), int(v.get("near_threshold_orders") or 0)
    share, start = v.get("near_threshold_share"), v.get("near_threshold_from")
    if not threshold or near < 10 or not share or share < 8 or start is None:
        return []
    short = (float(threshold) - float(start)) / 2
    impact = near / 3 * short
    return [
        _rec(
            f"Help the {near} orders just under free shipping ({money(threshold)}) reach it",
            f"{share}% of orders ({near}) end between {money(start)} and {money(threshold)}: "
            "these shoppers were close to free shipping and stopped. A nudge in the cart and a "
            "small add-on can carry part of them over and lift the average order.",
            f"{near} orders ({share}%) between {money(start)} and {money(threshold)}",
            "Medium",
            "Show how far the cart is from free shipping and offer small add-ons.",
            "Average order value",
            key="free_shipping:near",
            area="Cart & checkout",
            effort=EFFORT["free_shipping"],
            kind="free_shipping",
            act="test",
            segment=f"Orders just under {money(threshold)}",
            evidence_list=[
                f"{near} orders ({share}%) between {money(start)} and {money(threshold)}",
                f"{v.get('at_or_above_threshold_share')}% of orders already qualify",
                f"Average order {money(float(v.get('average') or 0))}, median "
                f"{money(float(v.get('median') or 0))}",
            ],
            impact=impact,
            formula=f"{near} orders ÷ 3 × {money(short)} average amount short",
            steps=[
                f"Add a 'You are $X away from free shipping' bar to the cart drawer and cart page "
                f"(theme editor or a cart app), set to {money(threshold)}.",
                f"Show 2-3 add-ons under {money(float(threshold) - float(start))} in the cart, "
                "such as napkins or pillow covers that match what is in it.",
                "Say the free-shipping amount on product pages near the price.",
            ],
            measure=_measure(
                "Share of orders just under free shipping", f"{share}%", f"{share * 0.7:.1f}%", 30
            ),
            experiment_metric="aov",
        )
    ]


def search_items(search: dict[str, Any] | None, aov: float | None) -> list[dict[str, Any]]:
    """Site searches that find nothing, and popular searches whose results few people click.
    Impact uses the store's own orders per search: searchers' orders ÷ searches."""
    s = search or {}
    out: list[dict[str, Any]] = []
    searches = int(s.get("searches") or 0)
    if not searches or not aov:
        return out
    orders = (s.get("sessions_with_searches") or 0) * (s.get("searcher_conversion_rate") or 0) / 100
    per_search = orders / searches if searches else 0
    none = [t for t in s.get("zero_result_terms") or [] if (t.get("searches") or 0) >= 5][:6]
    if none:
        n = sum(int(t["searches"]) for t in none)
        terms = ", ".join(f"'{t['term']}' ({t['searches']})" for t in none)
        out.append(
            _rec(
                f"Make {len(none)} searches that find nothing return products",
                f"Shoppers searched for {terms} and got no results. Searchers are the store's most "
                "ready-to-buy visitors, so each empty result is a likely lost order.",
                f"{n} searches with no results: {terms}",
                "Medium",
                "Add these words to matching products, or set up search redirects.",
                "Site search",
                key="search_none:terms",
                area="Site health",
                effort=EFFORT["search_none"],
                kind="search_none",
                segment="Site search · no results",
                evidence_list=[
                    f"{n} searches with no results: {terms}",
                    f"Searchers convert {_pct(s.get('searcher_conversion_rate'))} vs "
                    f"{_pct(s.get('non_searcher_conversion_rate'))} for others",
                ],
                impact=n * per_search * aov,
                formula=f"{n} searches × {per_search * 100:.2f}% orders per search × "
                f"{money(aov)} average order",
                steps=[
                    "For each term, find the products it should show and add the word to their "
                    "title, tags or description (or as a synonym in Search & Discovery).",
                    "For a term you do not sell, add a search redirect to the closest collection.",
                    "Search each term on the live store afterwards to confirm results appear.",
                ],
                measure=_measure("Searches with no results", str(n), "0", 21),
            )
        )
    overall = s.get("search_click_rate")
    weak = [
        t
        for t in s.get("top_terms") or []
        if overall
        and (t.get("searches") or 0) >= 50
        and t.get("click_rate") is not None
        and t["click_rate"] < overall - 15
    ][:6]
    if weak and overall:
        clicks = (s.get("search_click_rate") or 0) / 100 * searches
        per_click = orders / clicks if clicks else 0
        extra = sum(t["searches"] * (overall - t["click_rate"]) / 2 / 100 for t in weak)
        terms = ", ".join(f"'{t['term']}' ({t['click_rate']:.0f}%)" for t in weak)
        out.append(
            _rec(
                f"Improve the results of {len(weak)} popular searches few people click",
                f"Results for {terms} get far fewer clicks than the {overall:.0f}% average: the "
                "products shown first are probably not what shoppers typed.",
                f"Click rate: {terms} vs {overall:.0f}% for all searches",
                "Medium",
                "Boost the right products for these terms in Search & Discovery.",
                "Search click rate",
                key="search_clicks:terms",
                area="Site health",
                effort=EFFORT["search_clicks"],
                kind="search_clicks",
                segment="Site search · weak results",
                evidence_list=[
                    *(
                        f"'{t['term']}': {t['searches']} searches, {t['click_rate']:.0f}% clicked"
                        for t in weak
                    ),
                    f"All searches: {overall:.0f}% clicked",
                ],
                impact=extra * per_click * aov,
                formula=f"{extra:.0f} extra clicks (half the gap to {overall:.0f}%) × "
                f"{per_click * 100:.1f}% orders per click × {money(aov)} average order",
                steps=[
                    "Search each term on the live store and note what the first row shows.",
                    "In the Search & Discovery app, boost the products that match each term and "
                    "add synonyms (for example 'runner, table runner').",
                    "Check each term's click rate again after three weeks.",
                ],
                measure=_measure(
                    f"Click rate for '{weak[0]['term']}'",
                    f"{weak[0]['click_rate']:.0f}%",
                    f"{(weak[0]['click_rate'] + overall) / 2:.0f}%",
                    21,
                ),
            )
        )
    return out


SPEED_FIX = {
    "lcp": "make the main image smaller (under 200 KB), drop sliders above the fold and load "
    "it first",
    "inp": "remove or delay apps and scripts that run on this template (pop-ups, chat, reviews "
    "widgets) and retest a tap",
    "cls": "give images and banners a fixed height and stop late-loading blocks pushing the page "
    "down",
}
SPEED_NAME = {
    "lcp": "main content shows (LCP)",
    "inp": "reacts to a tap (INP)",
    "cls": "layout stays put (CLS)",
}


def speed_items(site: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Mobile page types rated poor (or LCP needing work) by Google with 500+ page loads; no money
    estimate (speed and sales are not measured together)."""
    out: list[dict[str, Any]] = []
    for row in (site or {}).get("page_types") or []:
        loads = int(row.get("page_loads") or 0)
        bad = [
            k
            for k in ("lcp", "inp", "cls")
            if (row.get(k) or {}).get("rating") == "poor"
            or (k == "lcp" and (row.get(k) or {}).get("rating") == "needs_improvement")
        ]
        if loads < 500 or not bad:
            continue
        label = str(row.get("label") or "Page")
        lines = [
            f"{SPEED_NAME[k]}: p75 {(row[k] or {}).get('p75')}"
            f"{' ms' if k != 'cls' else ''}, rated "
            f"{(row[k] or {}).get('rating', '').replace('_', ' ')}"
            for k in bad
        ]
        out.append(
            _rec(
                f"Speed up mobile {label.lower()} pages: {', '.join(k.upper() for k in bad)} "
                "rated slow",
                f"On mobile {label.lower()} pages ({loads:,} page loads), Google rates "
                f"{' and '.join(SPEED_NAME[k] for k in bad)} as not good. Slow or jumpy pages lose "
                "shoppers before they see the product.",
                lines[0],
                "Medium",
                f"On the {label.lower()} template, " + SPEED_FIX[bad[0]] + ".",
                "Page speed",
                key=f"page_speed:{label.lower()}",
                area="Site health",
                effort=EFFORT["page_speed"],
                kind="page_speed",
                segment=f"Mobile · {label}",
                evidence_list=[*lines, f"{loads:,} mobile page loads"],
                steps=[
                    *(f"On the {label.lower()} template, {SPEED_FIX[k]}." for k in bad),
                    "Check the Site health tab after a week (Shopify publishes speed 1-2 days "
                    "late).",
                ],
                measure=_measure(
                    f"Mobile {label.lower()} {bad[0].upper()}",
                    str((row[bad[0]] or {}).get("p75")),
                    {"lcp": "2,500 ms", "inp": "200 ms", "cls": "0.1"}[bad[0]],
                    14,
                ),
            )
        )
    return out[:3]


def discount_items(codes: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Discounts given without a code (automatic discounts) rising 1.5+ points of gross sales.
    Impact = the rise x gross sales of those orders."""
    c = codes or {}
    now, before = c.get("without_code") or {}, (c.get("previous") or {}).get("without_code") or {}
    pct, prev = now.get("discount_pct"), before.get("discount_pct")
    if pct is None or prev is None or (now.get("orders") or 0) < 50 or pct - prev < 1.5:
        return []
    gross = float(now.get("net_sales") or 0) + float(now.get("discount_given") or 0)
    rise = pct - prev
    return [
        _rec(
            f"Automatic discounts rose to {pct:.1f}% of sales on orders without a code",
            f"Orders placed without a code now get {pct:.1f}% off, against {prev:.1f}% before; the "
            f"average of these orders is {money(float(now.get('aov') or 0))} against "
            f"{money(float(before.get('aov') or 0))}. The store is giving away more without "
            "selling more per order.",
            f"Discount on no-code orders {prev:.1f}% → {pct:.1f}%",
            "Medium",
            "Review automatic discounts and add a minimum spend.",
            "Discount rate",
            key="discount_rise:no_code",
            area="Sales",
            effort=EFFORT["discount_rise"],
            kind="discount_rise",
            segment="Orders without a code",
            evidence_list=[
                f"Discount on no-code orders {prev:.1f}% → {pct:.1f}%",
                f"Average no-code order {money(float(before.get('aov') or 0))} → "
                f"{money(float(now.get('aov') or 0))}",
                f"{now.get('orders')} orders without a code",
            ],
            impact=rise / 100 * gross,
            formula=f"{rise:.1f} pts rise × {money(gross)} gross sales of no-code orders",
            steps=[
                "In Discounts, filter Automatic and list every discount active in these days with "
                "its start date and use.",
                "Give site-wide automatic discounts a minimum purchase just above the median "
                "order, so they lift the basket instead of cutting the price.",
                "End any automatic discount that has run its course.",
            ],
            measure=_measure(
                "Discount % on orders without a code", f"{pct:.1f}%", f"{prev + rise / 2:.1f}%", 30
            ),
            experiment_metric="aov",
        )
    ]


def bundle_items(bought: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Products often bought together (30%+ of the first product's orders, 8+ orders together):
    offer them as a set. No money estimate (the second product's price is not in this report)."""
    out = []
    for r in (bought or {}).get("rows") or []:
        pct, together = r.get("pct_of_a"), int(r.get("orders_together") or 0)
        if pct is None or pct < 30 or together < 8:
            continue
        a, b = r["a"], r["b"]
        out.append(
            _rec(
                f"Offer {a} with {b} as a set",
                f"{pct:.0f}% of orders with {a} also had {b} ({together} orders). Shoppers already "
                "pair them; making the pair one click raises the basket of those who buy only the "
                "first.",
                f"{together} orders together, {pct:.0f}% of {a}'s orders",
                "Low",
                f"Add a 'complete the set' block for {b} on {a}'s page.",
                "Items per order",
                key=f"bundle:{str(a).lower()}|{str(b).lower()}",
                area="Products",
                effort=EFFORT["bundle"],
                kind="bundle",
                act="test",
                segment=f"Products · {a} + {b}",
                evidence_list=[
                    f"{together} orders together, {pct:.0f}% of {a}'s orders",
                    *([f"{r['lift']} times more often than chance"] if r.get("lift") else []),
                ],
                steps=[
                    f"On {a}'s product page, add a 'complete the set' block with {b} "
                    "(theme editor: related or complementary products).",
                    f"Show {b} in the cart when {a} is in it.",
                    "If both sell well, create a bundle product with a small set price.",
                ],
                measure=_measure(
                    f"Share of {a} orders with {b}", f"{pct:.0f}%", f"{min(pct + 10, 95):.0f}%", 30
                ),
                experiment_metric="aov",
            )
        )
        if len(out) >= 3:
            break
    return out


def refund_items(refunds: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Products refunded at twice the store's rate (and at least 10% of their gross sales).
    Impact = the refunds above the store's rate."""
    r = refunds or {}
    store = float(r.get("store_refund_rate") or 0)
    out = []
    for p in r.get("by_rate") or []:
        rate, gross = p.get("refund_rate"), float(p.get("gross_sales") or 0)
        if rate is None or rate < max(10.0, store * 2) or not gross:
            continue
        name = p["name"]
        out.append(
            _rec(
                f"Find out why {name} is refunded {rate:.1f}% of the time",
                f"{name} has {rate:.1f}% of its gross sales refunded, against {store:.1f}% for the "
                "store. A product refunded this often usually differs from its page: size, colour "
                "or quality.",
                f"Refunded {money(float(p.get('refunded') or 0))} of {money(gross)} ({rate:.1f}%)",
                "Medium",
                "Read the refund reasons and fix the product page.",
                "Refund rate",
                key=f"refunds:{str(name).lower()}",
                area="Products",
                effort=EFFORT["refunds"],
                kind="refunds",
                segment=f"Product · {name}",
                evidence_list=[
                    f"Refunded {money(float(p.get('refunded') or 0))} of {money(gross)} "
                    f"({rate:.1f}%)",
                    f"Store refund rate {store:.1f}%",
                ],
                impact=(rate - store) / 100 * gross,
                formula=f"({rate:.1f}% - {store:.1f}%) × {money(gross)} gross sales",
                steps=[
                    f"In Orders, filter by {name} and Refunded; note the reason and note of each.",
                    "If the reason is size or colour, add measurements and a daylight photo to the "
                    "page; if quality, check the supplier batch.",
                    "Log the page change and watch the refund rate for a month.",
                ],
                measure=_measure(
                    f"Refund rate of {name}", f"{rate:.1f}%", f"{max(store, rate / 2):.1f}%", 30
                ),
            )
        )
        if len(out) >= 3:
            break
    return out


def deep_items(
    *,
    funnel: dict[str, Any] | None = None,
    order_values: dict[str, Any] | None = None,
    search: dict[str, Any] | None = None,
    site: dict[str, Any] | None = None,
    codes: dict[str, Any] | None = None,
    bought: dict[str, Any] | None = None,
    refunds: dict[str, Any] | None = None,
    aov: float | None = None,
) -> list[dict[str, Any]]:
    """The deep checks from the reports the Recommendations tab reads besides landing pages and
    payments. A missing report adds nothing."""
    return [
        *(funnel_step_items(funnel, aov) if aov else []),
        *free_shipping_items(order_values),
        *search_items(search, aov),
        *speed_items(site),
        *discount_items(codes),
        *bundle_items(bought),
        *refund_items(refunds),
    ]


def impact_items(
    *,
    landing: dict[str, Any] | None,
    payments: dict[str, Any] | None,
    aov: float | None,
    compare_label: str,
    funnel: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], float | None, int]:
    """(recommendations with an estimated impact, store conversion, visits) from the landing-page
    report (every landing page Shopify lists, up to 200), the payment report, the funnel per
    device and the average order value. Nothing when a source is missing."""
    if not landing or not aov:
        return [], None, 0
    store_cvr, visits = weighted_cvr(landing.get("by_device") or [])
    if not store_cvr:
        return [], None, visits
    out = _landing_items(landing, store_cvr, aov, compare_label)
    out += _segment_items(landing, store_cvr, visits, aov, compare_label, funnel)
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
