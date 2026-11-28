"""Tagging: Claude suggests, a person corrects.

Ads get a hook type, the hook line as written, a visual style, print and color (creative.ad_tag);
products get print, color, category and season fit (creative.product). Every value comes from the
fixed vocabulary in taxonomy.py, which the JSON schema enforces and the answer is checked against.

Rules that keep the team in charge:
  * Claude only fills items that have no tags yet. With `retag` it may also replace its own earlier
    tags, but never ones a person set or confirmed.
  * A manual edit sets source = 'manual' and confirmed; Claude never touches that item again.

It reuses SEO & Blog's Claude connection and the shared daily Claude limit: every call is checked
against what is left of today's limit first and recorded with its cost under the kind
"creative_tagging". One small call per item, at low effort.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..seo.integrations import claude
from ..seo.services import ai_budget
from . import products, taxonomy
from .config import store_for

log = logging.getLogger(__name__)

KIND = "creative_tagging"
MAX_BATCH = 50

SYSTEM = (
    "You tag marketing material for an online store selling hand block-printed cotton home "
    "textiles (bedding, quilts, table and kitchen linen, cushion covers) made by artisans in "
    "Jaipur, India. You classify; you do not write copy. Pick the single closest allowed value "
    "for every field. Use 'other' only when no value fits, 'mixed' or 'multicolor' when several "
    "prints or colors dominate equally. Keep 'note' to one short sentence explaining an uncertain "
    "choice, or leave it empty."
)


def _enum(values: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["print", "color", "category", "season_fit", "note"],
    "properties": {
        "print": _enum(taxonomy.PRINTS),
        "color": _enum(taxonomy.COLORS),
        "category": _enum(taxonomy.CATEGORIES),
        "season_fit": _enum(taxonomy.SEASON_FITS),
        "note": {"type": "string"},
    },
}

AD_FIELDS: dict[str, tuple[str, ...]] = {
    "hook_type": taxonomy.HOOK_TYPES,
    "visual_style": taxonomy.VISUAL_STYLES,
    "print": taxonomy.PRINTS,
    "color": taxonomy.COLORS,
}

AD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [*AD_FIELDS, "hook_text", "note"],
    "properties": {
        **{k: _enum(v) for k, v in AD_FIELDS.items()},
        "hook_text": {"type": "string"},
        "note": {"type": "string"},
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ask(
    prompt: str, image_url: str | None, schema: dict[str, Any], brand: str
) -> tuple[dict[str, Any], str]:
    """One schema-constrained Claude call, with the picture when there is one.

    Some image links (Meta's signed thumbnail URLs) cannot be fetched by the API; the call is then
    repeated once with text only rather than failing the item.
    """
    ai_budget.check(KIND)  # 429 daily_limit: nothing is sent to Claude
    blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_url and image_url.startswith("https://"):
        try:
            data, model = claude._structured(
                SYSTEM, [claude._image_block(image_url), *blocks], schema, "low", max_tokens=4000
            )
            ai_budget.record(claude.take_usage(), brand, KIND)
            return data, model
        except claude.ClaudeError as exc:
            ai_budget.record(claude.take_usage(), brand, KIND)
            if exc.kind in ("refusal", "truncated", "invalid_output"):
                raise
            log.info("Creative tagging: image not usable (%s); retrying with text only", exc.kind)
    data, model = claude._structured(SYSTEM, blocks, schema, "low", max_tokens=4000)
    ai_budget.record(claude.take_usage(), brand, KIND)
    return data, model


def _checked(raw: dict[str, Any], allowed: dict[str, tuple[str, ...]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in allowed:
        value = str(raw.get(field) or "")
        if value not in allowed[field]:
            raise claude.ClaudeError(
                f"Claude returned {value!r} for {field}, which is not an allowed value.",
                "invalid_output",
            )
        out[field] = value
    return out


# ---------------------------------------------------------------------------------- ads
def _ads_client() -> Any:
    from ..ads.config import ads_client
    from ..shipping.supabase import SupabaseClient

    c = ads_client()
    assert isinstance(c, SupabaseClient)  # noqa: S101 - narrows the lazily built client
    return c


def store_ads(brand: str) -> dict[str, dict[str, Any]]:
    """The store's ads from ads.ads (with their copy when synced), by id."""
    from . import service

    store_for(brand)
    ads = _ads_client()
    accounts = ads.select("accounts", [("select", "key"), ("brand", f"eq.{brand}")], limit=50).rows
    keys = ",".join(str(a["key"]) for a in accounts if a.get("key"))
    return service.ad_details(ads, keys) if keys else {}


def tags_by_ad(brand: str) -> dict[str, dict[str, Any]]:
    """creative.ad_tag rows of the store, by ad id."""
    rows = (
        products.client()
        .select("ad_tag", [("select", "*"), ("store", f"eq.{store_for(brand)}")], limit=100_000)
        .rows
    )
    return {str(r["ad_id"]): r for r in rows}


def tag_ads(brand: str, limit: int, retag: bool = False) -> dict[str, Any]:
    """Ask Claude to tag up to `limit` untagged ads, newest first."""
    if not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_BATCH}.")
    store = store_for(brand)
    products.require_live("Tagging with Claude")
    ads = store_ads(brand)
    tags = tags_by_ad(brand)

    def wanted(ad_id: str) -> bool:
        tag = tags.get(ad_id)
        if tag is None:
            return True
        return retag and tag.get("source") == "ai" and not tag.get("confirmed")

    todo = sorted(
        (a for i, a in ads.items() if wanted(i)),
        key=lambda a: str(a.get("created_time") or ""),
        reverse=True,
    )[:limit]
    tagged, failed = 0, []
    for ad in todo:
        prompt = (
            "Classify this Meta ad.\n"
            f"Format: {ad.get('format') or ''}\n"
            f"Headline: {ad.get('headline') or ''}\n"
            f"Primary text: {ad.get('primary_text') or ''}\n"
            f"Ad name (internal): {ad.get('name') or ''}\n"
            "hook_type is the angle of the opening line or first visual. hook_text is that "
            "opening line copied as written, or a few words describing the opening visual when "
            "there is no text. The image, if attached, is the ad's thumbnail."
        )
        try:
            raw, model = _ask(prompt, ad.get("thumbnail_url"), AD_SCHEMA, brand)
            values = _checked(raw, AD_FIELDS)
        except claude.ClaudeError as exc:
            failed.append({"id": str(ad["id"]), "name": ad.get("name") or "", "error": str(exc)})
            continue
        products.client().upsert(
            "ad_tag",
            [
                {
                    "ad_id": str(ad["id"]),
                    "store": store,
                    **values,
                    "hook_text": str(raw.get("hook_text") or "")[:300],
                    "source": "ai",
                    "confirmed": False,
                    "note": str(raw.get("note") or "")[:300],
                    "model": model,
                }
            ],
            on_conflict="ad_id",
        )
        tagged += 1
    left = sum(1 for i in ads if i not in tags) - sum(1 for a in todo if str(a["id"]) not in tags)
    return {
        "brand": brand,
        "tagged": tagged,
        "failed": failed,
        "untaggedLeft": max(0, left + len(failed)),
    }


