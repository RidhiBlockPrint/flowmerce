"""Claude's CRO action plan: Claude reads one store's own figures and recommends what the team
should do next to improve sales and conversion. Owner request 2026-11-20.

It reuses SEO & Blog's Claude connection (the same ANTHROPIC_API_KEY and model) and the same daily
Claude limit (`seo/services/ai_budget.py`): a request that does not fit in what is left of today's
limit is refused before anything is sent, and every call is recorded with its cost under the kind
"cro_advice".

What Claude sees: the store's figures from this module only (the last 30 days against the 30
before, the funnel, device and channel split, products, order health, the rule-based checks and the
change log). No customer names, emails or addresses are sent: the CRO reports hold none.

A plan is kept per store in the app's settings table (the local database), with the day it was made
in the store's time zone. The page asks for a new plan at most once a day by itself (`auto=True`);
"Refresh" asks for one at any time. Claude runs in a background thread; the page reads the state
until it is "ready" or "failed".
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..seo.db import get, now, run
from ..seo.integrations import claude
from ..seo.services import ai_budget
from ..seo.util import HttpError
from . import service
from .config import store_for

log = logging.getLogger(__name__)

KIND = "cro_advice"
MAX_ACTIONS = 8
_running: set[str] = set()
_lock = threading.Lock()

ADVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "actions"],
    "properties": {
        "summary": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "why",
                    "evidence",
                    "steps",
                    "impact",
                    "effort",
                    "area",
                    "metric",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                    "evidence": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "impact": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "effort": {"type": "string", "enum": ["Low", "Medium", "High"]},
                    "area": {
                        "type": "string",
                        "enum": [
                            "traffic",
                            "product_page",
                            "pricing",
                            "checkout",
                            "merchandising",
                            "retention",
                            "trust",
                            "operations",
                        ],
                    },
                    "metric": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM = (
    "You are a senior ecommerce conversion-rate (CRO) analyst advising the small team that "
    "runs a Shopify store. You are given the store's own figures as JSON. Recommend the "
    "actions that will most improve sales and conversion in the next few weeks. Rules:\n"
    "- Base every action on the figures given. Quote the exact numbers you rely on in "
    "`evidence`. Never invent a figure, a benchmark the data does not contain, a product, or "
    "a tool the team has not mentioned.\n"
    "- Prefer specific, doable actions (a named product, a named channel, a named checkout "
    "step) over generic advice.\n"
    "- `steps`: 2-5 short, concrete steps a non-technical team member can follow in Shopify "
    "or their ads tools.\n"
    "- `impact`: expected effect on sales or conversion; `effort`: work needed. Order actions"
    " by impact, then effort.\n"
    "- If a source is listed as not available, do not guess what it would show; you may "
    "recommend fixing the access.\n"
    "- If the figures are too thin to support advice (very few orders or sessions), say so in"
    " `summary` and give fewer actions.\n"
    "- At most 8 actions. `summary`: 2-3 plain sentences on how the store is doing and the "
    "biggest opportunity.\n"
    "- Write in plain British English for people who are not analysts.\n"
    "- Keep every field short so the page reads at a glance: `title` an instruction of at most "
    "10 words; `why` ONE sentence of at most 25 words; `evidence` 2-4 short figures separated "
    'by "; " (for example "Checkout reached 2,193; completed 1,463"); each step at most 15 '
    "words, starting with a verb; `metric` 2-4 words."
)


def _key(brand: str) -> str:
    return f"cro_advice:{brand}"


def _load(brand: str) -> dict[str, Any]:
    row = get("SELECT value_json FROM app_settings WHERE key = ?", _key(brand))
    try:
        saved = json.loads(row["value_json"]) if row else {}
    except ValueError:
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _save(brand: str, value: dict[str, Any]) -> None:
    run(
        """INSERT INTO app_settings (key, value_json, updated_at, updated_by)
           VALUES (?, ?, ?, NULL)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
           updated_at=excluded.updated_at""",
        _key(brand),
        json.dumps(value, ensure_ascii=False),
        now(),
    )


def _store_today(brand: str) -> str:
    try:
        return str(service.today_for(store_for(brand)).isoformat())
    except Exception:  # noqa: BLE001 — the time zone needs Shopify; fall back to the business day
        return str(ai_budget.today())


# ------------------------------------------------------------------------------------------ facts
def _try(label: str, fn: Callable[[], Any], skipped: list[str]) -> Any:
    """One report for Claude; one that cannot be read is named in `skipped`, never guessed."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — every report is optional; the reason is passed on
        skipped.append(f"{label} ({getattr(e, 'state', None) or type(e).__name__})")
        return None


