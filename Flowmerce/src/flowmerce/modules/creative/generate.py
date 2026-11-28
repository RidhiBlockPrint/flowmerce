"""Claude writes the creative: concepts with hooks, ad copy, carousel frames, Reel scripts, UGC
briefs and a one-variable test, plus fresh variations of a concept that already works, plus
trend-based recommendations (what changed and what to do about it, not ad copy).

It reuses SEO & Blog's Claude connection (the same ANTHROPIC_API_KEY and model) and the same daily
Claude limit (`seo/services/ai_budget.py`): a request that does not fit in what is left of today's
limit is refused before anything is sent, and every call is recorded with its cost under the kinds
"creative_pack", "creative_variations" and "creative_recommendations".

What Claude sees: the figures from `insights.findings` for the period (formats, hooks and platforms
with their rates and whether each group has enough data), the brand's voice and claims files, and
the team's own notes. No customer data: the figures hold none.

What comes back is kept per store in the app's settings table (the local database), like CRO's
action plan, with the day it was made. Nothing is written to Supabase here: a concept is saved to
`creative.concept` only when the team chooses to keep it, which is a later task.

Claude runs in a background thread; the page reads `state` until it is "ready" or "failed". The
answer is cleaned before it is stored, so a model that ignores a length or an enum cannot put
unusable text on the page.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from ..seo.db import get, now, run
from ..seo.integrations import claude
from ..seo.services import ai_budget
from ..seo.util import HttpError
from . import prompts, service
from .config import store_for

log = logging.getLogger(__name__)

PACK_KIND = "creative_pack"
VARIATIONS_KIND = "creative_variations"
AD_VARIATIONS_KIND = "creative_ad_variations"
BRIEF_KIND = "creative_designer_brief"
RECS_KIND = "creative_recommendations"
PACK_VERSION = 2  # 2: reads the tag patterns and writes a Story per concept
RECS_VERSION = 1
MAX_CONCEPTS = 5
MAX_VARIATIONS = 5
MAX_RECOMMENDATIONS = 5

_running: set[str] = set()
_running_recs: set[str] = set()
_lock = threading.Lock()


# ------------------------------------------------------------------------------------- storage
def _key(brand: str) -> str:
    return f"creative_pack:{brand}"


def _key_recs(brand: str) -> str:
    return f"creative_recs:{brand}"


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


# ------------------------------------------------------------------------------------- cleaning
def _text(value: Any, limit: int) -> str:
    """One field as plain text, cut to a length the page can show."""
    return str(value or "").strip()[:limit]


def _lines(value: Any, limit: int, most: int) -> list[str]:
    """A list of short lines, empty ones dropped."""
    if not isinstance(value, list):
        return []
    out = [_text(v, limit) for v in value]
    return [line for line in out if line][:most]


def _one_of(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else fallback


def _int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def _obj(value: Any, name: str = "") -> dict[str, Any]:
    """One object out of Claude's answer, or an empty one when it is missing or the wrong type.

    With `name`, reads that field of `value`; without it, checks `value` itself.
    """
    if name:
        value = value.get(name) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else {}


def _formats(value: Any) -> dict[str, Any]:
    """The four production formats, each cleaned; a missing one comes back empty, not invented."""
    data = _obj(value)
    static = _obj(data, "static")
    reel = _obj(data, "reel")
    ugc = _obj(data, "ugc")
    frames: list[dict[str, Any]] = []
    for i, frame in enumerate(data.get("carousel") or [], start=1):
        if not isinstance(frame, dict):
            continue
        frames.append(
            {
                "frame": _int(frame.get("frame"), 1, 20, i),
                "visual": _text(frame.get("visual"), 300),
                "caption": _text(frame.get("caption"), 200),
            }
        )
    story_frames: list[dict[str, Any]] = []
    for i, frame in enumerate(_obj(data, "story").get("frames") or [], start=1):
        if not isinstance(frame, dict):
            continue
        story_frames.append(
            {
                "frame": _int(frame.get("frame"), 1, 10, i),
                "visual": _text(frame.get("visual"), 300),
                "on_screen_text": _text(frame.get("on_screen_text"), 150),
                "sticker": _text(frame.get("sticker"), 100),
            }
        )
    shots: list[dict[str, Any]] = []
    for i, shot in enumerate(reel.get("shots") or [], start=0):
        if not isinstance(shot, dict):
            continue
        shots.append(
            {
                "at_second": _int(shot.get("at_second"), 0, 120, i * 3),
                "visual": _text(shot.get("visual"), 300),
                "on_screen_text": _text(shot.get("on_screen_text"), 200),
            }
        )
    return {
        "static": {
            "headline": _text(static.get("headline"), 200),
            "primary_text": _text(static.get("primary_text"), 1000),
            "visual_note": _text(static.get("visual_note"), 400),
        },
        "carousel": frames[:6],
        "reel": {
            "length_seconds": _int(reel.get("length_seconds"), 5, 90, 20),
            "shots": shots[:8],
        },
        "story": {"frames": story_frames[:5]},
        "ugc": {
            "creator_brief": _text(ugc.get("creator_brief"), 1500),
            "talking_points": _lines(ugc.get("talking_points"), 200, 6),
            "do_not_say": _lines(ugc.get("do_not_say"), 200, 8),
        },
    }


def _test(value: Any) -> dict[str, Any]:
    """The one-variable test plan, with any value the rest of the code cannot use replaced."""
    data = _obj(value)
    return {
        "hypothesis": _text(data.get("hypothesis"), 600),
        "variable": _one_of(data.get("variable"), prompts.TEST_VARIABLES, "hook"),
        "variants": _lines(data.get("variants"), 200, 5),
        "success_metric": _one_of(data.get("success_metric"), prompts.SUCCESS_METRICS, "roas"),
    }


def clean_pack(data: dict[str, Any]) -> dict[str, Any]:
    """Claude's answer, cut to what the page can show and to the values the rest of the code
    expects. Anything unrecognised is dropped rather than passed on."""
    concepts = []
    for raw in (data.get("concepts") or [])[:MAX_CONCEPTS]:
        if not isinstance(raw, dict):
            continue
        concepts.append(
            {
                "title": _text(raw.get("title"), 200) or "Untitled concept",
                "hook": _text(raw.get("hook"), 300),
                "alternative_hooks": _lines(raw.get("alternative_hooks"), 300, 4),
                "angle": _text(raw.get("angle"), 500),
                "message": _text(raw.get("message"), 1000),
                "offer": _text(raw.get("offer"), 300),
                "funnel_stage": _one_of(raw.get("funnel_stage"), prompts.FUNNEL_STAGES, "tof"),
                "persona": _text(raw.get("persona"), 300),
                "evidence": _lines(raw.get("evidence"), 300, 5),
                "formats": _formats(raw.get("formats")),
                "test": _test(raw.get("test")),
            }
        )
    return {
        "summary": _text(data.get("summary"), 2000),
        "data_caveat": _text(data.get("data_caveat"), 1000),
        "concepts": concepts,
    }


def clean_variations(data: dict[str, Any]) -> dict[str, Any]:
    """Claude's variations, cleaned the same way."""
    out: list[dict[str, Any]] = []
    for raw in (data.get("variations") or [])[:MAX_VARIATIONS]:
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "label": _text(raw.get("label"), 100) or f"Variant {len(out) + 1}",
                "hook": _text(raw.get("hook"), 300),
                "what_changed": _text(raw.get("what_changed"), 500),
                "why": _text(raw.get("why"), 500),
            }
        )
    return {
        "variable": _one_of(data.get("variable"), prompts.TEST_VARIABLES, "hook"),
        "kept": _text(data.get("kept"), 600),
        "variations": out,
    }


