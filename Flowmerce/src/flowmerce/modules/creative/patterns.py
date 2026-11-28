"""Winning and losing creative patterns: every ad's verdict, and results grouped by each tag.

The arithmetic part (`ad_performance`, `group_by`, `verdict`, `season_for`) is pure: it takes the
ad-day rows `service._rows` already builds plus the tags, products, season calendar and rules, so it
can be unit tested without Supabase. The reading and saving of rules and seasons is at the bottom.

Verdicts use the store's rules (creative.rule):
  * insufficient_data: spend below min_spend or impressions below min_impressions
  * winner: enough data and ROAS at or above target_roas
  * loser:  enough data and ROAS below breakeven_roas
  * average: everything in between
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from . import taxonomy

DIMENSIONS = (
    "hook_type",
    "visual_style",
    "format",
    "print",
    "color",
    "category",
    "season",
    "product",
)
SUM_FIELDS = (
    "spend",
    "impressions",
    "video_impressions",
    "clicks",
    "video_3s",
    "thruplays",
    "purchases",
    "value",
)
UNTAGGED = "untagged"
RULE_KEYS = ("min_spend", "min_impressions", "target_roas", "breakeven_roas")
DEFAULT_RULE = {
    "min_spend": 1000.0,
    "min_impressions": 1000.0,
    "target_roas": 2.0,
    "breakeven_roas": 1.0,
}
DEFAULT_SEASONS = [
    {"season": "winter", "start": "01-01", "end": "02-29"},
    {"season": "spring", "start": "03-01", "end": "05-31"},
    {"season": "summer", "start": "06-01", "end": "08-31"},
    {"season": "fall", "start": "09-01", "end": "11-14"},
    {"season": "holiday", "start": "11-15", "end": "12-31"},
]
MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
PRODUCT_PATH = re.compile(r"/products/([a-z0-9][a-z0-9\-]*)", re.IGNORECASE)


class RuleError(ValueError):
    """A rule or season value that cannot be saved (becomes HTTP 400)."""


# ------------------------------------------------------------------------------- pure helpers
def product_handle(url: str | None) -> str | None:
    """The Shopify product handle in a ``/products/<handle>`` link, or None."""
    match = PRODUCT_PATH.search(url or "")
    return match.group(1).lower() if match else None


def _in_range(mmdd: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= mmdd <= end
    return mmdd >= start or mmdd <= end


def season_for(day: str | None, calendar: list[dict[str, str]]) -> str | None:
    """The season of a YYYY-MM-DD day; the first matching season wins when ranges overlap."""
    if not day:
        return None
    mmdd = str(day)[5:10]
    for entry in calendar:
        if _in_range(mmdd, entry["start"], entry["end"]):
            return entry["season"]
    return None


def _ratio(top: float, bottom: float, scale: float = 1.0) -> float | None:
    return round(top / bottom * scale, 2) if bottom else None


def rates(sums: dict[str, float]) -> dict[str, float | None]:
    """Rates in the units the rest of the Creative page uses: CTR, hook and hold rate in percent."""
    return {
        "ctr": _ratio(sums["clicks"], sums["impressions"], 100),
        "hookRate": _ratio(sums["video_3s"], sums["video_impressions"], 100)
        if sums["video_3s"]
        else None,
        "holdRate": _ratio(sums["thruplays"], sums["video_3s"], 100),
        "cpa": _ratio(sums["spend"], sums["purchases"]),
        "roas": _ratio(sums["value"], sums["spend"]),
    }


def verdict(sums: dict[str, float], rule: dict[str, float]) -> str:
    """winner, loser, average or insufficient_data (see the module docstring)."""
    if sums["spend"] < rule["min_spend"] or sums["impressions"] < rule["min_impressions"]:
        return "insufficient_data"
    roas = sums["value"] / sums["spend"] if sums["spend"] else 0.0
    if roas >= rule["target_roas"]:
        return "winner"
    if roas < rule["breakeven_roas"]:
        return "loser"
    return "average"


def ad_performance(
    rows: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    products: dict[str, dict[str, Any]],
    calendar: list[dict[str, str]],
    rule: dict[str, float],
) -> list[dict[str, Any]]:
    """One entry per ad that delivered: summed figures, rates, verdict and every tag.

    Print and color come from the ad's own tags, else from the linked product. Format comes from the
    Ads sync. Season is the season of the ad's first day with impressions in the period.
    """
    ads: dict[str, dict[str, Any]] = {}
    for row in rows:
        ad_id = str(row.get("ad_id") or "")
        if not ad_id:
            continue
        ad = ads.get(ad_id)
        if ad is None:
            ad = ads[ad_id] = {
                "row": row,
                "sums": dict.fromkeys(SUM_FIELDS, 0.0),
                "first_day": None,
            }
        s = ad["sums"]
        impressions = float(row.get("impressions") or 0)
        s["spend"] += float(row.get("spend") or 0)
        s["impressions"] += impressions
        s["clicks"] += float(row.get("clicks") or 0)
        s["purchases"] += float(row.get("purchases") or 0)
        s["value"] += float(row.get("purchase_value") or 0)
        s["video_3s"] += float(row.get("video_3s_views") or 0)
        s["thruplays"] += float(row.get("video_thruplays") or 0)
        if str(row.get("ad_format") or "") == "video":
            s["video_impressions"] += impressions
        day = row.get("day")
        if day and impressions > 0 and (ad["first_day"] is None or str(day) < ad["first_day"]):
            ad["first_day"] = str(day)

    out: list[dict[str, Any]] = []
    for ad_id, ad in ads.items():
        sums, row = ad["sums"], ad["row"]
        if sums["spend"] <= 0 and sums["impressions"] <= 0:
            continue
        tag = tags.get(ad_id) or {}
        handle = product_handle(row.get("link_url"))
        product = products.get(handle or "") or {}
        out.append(
            {
                "adId": ad_id,
                "name": row.get("ad_name") or "",
                "platform": row.get("platform") or "",
                "thumbnailUrl": row.get("thumbnail_url"),
                "headline": row.get("headline"),
                "primaryText": row.get("primary_text"),
                "linkUrl": row.get("link_url"),
                "productTitle": product.get("title"),
                "firstDay": ad["first_day"],
                "tags": {
                    "hook_type": tag.get("hook_type"),
                    "hook_text": tag.get("hook_text") or "",
                    "visual_style": tag.get("visual_style"),
                    "format": row.get("ad_format") or None,
                    "print": tag.get("print") or product.get("print"),
                    "color": tag.get("color") or product.get("color"),
                    "category": product.get("category"),
                    "season": season_for(ad["first_day"], calendar),
                    "product": handle,
                    "source": tag.get("source"),
                    "confirmed": bool(tag.get("confirmed")),
                },
                "sums": {k: round(v, 2) for k, v in sums.items()},
                "rates": rates(sums),
                "verdict": verdict(sums, rule),
            }
        )
    out.sort(key=lambda a: a["sums"]["spend"], reverse=True)
    return out


def group_by(
    ads: list[dict[str, Any]], dimension: str, rule: dict[str, float]
) -> list[dict[str, Any]]:
    """Ads grouped by one tag: summed figures, rates, verdict counts and the group's own verdict."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown dimension {dimension!r}. Allowed: {', '.join(DIMENSIONS)}.")
    sums: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(SUM_FIELDS, 0.0))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ad in ads:
        key = ad["tags"].get(dimension) or UNTAGGED
        for field in SUM_FIELDS:
            sums[key][field] += ad["sums"][field]
        counts[key]["ads"] += 1
        counts[key][ad["verdict"]] += 1
    groups: list[dict[str, Any]] = []
    for key, total in sums.items():
        groups.append(
            {
                "value": key,
                "ads": counts[key]["ads"],
                "winners": counts[key]["winner"],
                "average": counts[key]["average"],
                "losers": counts[key]["loser"],
                "insufficient": counts[key]["insufficient_data"],
                "sums": {k: round(v, 2) for k, v in total.items()},
                "rates": rates(total),
                "verdict": verdict(total, rule),
            }
        )
    groups.sort(key=lambda g: g["sums"]["spend"], reverse=True)
    return groups


