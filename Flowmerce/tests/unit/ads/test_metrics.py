"""Ads rules (modules/ads/metrics.py): verdicts, weakest step, budget calls, the scaling gate,
product lines and rule validation. Pure functions: no database, no network."""

from __future__ import annotations

import pytest

from flowmerce.modules.ads import metrics
from flowmerce.modules.ads.metrics import Totals

R = metrics.rules_for("ridhi", {})


def t(spend: float, purchases: float = 0, value: float = 0, **kw: int) -> Totals:
    return Totals(spend=spend, purchases=purchases, value=value, **kw)


def test_rules_start_from_the_daily_sheet_and_take_the_teams_changes() -> None:
    assert R["target_roas"] == 2.2 and R["test_spend"] == 110 and R["goal_daily_sales"] == 20000
    assert metrics.rules_for("cpc", {})["goal_daily_sales"] == 8000
    changed = metrics.rules_for("ridhi", {"stop_roas": 1.2, "nonsense": 5, "target_mer": "x"})
    assert (
        changed["stop_roas"] == 1.2 and "nonsense" not in changed and changed["target_mer"] == 2.5
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"nonsense": 1},
        {"fx_rate": 0},
        {"budget_step_pct": 80},
        {"stop_roas": True},
        {"stop_roas": "2"},
        {"cbo_min_ads": 9},
    ],
)
def test_bad_rule_changes_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        metrics.check_rule_changes(changes, R)


def test_good_rule_changes_are_returned_as_numbers() -> None:
    assert metrics.check_rule_changes({"fx_rate": 95, "stop_roas": 1.4}, R) == {
        "fx_rate": 95.0,
        "stop_roas": 1.4,
    }


def test_verdicts_follow_the_test_and_proven_rules() -> None:
    none = t(0)
    assert metrics.verdict(none, none, t(80, 1, 300), False, R)[0] == "testing"
    assert metrics.verdict(none, none, t(150), False, R) == (
        "stop",
        "No purchase after $150 (test limit $110).",
    )
    assert metrics.verdict(none, none, t(180, 2, 400), False, R)[0] == "continue"
    assert (
        metrics.verdict(t(50, 1, 40), t(200, 2, 200), t(900, 20, 3000), False, R)[0] == "stop"
    )  # 7-day 1.0
    assert metrics.verdict(none, none, t(900, 9, 1000), False, R)[0] == "stop"  # lifetime 1.11
    assert metrics.verdict(t(60, 2, 150), t(300, 6, 900), t(900, 20, 2500), False, R)[0] == "scale"
    assert metrics.verdict(t(10, 0, 0), t(80, 1, 100), t(400, 5, 1200), True, R)[0] == "graduate"
    assert metrics.verdict(t(10, 0, 0), t(80, 1, 100), t(400, 5, 1200), False, R)[0] == "iterate"
    assert metrics.verdict(none, none, t(400, 5, 1200), False, R)[0] == "hold"


def test_weakest_step() -> None:
    assert metrics.weakest(True, Totals(impressions=100))["key"] == "early"
    assert (
        metrics.weakest(True, Totals(impressions=1000, vimp=1000, v3=100, clicks=50))["key"]
        == "hook"
    )
    assert metrics.weakest(False, Totals(impressions=1000, clicks=10)) == {
        "key": "click",
        "label": "Image",
    }
    assert (
        metrics.weakest(False, Totals(impressions=1000, clicks=40, lpv=100, atc=5))["key"]
        == "landing"
    )
    assert (
        metrics.weakest(False, Totals(impressions=1000, clicks=40, lpv=100, atc=20, purchases=1))[
            "key"
        ]
        == "checkout"
    )
    assert (
        metrics.weakest(False, Totals(impressions=1000, clicks=40, lpv=100, atc=20, purchases=4))[
            "key"
        ]
        == "none"
    )


def test_budget_call() -> None:
    assert metrics.budget_call(1000, 3, 3, 1.5, R)["key"] == "hold"  # changed in the last 72 hours
    up = metrics.budget_call(1000, 2.5, 2.0, None, R)
    assert up["key"] == "increase" and up["new_budget"] == 1200
    down = metrics.budget_call(1000, 1.5, 2.0, 10, R)
    assert down["key"] == "decrease" and down["new_budget"] == 800
    assert metrics.budget_call(1000, 1.9, 1.5, None, R)["key"] == "hold"


def test_scaling_gate() -> None:
    green = metrics.gate(2.3, 2.1, 3000, R)
    assert green["state"] == "green" and green["recommended_daily_spend"] == 3600
    assert metrics.gate(1.54, 1.8, 2774, R)["state"] == "red"  # the Daily sheet of 24 Oct: RED
    assert metrics.gate(2.0, 1.9, 3000, R)["state"] == "amber"
    # a missing figure, or days whose ad spend is not saved yet, is no call, never "cut back"
    assert metrics.gate(None, None, 0, R)["state"] == "unknown"
    assert metrics.gate(None, 7.03, 910, R)["state"] == "unknown"
    nocall = metrics.gate(2.3, 2.1, 3000, R, complete=False)
    assert nocall["state"] == "unknown" and nocall["recommended_daily_spend"] == 3000
    assert metrics.day_colour(2.45, R) == "green" and metrics.day_colour(1.92, R) == "amber"
    assert metrics.day_colour(1.22, R) == "red" and metrics.day_colour(None, R) is None


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("CBO | Sales | Quilt | #4 | 05-September-26", "quilt"),
        ("#1 Master Tablecloth CBO | Sales | USA | 29-July-2026", "rectangle"),
        ("ABO Testing | Round Tablecloth | Audinece Test | 02-Oct-26", "round"),
        ("CBO | #5 | Sales | Scallop Stripe Tablecloths | 25-September", "stripe"),
        ("ABO | Christmas Tree Skirt | Audience Test | 21-11-26", "skirt"),
        ("Full catalog Campaign 30-jan-26", "all"),
    ],
)
def test_product_line_from_real_campaign_names(name: str, line: str) -> None:
    assert metrics.product_line(name) == line


def test_campaign_type_and_ad_code() -> None:
    assert metrics.campaign_type("Anything", None, 136.0) == "cbo"
    assert metrics.campaign_type("Master Tablecloth ABO | Multiple Adset", None, None) == "abo"
    assert metrics.campaign_type("Full catalog Campaign", "OUTCOME_SALES", 160.0) == "catalog"
    assert (
        metrics.campaign_type("V2 | New Sales Retargetting campaign", None, 22.0) == "retargeting"
    )
    assert metrics.ad_code("CR291 | Real Product Unboxing | Quilt") == "CR291"
    assert metrics.ad_code("Q32 | made my bedroom") == "Q32"


def test_proven_needs_spend_roas_and_purchases() -> None:
    assert metrics.proven(t(290, 6, 1250), R)
    assert not metrics.proven(t(200, 6, 1250), R)
    assert not metrics.proven(t(290, 2, 1250), R)
    assert not metrics.proven(t(290, 6, 500), R)