def clean_recs(data: dict[str, Any]) -> dict[str, Any]:
    """Claude's recommendations, cleaned the same way as a pack."""
    out: list[dict[str, Any]] = []
    for raw in (data.get("recommendations") or [])[:MAX_RECOMMENDATIONS]:
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "title": _text(raw.get("title"), 200) or "Untitled recommendation",
                "diagnosis": _text(raw.get("diagnosis"), 400),
                "evidence": _lines(raw.get("evidence"), 300, 3),
                "action": _text(raw.get("action"), 300),
                "priority": _one_of(
                    raw.get("priority"), prompts.RECOMMENDATION_PRIORITIES, "medium"
                ),
            }
        )
    order = {p: i for i, p in enumerate(prompts.RECOMMENDATION_PRIORITIES)}
    out.sort(key=lambda r: order.get(r["priority"], 99))
    return {"summary": _text(data.get("summary"), 1000), "recommendations": out}


# ------------------------------------------------------------------------------------- the run
def _work(brand: str, by: str) -> None:
    """One creative pack, in a background thread. Never raises: the page reads the state."""
    try:
        findings = service.findings(brand)
        notes = _team_notes(brand)
        patterns = _patterns(brand)
        # High effort: the pack has to read a table of figures and then write for five formats.
        data, model = claude._structured(
            prompts.PACK_SYSTEM,
            prompts.pack_prompt(findings, brand, notes, patterns),
            prompts.PACK_SCHEMA,
            "high",
            max_tokens=32000,
        )
        cost = ai_budget.record(claude.take_usage(), brand, PACK_KIND)
        _write(
            _key(brand),
            {
                "version": PACK_VERSION,
                "status": "ready",
                "day": ai_budget.today(),
                "generated_at": now(),
                "by": by,
                "model": model,
                "cost_usd": cost,
                "source": findings.get("source"),
                "from": findings.get("from"),
                "to": findings.get("to"),
                "pack": clean_pack(data),
            },
        )
    except claude.ClaudeError as e:
        # A call that ran is paid for even when its answer cannot be used.
        ai_budget.record(claude.take_usage(), brand, PACK_KIND)
        _fail(brand, str(e))
    except HttpError as e:
        _fail(brand, e.message)
    except Exception as e:  # noqa: BLE001 — background thread boundary; shown on the page
        log.exception("Creative pack for %s failed", brand)
        _fail(brand, f"Unexpected error: {type(e).__name__}")
    finally:
        with _lock:
            _running.discard(brand)