def summary(ads: list[dict[str, Any]], rule: dict[str, float]) -> dict[str, Any]:
    """Verdict counts, top winners and losers, and every grouping, for the Insights tab."""
    winners = sorted(
        (a for a in ads if a["verdict"] == "winner"),
        key=lambda a: a["rates"]["roas"] or 0,
        reverse=True,
    )
    losers = sorted(
        (a for a in ads if a["verdict"] == "loser"), key=lambda a: a["sums"]["spend"], reverse=True
    )
    return {
        "adCount": len(ads),
        "untagged": sum(1 for a in ads if not a["tags"]["source"]),
        "verdicts": {
            v: sum(1 for a in ads if a["verdict"] == v)
            for v in ("winner", "average", "loser", "insufficient_data")
        },
        "topWinners": winners[:5],
        "topLosers": losers[:5],
        "dimensions": {d: group_by(ads, d, rule) for d in DIMENSIONS},
    }


# ------------------------------------------------------------------------- checking user input
def check_rule(values: dict[str, Any], current: dict[str, float]) -> dict[str, float]:
    """The rule after applying `values`, checked; raises RuleError."""
    checked: dict[str, float] = {}
    for key, value in values.items():
        if key not in RULE_KEYS:
            raise RuleError(f"Unknown rule {key!r}. Allowed: {', '.join(RULE_KEYS)}.")
        try:
            number = float(value)
        except TypeError, ValueError:
            raise RuleError(f"{key} must be a number.") from None
        if number < 0:
            raise RuleError(f"{key} cannot be negative.")
        checked[key] = number
    merged = {**current, **checked}
    if merged["breakeven_roas"] > merged["target_roas"]:
        raise RuleError("Break-even ROAS cannot be higher than the target ROAS.")
    return merged


