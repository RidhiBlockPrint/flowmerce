"""Automatic featured images: Claude's prompt -> an image API -> Shopify Files -> the article's featured image.
Owner request 2026-11-23: "a fully automated system" on top of the image prompts (services/image_prompts.py).

For each article whose prompt is ready (when this is switched on and an image API key is set, integrations/image_gen.py):
  1. The reference product photos the prompt names are downloaded (small copies) and sent with the prompt.
  2. The picture comes back and goes straight to the store's Shopify Files (needs the Shopify scope write_files),
     so nothing is kept on this server.
  3. Print check: when the picture shows real products, Claude compares it with their photos (about $0.04). If the print
     was changed or the picture looks fake, it is made once more; if the second one also fails, it is kept but NOT used,
     and the editor shows why, for a person to decide.
  4. It becomes the featured image only of an article that is still being written (idea, draft, changes requested).
     An article in review, approved, scheduled or live keeps its image: the new one waits in the editor ("Use this image"),
     because changing it would void the approval or change a live page.
  5. Optionally a tall Pinterest picture is made too (setting "pins"); it is stored, never attached.

Automatic blogs (services/autopilot.py) wait for this step before they are approved and saved as hidden Shopify drafts,
for at most WAIT_MINUTES; then they go ahead with the product photo picked as before.

Spending limits: at most `dailyLimit` pictures a day and `monthlyUsd` a month (image API costs are estimates per picture,
see image_gen.COST_USD), kept in table image_generations. Claude's print check counts against the Claude budget."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..audit import audit
from ..db import Row, all_rows, get, now, run
from ..integrations import claude, image_gen, shopify
from ..util import HttpError, s
from . import ai_budget
from .brands import brand, brand_settings

log = logging.getLogger(__name__)

SETTINGS_KEY = "image_generation"
DEFAULTS: dict[str, Any] = {"enabled": True, "pins": False, "check": True, "dailyLimit": 10, "monthlyUsd": 25.0}
MAX_DAILY = 100
MAX_MONTHLY_USD = 200.0
AUTO_ATTACH = ("idea", "draft", "changes_requested")
MAX_TRIES = 2          # pictures made per article before a failed print check is left to a person
MAX_ERRORS = 3         # failed requests (network, rate limit) before the step gives up
WAIT_MINUTES = 45      # how long an automatic blog waits for its picture
SCOPE_HELP = ("Shopify needs the write_files permission to store pictures. In Shopify admin open Settings, Apps and sales channels, "
              "Develop apps, the Flowmerce app, Configuration: tick write_files under Admin API scopes, save and reinstall the app.")


def _in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- settings and spending

def settings() -> dict[str, Any]:
    row = get("SELECT value_json FROM app_settings WHERE key = ?", SETTINGS_KEY)
    try:
        saved = json.loads(row["value_json"]) if row else {}
    except ValueError:
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in (saved if isinstance(saved, dict) else {}).items() if k in DEFAULTS}}


def update_settings(user: dict, patch: dict) -> dict[str, Any]:
    cur = settings()
    for k in ("enabled", "pins", "check"):
        if k in patch:
            cur[k] = bool(patch[k])
    if "dailyLimit" in patch:
        try:
            cur["dailyLimit"] = max(0, min(MAX_DAILY, int(patch["dailyLimit"])))
        except (TypeError, ValueError):
            raise HttpError(400, "dailyLimit must be a whole number.") from None
    if "monthlyUsd" in patch:
        try:
            cur["monthlyUsd"] = round(max(0.0, min(MAX_MONTHLY_USD, float(patch["monthlyUsd"]))), 2)
        except (TypeError, ValueError):
            raise HttpError(400, "monthlyUsd must be a number of US dollars.") from None
    run("""INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        SETTINGS_KEY, json.dumps(cur), now(), user["id"])
    audit(user, "image_generation.settings", "app_settings", SETTINGS_KEY, "", json.dumps(cur))
    from . import image_prompts
    image_prompts.wake()
    return cur


