"""Creative Strategist routes, mounted under /api/creative. Read-only for now: concepts and briefs
are produced, nothing is published.

Every route checks the `view` permission like the rest of Flowmerce. Errors the page can explain
come back with a `code`: 400 bad_request, 404 not_found, 503 for a Supabase problem.
`brand` is 'ridhi' or 'cpc' on every route.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Request

from ..seo.audit import audit
from ..seo.auth import require_perm
from ..seo.integrations.claude import ClaudeError
from ..seo.util import HttpError
from ..shipping.supabase import SupabaseError
from . import generate, service

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
                "db/central/115_ads.sql and 116_creative.sql first."
            )
        raise HttpError(_SUPABASE_STATUS.get(exc.state, 502), message, exc.state) from None


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value or default)))
    except (TypeError, ValueError):
        return default


@creative.get("/insights")
def insights(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """What the ads showed over the last `days` complete days: formats, hooks and platforms.

    Answers from sample ads while no ad platform is connected; `source` says which it was.
    """
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 0, 0, 400) or None
    return _call(lambda: service.findings(brand, days))


@creative.get("/trend")
def trend(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Day-by-day spend, CTR and ROAS over the last `days` complete days, for a chart."""
    require_perm(request, "view")
    days = _int(request.query_params.get("days"), 0, 0, 400) or None
    return _call(lambda: service.trend(brand, days))


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