def _block(b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not b:
        return None
    return {k: b.get(k) for k in ("value", "baseline_value", "change_pct", "too_early") if k in b}


def gather_facts(brand: str) -> dict[str, Any]:
    """The store's figures Claude reads: compact, numbers only, no customer details."""
    skipped: list[str] = []
    rq = service.RangeQuery(last=30, compare="previous", last_includes_today=False)
    facts: dict[str, Any] = {
        "store": brand,
        "period": "the last 30 complete days, against the 30 days before",
    }
    ov = _try("orders and revenue", lambda: service.overview(brand, rq), skipped)
    if ov:
        m = ov.get("metrics", {})
        facts["kpis"] = {
            k: _block(m.get(k)) for k in ("orders", "revenue", "aov", "conversion_rate")
        }
    conv = _try("conversion funnel", lambda: service.conversion_trend(brand, rq), skipped)
    if conv:
        facts["funnel"] = {"current": conv.get("total"), "comparison": conv.get("baseline_total")}
    for dim in ("device", "channel"):
        seg = _try(f"{dim} split", lambda d=dim: service.segments(brand, d, rq), skipped)  # type: ignore[misc]
        if seg:
            facts[f"by_{dim}"] = seg.get("rows", [])[:10]
    prods = _try("products", lambda: service.products(brand, rq), skipped)
    if prods:
        rows = prods.get("products", [])
        keep = ("name", "product_type", "quantity", "orders", "revenue", "performance_status")
        facts["products_top"] = [{k: p.get(k) for k in keep} for p in rows[:15]]
        facts["products_low"] = (
            [{k: p.get(k) for k in keep} for p in rows[-10:]] if len(rows) > 15 else []
        )
        facts["products_sold"] = len(rows)
    health = _try("order health", lambda: service.order_health(brand, rq), skipped)
    if health:
        facts["order_health"] = {
            k: health.get(k) for k in ("total_orders", "paid", "refunded", "cancelled", "pending")
        }
    sales = _try("sales breakdown", lambda: service.sales_breakdown(brand, rq), skipped)
    if sales:
        facts["sales_breakdown"] = [
            {k: r.get(k) for k in ("label", "value", "baseline_value", "change_pct")}
            for r in sales.get("rows", [])
        ]
    rules = _try("rule-based checks", lambda: service.recommendation_list(brand), skipped)
    if rules:
        facts["rule_based_findings"] = [
            {k: r.get(k) for k in ("title", "evidence", "priority")}
            for r in rules.get("recommendations", [])
        ]
        skipped.extend(rules.get("skipped", []))
    log_ = _try("change log", lambda: service.change_log(brand, 60), skipped)
    if log_:
        facts["store_changes_last_60_days"] = [
            {k: e.get(k) for k in ("entry_date", "area", "change")}
            for e in log_.get("entries", [])[:20]
        ]
    facts["not_available"] = skipped
    return facts


def _prompt(facts: dict[str, Any]) -> str:
    return (
        f"Today is {datetime.now(UTC).date().isoformat()}. Here are the store's figures (JSON). "
        "Money is in the store's "
        "currency; rates are percentages.\n\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
        + "\n\nRecommend the team's next actions to improve sales and conversion."
    )


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    actions = []
    for a in (data.get("actions") or [])[:MAX_ACTIONS]:
        if not isinstance(a, dict) or not str(a.get("title") or "").strip():
            continue
        actions.append(
            {
                "title": str(a.get("title"))[:200],
                "why": str(a.get("why") or "")[:1200],
                "evidence": str(a.get("evidence") or "")[:800],
                "steps": [str(x)[:400] for x in (a.get("steps") or [])][:6],
                "impact": a.get("impact")
                if a.get("impact") in ("High", "Medium", "Low")
                else "Medium",
                "effort": a.get("effort")
                if a.get("effort") in ("Low", "Medium", "High")
                else "Medium",
                "area": str(a.get("area") or "operations"),
                "metric": str(a.get("metric") or "")[:120],
            }
        )
    return {"summary": str(data.get("summary") or "")[:1500], "actions": actions}


# ------------------------------------------------------------------------------------------ the run
def _work(brand: str, by: str) -> None:
    try:
        facts = gather_facts(brand)
        data, model = claude._structured(
            SYSTEM, _prompt(facts), ADVICE_SCHEMA, "medium", max_tokens=12000
        )
        cost = ai_budget.record(claude.take_usage(), brand, KIND)
        _save(
            brand,
            {
                "status": "ready",
                "day": _store_today(brand),
                "generated_at": now(),
                "by": by,
                "model": model,
                "cost_usd": cost,
                "advice": _clean(data),
                "not_available": facts.get("not_available", []),
            },
        )
    except claude.ClaudeError as e:
        ai_budget.record(
            claude.take_usage(), brand, KIND
        )  # a call that ran is paid for even if its answer is unusable
        _fail(brand, str(e))
    except HttpError as e:
        _fail(brand, e.message)
    except Exception as e:  # noqa: BLE001 — background thread boundary: the failure is shown on the page
        log.exception("CRO advice for %s failed", brand)
        _fail(brand, f"Unexpected error: {type(e).__name__}")
    finally:
        with _lock:
            _running.discard(brand)


def _fail(brand: str, message: str) -> None:
    prev = _load(brand)
    _save(
        brand,
        {
            **prev,
            "status": "failed" if not prev.get("advice") else "ready",
            "error": message,
            "failed_at": now(),
        },
    )


def state(brand: str) -> dict[str, Any]:
    """The kept plan for a store, whether a new one is being made, and the Claude limit."""
    saved = _load(brand)
    with _lock:
        running = brand in _running
    return {
        "brand": brand,
        "configured": claude.configured(),
        "status": "running" if running else saved.get("status", "none"),
        "day": saved.get("day"),
        "fresh": saved.get("day") == _store_today(brand),
        "generated_at": saved.get("generated_at"),
        "by": saved.get("by"),
        "model": saved.get("model"),
        "advice": saved.get("advice"),
        "not_available": saved.get("not_available", []),
        "error": saved.get("error")
        if saved.get("failed_at", "") >= saved.get("generated_at", "")
        else None,
        "estimate_usd": ai_budget.ESTIMATE_USD.get(KIND),
        "budget": ai_budget.status(),
    }


def start(brand: str, by: str, auto: bool = False) -> dict[str, Any]:
    """Ask Claude for a new plan in the background. `auto` (the page opening) only asks when there
    is no plan from today
    and no failure today, so opening the page never spends more than once a day."""
    store_for(brand)  # raises for an unknown brand
    if not claude.configured():
        raise HttpError(
            412,
            "ANTHROPIC_API_KEY is not set on the server, so Claude cannot analyse the store.",
            "pending_setup",
        )
    saved = _load(brand)
    if auto and (
        saved.get("day") == _store_today(brand)
        or (saved.get("failed_at") or "")[:10] == ai_budget.today()
    ):
        return state(brand)
    with _lock:
        if brand in _running:
            return state(brand)
        ai_budget.check(KIND)  # 429 daily_limit: nothing is sent to Claude
        _running.add(brand)
    threading.Thread(
        target=_work, args=(brand, by), name=f"cro-advice-{brand}", daemon=True
    ).start()
    return state(brand)
