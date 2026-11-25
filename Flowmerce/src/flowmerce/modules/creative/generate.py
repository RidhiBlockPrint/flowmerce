"""Claude writes the creative: concepts with hooks, ad copy, carousel frames, Reel scripts, UGC
briefs and a one-variable test, plus fresh variations of a concept that already works.

It reuses SEO & Blog's Claude connection (the same ANTHROPIC_API_KEY and model) and the same daily
Claude limit (`seo/services/ai_budget.py`): a request that does not fit in what is left of today's
limit is refused before anything is sent, and every call is recorded with its cost under the kinds
"creative_pack" and "creative_variations".

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
PACK_VERSION = 1
MAX_CONCEPTS = 5
MAX_VARIATIONS = 5

_running: set[str] = set()
_lock = threading.Lock()


# ------------------------------------------------------------------------------------- storage
def _key(brand: str) -> str:
    return f"creative_pack:{brand}"


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


# ------------------------------------------------------------------------------------- the run
def _work(brand: str, by: str) -> None:
    """One creative pack, in a background thread. Never raises: the page reads the state."""
    try:
        findings = service.findings(brand)
        notes = _team_notes(brand)
        # High effort: the pack has to read a table of figures and then write for four formats.
        data, model = claude._structured(
            prompts.PACK_SYSTEM,
            prompts.pack_prompt(findings, brand, notes),
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
