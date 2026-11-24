"""The Ads rules, as pure functions: no database, no network. The same rules drive the sample data
in the preview copy (frontend/src/demo/modules/ads.js), so the screens behave the same on sample
and real numbers.

Units: money in US dollars, rates in percent (3.6 means 3.6%), ROAS and MER as plain ratios.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The rule set from the Daily sheet's Rules tab (24 Oct 2026). Every value is editable per brand on
# the Rules tab; ads.rules stores only what the team changed. fx_rate is not here: rates live in
# ads.fx_rates with a start day.
DEFAULT_RULES: dict[str, float] = {
    "goal_daily_sales": 20000,
    "bulk_order_min": 1500,
    "target_roas": 2.2,
    "target_mer": 2.5,
    "mer_floor": 2.2,
    "gate_green_3d": 2.2,
    "gate_green_7d": 2.0,
    "gate_red": 1.8,
    "budget_up_7d": 2.2,
    "budget_up_3d": 1.8,
    "budget_down_7d": 1.6,
    "budget_down_3d": 1.4,
    "budget_step_pct": 20,
    "test_spend": 110,
    "proven_spend": 220,
    "stop_roas": 1.5,
    "scale_roas": 2.2,
    "scale_3d_roas": 1.8,
    "scale_min_purchases": 5,
    "graduate_min_purchases": 3,
    "cbo_min_ads": 4,
    "cbo_max_ads": 8,
}
# Cotton Print Club's own starting goal; everything else starts as Ridhi's.
BRAND_DEFAULTS: dict[str, dict[str, float]] = {"cpc": {"goal_daily_sales": 8000}}
RULE_LIMITS: dict[str, tuple[float, float]] = {
    "fx_rate": (1, 500),
    "goal_daily_sales": (100, 1e7),
    "bulk_order_min": (50, 1e6),
    "budget_step_pct": (1, 50),
    "cbo_min_ads": (1, 50),
    "cbo_max_ads": (1, 50),
}
DEFAULT_LIMITS = (0.1, 100000.0)

# Where an ad loses people first. Placeholders until the owner sets them (docs/plans/ads-module.md).
WEAK_HOOK_PCT = 20.0
WEAK_CTR_PCT = 2.5
WEAK_ATC_PCT = 9.0
WEAK_PURCHASE_PCT = 8.0
MIN_IMPRESSIONS = 300

# Product line from a campaign name. First match wins, so "round" comes before the general
# "tablecloth".
PRODUCT_LINES: list[tuple[str, str, tuple[str, ...]]] = [
    ("quilt", "Quilt", ("quilt",)),
    ("skirt", "Tree skirt", ("tree skirt", "skirt")),
    ("round", "Round tablecloth", ("round", "oval")),
    ("stripe", "Stripe tablecloth", ("stripe", "scallop")),
    ("runner", "Table runner", ("runner",)),
    ("pillow", "Pillow cover", ("pillow", "cushion")),
    ("rectangle", "Rectangle tablecloth", ("rectangle", "tablecloth", "table cloth", " tc ")),
    ("all", "All products", ()),
]
LINE_LABEL = {k: label for k, label, _ in PRODUCT_LINES}


def rules_for(brand: str, saved: dict[str, Any]) -> dict[str, float]:
    """The brand's rules: the defaults, the brand's own defaults, then what the team changed."""
    out = {**DEFAULT_RULES, **BRAND_DEFAULTS.get(brand, {})}
    for k, v in saved.items():
        if k in out and isinstance(v, int | float):
            out[k] = float(v)
    return out


def check_rule_changes(changes: dict[str, Any], current: dict[str, float]) -> dict[str, float]:
    """Validated changes, or ValueError with a message for the page. `fx_rate` is allowed besides
    the rules."""
    out: dict[str, float] = {}
    for k, v in changes.items():
        if k not in DEFAULT_RULES and k != "fx_rate":
            raise ValueError(f"Unknown setting: {k}.")
        lo, hi = RULE_LIMITS.get(k, DEFAULT_LIMITS)
        if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= float(v) <= hi:
            raise ValueError(f"{k} must be a number between {lo:g} and {hi:g}.")
        out[k] = float(v)
    merged = {**current, **out}
    if merged["cbo_min_ads"] > merged["cbo_max_ads"]:
        raise ValueError("The smallest number of ads in a CBO cannot be above the largest.")
    return out


# ------------------------------------------------------------------ small helpers
def div(a: float | None, b: float | None) -> float | None:
    """a / b, or None when b is missing or 0."""
    return a / b if a is not None and b else None


def ratio(a: float | None, b: float | None) -> float | None:
    """a / b rounded to 2 decimals, or None."""
    v = div(a, b)
    return round(v, 2) if v is not None else None


def pct(a: float | None, b: float | None) -> float | None:
    """a as a percent of b, 1 decimal, or None."""
    v = div(a, b)
    return round(v * 100, 1) if v is not None else None


def block(value: float | None, base: float | None) -> dict[str, float | None]:
    """A figure with its comparison: {value, baseline_value, change_pct}."""
    change = None if value is None or not base else round((value / base - 1) * 100, 1)
    return {
        "value": None if value is None else round(value, 2),
        "baseline_value": None if base is None else round(base, 2),
        "change_pct": change,
    }


def product_line(name: str) -> str:
    """The product line a campaign sells, from its name ('all' when none matches)."""
    n = f" {name.lower()} "
    for key, _label, words in PRODUCT_LINES:
        if any(w in n for w in words):
            return key
    return "all"


def campaign_type(name: str, objective: str | None, daily_budget: float | None) -> str:
    """cbo (one budget for the campaign), abo (a budget per ad set), catalog or retargeting."""
    n = name.lower()
    if "catalog" in n or (objective or "").upper() == "PRODUCT_CATALOG_SALES":
        return "catalog"
    if "retarget" in n or "remarket" in n:
        return "retargeting"
    if daily_budget is not None or re.search(r"\bcbo\b", n):
        return "cbo"
    return "abo"


def ad_code(name: str) -> str:
    """The short code at the start of an ad's name: 'CR291 | Real Product ...' -> 'CR291'."""
    head = name.split("|", 1)[0].strip()
    return head.split()[0] if head else name[:12]