def check_seasons(entries: Any) -> list[dict[str, str]]:
    """Season entries [{season, start, end}] checked; raises RuleError."""
    if not isinstance(entries, list) or not entries:
        raise RuleError("Send a list of seasons.")
    out: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuleError("Each season must be an object with season, start and end.")
        season = str(entry.get("season") or "")
        start, end = str(entry.get("start") or ""), str(entry.get("end") or "")
        if season not in taxonomy.SEASONS:
            raise RuleError(f"Unknown season {season!r}. Allowed: {', '.join(taxonomy.SEASONS)}.")
        if not MMDD.match(start) or not MMDD.match(end):
            raise RuleError(f"{season}: dates must look like MM-DD (got {start!r}, {end!r}).")
        out.append({"season": season, "start": start, "end": end})
    return out


def ordered_calendar(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Season rows from creative.season in the fixed season order, defaults where missing."""
    by_season = {str(r.get("season")): r for r in rows}
    out = []
    for default in DEFAULT_SEASONS:
        r = by_season.get(default["season"])
        out.append(
            {
                "season": default["season"],
                "start": str(r["start_mmdd"]) if r else default["start"],
                "end": str(r["end_mmdd"]) if r else default["end"],
            }
        )
    return out


def rule_from_row(row: dict[str, Any] | None) -> dict[str, float]:
    """A creative.rule row as floats, defaults when the store has none."""
    if not row:
        return dict(DEFAULT_RULE)
    out: dict[str, float] = {}
    for k in RULE_KEYS:
        value = row.get(k)
        out[k] = float(value) if value is not None else DEFAULT_RULE[k]
    return out