def update_ad(brand: str, ad_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Set an ad's tags by hand, or confirm Claude's (`{"confirmed": true}`)."""
    store = store_for(brand)
    products.require_live("Editing tags")
    if ad_id not in store_ads(brand):
        raise products.NotFoundError(f"No ad {ad_id!r} for {brand}.")
    changes: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "confirmed":
            continue
        if key in ("hook_text", "note"):
            changes[key] = str(value or "")[:300]
        else:
            changes[key] = taxonomy.check_value(key, str(value or ""), AD_FIELDS)
    if not changes and not fields.get("confirmed"):
        raise taxonomy.InvalidTagError("Nothing to change: send tag values or confirmed=true.")
    c = products.client()
    existing = tags_by_ad(brand).get(ad_id)
    row: dict[str, Any] = {"ad_id": ad_id, "store": store, "confirmed": True}
    if changes or existing is None:
        row["source"] = "manual"
    row.update(changes)
    if existing is None:
        c.upsert("ad_tag", [row], on_conflict="ad_id")
    else:
        c.update(
            "ad_tag", [("ad_id", f"eq.{ad_id}")], {k: v for k, v in row.items() if k != "ad_id"}
        )
    return dict(c.select("ad_tag", [("select", "*"), ("ad_id", f"eq.{ad_id}")], limit=1).rows[0])


# ------------------------------------------------------------------------------ products
def tag_products(brand: str, limit: int, retag: bool = False) -> dict[str, Any]:
    """Ask Claude for print, color, category and season fit of up to `limit` untagged products."""
    if not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_BATCH}.")
    store = store_for(brand)
    products.require_live("Tagging with Claude")
    rows = products.listing(brand)

    def wanted(p: dict[str, Any]) -> bool:
        if not p.get("source"):
            return True
        return retag and p.get("source") == "ai" and not p.get("confirmed")

    todo = [p for p in rows if wanted(p)][:limit]
    tagged, failed = 0, []
    for p in todo:
        prompt = (
            "Classify this product.\n"
            f"Title: {p.get('title') or ''}\n"
            f"Product type: {p.get('product_type') or ''}\n"
            "The image, if attached, is the product's main photo."
        )
        try:
            raw, model = _ask(prompt, p.get("image_url"), PRODUCT_SCHEMA, brand)
            values = _checked(raw, taxonomy.PRODUCT_FIELDS)
        except claude.ClaudeError as exc:
            failed.append({"id": p["handle"], "name": p.get("title") or "", "error": str(exc)})
            continue
        products.client().update(
            "product",
            [("store", f"eq.{store}"), ("handle", f"eq.{p['handle']}"), ("confirmed", "eq.false")],
            {
                **values,
                "source": "ai",
                "note": str(raw.get("note") or "")[:300],
                "model": model,
                "tagged_at": _now(),
            },
        )
        tagged += 1
    left = sum(1 for p in rows if not p.get("source")) - sum(1 for p in todo if not p.get("source"))
    return {
        "brand": brand,
        "tagged": tagged,
        "failed": failed,
        "untaggedLeft": max(0, left + len(failed)),
    }