def active() -> bool:
    return bool(settings()["enabled"]) and image_gen.configured()


def spending() -> dict[str, Any]:
    day = ai_budget.today()
    t = get("SELECT COUNT(*) n, COALESCE(SUM(cost_usd), 0) usd FROM image_generations WHERE day = ?", day) or {"n": 0, "usd": 0}
    m = get("SELECT COALESCE(SUM(cost_usd), 0) usd FROM image_generations WHERE day >= ?", day[:8] + "01") or {"usd": 0}
    return {"today": int(t["n"]), "todayUsd": round(float(t["usd"]), 3), "monthUsd": round(float(m["usd"]), 3)}


def room() -> bool:
    st, sp = settings(), spending()
    return sp["today"] < st["dailyLimit"] and sp["monthUsd"] + image_gen.cost_estimate() <= st["monthlyUsd"]


def _record(brand_id: str, article_id: int, kind: str, ok: bool, error: str | None = None) -> float:
    cost = image_gen.cost_estimate() if ok else 0.0
    run("""INSERT INTO image_generations (ts, day, brand_id, article_id, kind, provider, model, ok, cost_usd, error) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        now(), ai_budget.today(), brand_id, article_id, kind, image_gen.provider() or "", image_gen.model(), 1 if ok else 0, cost, s(error, 300) if error else None)
    return cost


# ---------------------------------------------------------------- queueing

def queue(article_id: int, priority_note: str = "") -> bool:
    """Ask for a picture for an article whose prompt is ready. Does nothing when switched off or without an image key."""
    if not active():
        return False
    n = run("""UPDATE image_prompts SET image_status = 'queued', image_attempts = 0, image_error = NULL, image_next_at = NULL, image_updated_at = ?
               WHERE article_id = ? AND status = 'ready' AND prompt != '' AND image_status != 'working'""", now(), article_id).changes
    if n and priority_note:
        log.info("Picture queued for article %s (%s)", article_id, priority_note)
    return bool(n)


def request(user: dict, article_id: int) -> dict:
    """A person asks for a (new) picture from the editor."""
    from . import image_prompts
    if not image_gen.configured():
        raise HttpError(412, image_gen.status()["setup"], "pending_setup")
    p = get("SELECT status, image_status FROM image_prompts WHERE article_id = ?", article_id)
    if not p or p["status"] != "ready":
        raise HttpError(409, "The image prompt is not ready yet.", "no_prompt")
    if p["image_status"] == "working":
        raise HttpError(409, "A picture for this article is being made right now.", "busy")
    run("""UPDATE image_prompts SET image_status = 'queued', image_attempts = 0, image_error = NULL, image_next_at = NULL, image_updated_at = ?
           WHERE article_id = ?""", now(), article_id)
    audit(user, "image_generation.request", "article", article_id, "", "")
    image_prompts.wake()
    return image_prompts.state(article_id)


def use_image(user: dict, article_id: int) -> dict:
    """A person makes the generated picture the article's featured image (the normal save path: a new version)."""
    from . import articles, image_prompts
    p = get("SELECT image_url, alt_text FROM image_prompts WHERE article_id = ?", article_id)
    if not p or not p["image_url"]:
        raise HttpError(409, "There is no generated picture for this article yet.", "no_image")
    articles.save_article(user, article_id, {"image_url": p["image_url"], "image_alt": p["alt_text"]}, note="Featured image: AI picture chosen by a person")
    run("UPDATE image_prompts SET image_attached = 1 WHERE article_id = ?", article_id)
    return image_prompts.state(article_id)


def still_working(article_id: int, since: str) -> bool:
    """For an automatic blog: True while its prompt or picture is still being made and WAIT_MINUTES have not passed."""
    p = get("SELECT status, image_status FROM image_prompts WHERE article_id = ?", article_id)
    if not p:
        return False
    busy = p["status"] in ("queued", "working") or (p["status"] == "ready" and p["image_status"] in ("queued", "working"))
    if not busy:
        return False
    started = datetime.fromisoformat(since.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - started < timedelta(minutes=WAIT_MINUTES)


# ---------------------------------------------------------------- making one picture

def _download(url: str) -> tuple[bytes, str]:
    import httpx
    from .image_prompts import small
    r = httpx.get(small(url, 1024), timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    return r.content, mime if mime.startswith("image/") else "image/jpeg"


def _set(article_id: int, **cols: Any) -> None:
    cols["image_updated_at"] = now()
    run(f"UPDATE image_prompts SET {', '.join(f'{k} = ?' for k in cols)} WHERE article_id = ?", *cols.values(), article_id)


def _error(p: Row, message: str, retryable: bool) -> str:
    if retryable and p["image_attempts"] < MAX_ERRORS:
        _set(p["article_id"], image_status="queued", image_error=s(message, 500), image_next_at=_in(120 * p["image_attempts"]))
        return "retry"
    _set(p["article_id"], image_status="failed", image_error=s(message, 500), image_next_at=None)
    return "failed"


def _check(a: Row, refs: list[dict], url: str) -> dict[str, Any]:
    """Claude's print check. Returns {faithful, looks_real, problems} or {skipped: reason}."""
    from .image_prompts import small
    if not refs:
        return {"skipped": "No product in the picture, so there is no print to compare."}
    if not settings()["check"]:
        return {"skipped": "The print check is switched off."}
    try:
        ai_budget.check("image_check")
        try:
            data, _m = claude.image_check(brand(a["brand_id"]), brand_settings(a["brand_id"]),
                                          [{"url": small(r["url"]), "title": r["title"]} for r in refs], small(url))
        finally:
            ai_budget.record(claude.take_usage(), a["brand_id"], "image_check")
    except (claude.ClaudeError, HttpError) as e:
        return {"skipped": f"The print check could not run: {getattr(e, 'message', None) or e}"}
    return {"faithful": bool(data.get("faithful")), "looks_real": bool(data.get("looks_real")), "problems": s(data.get("problems"), 400)}


def process_next() -> str:
    """Make the next queued picture. Returns "done", "retry", "failed", "wait" (a limit is reached) or "empty"."""
    if not active():
        return "empty"
    rows = all_rows("""SELECT * FROM image_prompts WHERE status = 'ready' AND image_status = 'queued' AND (image_next_at IS NULL OR image_next_at <= ?)
                       AND brand_id NOT IN (SELECT brand_id FROM automation_state WHERE paused = 1)
                       ORDER BY priority, image_updated_at LIMIT 1""", now())
    if not rows:
        return "empty"
    p = rows[0]
    if not room():
        return "wait"
    if run("UPDATE image_prompts SET image_status = 'working', image_attempts = image_attempts + 1, image_updated_at = ? WHERE article_id = ? AND image_status = 'queued'",
           now(), p["article_id"]).changes != 1:
        return "retry"
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", p["article_id"])
    a = get("SELECT * FROM articles WHERE id = ?", p["article_id"])
    if not a:
        return "done"
    b = brand(a["brand_id"])
    from .image_prompts import FORMAT
    f = FORMAT[a["brand_id"]]
    refs = json.loads(p["references_json"] or "[]")
    try:
        photos = [_download(r["url"]) for r in refs[:2]]
    except Exception as e:  # noqa: BLE001 - any download problem is reported on the article
        return _error(p, f"A reference photo could not be downloaded ({type(e).__name__}).", True)
    try:
        data, mime = image_gen.generate(p["prompt"], photos, f["ratio"], f["width"], f["height"])
    except image_gen.ImageGenError as e:
        _record(a["brand_id"], a["id"], "banner", False, str(e))
        return _error(p, str(e), e.retryable)
    del photos
    _record(a["brand_id"], a["id"], "banner", True)
    ext = "png" if "png" in mime else "webp" if "webp" in mime else "jpg"
    name = p["file_name"].rsplit(".", 1)[0] + f".{ext}"
    try:
        url = shopify.upload_image(b, data, name, mime, p["alt_text"])
    except shopify.MissingScope:
        return _error(p, SCOPE_HELP, False)
    except RuntimeError as e:
        return _error(p, f"Shopify did not store the picture: {e}", True)
    finally:
        del data
    chk = _check(a, refs, url)
    bad = "skipped" not in chk and not (chk["faithful"] and chk["looks_real"])
    if bad and p["image_attempts"] < MAX_TRIES:
        _set(a["id"], image_status="queued", image_url=url, image_check_json=json.dumps(chk), image_next_at=None,
             image_error=f"The first picture did not pass the print check ({chk['problems'] or 'print differs'}); making another.")
        return "retry"
    pin_url = ""
    if settings()["pins"] and p["pin_prompt"]:
        pin_url = _make_pin(a, p, refs)
    error = None
    if bad:
        error = f"The picture did not pass the print check twice ({chk['problems'] or 'print differs'}). It is kept here but not used; a person should decide."
    elif "skipped" in chk and refs:
        error = f"Not checked: {chk['skipped']} It is kept here but not used; a person should look at it first."
    _set(a["id"], image_status="ready", image_url=url, pin_image_url=pin_url, image_check_json=json.dumps(chk), image_error=error, image_next_at=None)
    if not error:
        _attach(a, url, p["alt_text"])
    return "done"


def _make_pin(a: Row, p: Row, refs: list[dict]) -> str:
    """The tall Pinterest picture. Never attached; a failure is logged and leaves the banner alone."""
    from .image_prompts import PIN
    if not room():
        return ""
    try:
        photos = [_download(r["url"]) for r in refs[:2]]
        data, mime = image_gen.generate(p["pin_prompt"], photos, PIN["ratio"], 1024, 1536)
        _record(a["brand_id"], a["id"], "pin", True)
        return shopify.upload_image(brand(a["brand_id"]), data, p["file_name"].rsplit(".", 1)[0] + "-pin.jpg", mime, p["alt_text"])
    except Exception as e:  # noqa: BLE001
        log.info("Pinterest picture not made for article %s: %s", a["id"], e)
        return ""


def _attach(a: Row, url: str, alt: str) -> None:
    """Make the picture the featured image, but only while the article is still being written (see the module doc)."""
    from . import articles
    cur = get("SELECT status FROM articles WHERE id = ?", a["id"])
    if not cur or cur["status"] not in AUTO_ATTACH:
        return
    try:
        articles.save_article(None, a["id"], {"image_url": url, "image_alt": alt}, note=f"Featured image made by AI ({image_gen.model()})")
    except HttpError as e:
        log.info("AI picture not attached to article %s: %s", a["id"], e.message)
        return
    run("UPDATE image_prompts SET image_attached = 1 WHERE article_id = ?", a["id"])


# ---------------------------------------------------------------- what the dashboard sees

def state_part(p: Row | None) -> dict[str, Any]:
    gen = {"configured": image_gen.configured(), "active": active(), "providerName": image_gen.status()["providerName"], "model": image_gen.model()}
    if not p:
        return {"image": {"status": "none"}, "generation": gen}
    try:
        chk = json.loads(p["image_check_json"] or "{}")
    except ValueError:
        chk = {}
    return {"image": {"status": p["image_status"] or "none", "url": p["image_url"], "pinUrl": p["pin_image_url"], "attached": bool(p["image_attached"]),
                      "check": chk, "error": p["image_error"], "attempts": p["image_attempts"], "updatedAt": p["image_updated_at"]}, "generation": gen}


def summary_part() -> dict[str, Any]:
    return {"generation": {**image_gen.status(), "settings": settings(), "spending": spending(), "active": active()}}
