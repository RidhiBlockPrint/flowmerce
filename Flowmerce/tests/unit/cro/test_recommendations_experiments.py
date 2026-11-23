"""CRO batch 3: impact-ranked recommendations, their status, and experiment results.

No network: Shopify is a fake GraphQL function; Supabase is never called."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flowmerce.modules.cro import conversion, experiments, recommendations, service


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    conversion.clear_cache()
    yield
    conversion.clear_cache()


def page(path: str, visits: int, cvr: float, **over: Any) -> dict[str, Any]:
    return {
        "path": path,
        "page_type": "Collection",
        "sessions": visits,
        "conversion_rate": cvr,
        "bounce_rate": 50.0,
        "added_to_cart_rate": 4.0,
        "too_few_sessions": visits < 100,
        "bounce_change_pts": None,
        "conversion_change_pts": None,
        "previous_bounce_rate": None,
        "previous_conversion_rate": None,
        "revenue": 0.0,
        "orders": 0,
        "top_source": "social",
        "top_source_share": 70.0,
        **over,
    }


def seg(label: str, visits: int, cvr: float, prev: int = 0, prev_cvr: float | None = None) -> dict:
    return {
        "label": label,
        "sessions": visits,
        "conversion_rate": cvr,
        "bounce_rate": 40.0,
        "too_few_sessions": visits < 100,
        "previous_sessions": prev,
        "previous_conversion_rate": prev_cvr,
    }


LANDING = {
    "min_sessions": 100,
    "bounce_flag_pts": 5.0,
    "by_device": [seg("mobile", 8000, 1.5, 8000, 1.6), seg("desktop", 2000, 3.5, 2000, 3.4)],
    "by_source": [seg("social", 5000, 1.0), seg("email", 500, 4.5), seg("direct", 4500, 2.5)],
    "pages": [
        page("/collections/quilts", 6000, 0.9),
        page("/", 2500, 3.0),
        page(
            "/collections/fall",
            1000,
            1.6,
            bounce_change_pts=7.0,
            conversion_change_pts=-0.4,
            previous_bounce_rate=50.0,
            bounce_rate=57.0,
            previous_conversion_rate=2.0,
        ),
        page("/collections/runners", 300, 4.2, revenue=1200.0, orders=12),
        page("/pages/about", 40, 0.0),
    ],
}


def test_impact_items_follow_the_prototype_rules() -> None:
    items, store_cvr, visits = recommendations.impact_items(
        landing=LANDING, payments=None, aov=100.0, compare_label="before"
    )
    assert (store_cvr, visits) == (1.9, 10000)
    by_key = {r["key"]: r for r in items}
    fix = by_key["landing_fix:/collections/quilts"]
    # 6,000 visits x 1.0 pt gap (1.9 - 0.9) x $100 = $6,000
    assert (fix["action"], fix["effort"], fix["impact"]) == ("fix", "Medium", 6000.0)
    assert fix["impact_formula"].startswith("6,000 visits × 1.00 pts")
    assert "landing_bounce:/collections/fall" in by_key  # bounce +7 pts and conversion fell
    promote = by_key["landing_promote:/collections/runners"]
    assert promote["action"] == "promote" and promote["impact"] == 690.0  # 300 x 2.3 pts x $100
    assert by_key["source_test:social"]["action"] == "test"  # 1.0% < 0.6 x 1.9%
    assert "source_promote:email" in by_key  # 4.5% > 1.5 x 1.9%
    assert "device_gap:mobile" in by_key  # 1.5% < 0.85 x 1.9%
    assert "landing_fix:/pages/about" not in by_key  # too few visits to judge
    assert all(isinstance(r["evidence"], str) and r["evidence_list"] for r in items)


def test_no_impact_items_without_landing_or_order_value() -> None:
    assert (
        recommendations.impact_items(landing=None, payments=None, aov=100, compare_label="")[0]
        == []
    )
    assert (
        recommendations.impact_items(landing=LANDING, payments=None, aov=None, compare_label="")[0]
        == []
    )


def test_payment_methods_failing_more_than_the_rest() -> None:
    pay = {
        "success_rate": 98.0,
        "methods": [
            {"label": "credit_card", "attempts": 1000, "failed_attempts": 20, "success_rate": 98.5},
            {"label": "paypal", "attempts": 100, "failed_attempts": 9, "success_rate": 91.0},
            {"label": "klarna", "attempts": 10, "failed_attempts": 5, "success_rate": 50.0},
        ],
        "wallets": [],
    }
    items, _, _ = recommendations.impact_items(
        landing=LANDING, payments=pay, aov=100.0, compare_label=""
    )
    paid = [r for r in items if r["kind"] == "payment_method"]
    assert [r["key"] for r in paid] == ["payment_method:paypal"]  # klarna: under 30 attempts
    assert paid[0]["impact"] == 700.0  # 100 attempts x 7 pts x $100


def test_rank_puts_estimates_first_then_priority_and_keys_are_unique() -> None:
    extra, _, _ = recommendations.impact_items(
        landing=LANDING, payments=None, aov=100.0, compare_label=""
    )
    recs = recommendations.build(
        product_alarms=[
            {
                "status": "alarm_active",
                "keyword": "quilt",
                "hours_elapsed": 14.0,
                "threshold_hours": 12.0,
                "last_order": "#1",
            }
        ],
        cvr=None,
        funnel=None,
        today_revenue=None,
        declines=[],
        health=None,
        extra=extra + extra[:1],
    )
    impacts = [r["impact"] for r in recs]
    assert impacts[0] == max(i for i in impacts if i is not None)
    assert impacts[-1] is None and recs[-1]["key"] == "product_gap:quilt"
    assert [r["rank"] for r in recs] == list(range(1, len(recs) + 1))
    assert len({r["key"] for r in recs}) == len(recs)


def test_each_landing_page_gets_its_own_diagnosis_steps_and_measure() -> None:
    landing = {
        **LANDING,
        "by_device": [
            {**seg("mobile", 8000, 1.5), "bounce_rate": 45.0, "added_to_cart_rate": 6.0},
            {**seg("desktop", 2000, 3.5), "bounce_rate": 45.0, "added_to_cart_rate": 6.0},
        ],
        "pages": [
            page("/collections/quilts", 6000, 0.9, bounce_rate=46.0, added_to_cart_rate=3.0),
            page("/collections/fall", 3000, 0.8, bounce_rate=62.0),
            page("/blogs/news/size-guide", 3000, 0.0, page_type="Blog post"),
            page("/products/taupe-quilt", 900, 0.5, added_to_cart_rate=7.0),
            page("/pages/contact", 800, 0.0),  # not a shopping page
        ],
    }
    items, _, _ = recommendations.impact_items(
        landing=landing, payments=None, aov=100.0, compare_label="before"
    )
    by_key = {r["key"]: r for r in items}
    browse = by_key["landing_fix:/collections/quilts"]  # stays, but adds to cart rarely
    assert "only 3.00% add to cart" in browse["diagnosis"]
    assert browse["experiment_metric"] == "added_to_cart_rate"
    assert browse["page_path"] == "/collections/quilts"
    assert any("manual sort" in s for s in browse["steps"])
    bounce = by_key["landing_fix:/collections/fall"]  # leaves at once
    assert (
        bounce["experiment_metric"] == "bounce_rate" and "70% of its visits" in bounce["diagnosis"]
    )
    assert bounce["measure"]["baseline"] == "62.0%" and bounce["measure"]["goal"] == "45.0%"
    blog = by_key["landing_fix:/blogs/news/size-guide"]  # a content page
    assert "content page" in blog["diagnosis"] and any("Blog posts" in s for s in blog["steps"])
    cart = by_key["landing_fix:/products/taupe-quilt"]  # adds to cart, does not buy
    assert cart["experiment_metric"] == "conversion_rate" and "stall at" in cart["diagnosis"]
    assert all(r["steps"] and r["diagnosis"] for r in items)
    assert "landing_fix:/pages/contact" not in by_key


def _funnel(label: str, sessions: int, cart: int, checkout: int, done: int) -> dict[str, Any]:
    steps = [
        {"key": "added_to_cart", "count": cart},
        {"key": "reached_checkout", "count": checkout},
        {"key": "completed_checkout", "count": done},
    ]
    return {"label": label, "sessions": sessions, "steps": steps}


def test_the_funnel_step_that_breaks_on_one_device_is_named_and_sized() -> None:
    funnel = {
        "devices": [
            _funnel("Mobile", 60000, 3284, 1594, 1076),
            _funnel("Desktop", 8000, 661, 429, 307),
        ]
    }
    items = recommendations.funnel_step_items(funnel, 113.5)
    assert [r["key"] for r in items] == ["funnel_step:mobile:reached_checkout"]
    r = items[0]
    assert "48.5% go on to checkout vs 64.9% on desktop" in r["title"]
    # 3,284 carts x 16.4 pts x 67.5% checkout completion x $113.50
    assert r["impact"] == pytest.approx(3284 * 0.164 * 0.675 * 113.5, rel=0.01)
    assert recommendations.funnel_step_items({"devices": funnel["devices"][:1]}, 113.5) == []


def test_deep_checks_from_free_shipping_search_speed_discounts_bundles_and_refunds() -> None:
    items = recommendations.deep_items(
        order_values={
            "threshold": 100.0,
            "near_threshold_from": 75.0,
            "near_threshold_orders": 120,
            "near_threshold_share": 14.5,
            "at_or_above_threshold_share": 40.0,
            "average": 113.5,
            "median": 91.98,
        },
        search={
            "searches": 5830,
            "sessions_with_searches": 2419,
            "searcher_conversion_rate": 6.78,
            "non_searcher_conversion_rate": 1.85,
            "search_click_rate": 68.0,
            "zero_result_terms": [
                {"term": "king quilt", "searches": 12},
                {"term": "x", "searches": 1},
            ],
            "top_terms": [
                {"term": "round tablecloth", "searches": 468, "click_rate": 45.3},
                {"term": "quilt", "searches": 300, "click_rate": 70.0},
            ],
        },
        site={
            "page_types": [
                {"label": "Product", "page_loads": 9000, "lcp": {"p75": 3100, "rating": "poor"},
                 "inp": {"p75": 150, "rating": "good"}, "cls": {"p75": 0.02, "rating": "good"}},
                {"label": "Blog", "page_loads": 200, "cls": {"p75": 0.3, "rating": "poor"}},
            ]
        },
        codes={
            "without_code": {"orders": 1400, "discount_pct": 7.0, "aov": 113.97,
                             "net_sales": 117128.13, "discount_given": 9459.88},
            "previous": {"without_code": {"discount_pct": 4.2, "aov": 130.55}},
        },
        bought={"rows": [
            {"a": "Aquamarine Blue Quilt", "b": "Aquamarine Pillow Cover", "orders_together": 15,
             "pct_of_a": 78.9, "lift": 9.1},
            {"a": "Quilt", "b": "Napkin", "orders_together": 3, "pct_of_a": 50.0},
        ]},
        refunds={"store_refund_rate": 3.0, "by_rate": [
            {"name": "Sage Runner", "gross_sales": 2000.0, "refunded": 400.0, "refund_rate": 20.0},
            {"name": "Ok Runner", "gross_sales": 2000.0, "refunded": 100.0, "refund_rate": 5.0},
        ]},
        aov=113.5,
    )  # fmt: skip
    by_kind = {r["kind"]: r for r in items}
    assert by_kind["free_shipping"]["impact"] == pytest.approx(120 / 3 * 12.5)
    assert "'king quilt' (12)" in by_kind["search_none"]["evidence"]
    assert "'x'" not in by_kind["search_none"]["evidence"]  # under 5 searches
    assert "'round tablecloth'" in by_kind["search_clicks"]["evidence"]
    assert by_kind["page_speed"]["key"] == "page_speed:product"  # blog: too few page loads
    assert by_kind["discount_rise"]["impact"] == pytest.approx(
        0.028 * (117128.13 + 9459.88), abs=0.01
    )
    assert [r["key"] for r in items if r["kind"] == "bundle"] == [
        "bundle:aquamarine blue quilt|aquamarine pillow cover"
    ]
    assert [r["key"] for r in items if r["kind"] == "refunds"] == ["refunds:sage runner"]
    assert by_kind["refunds"]["impact"] == pytest.approx(0.17 * 2000)
    assert all(r["steps"] and r["measure"] and r["diagnosis"] for r in items)
    assert recommendations.deep_items(aov=None) == []


def test_status_input_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(service, "store_timezone", lambda _s: ZoneInfo("UTC"))
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        service.data, "set_rec_status", lambda s, k, st, by: saved.append((s, k, st))
    )
    assert service.set_rec_status("ridhi", {"key": "landing_fix:/", "status": "done"}, "me") == {
        "key": "landing_fix:/",
        "status": "done",
    }
    assert saved == [("RBP", "landing_fix:/", "done")]
    with pytest.raises(service.InputError):
        service.set_rec_status("ridhi", {"key": "x", "status": "finished"}, "me")
    with pytest.raises(service.InputError):
        service.set_rec_status("ridhi", {"key": "", "status": "done"}, "me")


# ----------------------------------------------------------------------------- experiments
def test_confidence_two_proportion_test() -> None:
    assert experiments.confidence(0.02, 10000, 0.02, 10000) == 0.0
    assert experiments.confidence(0.0175, 13857, 0.0205, 15383) == pytest.approx(93.9, abs=0.2)
    assert experiments.confidence(0.02, 0, 0.03, 100) is None
    assert experiments.confidence(0.0, 100, 0.0, 100) is None


def test_windows_before_and_during() -> None:
    today = date(2026, 11, 21)
    assert experiments.windows(date(2026, 11, 21), None, today)[-1] == "planned"
    b1, b2, d1, d2, state = experiments.windows(date(2026, 11, 14), None, today)
    assert (b1, b2, d1, d2, state) == (
        date(2026, 11, 7),
        date(2026, 11, 13),
        date(2026, 11, 14),
        date(2026, 11, 20),
        "running",
    )
    assert experiments.windows(date(2026, 11, 1), date(2026, 11, 10), today)[-1] == "finished"


def test_clean_checks_the_form() -> None:
    ok = {"name": " Sticky cart ", "hypothesis": "Lifts mobile", "metric": "conversion_rate"}
    with pytest.raises(ValueError, match="start date"):
        experiments.clean(ok)
    row = experiments.clean({**ok, "start_date": "2026-11-14", "page_path": "/collections/q"})
    assert row["name"] == "Sticky cart" and row["page_path"] == "/collections/q"
    assert experiments.clean({**ok, "metric": "aov", "start_date": "2026-11-14",
                              "page_path": "/x"})["page_path"] is None  # fmt: skip
    for bad in (
        {**ok, "metric": "revenue", "start_date": "2026-11-14"},
        {**ok, "start_date": "2026-11-14", "end_date": "2026-11-01"},
        {**ok, "start_date": "2026-11-14", "page_path": "collections/q"},
        {**ok, "name": "", "start_date": "2026-11-14"},
    ):
        with pytest.raises(ValueError):
            experiments.clean(bad)


def _fake(rows_for: Any) -> Any:
    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = rows_for(str((v or {}).get("q")))
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": rows}}}

    return gql


def test_result_for_a_landing_page_rate() -> None:
    def rows(q: str) -> list[dict[str, Any]]:
        during = "2026-11-14" in q
        return [
            {
                "landing_page_path": "/collections/quilts/",
                "sessions": "6000",
                "conversion_rate": "0.012" if during else "0.009",
                "added_to_cart_rate": "0.04",
                "bounce_rate": "0.5",
            },
            {"landing_page_path": "/other", "sessions": "999", "conversion_rate": "0.5"},
        ]

    exp = {
        "store": "TEST",
        "metric": "conversion_rate",
        "page_path": "/collections/quilts",
        "start_date": "2026-11-14",
        "end_date": None,
    }
    out = experiments.result(exp, date(2026, 11, 21), _fake(rows))
    assert (out["before"], out["during"], out["change"]) == (0.9, 1.2, 0.3)
    assert (out["before_n"], out["state"]) == (6000, "running")
    assert out["verdict"] in ("win_so_far", "running")
    assert out["before_label"] == "07 Nov - 13 Nov"
    planned = experiments.result({**exp, "start_date": "2026-12-01"}, date(2026, 11, 21))
    assert planned["verdict"] == "planned"


def test_summary_counts_wins() -> None:
    items = [
        {"result": {"state": "finished", "verdict": "win"}},
        {"result": {"state": "finished", "verdict": "no_clear_result"}},
        {"result": {"state": "running", "verdict": "running"}},
        {"result": {"state": "planned", "verdict": "planned"}},
    ]
    assert experiments.summary(items) == {
        "total": 4,
        "planned": 1,
        "running": 1,
        "finished": 2,
        "won": 1,
        "win_rate": 50,
    }