def _patterns(brand: str) -> dict[str, Any] | None:
    """The tag patterns for the default period, or None when they cannot be read (tables not set
    up yet, nothing tagged): the pack is still written from the format and hook figures alone."""
    try:
        return service.creative_patterns(brand)
    except Exception:  # noqa: BLE001 - optional context, never a reason to fail the pack
        log.info("Creative pack for %s: tag patterns not available", brand, exc_info=True)
        return None


def _team_notes(brand: str) -> str:
    """The team's notes about the store, which CRO already keeps. Empty when CRO has none."""
    try:
        from ..cro.ai_advice import notes as cro_notes

        return str(cro_notes(brand).get("text") or "")
    except Exception:  # noqa: BLE001 — notes are optional context, never a reason to fail
        return ""


def _fail(brand: str, message: str) -> None:
    """Record a failure without throwing away a pack that was already made."""
    prev = _read(_key(brand))
    _write(
        _key(brand),
        {
            **prev,
            "status": "failed" if not prev.get("pack") else "ready",
            "error": message,
            "failed_at": now(),
        },
    )


def state(brand: str) -> dict[str, Any]:
    """The kept pack for a store, whether a new one is being written, and the Claude limit."""
    store_for(brand)  # raises for an unknown brand
    saved = _read(_key(brand))
    with _lock:
        running = brand in _running
    return {
        "brand": brand,
        "configured": claude.configured(),
        "status": "running" if running else saved.get("status", "none"),
        "day": saved.get("day"),
        "fresh": saved.get("day") == ai_budget.today()
        and saved.get("version", 0) >= PACK_VERSION,
        "generated_at": saved.get("generated_at"),
        "by": saved.get("by"),
        "model": saved.get("model"),
        "cost_usd": saved.get("cost_usd"),
        "source": saved.get("source"),
        "from": saved.get("from"),
        "to": saved.get("to"),
        "pack": saved.get("pack"),
        "error": saved.get("error")
        if saved.get("failed_at", "") >= saved.get("generated_at", "")
        else None,
        "estimate_usd": ai_budget.ESTIMATE_USD.get(PACK_KIND),
        "budget": ai_budget.status(),
    }


def start(brand: str, by: str) -> dict[str, Any]:
    """Ask Claude for a new creative pack in the background.

    Unlike CRO's action plan this never runs by itself when a page opens: creative is asked for when
    somebody wants it, so nothing is spent on a page visit.
    """
    store_for(brand)
    if not claude.configured():
        raise HttpError(
            412,
            "ANTHROPIC_API_KEY is not set on the server, so Claude cannot write the creative.",
            "pending_setup",
        )
    with _lock:
        if brand in _running:
            return state(brand)
        ai_budget.check(PACK_KIND)  # 429 daily_limit: nothing is sent to Claude
        _running.add(brand)
    threading.Thread(
        target=_work, args=(brand, by), name=f"creative-pack-{brand}", daemon=True
    ).start()
    return state(brand)


