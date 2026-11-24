"""Claude's CRO action plan (modules/cro/ai_advice.py): it uses the shared daily Claude limit,
records its cost, keeps one plan per store, asks by itself at most once a day, and never guesses a
report it could not read. The deep dive (2026-11-23) reads every CRO report and the team's store
notes, and each action carries its target, diagnosis, money impact and how to measure it. No
network: Claude and the CRO reports are replaced by stand-ins."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from flowmerce.modules.cro import ai_advice, service
from flowmerce.modules.seo.db import get, run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget
from flowmerce.modules.seo.util import HttpError


def _action(title: str, usd: float, **extra: Any) -> dict[str, Any]:
    return {
        "title": title,
        "target": {"kind": "device", "name": "Mobile"},
        "diagnosis": "Mobile shoppers drop between cart and checkout.",
        "evidence": ["Mobile 0.9% vs desktop 2.1%", "Cart to checkout 38% on mobile"],
        "impact": "High",
        "impact_usd": usd,
        "impact_math": "60,000 visits x 0.6 pts x $95 x half",
        "effort": "Low",
        "area": "checkout",
        "steps": ["Open the checkout on a phone", "Remove the extra field"],
        "measure": {
            "metric": "Mobile conversion",
            "baseline": "0.9%",
            "goal": "1.3%",
            "check_after_days": 14,
        },
        "experiment_metric": "conversion_rate",
        "page_path": "",
        "confidence": "High",
        "assumptions": "",
        **extra,
    }


PLAN = {
    "summary": "Sales are steady; mobile converts at half the desktop rate.",
    "actions": [
        _action("Fix the mobile checkout", 1700.4),
        _action("", 0),  # no title: dropped
        _action(
            "Rework /collections/quilts for mobile",
            4200,
            page_path="/collections/quilts",
            area="not-an-area",
            experiment_metric="revenue",
            measure={"metric": "x", "baseline": "1", "goal": "2", "check_after_days": 900},
        ),
    ],
}


def _usage() -> dict[str, Any]:
    return {"model": "claude-opus-5-5", "inputTokens": 10_000, "outputTokens": 2_000}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    run("DELETE FROM app_settings WHERE key LIKE 'cro_advice:%'")
    run("DELETE FROM claude_usage")
    monkeypatch.setattr(claude, "configured", lambda: True)
    monkeypatch.setattr(ai_advice, "_store_today", lambda brand: "2026-11-20")
    seen: dict[str, Any] = {}

    def fake_structured(
        system: str, prompt: str, schema: dict[str, Any], effort: str, **_k: Any
    ) -> tuple[dict[str, Any], str]:
        seen.update(system=system, prompt=prompt, schema=schema)
        monkeypatch.setattr(claude._usage, "last", _usage(), raising=False)
        return PLAN, "claude-opus-5-5"

    monkeypatch.setattr(claude, "_structured", fake_structured)
    monkeypatch.setattr(
        service,
        "overview",
        lambda b, rq: {
            "metrics": {"orders": {"value": 120, "baseline_value": 100, "change_pct": 20.0}}
        },
    )
    monkeypatch.setattr(
        service,
        "conversion_trend",
        lambda b, rq: {"total": {"sessions": 9000}, "baseline_total": {"sessions": 8000}},
    )
    monkeypatch.setattr(
        service,
        "segments",
        lambda b, d, rq: {"rows": [{"label": "mobile", "conversion_rate": 0.9}]},
    )
    monkeypatch.setattr(
        service,
        "products",
        lambda b, rq: {"products": [{"name": "Quilt", "revenue": 900, "customer_email": "x@y.z"}]},
    )
    monkeypatch.setattr(service, "order_health", lambda b, rq: {"total_orders": 120})
    monkeypatch.setattr(service, "sales_breakdown", lambda b, rq: {"rows": []})
    monkeypatch.setattr(
        service,
        "landing_pages",
        lambda b, rq: {
            "min_sessions": 100,
            "bounce_flag_pts": 5,
            "pages": [
                {"path": "/collections/quilts", "sessions": 18231, "conversion_rate": 0.94},
                {"path": "/", "sessions": 40000, "conversion_rate": 2.1, "bounce_change_pts": 9.5},
            ],
        },
    )
    monkeypatch.setattr(
        service,
        "product_insights",
        lambda b, rq: {
            "products": [
                {"name": "Quilt", "net_sales": 900.0, "views": 4000, "customer_email": "x@y.z"}
            ],
            "views": {"message": "GA4 ready"},
            "bought_together": {"rows": []},
        },
    )
    monkeypatch.setattr(
        service,
        "site_health",
        lambda b, rq: {"search": {"zero_result_terms": [{"term": "king quilt", "searches": 41}]}},
    )
    monkeypatch.setattr(
        service,
        "buy_heatmap",
        lambda b, days: {
            "source": "shopify_sessions",
            "average_cvr": 1.9,
            "cells": [{"weekday": 6, "hour": 20, "cvr": 3.1, "sessions": 400}],
        },
    )
    monkeypatch.setattr(
        service,
        "recommendation_list",
        lambda b: {
            "recommendations": [{"title": "Fix landing page /x", "status": "ignored"}],
            "skipped": [],
        },
    )

    def no_shopify(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("no shopify")

    for name in ("traffic_changes", "checkout_extras", "discount_codes", "customers", "geo"):
        monkeypatch.setattr(service, name, no_shopify)
    run("DELETE FROM app_settings WHERE key LIKE 'cro_notes:%'")

    def no_log(b: str, days: int) -> dict[str, Any]:
        raise RuntimeError("no supabase")

    monkeypatch.setattr(service, "change_log", no_log)
    # Run the background work inline so the test can read the result at once.
    monkeypatch.setattr(threading, "Thread", _Inline)
    return seen


class _Inline:
    def __init__(self, target: Any, args: tuple[Any, ...] = (), **_k: Any) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


def test_a_plan_is_made_from_the_stores_figures_and_its_cost_recorded(env: Any) -> None:
    st = ai_advice.start("ridhi", "admin@test.local")
    assert st["status"] == "ready" and st["fresh"] and st["version"] == ai_advice.PLAN_VERSION
    # Empty actions are dropped; the rest are ordered by money impact, largest first.
    assert [a["title"] for a in st["advice"]["actions"]] == [
        "Rework /collections/quilts for mobile",
        "Fix the mobile checkout",
    ]
    assert (
        '"orders"' in env["prompt"] and "x@y.z" not in env["prompt"]
    )  # figures only, no customer details
    assert (
        "change log (RuntimeError)" in st["not_available"]
    )  # an unreadable report is named, not guessed
    row = get("SELECT kind, brand_id, cost_usd FROM claude_usage")
    assert row["kind"] == "cro_advice" and row["brand_id"] == "ridhi" and row["cost_usd"] > 0


def test_claude_reads_every_report_the_cro_pages_show(env: Any) -> None:
    ai_advice.start("ridhi", "admin")
    prompt = env["prompt"]
    for figure in (
        "/collections/quilts",  # landing pages
        '"views":4000',  # products with GA4 views
        "king quilt",  # site search with no results
        "Sun 20:00",  # best hours
        '"status":"ignored"',  # the team's status on the rule-based checks
    ):
        assert figure in prompt, figure
    st = ai_advice.state("ridhi")
    for missing in ("payments and order values", "discount codes", "countries"):
        assert any(x.startswith(missing) for x in st["not_available"]), missing
    assert "No generic best practice" in env["system"]


def test_each_action_is_cleaned_to_what_the_page_can_show(env: Any) -> None:
    ai_advice.start("ridhi", "admin")
    first, second = ai_advice.state("ridhi")["advice"]["actions"]
    assert first["impact_usd"] == 4200 and second["impact_usd"] == 1700
    assert first["page_path"] == "/collections/quilts" and second["page_path"] == ""
    assert first["area"] == "operations"  # an unknown area falls back
    assert first["experiment_metric"] == "conversion_rate"  # only metrics the tracker follows
    assert first["measure"]["check_after_days"] == 90  # kept within 1-90 days
    assert second["target"] == {"kind": "device", "name": "Mobile"}
    assert second["evidence"] == ["Mobile 0.9% vs desktop 2.1%", "Cart to checkout 38% on mobile"]


def test_the_team_notes_reach_claude_and_are_kept_per_store(env: Any) -> None:
    assert ai_advice.notes("ridhi")["text"] == ""
    saved = ai_advice.set_notes("ridhi", "  Abandoned-checkout emails are on (Klaviyo).  ", "a@b.c")
    assert saved["text"] == "Abandoned-checkout emails are on (Klaviyo)." and saved["updated_by"]
    assert ai_advice.notes("cpc")["text"] == ""  # per store
    ai_advice.start("ridhi", "admin")
    assert (
        "<team_notes>\nAbandoned-checkout emails are on (Klaviyo).\n</team_notes>" in env["prompt"]
    )
    with pytest.raises(HttpError) as e:
        ai_advice.set_notes("ridhi", "x" * (ai_advice.NOTES_MAX + 1), "a@b.c")
    assert e.value.code == "bad_request"
    assert ai_advice.set_notes("ridhi", "", "a@b.c")["text"] == ""  # clearing is allowed


def test_an_older_short_plan_from_today_is_replaced_once(env: Any) -> None:
    ai_advice._save("ridhi", {"status": "ready", "day": "2026-11-20", "advice": {"actions": []}})
    assert ai_advice.state("ridhi")["fresh"] is False and ai_advice.state("ridhi")["version"] == 1
    ai_advice.start("ridhi", "admin", auto=True)
    ai_advice.start("ridhi", "admin", auto=True)
    assert get("SELECT COUNT(*) n FROM claude_usage")["n"] == 1


def test_opening_the_page_asks_at_most_once_a_day(env: Any) -> None:
    ai_advice.start("ridhi", "admin", auto=True)
    ai_advice.start("ridhi", "admin", auto=True)
    assert get("SELECT COUNT(*) n FROM claude_usage")["n"] == 1
    ai_advice.start("ridhi", "admin")  # Refresh always asks
    assert get("SELECT COUNT(*) n FROM claude_usage")["n"] == 2


def test_nothing_is_sent_when_todays_limit_is_used(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ai_budget, "status", lambda: {"todayUsd": 3.0, "dailyLimitUsd": 3.0, "remainingTodayUsd": 0}
    )
    with pytest.raises(HttpError) as e:
        ai_advice.start("ridhi", "admin")
    assert e.value.code == "daily_limit" and "prompt" not in env


def test_a_claude_failure_keeps_the_last_plan_and_shows_the_error(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_advice.start("cpc", "admin")

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise claude.ClaudeError("Claude rejected the API key", "auth")

    monkeypatch.setattr(claude, "_structured", refuse)
    st = ai_advice.start("cpc", "admin")
    assert st["status"] == "ready" and st["advice"]["actions"] and "API key" in (st["error"] or "")


def test_without_a_key_the_page_is_told_how_to_set_it_up(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude, "configured", lambda: False)
    with pytest.raises(HttpError) as e:
        ai_advice.start("ridhi", "admin")
    assert e.value.code == "pending_setup"
    assert ai_advice.state("ridhi")["configured"] is False
