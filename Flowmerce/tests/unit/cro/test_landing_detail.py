"""Landing pages week on week / month on month and one page's deep dive
(modules/cro/landing_detail.py). No network: Shopify is a fake run function."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flowmerce.modules.cro import conversion, landing_detail, traffic

Y = date(2026, 11, 22)  # yesterday


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    conversion.clear_cache()
    yield
    conversion.clear_cache()


def test_only_plain_paths_go_into_a_query() -> None:
    assert landing_detail.clean_path("https://shop.com/Collections/Quilts/?page=2") == (
        "/collections/quilts"
    )
    for bad in ("/x' OR 1=1", "/a b", "/collections/<script>"):
        with pytest.raises(landing_detail.PathError):
            landing_detail.clean_path(bad)


def test_week_and_month_windows_are_complete_days_ending_yesterday() -> None:
    w = landing_detail.windows(Y)
    assert w["week"] == ((date(2026, 11, 16), Y), (date(2026, 11, 9), date(2026, 11, 15)))
    assert w["month"] == ((date(2026, 10, 24), Y), (date(2026, 9, 24), date(2026, 10, 23)))


def _page(
    path: str, sessions: int, bounce: float, atc: float, cvr: float, kind: str = "Collection"
) -> dict[str, str]:
    return {
        "landing_page_path": path,
        "landing_page_type": kind,
        "sessions": str(sessions),
        "bounce_rate": str(bounce),
        "added_to_cart_rate": str(atc),
        "conversion_rate": str(cvr),
    }


def test_each_page_gets_both_periods_and_the_change() -> None:
    rows = landing_detail.compare_rows(
        [_page("/collections/quilts", 3085, 0.599, 0.0376, 0.0091),
         _page("/collections/xmas", 221, 0.67, 0.0226, 0.0136)],
        [_page("/collections/quilts", 3959, 0.536, 0.0283, 0.0078),
         _page("/collections/xmas", 38, 0.5, 0.158, 0.0526)],
        [{"order_landing_page_path": "/collections/quilts", "total_sales": "4928", "orders": "32"}],
        [{"order_landing_page_path": "/collections/quilts", "total_sales": "4111", "orders": "30"}],
        100,
    )  # fmt: skip
    quilts, xmas = rows
    assert quilts["now"]["sessions"] == 3085 and quilts["before"]["sessions"] == 3959
    assert quilts["change"]["sessions"] == -874 and quilts["change"]["sessions_pct"] == -22.1
    assert quilts["change"]["bounce_pts"] == 6.3 and quilts["change"]["conversion_pts"] == 0.13
    assert quilts["change"]["revenue_pct"] == 19.9 and quilts["now"]["revenue_per_session"] == 1.6
    assert quilts["low_data"] is False
    assert xmas["low_data"] is True  # 38 visits last time


def test_the_deep_dive_adds_up_its_days_and_names_what_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_run(store: str, q: str, gql: Any = None) -> list[dict[str, Any]]:
        seen.append(q)
        if "TIMESERIES day" in q and "FROM sessions" in q:
            out = []
            for i in range(60):
                d = date.fromordinal(Y.toordinal() - 59 + i)
                last_week = d >= date(2026, 11, 16)
                out.append({"day": d.isoformat(), "sessions": "400" if last_week else "560",
                            "bounce_rate": "0.6" if last_week else "0.5",
                            "added_to_cart_rate": "0.04", "conversion_rate": "0.01"})  # fmt: skip
            return out
        if "FROM sales" in q:
            return [{"day": Y.isoformat(), "total_sales": "300", "orders": "3"}]
        if "sessions_with_cart_additions" in q:  # this page's funnel by device
            week = "SINCE 2026-11-16" in q
            return [
                {"session_device_type": "mobile", "session_viewed_product": True,
                 "sessions": "800", "sessions_with_cart_additions": "90",
                 "sessions_that_reached_checkout": "36" if week else "50",
                 "sessions_that_completed_checkout": "20"},
                {"session_device_type": "mobile", "session_viewed_product": False,
                 "sessions": "1852", "sessions_with_cart_additions": "8",
                 "sessions_that_reached_checkout": "4", "sessions_that_completed_checkout": "2"},
                {"session_device_type": "desktop", "session_viewed_product": True,
                 "sessions": "271", "sessions_with_cart_additions": "9",
                 "sessions_that_reached_checkout": "5", "sessions_that_completed_checkout": "1"},
            ]  # fmt: skip
        if "referrer_source" in q:
            week = "SINCE 2026-11-16" in q
            return [{"referrer_source": "social", "sessions": "2121" if week else "3103",
                     "bounce_rate": "0.59", "added_to_cart_rate": "0.036",
                     "conversion_rate": "0.0045" if week else "0.0129"}]  # fmt: skip
        return []

    monkeypatch.setattr(traffic, "run", fake_run)
    d = landing_detail.page_detail("RBP", "/collections/quilts", Y)
    assert all("landing_page_path = '/collections/quilts'" in q or "FROM sales" in q for q in seen)
    assert len(d["daily"]) == 60 and d["daily"][-1]["revenue"] == 300.0
    week = d["week"]
    assert week["now"]["sessions"] == 2800 and week["before"]["sessions"] == 3920
    assert week["change"]["bounce_pts"] == 10.0 and week["now"]["orders"] == 3
    texts = [c["text"] for c in d["what_changed"]]
    assert any(t.startswith("Bounce rate up 10.0 pts week on week") for t in texts)
    assert any("Sessions -29% WoW" in t for t in texts)
    assert any("Source 'social': conversion 1.29% -> 0.45%" in t for t in texts)
    assert any("Biggest traffic shift: source 'social' 3,103 -> 2,121" in t for t in texts)
    assert d["sources_week"][0]["share"] == 100.0
    # This page's funnel, all devices together and per device, this week and the week before.
    f = d["funnel"]["week"]
    steps = {s["key"]: s["count"] for s in f["now"]["all"]["steps"]}
    assert f["now"]["all"]["sessions"] == 2923 and steps["viewed_product"] == 1071
    assert steps == {"viewed_product": 1071, "added_to_cart": 107, "reached_checkout": 45,
                     "completed_checkout": 23}  # fmt: skip
    assert [x["label"] for x in f["now"]["devices"]] == ["Mobile", "Desktop"]
    before = {s["key"]: s["count"] for s in f["before"]["all"]["steps"]}
    assert before["reached_checkout"] == 59 and d["funnel"]["month"]["now"] is not None
    with pytest.raises(landing_detail.PathError):
        landing_detail.page_detail("RBP", "/x' OR 1=1", Y)


def _funnel_row(path: str, viewed: bool, s: int, cart: int, chk: int, done: int) -> dict[str, Any]:
    return {
        "landing_page_path": path,
        "landing_page_type": "Collection",
        "session_viewed_product": viewed,
        "sessions": str(s),
        "sessions_with_cart_additions": str(cart),
        "sessions_that_reached_checkout": str(chk),
        "sessions_that_completed_checkout": str(done),
    }


def test_each_page_funnel_counts_product_views_and_steps() -> None:
    rows = landing_detail.funnel_rows(
        [
            _funnel_row("/collections/quilts", False, 2059, 10, 5, 2),
            _funnel_row("/collections/quilts", True, 1026, 106, 45, 26),
        ],
        [
            _funnel_row("/collections/quilts", False, 2500, 10, 5, 2),
            _funnel_row("/collections/quilts", True, 1459, 102, 30, 28),
        ],
        100,
    )
    (q,) = rows
    steps = {s["key"]: s for s in q["now"]["steps"]}
    assert q["now"]["sessions"] == 3085 and q["sessions_change"] == -874
    assert steps["viewed_product"]["count"] == 1026 and steps["viewed_product"]["step_pct"] == 33.3
    assert steps["added_to_cart"]["count"] == 116 and steps["added_to_cart"]["step_pct"] == 11.3
    assert steps["reached_checkout"]["step_pct"] == 43.1
    assert (
        steps["completed_checkout"]["count"] == 28
        and steps["completed_checkout"]["step_pct"] == 56.0
    )
    assert q["now"]["purchase_rate"] == 0.91 and q["now"]["checkout_abandonment"] == 44.0
    assert q["step_change_pts"]["added_to_cart"] == 0.93  # 3.76% now vs 2.83% before


def test_pages_side_by_side_day_by_day(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run(store: str, q: str, gql: Any = None) -> list[dict[str, Any]]:
        seen.append(q)
        if "LIMIT 200" in q:
            return [
                {"landing_page_path": p, "landing_page_type": "Collection", "sessions": str(s)}
                for p, s in (("/collections/quilts", 19193), ("/", 5006), ("/a", 10))
            ]
        if "FROM sales" in q:
            return [{"day": Y.isoformat(), "order_landing_page_path": "/", "total_sales": "90",
                     "orders": "1"}]  # fmt: skip
        return [{"day": Y.isoformat(), "landing_page_path": "/collections/quilts",
                 "sessions": "470", "bounce_rate": "0.57", "added_to_cart_rate": "0.04",
                 "conversion_rate": "0.01"}]  # fmt: skip

    monkeypatch.setattr(traffic, "run", fake_run)
    d = landing_detail.pages_daily("RBP", Y, None, 30)
    assert [p["path"] for p in d["pages"]] == ["/collections/quilts", "/", "/a"]  # busiest first
    quilts, home, _ = d["pages"]
    assert len(quilts["rows"]) == 30 and quilts["rows"][-1]["sessions"] == 470
    assert home["rows"][-1]["revenue"] == 90.0 and home["rows"][0]["sessions"] == 0
    assert (
        "IN ('/collections/quilts', '/', '/a')" in seen[-1]
        or "IN ('/collections/quilts'" in seen[-2]
    )
    picked = landing_detail.pages_daily("RBP", Y, ["/", "/x' OR 1=1"], 7)
    assert [p["path"] for p in picked["pages"]] == ["/"]  # an unsafe path is never queried