# ------------------------------------------------------------------------------- recommendations
def _work_recs(brand: str, by: str) -> None:
    """One round of trend recommendations, in a background thread."""
    try:
        trend = service.trend(brand)
        findings = service.findings(brand)
        notes = _team_notes(brand)
        data, model = claude._structured(
            prompts.RECS_SYSTEM,
            prompts.recs_prompt(trend, findings, brand, notes),
            prompts.RECS_SCHEMA,
            "medium",
            max_tokens=6000,
        )
        cost = ai_budget.record(claude.take_usage(), brand, RECS_KIND)
        _write(
            _key_recs(brand),
            {
                "version": RECS_VERSION,
                "status": "ready",
                "day": ai_budget.today(),
                "generated_at": now(),
                "by": by,
                "model": model,
                "cost_usd": cost,
                "source": findings.get("source"),
                "from": findings.get("from"),
                "to": findings.get("to"),
                "recs": clean_recs(data),
            },
        )
    except claude.ClaudeError as e:
        ai_budget.record(claude.take_usage(), brand, RECS_KIND)
        _fail_recs(brand, str(e))
    except HttpError as e:
        _fail_recs(brand, e.message)
    except Exception as e:  # noqa: BLE001 — background thread boundary; shown on the page
        log.exception("Creative recommendations for %s failed", brand)
        _fail_recs(brand, f"Unexpected error: {type(e).__name__}")
    finally:
        with _lock:
            _running_recs.discard(brand)


def _fail_recs(brand: str, message: str) -> None:
    """Record a failure without throwing away recommendations that were already made."""
    prev = _read(_key_recs(brand))
    _write(
        _key_recs(brand),
        {
            **prev,
            "status": "failed" if not prev.get("recs") else "ready",
            "error": message,
            "failed_at": now(),
        },
    )


def state_recs(brand: str) -> dict[str, Any]:
    """The kept recommendations for a store, whether new ones are being written, and the limit."""
    store_for(brand)
    saved = _read(_key_recs(brand))
    with _lock:
        running = brand in _running_recs
    return {
        "brand": brand,
        "configured": claude.configured(),
        "status": "running" if running else saved.get("status", "none"),
        "day": saved.get("day"),
        "fresh": saved.get("day") == ai_budget.today()
        and saved.get("version", 0) >= RECS_VERSION,
        "generated_at": saved.get("generated_at"),
        "by": saved.get("by"),
        "model": saved.get("model"),
        "cost_usd": saved.get("cost_usd"),
        "source": saved.get("source"),
        "from": saved.get("from"),
        "to": saved.get("to"),
        "recs": saved.get("recs"),
        "error": saved.get("error")
        if saved.get("failed_at", "") >= saved.get("generated_at", "")
        else None,
        "estimate_usd": ai_budget.ESTIMATE_USD.get(RECS_KIND),
        "budget": ai_budget.status(),
    }


def start_recs(brand: str, by: str) -> dict[str, Any]:
    """Ask Claude for a new round of trend recommendations in the background."""
    store_for(brand)
    if not claude.configured():
        raise HttpError(
            412,
            "ANTHROPIC_API_KEY is not set on the server, so Claude cannot write recommendations.",
            "pending_setup",
        )
    with _lock:
        if brand in _running_recs:
            return state_recs(brand)
        ai_budget.check(RECS_KIND)  # 429 daily_limit: nothing is sent to Claude
        _running_recs.add(brand)
    threading.Thread(
        target=_work_recs, args=(brand, by), name=f"creative-recs-{brand}", daemon=True
    ).start()
    return state_recs(brand)


# ------------------------------------------------------------------------------------ variations
def variations(brand: str, concept: dict[str, Any]) -> dict[str, Any]:
    """Fresh variations of one concept, in the caller's own request (not a background job).

    Returned, not stored: the team reads them, then chooses what to test.
    """
    store_for(brand)
    if not claude.configured():
        raise HttpError(
            412,
            "ANTHROPIC_API_KEY is not set on the server, so Claude cannot write variations.",
            "pending_setup",
        )
    if not isinstance(concept, dict) or not str(concept.get("title") or concept.get("hook") or ""):
        raise service.InputError("Send the concept to vary, with at least a title or a hook.")
    ai_budget.check(VARIATIONS_KIND)
    findings = service.findings(brand)
    data, model = claude._structured(
        prompts.VARIATIONS_SYSTEM,
        prompts.variations_prompt(concept, findings, brand),
        prompts.VARIATIONS_SCHEMA,
        "medium",
        max_tokens=8000,
    )
    cost = ai_budget.record(claude.take_usage(), brand, VARIATIONS_KIND)
    return {
        "brand": brand,
        "model": model,
        "cost_usd": cost,
        "source": findings.get("source"),
        **clean_variations(data),
    }


# ------------------------------------------------------------------------ variations of an ad
def _need_claude(what: str) -> None:
    if not claude.configured():
        raise HttpError(
            412,
            f"ANTHROPIC_API_KEY is not set on the server, so Claude cannot write {what}.",
            "pending_setup",
        )


