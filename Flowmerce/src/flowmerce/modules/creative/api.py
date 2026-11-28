"""Creative Strategist routes, mounted under /api/creative. Nothing is published: concepts, briefs,
tags and rules are stored in Flowmerce only, and Meta and Shopify are only read.

Every route checks the `view` permission like the rest of Flowmerce. Errors the page can explain
come back with a `code`: 400 bad_request, 404 not_found, 503 for a Supabase problem.
`brand` is 'ridhi' or 'cpc' on every route.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Request

from ..seo.audit import audit
from ..seo.auth import require_perm
from ..seo.integrations.claude import ClaudeError
from ..seo.util import HttpError
from ..shipping.supabase import SupabaseError
from . import generate, products, service, tagging, taxonomy

creative = APIRouter(prefix="/api/creative")

# One shared JSON-body marker for the write routes (FastAPI reads the request body into it).
_BODY: Any = Body(default={})

_SUPABASE_STATUS = {
    "not_configured": 503,
    "schema_missing": 503,
    "permission_denied": 503,
    "connection_failed": 503,
    "bad_request": 400,
    "not_found": 404,
    "conflict": 409,
}


def _call[T](fn: Callable[[], T]) -> T:
    """Run a service call and turn its known failures into explained HTTP errors."""
    try:
        return fn()
    except service.InputError as exc:
        raise HttpError(400, str(exc), "bad_request") from None
    except products.NotFoundError as exc:
        raise HttpError(404, str(exc), "not_found") from None
    except products.NotConfiguredError as exc:
        raise HttpError(412, str(exc), "pending_setup") from None
    except ValueError as exc:  # unknown brand from store_for()
        raise HttpError(400, str(exc), "bad_request") from None
    except ClaudeError as exc:
        # Claude's own failures (no key, overloaded, refused) are already explained; 502 because
        # the problem is upstream of Flowmerce, not in the request.
        raise HttpError(502, str(exc), "claude_error") from None
    except SupabaseError as exc:
        message = exc.message
        if exc.state == "schema_missing":
            message = (
                "The Creative tables are missing, or the `creative` schema is not exposed in "
                "Supabase (Project Settings -> Data API -> Exposed schemas). Run "
                "db/central/115_ads.sql, 116_creative.sql and 118_creative_tags.sql first."
            )
        raise HttpError(_SUPABASE_STATUS.get(exc.state, 502), message, exc.state) from None


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value or default)))
    except (TypeError, ValueError):
        return default


def _date(value: str | None) -> date | None:
    """A `?from=`/`?to=` query value as a date, or None when it is absent."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HttpError(400, "Dates must be in YYYY-MM-DD form.", "bad_request") from None


@creative.get("/insights")
def insights(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """What the ads showed over the period: formats, hooks and platforms.

    The period is `?from=`/`?to=` (the page's own date picker) when both are given, else the last
    `?days=` complete days. Answers from sample ads while no ad platform is connected; `source`
    says which it was.
    """
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 0, 0, 400) or None
    since = _date(request.query_params.get("from"))
    until = _date(request.query_params.get("to"))
    return _call(lambda: service.findings(brand, days, since, until))


