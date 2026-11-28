"""What the /creative page asks for: insights, concepts, briefs and tests.

Two sources, never mixed in one answer:
  * demo   fixed sample ads and findings, so the page can be built and reviewed before any ad
           account is connected. Every answer carries ``"source": "demo"``.
  * live   the Ads teammate's own sync tables in schema `ads` (``accounts``, ``ads``, ``daily``),
           read through Supabase. That sync is Meta-only today and does not yet store the ad's own
           headline or primary text, so hooks cannot be grouped from live data: `by_hook` comes back
           empty rather than guessing from the ad's internal name, which is not real ad copy.

The AI step (Claude writing concepts and briefs from these findings) is deliberately not here yet:
the figures have to be right and checkable first. The brief template below is written by rule, not
by a model, so the page has something real to show in the meantime.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import insights
from .config import MIN_SPEND, creative_config, store_for

log = logging.getLogger(__name__)


class InputError(ValueError):
    """A value the caller sent that cannot be used (becomes HTTP 400)."""


def _range(days: int) -> tuple[date, date]:
    """The last `days` complete days, ending yesterday (today is still being restated)."""
    if days < 1 or days > 400:
        raise InputError("Choose between 1 and 400 days.")
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    return yesterday - timedelta(days=days - 1), yesterday


def _explicit_range(since: date, until: date) -> tuple[date, date]:
    """A caller-picked date range (the page's own calendar), checked the same way as `_range`.

    `until` is clamped to today rather than refused: a picker that lets today be the end of
    "custom range" would otherwise error on the one day people are most likely to pick. Today is
    allowed through (unlike `_range`'s rolling windows): the Ads sync already reads today's figures
    every run, so there is something real to show; the caller marks it "partial" rather than hiding
    it, since Meta can still revise today's numbers later.
    """
    today = datetime.now(UTC).date()
    if until > today:
        until = today
    if since > until:
        raise InputError("The start date must be on or before the end date.")
    if (until - since).days + 1 > 400:
        raise InputError("Choose a range of at most 400 days.")
    return since, until


# ------------------------------------------------------------------ demo ads
# Fixed sample rows in the shape of ads.v_ad_daily: one row per ad per day would be long, so each ad
# appears once with its totals, which the grouping treats identically.
#
# The copy matches what these stores actually sell and how their brand guide says they speak.
# Read on 2026-11-25: Ridhi has 1,045 products (196 tablecloths, 88 pillow covers, placemats,
# napkins, runners) and Cotton Print Club 493, and the brand guide sets US customers aged 35-70,
# promotions of "up to 40% off" and free standard shipping on all orders. The first samples written
# that day were Hindi copy about clothing with a 50% discount and a shipping threshold in rupees;
# Claude's first live answer correctly flagged all of it as breaking the guide.
_DEMO_ADS: list[dict[str, Any]] = [
    {
        "ad_id": "1", "platform": "meta", "ad_name": "Craft story · artisan hands",
        "ad_format": "video", "headline": "Hand block printed in Jaipur",
        "primary_text": "Watch how one tablecloth is printed, one carved block at a time.",
        "spend": 1240.0, "impressions": 184_000, "clicks": 3_128, "purchases": 48.0,
        "purchase_value": 7_680.0, "video_3s_views": 42_300, "video_thruplays": 9_800,
    },
    {
        "ad_id": "2", "platform": "meta", "ad_name": "Discount · up to 40 off",
        "ad_format": "image", "headline": "Up to 40% off",
        "primary_text": "Up to 40% off our hand block printed tablecloths. This week only.",
        "spend": 1480.0, "impressions": 221_000, "clicks": 2_652, "purchases": 31.0,
        "purchase_value": 4_200.0, "video_3s_views": 0, "video_thruplays": 0,
    },
    {
        "ad_id": "3", "platform": "meta", "ad_name": "Table styling · carousel",
        "ad_format": "carousel", "headline": "One cloth, four tables",
        "primary_text": "Watch how one tablecloth is styled, from breakfast to a dinner party.",
        "spend": 890.0, "impressions": 131_400, "clicks": 2_103, "purchases": 27.0,
        "purchase_value": 4_490.0, "video_3s_views": 0, "video_thruplays": 0,
    },
    {
        "ad_id": "4", "platform": "meta", "ad_name": "Customer review · UGC",
        "ad_format": "video", "headline": "What customers say",
        "primary_text": "Washed it for three months and the colour has not moved. Honestly.",
        "spend": 625.0, "impressions": 76_000, "clicks": 1_303, "purchases": 22.0,
        "purchase_value": 3_278.0, "video_3s_views": 19_400, "video_thruplays": 6_100,
    },
    {
        "ad_id": "5", "platform": "google", "ad_name": "Search · block print tablecloth",
        "ad_format": "rsa", "headline": "Hand Block Print Tablecloth",
        "primary_text": "Handmade cotton tablecloths with free shipping on every order.",
        "spend": 1890.0, "impressions": 141_300, "clicks": 4_521, "purchases": 61.0,
        "purchase_value": 9_760.0, "video_3s_views": 0, "video_thruplays": 0,
    },
    {
        "ad_id": "6", "platform": "meta", "ad_name": "New arrivals · too early",
        "ad_format": "image", "headline": "New this week",
        "primary_text": "New arrivals are here.",
        "spend": 42.0, "impressions": 4_100, "clicks": 38, "purchases": 0.0,
        "purchase_value": 0.0, "video_3s_views": 0, "video_thruplays": 0,
    },
]


def _rows(brand: str, since: date, until: date) -> tuple[list[dict[str, Any]], str, str]:
    """The ad-level rows one round of insights works from, where they came from, and their currency.

    Live rows are built from three of the Ads teammate's tables, none of which this module ever
    writes to: ``ads.accounts`` (one row per ad account, to find this brand's account keys, each
    one's platform, and the currency it reports spend in), ``ads.ads`` (the ad's format and name,
    synced once), and ``ads.daily`` (the figures for the period, one row per ad per day). There is
    no view joining them yet, so this builds the join itself, in memory, from a handful of small
    reads. A brand's accounts are assumed to share one currency (true today: one Meta account per
    brand); spend is not converted or added across currencies.
    """
    cfg = creative_config()
    if cfg.demo:
        return list(_DEMO_ADS), "demo", "USD"
    store_for(brand)  # raises for an unknown brand; the real tables key by brand text, not store id
    from ..ads.config import ads_client
    from ..shipping.supabase import SupabaseClient

    ads = ads_client()
    assert isinstance(ads, SupabaseClient)  # noqa: S101 - narrows the lazily built client

    accounts = ads.select(
        "accounts", [("select", "key,platform,currency"), ("brand", f"eq.{brand}")], limit=50
    ).rows
    keys = [str(a["key"]) for a in accounts if a.get("key")]
    if not keys:
        return [], "live", "USD"
    platform_of = {str(a["key"]): str(a.get("platform") or "") for a in accounts}
    currency = str(accounts[0].get("currency") or "USD").strip() or "USD"
    key_list = ",".join(keys)

    ad_rows = ads.select(
        "ads",
        [("select", "id,account_key,format,name"), ("account_key", f"in.({key_list})")],
        limit=100_000,
    ).rows
    ad_info = {str(a["id"]): a for a in ad_rows if a.get("id")}

    daily_rows = ads.select(
        "daily",
        [
            ("select", "ad_id,account_key,day,spend,impressions,clicks,purchases,value,v3,p75"),
            ("account_key", f"in.({key_list})"),
            ("day", f"gte.{since.isoformat()}"),
            ("day", f"lte.{until.isoformat()}"),
        ],
        limit=100_000,
    ).rows

    out: list[dict[str, Any]] = []
    for row in daily_rows:
        ad_id = str(row.get("ad_id") or "")
        info = ad_info.get(ad_id, {})
        out.append(
            {
                "ad_id": ad_id,
                "day": row.get("day"),
                "platform": platform_of.get(str(row.get("account_key") or ""), ""),
                "ad_name": info.get("name") or "",
                "ad_format": info.get("format") or "",
                # Not synced yet: the ad's own headline/primary text, so hooks cannot be grouped.
                "headline": None,
                "primary_text": None,
                "spend": row.get("spend"),
                "impressions": row.get("impressions"),
                "clicks": row.get("clicks"),
                "purchases": row.get("purchases"),
                "purchase_value": row.get("value"),
                "video_3s_views": row.get("v3"),
                # No distinct "thruplay" event is synced; p75 (watched at least three-quarters of
                # the video) is the closest available signal for whether the middle held attention.
                "video_thruplays": row.get("p75"),
            }
        )
    return out, "live", currency


# ------------------------------------------------------------------ insights
def findings(
    brand: str,
    days: int | None = None,
    since: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    """What the ads showed over the period: formats, hooks and platforms compared.

    Each group says whether there is enough data behind it. Nothing here is a recommendation yet:
    the page shows these figures next to the concepts so a suggestion can be checked against them.

    `since`/`until` (the page's own date picker) win when both are given; otherwise the period is
    the last `days` complete days, or the configured default when `days` is also None.
    """
    cfg = creative_config()
    if since is not None and until is not None:
        since, until = _explicit_range(since, until)
    else:
        # None means "the configured default"; any other value is checked, so days=0 is an error
        # rather than a silent fall back to 28.
        since, until = _range(cfg.insight_days if days is None else days)
    rows, source, currency = _rows(brand, since, until)
    by_format = insights.by_format(rows)
    by_hook = insights.by_hook(rows)
    by_platform = insights.by_platform(rows)
    low, spend_floor = cfg.min_impressions, MIN_SPEND
    return {
        "brand": brand,
        "source": source,
        "currency": currency,
        "from": since.isoformat(),
        "to": until.isoformat(),
        "partial": until >= datetime.now(UTC).date(),
        "adsSeen": len({str(r.get("ad_id") or "") for r in rows if r.get("ad_id")}),
        "formats": [g.as_dict(low, spend_floor) for g in by_format],
        "hooks": [g.as_dict(low, spend_floor) for g in by_hook],
        "platforms": [g.as_dict(low, spend_floor) for g in by_platform],
        "comparisons": {
            "formatRoas": insights.compare(by_format, "roas", low, spend_floor),
            "hookCtr": insights.compare(by_hook, "ctr", low, spend_floor),
            "formatHookRate": insights.compare(by_format, "hook_rate", low, spend_floor),
        },
        "thresholds": {"minImpressions": low, "minSpend": spend_floor},
        "note": (
            "Purchases and value are what the platform reports, not Shopify orders. A group marked "
            "sampleOk = false has too little behind it to act on yet."
        ),
    }


def _day_point(day: str, acc: dict[str, float]) -> dict[str, Any]:
    """One day's totals, with CTR and ROAS worked out the same way as a `Group`."""
    ctr = round(acc["clicks"] / acc["impressions"] * 100, 2) if acc["impressions"] else None
    roas = round(acc["value"] / acc["spend"], 2) if acc["spend"] > 0 else None
    return {
        "date": day,
        "spend": round(acc["spend"], 2),
        "impressions": int(acc["impressions"]),
        "clicks": int(acc["clicks"]),
        "purchases": round(acc["purchases"], 2),
        "purchaseValue": round(acc["value"], 2),
        "ctr": ctr,
        "roas": roas,
    }


# Monday..Sunday relative weight, so the demo trend looks like a real campaign (weekend lift)
# instead of a flat, obviously-fake line.
_DEMO_DAY_WEIGHT = (0.85, 0.95, 1.0, 0.95, 1.1, 1.35, 1.2)


def _demo_shares(since: date, n: int, amplitude: float, period: float, phase: float) -> list[float]:
    """One metric's share of each day in the period: the same weekday shape every metric uses,
    bent by its own gentle wave so CTR and ROAS move day to day instead of staying flat.

    If every metric scaled by the identical weekday weight, spend and clicks would rise and fall
    together in lockstep, and a ratio of two such series is mathematically constant: the first
    version of this function did exactly that, and the chart showed a dead-flat CTR and ROAS line.
    Each metric here gets its own normalised share list (summing to 1 across the period, so the
    metric's own total is unchanged), with a different wave period and phase so the shapes diverge.
    """
    raw = [
        _DEMO_DAY_WEIGHT[(since + timedelta(days=i)).weekday()]
        * (1 + amplitude * math.sin(2 * math.pi * i / period + phase))
        for i in range(n)
    ]
    raw = [max(w, 0.05) for w in raw]
    total = sum(raw) or 1.0
    return [w / total for w in raw]


def _demo_trend(brand: str, since: date, until: date, currency: str) -> dict[str, Any]:
    """A day-by-day split of the demo totals, so the chart has something to show before any ad
    account is connected. The demo ads themselves carry no day, only a period total."""
    totals = {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "purchases": 0.0, "value": 0.0}
    for ad in _DEMO_ADS:
        totals["spend"] += ad["spend"]
        totals["impressions"] += ad["impressions"]
        totals["clicks"] += ad["clicks"]
        totals["purchases"] += ad["purchases"]
        totals["value"] += ad["purchase_value"]
    n = (until - since).days + 1
    spend_share = _demo_shares(since, n, 0.0, 7, 0.0)
    impr_share = _demo_shares(since, n, 0.15, 6, 0.4)
    click_share = _demo_shares(since, n, 0.22, 5, 1.1)
    value_share = _demo_shares(since, n, 0.28, 8, 2.0)
    days = []
    for i in range(n):
        day = since + timedelta(days=i)
        acc = {
            "spend": totals["spend"] * spend_share[i],
            "impressions": totals["impressions"] * impr_share[i],
            "clicks": totals["clicks"] * click_share[i],
            "purchases": totals["purchases"] * value_share[i],
            "value": totals["value"] * value_share[i],
        }
        days.append(_day_point(day.isoformat(), acc))
    return {
        "brand": brand,
        "source": "demo",
        "currency": currency,
        "from": since.isoformat(),
        "to": until.isoformat(),
        "partial": until >= datetime.now(UTC).date(),
        "days": days,
    }


def trend(
    brand: str,
    days: int | None = None,
    since: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    """Day-by-day totals across the period, for a chart: spend, CTR and ROAS over time.

    Reuses `_rows`, so live and demo stay the same two sources as `findings`; the grouping here is
    by day instead of by format or hook. `since`/`until` win when both are given, same as
    `findings`.
    """
    cfg = creative_config()
    if since is not None and until is not None:
        since, until = _explicit_range(since, until)
    else:
        since, until = _range(cfg.insight_days if days is None else days)
    rows, source, currency = _rows(brand, since, until)
    if source == "demo":
        return _demo_trend(brand, since, until, currency)
    by_day: dict[str, dict[str, float]] = {}
    for row in rows:
        day = str(row.get("day") or "")
        if not day:
            continue
        acc = by_day.setdefault(
            day, {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "purchases": 0.0, "value": 0.0}
        )
        acc["spend"] += float(row.get("spend") or 0)
        acc["impressions"] += float(row.get("impressions") or 0)
        acc["clicks"] += float(row.get("clicks") or 0)
        acc["purchases"] += float(row.get("purchases") or 0)
        acc["value"] += float(row.get("purchase_value") or 0)
    return {
        "brand": brand,
        "source": source,
        "currency": currency,
        "from": since.isoformat(),
        "to": until.isoformat(),
        "partial": until >= datetime.now(UTC).date(),
        "days": [_day_point(day, acc) for day, acc in sorted(by_day.items())],
    }


# ------------------------------------------------------------------ brief template
# Written by rule, not by a model: a brief has a fixed shape, and the team can use it today while
# the AI step is still to come. Claude's job later is to fill the same shape with sharper words.
def brief_markdown(concept: dict[str, Any]) -> str:
    """One brief in markdown, ready to paste into a message to a designer or editor."""
    title = str(concept.get("title") or "Untitled concept").strip()
    hook = str(concept.get("hook") or "").strip()
    angle = str(concept.get("angle") or "").strip()
    message = str(concept.get("message") or "").strip()
    offer = str(concept.get("offer") or "").strip()
    stage = str(concept.get("funnel_stage") or concept.get("funnelStage") or "tof").lower()
    stage_text = {
        "tof": "People who do not know the brand yet. Lead with the craft, not the discount.",
        "mof": "People comparing options. Answer the doubt: quality, fit, how it washes.",
        "bof": "People ready to buy. Make the offer and the delivery promise plain.",
    }.get(stage, "")
    lines = [
        f"# {title}",
        "",
        f"**Funnel stage:** {stage.upper()} — {stage_text}",
        "",
        "## The idea",
        angle or "(angle not set)",
        "",
        "## Hook (first line or first three seconds)",
        f"> {hook}" if hook else "> (hook not set)",
        "",
        "## What the ad must say",
        message or "(message not set)",
    ]
    if offer:
        lines += ["", "## Offer", offer]
    lines += [
        "",
        "## Deliverables",
        "- 1 main version, 9:16 for Reels and Stories",
        "- 1 cut to 1:1 for the feed",
        "- Captions burnt in: most people watch with the sound off",
        "",
        "## Rules",
        "- Brand voice: no claim the brand guide does not allow",
        "- Show the real product; no stock footage of somebody else's goods",
        "- One variable changes against the current ad, nothing else",
    ]
    evidence = concept.get("evidence")
    if isinstance(evidence, list):
        evidence = "; ".join(str(e) for e in evidence if e)
    if evidence:
        lines += ["", "## Why this idea", f"```\n{evidence}\n```"]
    return "\n".join(lines)


# ------------------------------------------------------------------ demo concepts
# Derived from the demo findings above by hand, so the page shows the connection between a finding
# and an idea. Live concepts will be written by Claude from the same findings, in a later task.
_DEMO_CONCEPTS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "From the carved block to your table",
        "hook": "One block. Pressed by hand, hundreds of times.",
        "angle": "The craft story outperforms the discount ad, so lead with how it is made.",
        "message": "Every cloth is hand block printed in Jaipur; the small wobble in the print is "
                   "the proof of a human hand, not a fault.",
        "offer": "",
        "funnel_stage": "tof",
        "status": "idea",
        "origin": "human",
        "evidence": "video format ROAS 6.19 vs image 2.84 over 28 days; craft hook CTR 1.70%",
    },
    {
        "id": 2,
        "title": "Three months later: the colour test",
        "hook": "Three months of washing. The colour has not moved.",
        "angle": "The review ad holds attention best, so answer the washing doubt directly.",
        "message": "Machine washable, colourfast and pre-washed. Shown on a cloth a customer has "
                   "used daily for three months.",
        "offer": "",
        "funnel_stage": "mof",
        "status": "idea",
        "origin": "human",
        "evidence": "UGC video hold rate 31.4%, the highest of any format in the period",
    },
    {
        "id": 3,
        "title": "Free shipping, said plainly",
        "hook": "Free shipping on every order. No minimum.",
        "angle": "Search already converts on intent; put the brand's own shipping promise in the "
                 "headline for people who are close to buying.",
        "message": "Hand block printed cotton tablecloths with free worldwide standard shipping on "
                   "all orders.",
        "offer": "Free standard shipping on all orders",
        "funnel_stage": "bof",
        "status": "idea",
        "origin": "human",
        "evidence": "google search ROAS 5.16 on 1,890 spend; highest CTR of all groups",
    },
]


def concepts(brand: str) -> dict[str, Any]:
    """The concept list for a store.

    In demo mode these are the three worked examples above. Live concepts are read from
    creative.concept once the page can write them (a later task); until then the live answer is an
    empty list rather than a pretend one.
    """
    cfg = creative_config()
    if cfg.demo:
        return {
            "brand": brand,
            "source": "demo",
            "concepts": _DEMO_CONCEPTS,
            "note": "Sample concepts, written by hand from the sample findings.",
        }
    store = store_for(brand)
    from ..shipping.supabase import SupabaseClient
    from .config import creative_client

    client = creative_client()
    assert isinstance(client, SupabaseClient)  # noqa: S101 - narrows the lazily built client
    page = client.select(
        "concept",
        [("store", f"eq.{store}"), ("order", "created_at.desc"), ("select", "*")],
        limit=200,
    )
    return {
        "brand": brand,
        "source": "live",
        "concepts": page.rows,
        "note": "Concepts saved in Flowmerce. Writing them from the AI step is a later task.",
    }


_FUNNEL_STAGES = ("tof", "mof", "bof")


def _clip(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def save_concept(brand: str, concept: dict[str, Any], by: str) -> dict[str, Any]:
    """Keep one concept (from the AI pack, or written by hand) in ``creative.concept``.

    Not available in demo mode: there is nothing real yet to attach a saved idea to, and the demo
    concepts already behave as if saved. The row keeps `evidence` as a list, same shape as a pack
    concept's, so a later re-read and `brief_markdown` both already know what to do with it.
    """
    cfg = creative_config()
    if cfg.demo:
        raise InputError("Switch off demo mode before saving a concept.")
    store = store_for(brand)
    title = _clip(concept.get("title"), 300)
    if not title:
        raise InputError("A concept needs at least a title.")
    stage = str(concept.get("funnel_stage") or concept.get("funnelStage") or "tof").lower()
    evidence = concept.get("evidence")
    if isinstance(evidence, str):
        evidence = [evidence] if evidence.strip() else []
    elif not isinstance(evidence, list):
        evidence = []
    row = {
        "store": store,
        "title": title,
        "hook": _clip(concept.get("hook"), 500),
        "angle": _clip(concept.get("angle"), 500),
        "message": _clip(concept.get("message"), 1000),
        "offer": _clip(concept.get("offer"), 500),
        "funnel_stage": stage if stage in _FUNNEL_STAGES else "tof",
        "persona": _clip(concept.get("persona"), 300),
        "evidence": [str(e) for e in evidence if str(e).strip()][:10],
        "origin": concept.get("origin")
        if concept.get("origin") in ("ai", "human", "mixed")
        else "ai",
        "status": "idea",
        "created_by": by,
    }
    from ..shipping.supabase import SupabaseClient
    from .config import creative_client

    client = creative_client()
    assert isinstance(client, SupabaseClient)  # noqa: S101 - narrows the lazily built client
    saved = client.insert_returning("concept", row)
    return {"brand": brand, "source": "live", "concept": saved}


def brief_for(concept_id: int, brand: str) -> dict[str, Any]:
    """The brief markdown for one concept.

    In demo mode the concept comes from the samples; live it is read from creative.concept.
    """
    cfg = creative_config()
    if cfg.demo:
        found = next((c for c in _DEMO_CONCEPTS if int(c["id"]) == concept_id), None)
        if found is None:
            raise InputError(f"No sample concept with id {concept_id}.")
        return {"source": "demo", "conceptId": concept_id, "markdown": brief_markdown(found)}
    rows = concepts(brand)["concepts"]
    found = next((c for c in rows if int(c.get("id") or 0) == concept_id), None)
    if found is None:
        raise InputError(f"No concept with id {concept_id} for this store.")
    return {"source": "live", "conceptId": concept_id, "markdown": brief_markdown(found)}