def ad_variations(brand: str, ad_id: str) -> dict[str, Any]:
    """Fresh variations of one of the store's own ads (usually a winner), in the caller's request.

    The ad's copy, tags and figures come from the same patterns the page shows. Returned, not
    stored: the team picks a variation and saves it as a concept if it wants to keep it.
    """
    from . import products

    store_for(brand)
    _need_claude("variations")
    patterns = service.creative_patterns(brand)
    ad = next((a for a in patterns.get("ads") or [] if str(a.get("adId")) == str(ad_id)), None)
    if ad is None:
        raise products.NotFoundError(f"Ad {ad_id!r} did not deliver in the period for {brand}.")
    ai_budget.check(AD_VARIATIONS_KIND)
    data, model = claude._structured(
        prompts.VARIATIONS_SYSTEM,
        prompts.ad_variations_prompt(ad, patterns, brand),
        prompts.VARIATIONS_SCHEMA,
        "medium",
        max_tokens=8000,
    )
    cost = ai_budget.record(claude.take_usage(), brand, AD_VARIATIONS_KIND)
    return {
        "brand": brand,
        "adId": str(ad_id),
        "adName": ad.get("name"),
        "verdict": ad.get("verdict"),
        "model": model,
        "cost_usd": cost,
        "source": patterns.get("source"),
        **clean_variations(data),
    }


# ------------------------------------------------------------------------------ designer brief
def clean_brief(data: dict[str, Any]) -> dict[str, Any]:
    """Claude's designer brief, cut to lengths the page and a message can carry."""
    sizes = [s for s in (data.get("sizes") or []) if s in prompts.BRIEF_SIZES]
    return {
        "objective": _text(data.get("objective"), 400),
        "sizes": list(dict.fromkeys(sizes)) or ["9:16"],
        "product": _text(data.get("product"), 300),
        "print_color": _text(data.get("print_color"), 300),
        "visual_direction": _text(data.get("visual_direction"), 800),
        "reference": _text(data.get("reference"), 400),
        "on_screen_text": _lines(data.get("on_screen_text"), 120, 6),
        "must_say": _lines(data.get("must_say"), 200, 6),
        "must_not_say": _lines(data.get("must_not_say"), 200, 8),
        "deliverables": _lines(data.get("deliverables"), 200, 8),
    }


def brief_to_markdown(concept: dict[str, Any], brief: dict[str, Any]) -> str:
    """The cleaned brief as markdown, ready to paste into a message to a designer or editor."""

    def bullets(items: list[str]) -> list[str]:
        return [f"- {i}" for i in items] or ["- (none)"]

    lines = [
        f"# Designer brief: {concept.get('title') or 'Untitled concept'}",
        "",
        f"**Objective:** {brief['objective']}",
        f"**Sizes:** {', '.join(brief['sizes'])}",
        f"**Product:** {brief['product'] or '(not product specific)'}",
        f"**Print and color:** {brief['print_color'] or '(open)'}",
        "",
        "## Hook",
        f"> {concept.get('hook') or '(hook not set)'}",
        "",
        "## Visual direction",
        brief["visual_direction"] or "(not set)",
        "",
        "## Reference: what already works",
        brief["reference"] or "(no winner yet)",
        "",
        "## Words on screen",
        *bullets(brief["on_screen_text"]),
        "",
        "## Must say",
        *bullets(brief["must_say"]),
        "",
        "## Must not say",
        *bullets(brief["must_not_say"]),
        "",
        "## Deliverables",
        *bullets(brief["deliverables"]),
    ]
    return "\n".join(lines)


def designer_brief(brand: str, concept_id: int, by: str) -> dict[str, Any]:
    """Claude writes a designer brief for one saved concept; it is kept in creative.brief as a
    draft that somebody approves. Runs in the caller's request (one medium-effort call)."""
    from . import products

    store = store_for(brand)
    products.require_live("Writing a designer brief")
    _need_claude("a designer brief")
    concept = service.concept_row(brand, concept_id)
    patterns = _patterns(brand)
    try:
        product_rows = [p for p in products.listing(brand) if p.get("source")]
    except Exception:  # noqa: BLE001 - product context is optional for a brief
        product_rows = []
    ai_budget.check(BRIEF_KIND)
    try:
        data, model = claude._structured(
            prompts.DESIGNER_BRIEF_SYSTEM,
            prompts.designer_brief_prompt(concept, patterns, product_rows, brand),
            prompts.DESIGNER_BRIEF_SCHEMA,
            "medium",
            max_tokens=8000,
        )
    finally:
        cost = ai_budget.record(claude.take_usage(), brand, BRIEF_KIND)
    brief = clean_brief(data)
    row = service.save_brief(
        store,
        concept_id,
        brief_to_markdown(concept, brief),
        {**brief, "model": model},
        by,
    )
    return {"brand": brand, "cost_usd": cost, "brief": row}