@creative.get("/trend")
def trend(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Day-by-day spend, CTR and ROAS over the period, for a chart.

    Same period rule as `/insights`: `?from=`/`?to=` win over `?days=`.
    """
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 0, 0, 400) or None
    since = _date(request.query_params.get("from"))
    until = _date(request.query_params.get("to"))
    return _call(lambda: service.trend(brand, days, since, until))


@creative.get("/concepts")
def concepts(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The creative ideas for a store, newest first."""
    require_perm(request, "view")
    return _call(lambda: service.concepts(brand))


@creative.post("/concepts")
def save_concept(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Save one concept (from the AI pack, or written by hand) so it persists and gets a brief."""
    user = require_perm(request, "view")
    who = str(user.get("email") or user.get("name") or "team")
    out = _call(lambda: service.save_concept(brand, body, who))
    audit(
        user,
        "creative.concept.save",
        "creative_store",
        None,
        brand,
        f"Saved concept: {str(body.get('title') or '')[:100]}",
    )
    return out


@creative.get("/concepts/{concept_id}/brief")
def brief(request: Request, concept_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """The brief for one concept, as markdown ready to send to a designer or editor."""
    require_perm(request, "view")
    return _call(lambda: service.brief_for(concept_id, brand))


# ------------------------------------------------------------------------------ Claude's creative
@creative.get("/pack")
def pack(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The creative pack Claude wrote for this store, and whether a new one is being written.

    Reads only: opening the page never spends money. `POST /pack` asks for a new one.
    """
    require_perm(request, "view")
    return _call(lambda: generate.state(brand))


@creative.post("/pack")
def new_pack(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Ask Claude for a new creative pack. Returns at once; the work runs in the background."""
    user = require_perm(request, "view")
    who = str(user.get("email") or user.get("name") or "team")
    out = _call(lambda: generate.start(brand, who))
    audit(user, "creative.pack", "creative_store", None, brand, "Asked Claude for a creative pack")
    return out


@creative.get("/recommendations")
def recommendations(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """What Claude read in the trend, and whether a new round is being written.

    Reads only: opening the page never spends money. `POST /recommendations` asks for a new round.
    """
    require_perm(request, "view")
    return _call(lambda: generate.state_recs(brand))


@creative.post("/recommendations")
def new_recommendations(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Ask Claude for a new round of trend recommendations. Runs in the background."""
    user = require_perm(request, "view")
    who = str(user.get("email") or user.get("name") or "team")
    out = _call(lambda: generate.start_recs(brand, who))
    audit(
        user,
        "creative.recommendations",
        "creative_store",
        None,
        brand,
        "Asked Claude for trend recommendations",
    )
    return out


@creative.post("/variations")
def variations(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Fresh variations of one concept that already works, changing a single variable.

    The concept goes in the request body as `concept`; the answer is returned, not stored.
    """
    user = require_perm(request, "view")
    concept = body.get("concept") if isinstance(body, dict) else None
    out = _call(lambda: generate.variations(brand, concept if isinstance(concept, dict) else {}))
    audit(
        user,
        "creative.variations",
        "creative_store",
        None,
        brand,
        f"Asked Claude for variations of {str((concept or {}).get('title') or 'a concept')[:100]}",
    )
    return out


# --------------------------------------------------------- what it monitors: tags and patterns
def _user(request: Request) -> tuple[dict[str, Any], str]:
    user = require_perm(request, "view")
    return user, str(user.get("email") or user.get("name") or "team")


@creative.get("/taxonomy")
def get_taxonomy(request: Request) -> dict[str, list[str]]:
    """The allowed values of every tag."""
    require_perm(request, "view")
    return taxonomy.as_dict()


@creative.get("/patterns")
def get_patterns(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Every ad's verdict and tags, and results grouped by each tag. Same period rule as
    `/insights`: `?from=`/`?to=` win over `?days=`."""
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 0, 0, 400) or None
    since = _date(request.query_params.get("from"))
    until = _date(request.query_params.get("to"))
    return _call(lambda: service.creative_patterns(brand, days, since, until))


@creative.get("/rules")
def get_rules(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The store's winner / loser thresholds and season calendar."""
    require_perm(request, "view")
    return _call(lambda: service.rules(brand))


@creative.put("/rules")
def put_rules(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Change some or all thresholds: min_spend, min_impressions, target_roas, breakeven_roas."""
    user, who = _user(request)
    out = _call(lambda: service.save_rule(brand, body, who))
    audit(user, "creative.rules", "creative_store", None, brand, "Changed winner/loser rules")
    return out


@creative.put("/seasons")
def put_seasons(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Change season date ranges: {"seasons": [{"season", "start", "end"}]} (MM-DD)."""
    user, _who = _user(request)
    out = _call(lambda: service.save_seasons(brand, body.get("seasons")))
    audit(user, "creative.seasons", "creative_store", None, brand, "Changed the season calendar")
    return out


@creative.get("/products")
def get_products(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The store's products with print, color, category and season fit."""
    require_perm(request, "view")
    return _call(lambda: {"brand": brand, "products": products.listing(brand)})


@creative.post("/products/sync")
def sync_products(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Read the store's active products from Shopify (read-only)."""
    user, _who = _user(request)
    out = _call(lambda: products.sync(brand))
    audit(user, "creative.products.sync", "creative_store", None, brand,
          f"Read {out['products']} products from Shopify")
    return out


@creative.post("/products/tag")
def tag_products(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Let Claude tag up to `limit` untagged products (default 20)."""
    user, _who = _user(request)
    limit = _int(str(body.get("limit") or ""), 20, 1, tagging.MAX_BATCH)
    out = _call(lambda: tagging.tag_products(brand, limit, bool(body.get("retag"))))
    audit(user, "creative.products.tag", "creative_store", None, brand,
          f"Claude tagged {out['tagged']} products")
    return out


@creative.patch("/products/{handle}")
def patch_product(
    request: Request, handle: str, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Correct or confirm a product's attributes (addressed by its Shopify handle)."""
    user, _who = _user(request)
    out = _call(lambda: {"product": products.update(brand, handle, body)})
    audit(user, "creative.product.edit", "creative_store", None, brand, f"Edited product {handle}")
    return out


@creative.post("/tags/run")
def tag_ads(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Let Claude tag up to `limit` untagged ads (default 20), newest first."""
    user, _who = _user(request)
    limit = _int(str(body.get("limit") or ""), 20, 1, tagging.MAX_BATCH)
    out = _call(lambda: tagging.tag_ads(brand, limit, bool(body.get("retag"))))
    audit(user, "creative.tags.run", "creative_store", None, brand,
          f"Claude tagged {out['tagged']} ads")
    return out


@creative.patch("/tags/{ad_id}")
def patch_ad_tags(
    request: Request, ad_id: str, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Correct or confirm an ad's tags."""
    user, _who = _user(request)
    out = _call(lambda: {"tags": tagging.update_ad(brand, ad_id, body)})
    audit(user, "creative.tags.edit", "creative_store", None, brand, f"Edited tags of ad {ad_id}")
    return out


# ---------------------------------------------------------------------- outputs: variations, briefs
@creative.post("/ads/{ad_id}/variations")
def ad_variations(request: Request, ad_id: str, brand: str = "ridhi") -> dict[str, Any]:
    """Claude's variations of one of the store's own ads (usually a winner); not stored."""
    user, _who = _user(request)
    out = _call(lambda: generate.ad_variations(brand, ad_id))
    audit(user, "creative.ad_variations", "creative_store", None, brand,
          f"Asked Claude for variations of ad {ad_id}")
    return out


@creative.get("/concepts/{concept_id}/designer-briefs")
def designer_briefs(request: Request, concept_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """The designer briefs written for one saved concept, newest first."""
    require_perm(request, "view")
    return _call(lambda: service.briefs_for(brand, concept_id))


@creative.post("/concepts/{concept_id}/designer-brief")
def new_designer_brief(request: Request, concept_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """Claude writes a designer brief for one saved concept; kept as a draft."""
    user, who = _user(request)
    out = _call(lambda: generate.designer_brief(brand, concept_id, who))
    audit(user, "creative.designer_brief", "creative_store", None, brand,
          f"Claude wrote a designer brief for concept {concept_id}")
    return out


@creative.post("/briefs/{brief_id}/approve")
def approve_brief(request: Request, brief_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """Approve a draft designer brief (records who and when)."""
    user, who = _user(request)
    out = _call(lambda: {"brief": service.approve_brief(brand, brief_id, who)})
    audit(user, "creative.brief.approve", "creative_store", None, brand,
          f"Approved brief {brief_id}")
    return out
