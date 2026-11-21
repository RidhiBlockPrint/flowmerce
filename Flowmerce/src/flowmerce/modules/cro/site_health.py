"""Page speed (Core Web Vitals) and site search, from Shopify (ShopifyQL).

* Page speed: the 75th-percentile Largest Contentful Paint (LCP), Interaction to Next Paint (INP)
  and Cumulative Layout Shift (CLS) against Google's limits, by device (with the comparison
  period), by page type and for the busiest mobile pages, plus a daily mobile trend. ShopifyQL
  `web_performance`.
* Site search: the share of visits that search, how searchers convert against everyone else, top
  searches and searches that found nothing. ShopifyQL `search_conversions`, `searches`,
  `search_queries`.
Shopify publishes both about 1-2 days late; a window with nothing published yet says so.
"""

from __future__ import annotations

from typing import Any

from . import shopify
from .conversion import HUMAN
from .traffic import Window, num, rate, run_many, since

# metric -> (good up to, poor above, unit): Google's Core Web Vitals limits.
LIMITS: dict[str, tuple[float, float, str]] = {
    "lcp": (2500.0, 4000.0, "ms"),
    "inp": (200.0, 500.0, "ms"),
    "cls": (0.1, 0.25, ""),
}
CWV_SHOW = (
    "page_loads, lcp_p75_ms, inp_p75_ms, p75_cls, "
    "lcp_good_view_count, lcp_okay_view_count, lcp_poor_view_count, "
    "inp_good_view_count, inp_okay_view_count, inp_poor_view_count, "
    "cls_good_view_count, cls_okay_view_count, cls_poor_view_count"
)
MOBILE = "WHERE device_type = 'Mobile' "
FIELDS = {"lcp": "lcp_p75_ms", "inp": "inp_p75_ms", "cls": "p75_cls"}


def rating(metric: str, value: float | None) -> str | None:
    """'good' | 'needs_improvement' | 'poor' for a p75 value."""
    if value is None:
        return None
    good, poor, _ = LIMITS[metric]
    return "good" if value <= good else ("poor" if value > poor else "needs_improvement")


def vitals(row: dict[str, Any]) -> dict[str, Any]:
    """One row's page loads and, per metric, its p75, rating and good / poor shares (pure)."""
    out: dict[str, Any] = {"page_loads": int(num(row.get("page_loads")))}
    for m, key in FIELDS.items():
        raw = row.get(key)
        v: float | None = None
        if raw not in (None, ""):
            v = round(num(raw), 3) if m == "cls" else float(round(num(raw)))
        good, okay, poor = (
            int(num(row.get(f"{m}_{b}_view_count"))) for b in ("good", "okay", "poor")
        )
        measured = good + okay + poor
        out[m] = {
            "p75": v,
            "rating": rating(m, v),
            "good_share": rate(good, measured, 1),
            "poor_share": rate(poor, measured, 1),
        }
    return out


def _by(rows: list[dict[str, Any]] | None, key: str) -> dict[str, dict[str, Any]]:
    return {
        (str(r.get(key)).strip() or "Unknown"): vitals(r)
        for r in rows or []
        if r.get(key) is not None and num(r.get("page_loads")) > 0
    }