# ------------------------------------------------------------------ verdicts
@dataclass(frozen=True)
class Totals:
    """An ad's figures for one window (money in US dollars)."""

    spend: float = 0.0
    purchases: float = 0.0
    value: float = 0.0
    impressions: int = 0
    vimp: int = 0
    clicks: int = 0
    lpv: int = 0
    atc: int = 0
    v3: int = 0

    @property
    def roas(self) -> float:
        """Purchase value per dollar spent (0 without spend)."""
        return self.value / self.spend if self.spend else 0.0


def verdict(
    t3: Totals, t7: Totals, life: Totals, is_test: bool, r: dict[str, float]
) -> tuple[str, str]:
    """The rule set's answer for one ad, and the reason in words."""

    def money(v: float) -> str:
        return f"${round(v):,}"

    if life.spend < r["test_spend"]:
        return "testing", f"In test: {money(life.spend)} of {money(r['test_spend'])} spent."
    if life.purchases == 0:
        return (
            "stop",
            f"No purchase after {money(life.spend)} (test limit {money(r['test_spend'])}).",
        )
    if life.spend < r["proven_spend"]:
        n = int(life.purchases)
        return "continue", (
            f"{n} purchase{'' if n == 1 else 's'} at {money(life.spend)}: "
            f"continue to {money(r['proven_spend'])}."
        )
    if t7.spend >= r["test_spend"] and t7.roas < r["stop_roas"]:
        return (
            "stop",
            f"7-day ROAS {t7.roas:.2f} on {money(t7.spend)} (stop below {r['stop_roas']:g}).",
        )
    if life.roas < r["stop_roas"]:
        return (
            "stop",
            f"Lifetime ROAS {life.roas:.2f} on {money(life.spend)} "
            f"(stop below {r['stop_roas']:g}).",
        )
    if (
        t7.roas >= r["scale_roas"]
        and t7.purchases >= r["scale_min_purchases"]
        and t3.roas >= r["scale_3d_roas"]
    ):
        return (
            "scale",
            f"7-day ROAS {t7.roas:.2f} with {int(t7.purchases)} purchases, 3-day {t3.roas:.2f}.",
        )
    if is_test and life.roas >= r["scale_roas"] and life.purchases >= r["graduate_min_purchases"]:
        return "graduate", (
            f"Lifetime ROAS {life.roas:.2f} with {int(life.purchases)} purchases: ready for the "
            "scaling campaign."
        )
    if t7.roas < r["scale_roas"] and t7.spend > 0:
        if t7.roas < r["stop_roas"]:  # below the stop line, but on too little spend to stop on
            return "iterate", (
                f"7-day ROAS {t7.roas:.2f} on only {money(t7.spend)} (stop needs "
                f"{money(r['test_spend'])}); lifetime ROAS {life.roas:.2f}."
            )
        return (
            "iterate",
            f"7-day ROAS {t7.roas:.2f} is between {r['stop_roas']:g} and {r['scale_roas']:g}.",
        )
    return "hold", f"Lifetime ROAS {life.roas:.2f}; nothing to change."


