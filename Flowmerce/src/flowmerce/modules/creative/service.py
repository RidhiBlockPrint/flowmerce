"""What the /creative page asks for: insights, concepts, briefs and tests.

Two sources, never mixed in one answer:
  * demo   fixed sample ads and findings, so the page can be built and reviewed before any ad
           account is connected. Every answer carries ``"source": "demo"``.
  * live   ads.v_ad_daily through Supabase.

The AI step (Claude writing concepts and briefs from these findings) is deliberately not here yet:
the figures have to be right and checkable first. The brief template below is written by rule, not
by a model, so the page has something real to show in the meantime.
"""

from __future__ import annotations

import logging
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


def _rows(brand: str, since: date, until: date) -> tuple[list[dict[str, Any]], str]:
    """The ad-level rows one round of insights works from, and where they came from."""
    cfg = creative_config()
    if cfg.demo:
        return list(_DEMO_ADS), "demo"
    store = store_for(brand)
    from ..shipping.supabase import SupabaseClient
    from .config import creative_client

    client = creative_client()
    assert isinstance(client, SupabaseClient)  # noqa: S101 - narrows the lazily built client
    # ads.v_ad_daily is in schema `ads`, which the Ads module exposes; read it with that profile.
    from ..ads.config import ads_client

    ads = ads_client()
    assert isinstance(ads, SupabaseClient)  # noqa: S101
    page = ads.select(
        "v_ad_daily",
        [
            ("store", f"eq.{store}"),
            ("metric_date", f"gte.{since.isoformat()}"),
            ("metric_date", f"lte.{until.isoformat()}"),
            ("select", "*"),
        ],
        limit=10_000,
    )
    return page.rows, "live"


# ------------------------------------------------------------------ insights
def findings(brand: str, days: int | None = None) -> dict[str, Any]:
    """What the ads showed over the period: formats, hooks and platforms compared.

    Each group says whether there is enough data behind it. Nothing here is a recommendation yet:
    the page shows these figures next to the concepts so a suggestion can be checked against them.
    """
    cfg = creative_config()
    # None means "the configured default"; any other value is checked, so days=0 is an error rather
    # than a silent fall back to 28.
    since, until = _range(cfg.insight_days if days is None else days)
    rows, source = _rows(brand, since, until)
    by_format = insights.by_format(rows)
    by_hook = insights.by_hook(rows)
    by_platform = insights.by_platform(rows)
    low, spend_floor = cfg.min_impressions, MIN_SPEND
    return {
        "brand": brand,
        "source": source,
        "from": since.isoformat(),
        "to": until.isoformat(),
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
