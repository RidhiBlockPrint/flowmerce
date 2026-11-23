"""Claude's CRO action plan: Claude reads one store's own figures and recommends what the team
should do next to improve sales and conversion. Owner request 2026-11-20; made a data-driven deep
dive on 2026-11-23 (owner: the first plans were too generic to act on).

It reuses SEO & Blog's Claude connection (the same ANTHROPIC_API_KEY and model) and the same daily
Claude limit (`seo/services/ai_budget.py`): a request that does not fit in what is left of today's
limit is refused before anything is sent, and every call is recorded with its cost under the kind
"cro_advice".

What Claude sees: every report the CRO pages show, for the last 30 complete days against the 30
before (KPIs, the funnel per device, device and channel splits, landing pages, products with GA4
views, refunds, price bands and products bought together, payments, order values and the
free-shipping amount, discount codes, new vs returning customers, countries, page speed and site
search, what moved orders, the best and worst hours), the rule-based checks with the team's status,
the change log, and the team's own notes about the store (`notes` / `set_notes`). No customer
names, emails or addresses are sent: the CRO reports hold none.

Each action names its exact target, the root cause, the figures behind it, an estimated money impact
with its arithmetic, the steps, how to measure the result and how sure Claude is. The prompt forbids
generic advice that no figure supports and advice that assumes setup Claude cannot see.

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
from . import experiments, service
from .config import store_for

log = logging.getLogger(__name__)

KIND = "cro_advice"
MAX_ACTIONS = 8
NOTES_MAX = 3000  # characters of the team's notes about a store
FACT_DAYS = 30  # Claude reads the last 30 complete days against the 30 before
PLAN_VERSION = 2  # 2: the deep-dive plan (diagnosis, target, money impact, measure, confidence)
_running: set[str] = set()
_lock = threading.Lock()

AREAS = (
    "traffic",
    "landing_page",
    "product_page",
    "pricing",
    "checkout",
    "payments",
    "merchandising",
    "search",
    "site_speed",
    "retention",
    "trust",
    "operations",
)
TARGET_KINDS = (
    "page",
    "product",
    "collection",
    "device",
    "channel",
    "country",
    "discount_code",
    "checkout_step",
    "payment_method",
    "search_term",
    "store",
)
_LEVEL = ["High", "Medium", "Low"]

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
                    "target",
                    "diagnosis",
                    "evidence",
                    "impact",
                    "impact_usd",
                    "impact_math",
                    "effort",
                    "area",
                    "steps",
                    "measure",
                    "experiment_metric",
                    "page_path",
                    "confidence",
                    "assumptions",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "target": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "name"],
                        "properties": {
                            "kind": {"type": "string", "enum": list(TARGET_KINDS)},
                            "name": {"type": "string"},
                        },
                    },
                    "diagnosis": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "impact": {"type": "string", "enum": _LEVEL},
                    "impact_usd": {"type": "number"},
                    "impact_math": {"type": "string"},
                    "effort": {"type": "string", "enum": ["Low", "Medium", "High"]},
                    "area": {"type": "string", "enum": list(AREAS)},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "measure": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["metric", "baseline", "goal", "check_after_days"],
                        "properties": {
                            "metric": {"type": "string"},
                            "baseline": {"type": "string"},
                            "goal": {"type": "string"},
                            "check_after_days": {"type": "integer"},
                        },
                    },
                    "experiment_metric": {"type": "string", "enum": list(experiments.METRICS)},
                    "page_path": {"type": "string"},
                    "confidence": {"type": "string", "enum": _LEVEL},
                    "assumptions": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM = (
    "You are a senior ecommerce conversion-rate-optimisation (CRO) strategist doing a deep dive "
    "for the small team that runs a Shopify store. You are given the store's own figures as "
    "JSON (the last 30 complete days against the 30 before) and, when the team wrote them, their "
    "notes about the store. Find where this store is losing the most money and say exactly what "
    "to change, so that the team can act on each item tomorrow and measure whether it worked.\n"
    "\n"
    "How to work:\n"
    "1. Find the leaks. Walk the funnel (visit, product view, add to cart, checkout, payment) "
    "and cut it by device, traffic source, landing page, product, country and hour. A leak is a "
    "segment with real volume that converts clearly worse than the store, than its own previous "
    "30 days, or than comparable segments (for example a product against its category).\n"
    "2. Find the root cause by combining at least two reports. Example: mobile converts below "
    "desktop AND the mobile drop is at cart-to-checkout AND mobile LCP is poor on product pages "
    "-> the cause is the mobile product and cart experience, not traffic quality. Say what the "
    "figures rule out as well as what they point to.\n"
    "3. Size it. `impact_usd` is the extra net sales over the next 30 days if the fix closes "
    "about half of the gap (be conservative), worked out from the figures given: for example "
    "visits x conversion gap x average order, attempts x payment success gap x average order, "
    "orders just under the free-shipping amount x share likely to add an item x item price. "
    "Show the arithmetic with the real numbers in `impact_math`. Use 0 only when no figure "
    "allows an estimate, and say why in `impact_math`.\n"
    "4. Prescribe the exact change: name the page path, product, collection, discount code, "
    "search term, payment method, channel or device; say what to change on it and where in "
    "Shopify admin or the ad tool.\n"
    "5. Say how to know it worked: the metric, its value now (`baseline`), a realistic `goal` "
    "and after how many days to check. Pick `experiment_metric` (conversion_rate, "
    "added_to_cart_rate, bounce_rate or aov) that Flowmerce's experiment tracker should "
    "follow; set `page_path` to the landing page path (starting with /) when the action is about "
    'one page, otherwise "".\n'
    "\n"
    "Rules:\n"
    "- Every action must rest on figures from the JSON. Each `evidence` line has exact numbers "
    "from the data and what they are compared with. Never invent a figure, "
    "benchmark, product, page or tool.\n"
    "- No generic best practice. Do not suggest things like 'add reviews', 'improve photos', "
    "'send more emails', 'post more on social', 'add trust badges' or 'speed up the site' unless "
    "the data points to a specific page, product or segment and shows why there. Each action "
    "must be one the team could not have written without this store's data.\n"
    "- You cannot see stock levels, apps, theme settings, email flows, ad accounts or prices "
    "outside the data. Do not state what they are. If the team's notes say something is already "
    "in place, do not recommend it again. Anything you must assume goes in `assumptions` as a "
    "short thing to check first.\n"
    "- The rule-based checks are a starting point, not the answer: go deeper than them (root "
    "cause, combined segments, money). Skip findings the team marked done or ignored.\n"
    "- `landing_pages.all_judged_pages` lists every landing page with enough visits. Read all "
    "of them, not only the busiest: a mid-sized page with a large gap can be worth more than a "
    "big page with a small one. When several pages share one cause (for example seasonal "
    "collections that bounce for the same reason), make them one action and name each page.\n"
    "- If a report is listed as not available, do not guess what it would show.\n"
    "- `confidence`: High when the segment has plenty of volume and two or more reports agree; "
    "Low when volumes are thin or the cause is a guess. With very few orders or sessions, say "
    "so in `summary` and give fewer actions.\n"
    "- 5-8 actions, largest `impact_usd` first; each action targets a different leak.\n"
    "- Keep it tidy: the depth is in the figures, not in long text. The page shows each action "
    "as a card, so stay within these lengths:\n"
    "  `title`: the instruction, at most 10 words, naming the target.\n"
    "  `target.name`: the page path, product or segment only, at most 8 words.\n"
    "  `diagnosis`: at most 2 sentences and 45 words: what is wrong, where, and the most likely "
    "cause (and what the figures rule out, if it fits).\n"
    "  `evidence`: 3-5 lines, each at most 20 words, one comparison per line, for example "
    '"Mobile cart to checkout 48.5% vs desktop 64.9%".\n'
    "  `steps`: 3-5 steps, each one sentence of at most 30 words, starting with a verb and "
    "naming where to do it.\n"
    "  `impact_math`: one line of arithmetic, at most 35 words.\n"
    "  `measure.metric`: at most 8 words; `baseline` and `goal`: just the value, like "
    '"48.5%" or "$113.50".\n'
    "  `assumptions`: one sentence, at most 25 words, or empty.\n"
    "  `summary`: 2-3 sentences, at most 70 words: how the store is doing, the biggest leak "
    "and the money at stake.\n"
    "- Money is in the store's currency. Write in plain British English for a team that are not "
    "analysts, but keep every number exact."
)


def _key(brand: str) -> str:
    return f"cro_advice:{brand}"


def _notes_key(brand: str) -> str:
    return f"cro_notes:{brand}"


def _read(key: str) -> dict[str, Any]:
    row = get("SELECT value_json FROM app_settings WHERE key = ?", key)
    try:
        saved = json.loads(row["value_json"]) if row else {}
    except ValueError:
        saved = {}
    return saved if isinstance(saved, dict) else {}


def _write(key: str, value: dict[str, Any]) -> None:
    run(
        """INSERT INTO app_settings (key, value_json, updated_at, updated_by)
           VALUES (?, ?, ?, NULL)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
           updated_at=excluded.updated_at""",
        key,
        json.dumps(value, ensure_ascii=False),
        now(),
    )


def _load(brand: str) -> dict[str, Any]:
    return _read(_key(brand))


def _save(brand: str, value: dict[str, Any]) -> None:
    _write(_key(brand), value)


# ------------------------------------------------------------------------------------------ notes
def notes(brand: str) -> dict[str, Any]:
    """The team's notes about a store for Claude (what it sells, apps and setup already in place,
    what has been tried), with who saved them and when. Empty text when none were written."""
    saved = _read(_notes_key(brand))
    return {
        "brand": brand,
        "text": str(saved.get("text") or ""),
        "updated_at": saved.get("updated_at"),
        "updated_by": saved.get("updated_by"),
        "max_length": NOTES_MAX,
    }


def set_notes(brand: str, text: Any, by: str) -> dict[str, Any]:
    """Save (or clear, with an empty text) the team's notes about a store."""
    clean = str(text or "").strip()
    if len(clean) > NOTES_MAX:
        raise HttpError(400, f"Keep the notes to {NOTES_MAX:,} characters or fewer.", "bad_request")
    _write(_notes_key(brand), {"text": clean, "updated_at": now(), "updated_by": by[:200]})
    return notes(brand)


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