def weakest(is_video: bool, t: Totals) -> dict[str, str]:
    """Where the ad loses people first: hook, click, landing page or checkout ('none', or 'early' if
    too new)."""
    if t.impressions < MIN_IMPRESSIONS:
        return {"key": "early", "label": "Too early"}
    if is_video and t.vimp and t.v3 / t.vimp * 100 < WEAK_HOOK_PCT:
        return {"key": "hook", "label": "Hook"}
    if t.clicks / t.impressions * 100 < WEAK_CTR_PCT:
        return {"key": "click", "label": "Call to action" if is_video else "Image"}
    if t.lpv >= 20 and t.atc / t.lpv * 100 < WEAK_ATC_PCT:
        return {"key": "landing", "label": "Landing page"}
    if t.atc >= 10 and t.purchases / t.atc * 100 < WEAK_PURCHASE_PCT:
        return {"key": "checkout", "label": "Checkout"}
    return {"key": "none", "label": "None"}


def proven(life: Totals, r: dict[str, float]) -> bool:
    """The ABO to CBO gap's rule: spend, ROAS and purchases since the ad started."""
    return (
        life.spend >= r["proven_spend"]
        and life.roas >= r["scale_roas"]
        and life.purchases >= r["graduate_min_purchases"]
    )


# ------------------------------------------------------------------ budgets and the scaling gate
def budget_call(
    budget: float, roas7: float, roas3: float, changed_days_ago: float | None, r: dict[str, float]
) -> dict[str, Any]:
    """What the CBO budget rule says: raise, lower or hold, with the new budget."""
    step = r["budget_step_pct"]
    if changed_days_ago is not None and changed_days_ago < 3:
        return {
            "key": "hold",
            "label": "Hold",
            "why": "The budget changed in the last 72 hours.",
            "new_budget": None,
        }
    if roas7 >= r["budget_up_7d"] and roas3 >= r["budget_up_3d"]:
        return {
            "key": "increase",
            "label": f"Raise {step:g}%",
            "new_budget": round(budget * (1 + step / 100)),
            "why": f"7-day ROAS {roas7:.2f} and 3-day {roas3:.2f} are both above the raise line.",
        }
    if roas7 < r["budget_down_7d"] or roas3 < r["budget_down_3d"]:
        return {
            "key": "decrease",
            "label": f"Lower {step:g}%",
            "new_budget": round(budget * (1 - step / 100)),
            "why": f"7-day ROAS {roas7:.2f}, 3-day {roas3:.2f}: below the lower line.",
        }
    return {
        "key": "hold",
        "label": "Hold",
        "new_budget": None,
        "why": f"7-day ROAS {roas7:.2f} is between {r['budget_down_7d']:g} and "
        f"{r['budget_up_7d']:g}.",
    }


def gate(
    mer3: float | None,
    mer7: float | None,
    avg_spend: float,
    r: dict[str, float],
    complete: bool = True,
) -> dict[str, Any]:
    """Red, amber or green from the 3-day and 7-day MER without bulk orders, and the daily spend it
    suggests. "unknown" (no call) when either MER is missing or the ad spend of those days is not
    all saved yet: a missing figure is not a bad one, so it must never read as "cut back"."""
    if mer3 is None or mer7 is None or not complete:
        return {
            "state": "unknown",
            "mer_3d": None if mer3 is None else round(mer3, 2),
            "mer_7d": None if mer7 is None else round(mer7, 2),
            "avg_daily_spend_7d": round(avg_spend),
            "recommended_daily_spend": round(avg_spend / 10) * 10,
            "advice": "No spend call until the ad spend of the last 7 days is saved.",
        }
    m3, m7 = mer3, mer7
    if m3 >= r["gate_green_3d"] and m7 >= r["gate_green_7d"]:
        state, factor = "green", 1 + r["budget_step_pct"] / 100
        advice = f"Raise total spend by up to {r['budget_step_pct']:g}% over the next 72 hours."
    elif min(m3, m7) < r["gate_red"]:
        state, factor = "red", 1 - r["budget_step_pct"] * 0.75 / 100
        advice = "Cut total spend by 10 to 20% and fix from inside the campaigns."
    else:
        state, factor = "amber", 1.0
        advice = "Hold total spend and move budget to the better campaigns."
    return {
        "state": state,
        "mer_3d": None if mer3 is None else round(mer3, 2),
        "mer_7d": None if mer7 is None else round(mer7, 2),
        "avg_daily_spend_7d": round(avg_spend),
        "recommended_daily_spend": round(avg_spend * factor / 10) * 10,
        "advice": advice,
    }


def day_colour(mer: float | None, r: dict[str, float]) -> str | None:
    """A day's colour on the strip from its MER without bulk orders."""
    if mer is None:
        return None
    return "green" if mer >= r["gate_green_3d"] else "amber" if mer >= r["gate_red"] else "red"