def with_change(cur: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
    """A device's vitals with each metric's comparison p75 and change (pure)."""
    for m in LIMITS:
        p = ((prev or {}).get(m) or {}).get("p75")
        c = cur[m]["p75"]
        cur[m]["previous_p75"] = p
        cur[m]["change"] = (
            (round(c - p, 3) if m == "cls" else round(c - p))
            if c is not None and p is not None
            else None
        )
    return cur


def search_summary(
    conv: dict[str, Any] | None,
    sessions: dict[str, Any] | None,
    results: list[dict[str, Any]] | None,
    top: list[dict[str, Any]] | None,
    zero: list[dict[str, Any]] | None,
    clicks: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Site search figures from the query rows (pure); None when Shopify has none."""
    if not conv:
        return None
    s_sessions = int(num(conv.get("sessions_with_searches")))
    s_orders = int(num(conv.get("search_sessions_that_completed_checkout")))
    all_sessions = int(num((sessions or {}).get("sessions")))
    all_orders = int(num((sessions or {}).get("sessions_that_completed_checkout")))
    others, other_orders = all_sessions - s_sessions, all_orders - s_orders
    searches = zero_count = 0
    for r in results or []:
        flag = r.get("search_results_were_returned")
        if flag is None:
            continue
        n = int(num(r.get("searches")))
        searches += n
        if str(flag).strip().lower() in ("false", "0", "no"):
            zero_count += n
    click_rate: dict[str, float | None] = {}
    for r in clicks or []:
        term = str(r.get("search_query") or "").strip().lower()
        if term:
            click_rate[term] = rate(
                num(r.get("search_queries_with_clicks")), num(r.get("search_queries")), 1
            )
    return {
        "sessions_with_searches": s_sessions,
        "share_of_sessions": rate(s_sessions, all_sessions),
        "searcher_conversion_rate": rate(s_orders, s_sessions),
        "non_searcher_conversion_rate": (
            rate(other_orders, others) if sessions and others > 0 and other_orders >= 0 else None
        ),
        "search_added_to_cart_rate": round(num(conv.get("search_added_to_cart_rate")) * 100, 2),
        "search_click_rate": round(num(conv.get("search_click_rate")) * 100, 2),
        "searches": searches or None,
        "zero_result_searches": zero_count if searches else None,
        "zero_result_share": rate(zero_count, searches, 1),
        "top_terms": [
            {
                "term": str(r["search_query"]),
                "searches": int(num(r.get("searches"))),
                "click_rate": click_rate.get(str(r["search_query"]).strip().lower()),
            }
            for r in top or []
            if r.get("search_query")
        ],
        "zero_result_terms": [
            {"term": str(r["search_query"]), "searches": int(num(r.get("searches")))}
            for r in zero or []
            if r.get("search_query")
        ],
    }


def site_health(
    store: str, cur: Window, base: Window | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Page speed and site search for `cur` (page speed by device also for `base`)."""
    c = since(cur)
    queries = {
        "device": f"FROM web_performance SHOW {CWV_SHOW} GROUP BY device_type {c} "
        "ORDER BY page_loads DESC",
        "page_type": f"FROM web_performance SHOW {CWV_SHOW} {MOBILE}GROUP BY page_type {c} "
        "ORDER BY page_loads DESC",
        "pages": f"FROM web_performance SHOW {CWV_SHOW} {MOBILE}GROUP BY page_path {c} "
        "ORDER BY page_loads DESC LIMIT 15",
        "trend": f"FROM web_performance SHOW page_loads, lcp_p75_ms, inp_p75_ms, p75_cls {MOBILE}"
        f"TIMESERIES day {c} ORDER BY day ASC",
        "search_conv": "FROM search_conversions SHOW sessions_with_searches, "
        "search_sessions_that_completed_checkout, search_conversion_rate, "
        f"search_added_to_cart_rate, search_click_rate {c}",
        "sessions": f"FROM sessions SHOW sessions, sessions_that_completed_checkout {HUMAN}{c}",
        "search_results": f"FROM searches SHOW searches GROUP BY search_results_were_returned {c}",
        "top_terms": f"FROM searches SHOW searches GROUP BY search_query {c} "
        "ORDER BY searches DESC LIMIT 15",
        "zero_terms": "FROM searches SHOW searches WHERE search_results_were_returned = false "
        f"GROUP BY search_query {c} ORDER BY searches DESC LIMIT 15",
        "term_clicks": "FROM search_queries SHOW search_queries, search_queries_with_clicks "
        f"GROUP BY search_query {c} ORDER BY search_queries DESC LIMIT 200",
    }
    if base:
        queries["device_prev"] = (
            f"FROM web_performance SHOW {CWV_SHOW} GROUP BY device_type {since(base)} "
            "ORDER BY page_loads DESC"
        )
    rows, errors = run_many(store, queries, gql)
    if rows.get("device") is None and rows.get("search_conv") is None:
        raise shopify.AnalyticsError(
            "shopify_error", errors.get("device") or "Shopify did not answer page speed or search."
        )
    prev = _by(rows.get("device_prev"), "device_type")
    devices = {
        k: with_change(v, prev.get(k)) for k, v in _by(rows.get("device"), "device_type").items()
    }
    trend = []
    for r in rows.get("trend") or []:
        lcp = num(r.get("lcp_p75_ms"))
        if not r.get("day") or not num(r.get("page_loads")) or lcp <= 0:
            continue  # a day Shopify has not filled in yet, not "0 seconds"
        trend.append(
            {
                "date": str(r["day"])[:10],
                "page_loads": int(num(r.get("page_loads"))),
                "lcp_s": round(lcp / 1000, 2),
                "inp_ms": round(num(r.get("inp_p75_ms"))),
                "cls": round(num(r.get("p75_cls")), 3),
            }
        )

    def first(name: str) -> dict[str, Any] | None:
        got = rows.get(name)
        return got[0] if got else None

    search = search_summary(
        first("search_conv"),
        first("sessions"),
        rows.get("search_results"),
        rows.get("top_terms"),
        rows.get("zero_terms"),
        rows.get("term_clicks"),
    )
    published = bool(devices) or bool(search and search["sessions_with_searches"])
    return {
        "limits": {m: {"good": g, "poor": p, "unit": u} for m, (g, p, u) in LIMITS.items()},
        "speed_available": bool(devices),
        "devices": devices,
        "page_types": [
            {"label": k, **v} for k, v in _by(rows.get("page_type"), "page_type").items()
        ],
        "pages": [{"path": k, **v} for k, v in _by(rows.get("pages"), "page_path").items()],
        "trend": trend,
        "search": search,
        "late_note": None
        if published
        else "Shopify publishes page speed and site search about 1-2 days late, so there is "
        "nothing for these days yet. Pick a range that ends 2 days ago.",
        "errors": errors,
    }