def _num(v: Any) -> Any:
    """Floats to 2 decimals so the figures stay short; everything else as it is."""
    return round(v, 2) if isinstance(v, float) else v


def _pick(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """The named fields of a report row that have a value (empty ones are left out)."""
    if not isinstance(row, dict):
        return {}
    out: dict[str, Any] = {}
    for k in keys:
        v = row.get(k)
        if v is None or v == "" or v == []:
            continue
        out[k] = _pick(v, tuple(v)) if isinstance(v, dict) else _num(v)
    return out


def _rows(rows: Any, keys: tuple[str, ...], n: int) -> list[dict[str, Any]]:
    """The first `n` rows of a report list, each cut to `keys`."""
    return [_pick(r, keys) for r in (rows or [])[:n] if isinstance(r, dict)]


def _block(b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not b:
        return None
    return {k: b.get(k) for k in ("value", "baseline_value", "change_pct", "too_early") if k in b}


SEGMENT = (
    "label",
    "sessions",
    "sessions_change_pct",
    "added_to_cart_rate",
    "conversion_rate",
    "conversion_rate_change_pts",
    "orders",
)
PAGE = (
    "path",
    "page_type",
    "sessions",
    "bounce_rate",
    "bounce_change_pts",
    "added_to_cart_rate",
    "conversion_rate",
    "conversion_change_pts",
    "orders",
    "revenue",
    "revenue_per_session",
    "top_source",
    "top_source_share",
    "too_few_sessions",
)
PRODUCT = (
    "name",
    "category",
    "price",
    "orders",
    "items",
    "net_sales",
    "discounts",
    "refund_rate",
    "views",
    "add_to_cart_rate",
    "conversion_rate",
    "group",
)
PAY = ("label", "share_of_payments", "attempts", "failed_attempts", "success_rate")
CODE_SIDE = ("orders", "share_of_orders", "aov", "discount_given", "discount_pct", "net_sales")
PLACE = (
    "label",
    "sessions",
    "share_pct",
    "cart_rate",
    "conversion_rate",
    "conversion_change_pts",
    "orders",
    "too_few_sessions",
)
VITAL = ("p75", "rating", "good_share", "poor_share")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _funnel(f: dict[str, Any] | None) -> dict[str, Any] | None:
    """A funnel per device as {device: {sessions, step: count}} (all devices under 'all')."""
    if not f:
        return None

    def one(x: dict[str, Any] | None) -> dict[str, Any]:
        x = x or {}
        steps = {
            s.get("key"): s.get("count") for s in x.get("steps") or [] if s.get("count") is not None
        }
        return {"sessions": x.get("sessions"), **steps}

    out = {"all": one(f.get("all"))}
    for d in (f.get("devices") or [])[:4]:
        if d.get("sessions"):
            out[str(d.get("label"))] = one(d)
    return out


LANDING_PAGES_MAX = 200  # every landing page Shopify lists (its report stops at 200)


def _landing(lp: dict[str, Any]) -> dict[str, Any]:
    """Every landing page with enough visits to judge (owner request 2026-11-23: all landing
    pages, not only the busiest 25), busiest first, and how many more had too few visits."""
    pages = lp.get("pages") or []
    by_visits = sorted(pages, key=lambda p: -int(p.get("sessions") or 0))
    judged = [p for p in by_visits if not p.get("too_few_sessions")]
    few = [p for p in by_visits if p.get("too_few_sessions")]
    keys = tuple(k for k in PAGE if k != "too_few_sessions")
    return {
        "note": f"Every landing page with at least {lp.get('min_sessions')} visits, busiest first "
        f"({len(judged)} pages). {len(few)} more pages had fewer visits "
        f"({sum(int(p.get('sessions') or 0) for p in few):,} visits together) and are too few to "
        "judge one by one.",
        "all_judged_pages": _rows(judged, keys, LANDING_PAGES_MAX),
        "page_types": _rows(
            lp.get("page_types"),
            (
                "label",
                "sessions",
                "share_of_sessions",
                "bounce_rate",
                "added_to_cart_rate",
                "conversion_rate",
                "conversion_change_pts",
            ),
            10,
        ),
        "by_source": _rows(
            lp.get("by_source"),
            ("label", "sessions", "bounce_rate", "conversion_rate", "conversion_change_pts"),
            10,
        ),
    }


def _products(pi: dict[str, Any]) -> dict[str, Any]:
    rows = [p for p in pi.get("products") or [] if isinstance(p, dict)]
    viewed = [p for p in rows if p.get("views")]
    out: dict[str, Any] = {
        "views_note": (pi.get("views") or {}).get("message"),
        "top_by_net_sales": _rows(
            sorted(rows, key=lambda p: -float(p.get("net_sales") or 0)), PRODUCT, 20
        ),
        "most_viewed": _rows(sorted(viewed, key=lambda p: -int(p.get("views") or 0)), PRODUCT, 15),
        "price_bands": _rows(
            pi.get("price_bands"),
            ("band", "products", "orders", "share_of_sales", "views", "conversion_rate"),
            10,
        ),
    }
    groups = pi.get("groups")
    if groups:
        out["groups"] = _rows(
            groups.get("groups"), ("group", "products", "views", "net_sales", "top"), 4
        )
        out["leaky_fix_first"] = _rows(
            groups.get("fix_first"),
            (
                "name",
                "category",
                "views",
                "add_to_cart_rate",
                "conversion_rate",
                "category_rate",
                "price",
                "left_on_table",
            ),
            8,
        )
    refunds = pi.get("refunds")
    if refunds:
        out["refunds"] = {
            **_pick(refunds, ("store_refund_rate", "total_refunded", "products_with_refunds")),
            "highest_rate": _rows(
                refunds.get("by_rate"),
                ("name", "category", "gross_sales", "refunded", "refund_rate"),
                8,
            ),
        }
    bt = pi.get("bought_together") or {}
    out["bought_together"] = {
        **_pick(bt, ("orders", "multi_product_orders", "multi_share")),
        "pairs": _rows(bt.get("rows"), ("a", "b", "orders_together", "pct_of_a", "lift"), 10),
    }
    return out


def _checkout(ce: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pay = ce.get("payments")
    if pay:
        out["payments"] = {
            **_pick(
                pay,
                (
                    "attempts",
                    "successful",
                    "failed_attempts",
                    "success_rate",
                    "previous_success_rate",
                    "previous_failed_attempts",
                ),
            ),
            "methods": _rows(pay.get("methods"), PAY, 6),
            "wallets": _rows(pay.get("wallets"), PAY, 6),
        }
    values = (
        "orders",
        "average",
        "median",
        "threshold",
        "near_threshold_from",
        "near_threshold_orders",
        "near_threshold_share",
        "at_or_above_threshold_share",
    )
    ov = ce.get("order_values") or {}
    out["order_values"] = {
        **_pick(ov, values),
        "bands": _rows(ov.get("bars"), ("label", "orders", "share"), 12),
        "items_per_order": _pick(ov.get("items"), ("average", "single_item_share")),
        "free_shipping_source": ce.get("free_shipping_source")
        or "not set: the team has not entered the free-shipping amount",
    }
    prev = ce.get("previous_order_values")
    if prev:
        out["previous_order_values"] = {
            **_pick(prev, values),
            "items_per_order": _pick(prev.get("items"), ("average", "single_item_share")),
        }
    return out


def _codes(dc: dict[str, Any]) -> dict[str, Any]:
    prev = dc.get("previous") or {}
    return {
        **_pick(dc, ("total_orders", "code_count")),
        "with_code": _pick(dc.get("with_code"), CODE_SIDE),
        "without_code": _pick(dc.get("without_code"), CODE_SIDE),
        "previous_with_code": _pick(prev.get("with_code"), CODE_SIDE),
        "previous_without_code": _pick(prev.get("without_code"), CODE_SIDE),
        "top_codes": _rows(
            dc.get("codes"),
            ("code", "orders", "share_of_orders", "aov", "discount_given", "discount_pct"),
            10,
        ),
    }


def _site(sh: dict[str, Any]) -> dict[str, Any]:
    def vitals(row: dict[str, Any]) -> dict[str, Any]:
        return {k: _pick(row.get(k), VITAL) for k in ("lcp", "inp", "cls") if row.get(k)}

    devices = {
        name: {"page_loads": d.get("page_loads"), **vitals(d)}
        for name, d in (sh.get("devices") or {}).items()
        if isinstance(d, dict)
    }
    search = sh.get("search") or {}
    return {
        "speed_note": "LCP and INP in milliseconds, CLS unitless; p75 = what 3 in 4 visits get. "
        + str(sh.get("late_note") or ""),
        "by_device": devices,
        "by_page_type": [
            {"label": r.get("label"), "page_loads": r.get("page_loads"), **vitals(r)}
            for r in (sh.get("page_types") or [])[:8]
        ],
        "busiest_mobile_pages": [
            {"path": r.get("path"), "page_loads": r.get("page_loads"), **vitals(r)}
            for r in (sh.get("pages") or [])[:10]
        ],
        "site_search": {
            **_pick(
                search,
                (
                    "share_of_sessions",
                    "sessions_with_searches",
                    "searcher_conversion_rate",
                    "non_searcher_conversion_rate",
                    "search_click_rate",
                    "search_added_to_cart_rate",
                    "searches",
                    "zero_result_searches",
                    "zero_result_share",
                ),
            ),
            "top_terms": _rows(search.get("top_terms"), ("term", "searches", "click_rate"), 10),
            "no_result_terms": _rows(search.get("zero_result_terms"), ("term", "searches"), 15),
        }
        if search
        else None,
    }


def _hours(hm: dict[str, Any]) -> dict[str, Any] | None:
    cells = [c for c in hm.get("cells") or [] if c.get("cvr") is not None]
    if not cells:
        return None

    def name(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "when": f"{DAY_NAMES[int(c['weekday']) % 7]} {int(c['hour']):02d}:00",
            "sessions": c.get("sessions"),
            "conversion_rate": _num(c.get("cvr")),
        }

    busy = [c for c in cells if (c.get("sessions") or 0) >= 50] or cells
    ranked = sorted(busy, key=lambda c: -float(c["cvr"]))
    return {
        "days": hm.get("days"),
        "average_conversion_rate": _num(hm.get("average_cvr")),
        "best": [name(c) for c in ranked[:6]],
        "worst_busy": [name(c) for c in ranked[-6:]],
    }


def gather_facts(brand: str) -> dict[str, Any]:
    """The store's figures Claude reads: every CRO report for the last 30 complete days against the
    30 before, compact, numbers only, no customer details."""
    skipped: list[str] = []
    rq = service.RangeQuery(last=FACT_DAYS, compare="previous", last_includes_today=False)
    facts: dict[str, Any] = {
        "store": brand,
        "period": f"the last {FACT_DAYS} complete days, against the {FACT_DAYS} days before",
        "units": "money in the store's currency; *_rate, *_share and *_pct are percentages "
        "(2.5 means 2.5%); *_pts are percentage points",
    }
    ov = _try("orders and revenue", lambda: service.overview(brand, rq), skipped)
    if ov:
        m = ov.get("metrics", {})
        facts["kpis"] = {
            k: _block(m.get(k))
            for k in (
                "orders",
                "revenue",
                "aov",
                "conversion_rate",
                "sessions",
                "revenue_per_session",
            )
            if m.get(k)
        }
    conv = _try("conversion funnel", lambda: service.conversion_trend(brand, rq), skipped)
    if conv:
        facts["funnel"] = {
            "current": conv.get("total"),
            "comparison": conv.get("baseline_total"),
            "by_device_now": _funnel(conv.get("funnel")),
            "by_device_comparison": _funnel(conv.get("baseline_funnel")),
        }
    for dim in ("device", "channel"):
        seg = _try(f"{dim} split", lambda d=dim: service.segments(brand, d, rq), skipped)  # type: ignore[misc]
        if seg:
            facts[f"by_{dim}"] = _rows(seg.get("rows"), SEGMENT, 10)
    moved = _try("what moved orders", lambda: service.traffic_changes(brand, rq), skipped)
    if moved:
        facts["what_moved_orders"] = _rows(
            moved.get("movers"), ("text", "effect", "kind", "dimension"), 8
        )
        facts["revenue_per_visit_by_channel"] = _rows(
            moved.get("channel"),
            ("key", "sessions", "revenue_per_session", "revenue_per_session_change_pct"),
            10,
        )
    lp = _try("landing pages", lambda: service.landing_pages(brand, rq), skipped)
    if lp:
        facts["landing_pages"] = _landing(lp)
    pi = _try("products", lambda: service.product_insights(brand, rq), skipped)
    if pi:
        facts["products"] = _products(pi)
    ce = _try("payments and order values", lambda: service.checkout_extras(brand, rq), skipped)
    if ce:
        facts["checkout"] = _checkout(ce)
        if ce.get("payments_error"):
            skipped.append(f"payments ({ce['payments_error'].get('state')})")
    dc = _try("discount codes", lambda: service.discount_codes(brand, rq), skipped)
    if dc:
        facts["discount_codes"] = _codes(dc)
    cu = _try("new vs returning customers", lambda: service.customers(brand, rq), skipped)
    if cu and cu.get("new_vs_returning"):
        nr = cu["new_vs_returning"]
        side = ("orders", "share_of_orders", "aov", "net_sales")
        prev = nr.get("previous") or {}
        facts["customers"] = {
            "new": _pick(nr.get("new"), side),
            "returning": _pick(nr.get("returning"), side),
            "returning_customer_rate": nr.get("returning_customer_rate"),
            "previous_returning_customer_rate": prev.get("returning_customer_rate"),
        }
    geo = _try("countries", lambda: service.geo(brand, rq), skipped)
    if geo:
        facts["places"] = {
            "countries": _rows(geo.get("countries"), PLACE, 8),
            "us_states": _rows(geo.get("us_states"), PLACE, 8),
        }
    sh = _try("page speed and site search", lambda: service.site_health(brand, rq), skipped)
    if sh:
        facts["site_health"] = _site(sh)
    hm = _try("best hours", lambda: service.buy_heatmap(brand, 28), skipped)
    if hm and hm.get("source") == "shopify_sessions":
        facts["hours"] = _hours(hm)
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
            _pick(r, ("title", "evidence_list", "impact", "status", "segment"))
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


def _prompt(facts: dict[str, Any], team_notes: str = "") -> str:
    notes_part = (
        "The team's notes about the store (their own words: context and setup already in place, "
        "not figures):\n<team_notes>\n" + team_notes + "\n</team_notes>\n\n"
        if team_notes
        else "The team has not written notes about the store, so you know nothing about its "
        "apps, theme, stock or email setup beyond the figures.\n\n"
    )
    return (
        f"Today is {datetime.now(UTC).date().isoformat()}.\n\n"
        + notes_part
        + "The store's figures (JSON):\n"
        + json.dumps(facts, ensure_ascii=False, default=str, separators=(",", ":"))
        + "\n\nDo the deep dive and give the team's next actions, largest money impact first."
    )


def _text(v: Any, n: int) -> str:
    return str(v or "").strip()[:n]


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for a in (data.get("actions") or [])[:MAX_ACTIONS]:
        if not isinstance(a, dict) or not _text(a.get("title"), 200):
            continue
        raw_target, raw_measure = a.get("target"), a.get("measure")
        target: dict[str, Any] = raw_target if isinstance(raw_target, dict) else {}
        measure: dict[str, Any] = raw_measure if isinstance(raw_measure, dict) else {}
        try:
            usd = max(0.0, round(float(a.get("impact_usd") or 0), 0))
        except TypeError, ValueError:
            usd = 0.0
        try:
            days = max(1, min(90, int(measure.get("check_after_days") or 14)))
        except TypeError, ValueError:
            days = 14
        evidence = a.get("evidence")
        evidence = evidence if isinstance(evidence, list) else [evidence] if evidence else []
        page = _text(a.get("page_path"), 500)
        actions.append(
            {
                "title": _text(a.get("title"), 200),
                "target": {
                    "kind": target.get("kind") if target.get("kind") in TARGET_KINDS else "store",
                    "name": _text(target.get("name"), 300),
                },
                "diagnosis": _text(a.get("diagnosis"), 1500),
                "evidence": [_text(x, 400) for x in evidence if _text(x, 400)][:8],
                "impact": a.get("impact") if a.get("impact") in _LEVEL else "Medium",
                "impact_usd": usd,
                "impact_math": _text(a.get("impact_math"), 600),
                "effort": a.get("effort")
                if a.get("effort") in ("Low", "Medium", "High")
                else "Medium",
                "area": a.get("area") if a.get("area") in AREAS else "operations",
                "steps": [_text(x, 600) for x in (a.get("steps") or []) if _text(x, 600)][:8],
                "measure": {
                    "metric": _text(measure.get("metric"), 120),
                    "baseline": _text(measure.get("baseline"), 120),
                    "goal": _text(measure.get("goal"), 120),
                    "check_after_days": days,
                },
                "experiment_metric": a.get("experiment_metric")
                if a.get("experiment_metric") in experiments.METRICS
                else "conversion_rate",
                "page_path": page if page.startswith("/") else "",
                "confidence": a.get("confidence") if a.get("confidence") in _LEVEL else "Medium",
                "assumptions": _text(a.get("assumptions"), 600),
            }
        )
    actions.sort(key=lambda x: -float(x["impact_usd"]))
    return {"summary": _text(data.get("summary"), 2000), "actions": actions}


# ------------------------------------------------------------------------------------------ the run
def _work(brand: str, by: str) -> None:
    try:
        facts = gather_facts(brand)
        # High effort: the deep dive combines many reports; the room covers Claude's thinking and
        # up to 8 detailed actions.
        data, model = claude._structured(
            SYSTEM,
            _prompt(facts, notes(brand)["text"]),
            ADVICE_SCHEMA,
            "high",
            max_tokens=32000,
        )
        cost = ai_budget.record(claude.take_usage(), brand, KIND)
        _save(
            brand,
            {
                "version": PLAN_VERSION,
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
        "fresh": _fresh(brand, saved),
        "version": saved.get("version", 1),
        "generated_at": saved.get("generated_at"),
        "by": saved.get("by"),
        "model": saved.get("model"),
        "cost_usd": saved.get("cost_usd"),
        "advice": saved.get("advice"),
        "not_available": saved.get("not_available", []),
        "error": saved.get("error")
        if saved.get("failed_at", "") >= saved.get("generated_at", "")
        else None,
        "estimate_usd": ai_budget.ESTIMATE_USD.get(KIND),
        "budget": ai_budget.status(),
    }


def _fresh(brand: str, saved: dict[str, Any]) -> bool:
    """A plan of the current kind made on the store's today. An older, shorter plan (version 1)
    counts as stale, so opening the page once replaces it with the deep dive."""
    return saved.get("day") == _store_today(brand) and saved.get("version", 1) >= PLAN_VERSION


def start(brand: str, by: str, auto: bool = False) -> dict[str, Any]:
    """Ask Claude for a new plan in the background. `auto` (the page opening) only asks when there
    is no current plan from today and no failure today, so opening the page never spends more than
    once a day."""
    store_for(brand)  # raises for an unknown brand
    if not claude.configured():
        raise HttpError(
            412,
            "ANTHROPIC_API_KEY is not set on the server, so Claude cannot analyse the store.",
            "pending_setup",
        )
    saved = _load(brand)
    if auto and (_fresh(brand, saved) or (saved.get("failed_at") or "")[:10] == ai_budget.today()):
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
