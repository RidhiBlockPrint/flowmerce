"""Claude's CRO action plan (modules/cro/ai_advice.py): it uses the shared daily Claude limit,
records its cost, keeps one plan per store, asks by itself at most once a day, and never guesses a
report it could not read. No network: Claude and the CRO reports are replaced by stand-ins."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from flowmerce.modules.cro import ai_advice, service
from flowmerce.modules.seo.db import get, run
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_budget
from flowmerce.modules.seo.util import HttpError

PLAN = {
    "summary": "Sales are steady; mobile converts at half the desktop rate.",
    "actions": [
        {
            "title": "Fix the mobile checkout",
            "why": "Mobile converts far worse.",
            "evidence": "Mobile 0.9% vs desktop 2.1%",
            "steps": ["Open the checkout on a phone", "Remove the extra field"],
            "impact": "High",
            "effort": "Low",
            "area": "checkout",
            "metric": "conversion rate",
        },
        {
            "title": "",
            "why": "",
            "evidence": "",
            "steps": [],
            "impact": "Low",
            "effort": "Low",
            "area": "trust",
            "metric": "",
        },
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
        service, "recommendation_list", lambda b: {"recommendations": [], "skipped": []}
    )

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
    assert st["status"] == "ready" and st["fresh"]
    assert [a["title"] for a in st["advice"]["actions"]] == [
        "Fix the mobile checkout"
    ]  # empty actions are dropped
    assert "Mobile" in st["advice"]["actions"][0]["evidence"]
    assert (
        '"orders"' in env["prompt"] and "x@y.z" not in env["prompt"]
    )  # figures only, no customer details
    assert (
        "change log (RuntimeError)" in st["not_available"]
    )  # an unreadable report is named, not guessed
    row = get("SELECT kind, brand_id, cost_usd FROM claude_usage")
    assert row["kind"] == "cro_advice" and row["brand_id"] == "ridhi" and row["cost_usd"] > 0


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
