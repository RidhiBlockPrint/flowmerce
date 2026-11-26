"""AI image prompts for blog featured images. Owner request 2026-11-23.

For each article Flowmerce writes ONE prompt that a person pastes into any AI image tool. We recommend Google Gemini
(Nano Banana Pro) because it keeps a real product photo most faithfully when one is attached; ChatGPT Images works too.
The person then uploads the finished picture with the editor's "From your computer" option (services/images.py).

How a prompt is made:
  1. The brand's visual style. Once per brand (and again after STYLE_MAX_AGE_DAYS), Claude looks at photos the store
     already uses (live blog banners and product photos) and describes their light, palette, surfaces, props,
     composition and mood. Kept in app_settings under "image_style:<brand>".
  2. The article's prompt. Claude reads the article (title, keyword, summary, section headings, opening), the visual
     style, up to MAX_PRODUCT_PHOTOS matching product photos (it may pick at most 2 as references) and the concepts
     already used for the brand's other articles, which it must not repeat. So every article gets its own picture.
  3. Flowmerce adds the fixed part itself: the exact size for the brand's Shopify theme (FORMAT), the instruction to
     attach the reference photos, and what the image must not contain. Claude's answer can never change those.

When it runs: automatically for every article written from FEATURE_START on (Claude drafts and articles people write
in Flowmerce, once they have MIN_WORDS words), when a person asks in the editor, and for older drafts and live blogs
when a person starts "Create prompts for past articles". A backfill item only runs when today's Claude limit still has
room for one automatic blog, so old articles never hold up new ones. Work happens one article at a time in a background
thread; photos are passed to Claude by link, so this server never loads them (the hosted app has 512 MB).

The brand rule kept everywhere (Ridhi's master brief): a real product may only appear from its real photo as a
reference, and a generated picture is never presented as a photograph of the actual item."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..audit import audit
from ..config import is_brand
from ..db import Row, all_rows, get, now, run
from ..integrations import claude
from ..util import HttpError, s, similarity, slugify, strip_html
from . import ai_budget
from .brands import brand, brand_settings

log = logging.getLogger(__name__)

FEATURE_START = "2026-11-23"   # articles created from this day on get a prompt by themselves; older ones by backfill
MIN_WORDS = 150                # an article with fewer words has too little to picture yet
MAX_PRODUCT_PHOTOS = 4
STYLE_PHOTOS = 12
STYLE_MAX_AGE_DAYS = 60
USED_CONCEPTS = 30
MAX_ATTEMPTS = 3
STALE_MINUTES = 15
WAIT_SECONDS = 300             # how long the worker rests when today's limit has no room

# The featured image size each brand's live Shopify theme shows, measured on the storefronts on 2026-11-23.
# If a theme or its blog settings change, change this too.
FORMAT: dict[str, dict[str, Any]] = {
    "ridhi": {"shape": "square", "ratio": "1:1", "width": 2048, "height": 2048, "preview": "1 / 1",
              "safe": "Keep the focal point inside the middle half of the height: social media link previews crop the picture to a wide strip.",
              "theme": "Yuva theme: blog cards and the article banner show the image at its own shape, and most posts are square, "
                       "so a square image keeps the blog grid even."},
    "cpc": {"shape": "landscape", "ratio": "4:3", "width": 2400, "height": 1800, "preview": "4 / 3",
            "safe": "Keep the focal point inside the middle 60% of the height: the article banner trims a little from the top and bottom, "
                    "and social media link previews crop to a wide strip.",
            "theme": "Nimbus theme: blog cards crop to 4:3 and the article banner and featured post crop to 10:7, from the centre."},
}
# The tall Pinterest pin made beside every banner (Pinterest's recommended 2:3 shape).
PIN = {"shape": "portrait", "ratio": "2:3", "width": 1000, "height": 1500,
       "safe": "Leave calm, uncluttered space in the top quarter, where a title can be added later in Canva or Pinterest."}
TOOL = {"name": "Google Gemini (Nano Banana Pro)", "also": "ChatGPT Images or any other tool that accepts a reference photo",
        "why": "It keeps an attached product photo's print and colours most faithfully."}

SCOPES = {
    "drafts": ("idea", "draft", "in_review", "changes_requested", "approved", "publish_requested", "scheduled", "failed"),
    "published": ("published",),
}
SCOPES["all"] = SCOPES["drafts"] + SCOPES["published"]
STATUSES = ("queued", "working", "ready", "failed")

_lock = threading.Lock()
_thread: threading.Thread | None = None
_rest_until = 0.0
_recovered = False
_enabled = False               # set by start(), when the server's AI job runner starts; tests drive process_next() themselves


# ---------------------------------------------------------------- small helpers

def _in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def words(html: str) -> int:
    return len(strip_html(html or "").split())


def small(url: str, width: int = 800) -> str:
    """A Shopify CDN image at `width` pixels: Claude needs no more to see it, and a smaller picture costs fewer tokens."""
    if not url or not ("cdn.shopify.com" in url or "/cdn/shop/" in url):
        return url
    url = re.sub(r"([?&])width=\d+&?", r"\1", url).rstrip("?&")
    return f"{url}{'&' if '?' in url else '?'}width={width}"


def format_line(brand_id: str) -> str:
    f = FORMAT[brand_id]
    return f"{f['shape']} {f['ratio']}, {f['width']} × {f['height']} pixels"


def compose(brand_id: str, scene: str, refs: list[dict], pin: bool = False) -> str:
    """The prompt a person copies: Claude's scene, then the fixed part Flowmerce owns (references, size, exclusions).
    pin=True: the tall Pinterest version."""
    f = PIN if pin else FORMAT[brand_id]
    parts = [scene.strip(), ""]
    if refs:
        names = " and ".join(f"“{r['title']}”" for r in refs)
        one = len(refs) == 1
        parts += [f"Reference photo{'' if one else 's'}: attach the {'photo' if one else f'{len(refs)} photos'} of {names} that {'comes' if one else 'come'} with this prompt. "
                  f"Show {'that product' if one else 'those products'} exactly as in the reference: the same block-print pattern, colours, "
                  "scale of the print and proportions. Do not redraw, simplify or change the print. Use the photo only for the product "
                  "itself: the room, styling, camera angle and composition come from the description above, not from the photo.", ""]
    parts += [f"Format: a {f['shape']} image, aspect ratio {f['ratio']}, {f['width']} × {f['height']} pixels. "
              f"If the tool offers only preset shapes, choose {f['ratio']}. {f['safe']}",
              "It must look like a real photograph taken with a good camera: natural textures, true-to-life colour, no illustration, "
              "cartoon, 3D render or plastic AI sheen.",
              "Do not include any words, letters, numbers, logos, watermarks, borders, frames or collage panels."]
    return "\n".join(parts).strip()


# ---------------------------------------------------------------- the brand's visual style

def _style_key(brand_id: str) -> str:
    return f"image_style:{brand_id}"


def style_of(brand_id: str) -> dict | None:
    row = get("SELECT value_json, updated_at FROM app_settings WHERE key = ?", _style_key(brand_id))
    if not row:
        return None
    try:
        v = json.loads(row["value_json"])
    except ValueError:
        return None
    return v if isinstance(v, dict) and v.get("style") else None


def _style_stale(st: dict | None) -> bool:
    if not st or not st.get("builtAt"):
        return True
    built = datetime.fromisoformat(st["builtAt"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - built > timedelta(days=STYLE_MAX_AGE_DAYS)


def style_photos(brand_id: str) -> list[dict]:
    """Photos the store already uses: live blog banners first (they show the blog's look), then product photos."""
    out: list[dict] = []
    seen: set[str] = set()
    for a in all_rows("""SELECT title, image_url FROM articles WHERE brand_id = ? AND status = 'published' AND image_url LIKE 'https://%'
                         ORDER BY COALESCE(published_at, updated_at) DESC LIMIT 20""", brand_id):
        if a["image_url"] not in seen and len(out) < STYLE_PHOTOS // 2:
            seen.add(a["image_url"])
            out.append({"url": small(a["image_url"]), "label": f"blog banner of “{a['title']}”"})
    for p in all_rows("SELECT title, image_url FROM products WHERE brand_id = ? AND image_url LIKE 'https://%' ORDER BY synced_at DESC, title LIMIT 60", brand_id):
        if len(out) >= STYLE_PHOTOS:
            break
        if p["image_url"] not in seen:
            seen.add(p["image_url"])
            out.append({"url": small(p["image_url"]), "label": f"product photo of “{p['title']}”"})
    return out


def build_style(brand_id: str) -> dict:
    """Ask Claude to describe the brand's look from its photos and keep it. Raises ClaudeError / HttpError(daily_limit)."""
    photos = style_photos(brand_id)
    if not photos:
        raise HttpError(412, "No product photos or blog banners are synced for this brand yet. Run the Shopify sync first.", "no_photos")
    ai_budget.check("image_style")
    try:
        data, model = claude.image_style(brand(brand_id), brand_settings(brand_id), photos)
    finally:
        cost = ai_budget.record(claude.take_usage(), brand_id, "image_style")
    text = s(data.get("style"), 3000).strip()
    if not text:
        raise claude.ClaudeError("Claude returned an empty style description.", "invalid_output")
    value = {"style": text, "builtAt": now(), "photos": len(photos), "model": model, "costUsd": cost}
    run("""INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?, ?, ?, NULL)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
        _style_key(brand_id), json.dumps(value, ensure_ascii=False), now())
    return value


def _style_text(brand_id: str) -> str:
    st = style_of(brand_id)
    if _style_stale(st):
        try:
            st = build_style(brand_id)
        except HttpError as e:
            if e.code == "daily_limit":
                raise
            log.info("Visual style not built for %s: %s", brand_id, e.message)   # no photos yet: the prompt is still made, without it
    return (st or {}).get("style", "")


# ---------------------------------------------------------------- what Claude is given for one article

def _article_input(a: Row) -> dict:
    body = a["body_html"] or ""
    heads = [strip_html(h).strip() for h in re.findall(r"<h[23][^>]*>([\s\S]*?)</h[23]>", body, re.I)]
    first = re.search(r"<p[^>]*>([\s\S]*?)</p>", body, re.I)
    return {"title": a["title"], "primary_keyword": a["primary_keyword"], "summary": s(strip_html(a["summary_html"] or ""), 400),
            "headings": [h for h in heads if h][:12], "opening": s(strip_html(first.group(1)) if first else strip_html(body), 900)}


# Words every product of these stores shares: they say nothing about which product fits an article.
_COMMON = {"cotton", "block", "print", "printed", "hand", "handmade", "fabric", "the", "and", "for", "with", "your", "how", "what", "why",
           "which", "are", "you", "one", "set", "size", "sizes", "inch", "need", "guide", "ideas", "idea", "best", "make", "use"}


def _stems(text: str) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in _COMMON}


def candidate_products(a: Row) -> list[dict]:
    """Product photos that fit the article. A product type named in the title or keyword counts most, then shared words in
    the product name; a product the article links to gets a small boost (articles also link to loosely related products)."""
    products = all_rows("SELECT handle, title, url, image_url, product_type FROM products WHERE brand_id = ? AND image_url LIKE 'https://%'", a["brand_id"])
    body = a["body_html"] or ""
    linked = [p for p in products if f"/products/{p['handle']}" in body]
    text = f"{a['title']} {a['primary_keyword']}"
    want = _stems(text)

    def score(p: Row) -> float:
        kind = _stems(p["product_type"] or "")
        return 3 * len(want & kind) + len(want & _stems(p["title"])) + similarity(p["title"], text) + (0.75 if p in linked else 0)

    scored = sorted(((score(p), p) for p in products), key=lambda x: -x[0])
    picks = [p for sc, p in scored if sc >= 1][:MAX_PRODUCT_PHOTOS]
    return [{"url": p["image_url"], "title": p["title"], "handle": p["handle"], "product_url": p["url"]} for p in picks]


def used_concepts(brand_id: str, article_id: int) -> list[str]:
    return [r["concept"] for r in all_rows("""SELECT concept FROM image_prompts WHERE brand_id = ? AND article_id != ? AND concept != ''
                                               ORDER BY updated_at DESC LIMIT ?""", brand_id, article_id, USED_CONCEPTS)]


def clean_result(data: dict, products: list[dict]) -> dict:
    """Claude's answer, checked: text only, bounded lengths, references only from the photos it was shown."""
    if not isinstance(data, dict):
        raise claude.ClaudeError("Claude returned an answer of the wrong shape.", "invalid_output")
    scene = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s(data.get("scene"), 3000)).strip()
    if len(scene.split()) < 40:
        raise claude.ClaudeError("Claude's image description was too short to use.", "invalid_output")
    refs: list[dict] = []
    for n in data.get("references") or []:
        if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(products) and products[n - 1] not in refs and len(refs) < 2:
            refs.append(products[n - 1])
    name = slugify(re.sub(r"\.(jpe?g|png|webp)$", "", s(data.get("file_name"), 120), flags=re.I))[:80] or "blog-banner"
    pin = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s(data.get("pin_scene"), 3000)).strip()
    return {"scene": scene, "pin_scene": pin if len(pin.split()) >= 30 else "", "payoff": s(data.get("payoff"), 400).strip(), "refs": refs, "concept": s(data.get("concept"), 300).strip(), "alt_text": s(data.get("alt_text"), 300).strip(),
            "file_name": f"{name}.jpg"}


# ---------------------------------------------------------------- the queue

def _upsert(article_id: int, brand_id: str, reason: str, priority: int, user_id: int | None) -> None:
    t = now()
    run("""INSERT INTO image_prompts (article_id, brand_id, status, priority, reason, requested_by, attempts, created_at, updated_at)
           VALUES (?, ?, 'queued', ?, ?, ?, 0, ?, ?)
           ON CONFLICT(article_id) DO UPDATE SET status='queued', priority=excluded.priority, reason=excluded.reason, requested_by=excluded.requested_by,
             attempts=0, error=NULL, next_attempt_at=NULL, updated_at=excluded.updated_at""",
        article_id, brand_id, priority, reason, user_id, t, t)


def maybe_queue_new(a: Row | None) -> bool:
    """Called whenever an article is created or saved. Queues a prompt once for an article written from FEATURE_START on, as
    soon as it has enough text to picture. Imported and live Shopify articles are left to the backfill. Never raises."""
    try:
        if not a or a["origin"] not in ("app", "excel") or (a["created_at"] or "") < FEATURE_START or words(a["body_html"]) < MIN_WORDS:
            return False
        if get("SELECT 1 FROM image_prompts WHERE article_id = ?", a["id"]):
            return False
        _upsert(a["id"], a["brand_id"], "new_article", 0, None)
    except Exception:  # noqa: BLE001 - a prompt must never stop an article from being saved
        log.exception("Could not queue an image prompt for article %s", a["id"] if a else None)
        return False
    kick()
    return True


def request(user: dict, article_id: int) -> dict:
    """A person asks for a (new) prompt for one article, from the editor. It goes ahead of backfill work."""
    a = get("SELECT * FROM articles WHERE id = ?", article_id)
    if not a:
        raise HttpError(404, "Article not found.")
    if not claude.configured():
        raise HttpError(412, "ANTHROPIC_API_KEY is not set on the server.", "pending_setup")
    if words(a["body_html"]) < 40 and not a["primary_keyword"]:
        raise HttpError(400, "Write a little of the article (or add its primary keyword) first, so there is something to picture.")
    cur = get("SELECT status FROM image_prompts WHERE article_id = ?", article_id)
    if cur and cur["status"] == "working":
        raise HttpError(409, "A prompt for this article is being written right now.", "busy")
    _upsert(article_id, a["brand_id"], "editor", 0, user["id"])
    audit(user, "image_prompt.request", "article", article_id, a["brand_id"], a["title"])
    kick()
    return state(article_id)


def backfill(user: dict, brand_id: str | None, scope: str, redo: bool = False) -> dict:
    """Queue prompts for older articles: "drafts" (anything not live yet), "published" (live on Shopify) or "all".
    Articles that already have a prompt are skipped unless `redo`."""
    if scope not in SCOPES:
        raise HttpError(400, f"scope must be one of {', '.join(SCOPES)}.")
    if brand_id is not None and not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    if not claude.configured():
        raise HttpError(412, "ANTHROPIC_API_KEY is not set on the server.", "pending_setup")
    st = SCOPES[scope]
    where = f"a.status IN ({','.join('?' for _ in st)}) AND a.title != ''"
    args: list[Any] = list(st)
    if brand_id:
        where += " AND a.brand_id = ?"
        args.append(brand_id)
    skip = "" if redo else " AND (p.article_id IS NULL OR p.status = 'failed')"
    rows = all_rows(f"""SELECT a.id, a.brand_id FROM articles a LEFT JOIN image_prompts p ON p.article_id = a.id
                        WHERE {where}{skip} AND (p.status IS NULL OR p.status != 'working') ORDER BY a.updated_at DESC""", *args)
    for r in rows:
        _upsert(r["id"], r["brand_id"], "backfill", 1, user["id"])
    audit(user, "image_prompt.backfill", "image_prompts", scope, brand_id or "", f"{len(rows)} articles queued")
    kick()
    return {"queued": len(rows), "estimateUsd": round(len(rows) * ai_budget.ESTIMATE_USD["image_prompt"], 2), **summary(brand_id)}


def cancel_backfill(user: dict, brand_id: str | None) -> dict:
    """Take the older articles that are still waiting out of the queue (nothing already written is removed)."""
    args: list[Any] = []
    extra = ""
    if brand_id:
        extra, args = " AND brand_id = ?", [brand_id]
    n = run(f"DELETE FROM image_prompts WHERE status = 'queued' AND reason = 'backfill' AND prompt = ''{extra}", *args).changes
    run(f"UPDATE image_prompts SET status = 'ready', updated_at = ? WHERE status = 'queued' AND reason = 'backfill' AND prompt != ''{extra}", now(), *args)
    audit(user, "image_prompt.backfill_cancel", "image_prompts", "", brand_id or "", f"{n} waiting articles removed")
    return summary(brand_id)


def _recover() -> None:
    """Work left "working" by a stopped server goes back to the queue (only one Flowmerce process uses the database)."""
    global _recovered
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not _recovered:
        run("UPDATE image_prompts SET status = 'queued', updated_at = ? WHERE status = 'working'", now())
        run("UPDATE image_prompts SET image_status = 'queued' WHERE image_status = 'working'")
        _recovered = True
    else:
        run("UPDATE image_prompts SET status = 'queued', updated_at = ? WHERE status = 'working' AND updated_at < ?", now(), cutoff)


def _room_for(priority: int) -> bool:
    """Whether today's Claude limit has room for this item (and, for backfill, still for one automatic blog after it)."""
    from . import auto_blog   # imported here: auto_blog imports the job modules
    st = ai_budget.status()
    need = ai_budget.ESTIMATE_USD["image_prompt"]
    if priority > 0 and auto_blog.settings().get("enabled"):
        need += auto_blog.BLOG_ESTIMATE_USD
    return st["todayUsd"] + need <= st["dailyLimitUsd"]


def process_next() -> str:
    """Write the next due prompt. Returns "done", "failed", "retry", "wait" (no room in today's limit) or "empty"."""
    _recover()
    t = now()
    rows = all_rows("""SELECT * FROM image_prompts WHERE status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                       AND brand_id NOT IN (SELECT brand_id FROM automation_state WHERE paused = 1)
                       ORDER BY priority, created_at LIMIT 1""", t)
    if not rows:
        return "empty"
    job = rows[0]
    if not _room_for(job["priority"]):
        return "wait"
    if run("UPDATE image_prompts SET status = 'working', attempts = attempts + 1, updated_at = ? WHERE article_id = ? AND status = 'queued'",
           now(), job["article_id"]).changes != 1:
        return "retry"
    a = get("SELECT * FROM articles WHERE id = ?", job["article_id"])
    if not a:
        run("DELETE FROM image_prompts WHERE article_id = ?", job["article_id"])
        return "done"
    b, st = brand(a["brand_id"]), brand_settings(a["brand_id"])
    try:
        style = _style_text(a["brand_id"])
        products = candidate_products(a)
        ai_budget.check("image_prompt")
        try:
            data, _model = claude.image_prompt(b, st, style, _article_input(a), [{"url": small(p["url"]), "title": p["title"]} for p in products],
                                               used_concepts(a["brand_id"], a["id"]), format_line(a["brand_id"]),
                                               f"{PIN['shape']} {PIN['ratio']}, {PIN['width']} × {PIN['height']} pixels")
        finally:
            cost = ai_budget.record(claude.take_usage(), a["brand_id"], "image_prompt")
            run("UPDATE image_prompts SET cost_usd = cost_usd + ? WHERE article_id = ?", cost, a["id"])
        r = clean_result(data, products)
    except HttpError as e:
        if e.code == "daily_limit":
            run("UPDATE image_prompts SET status = 'queued', attempts = attempts - 1, updated_at = ? WHERE article_id = ?", now(), a["id"])
            return "wait"
        _fail(a["id"], e.message)
        return "failed"
    except claude.ClaudeError as e:
        if e.retryable and job["attempts"] + 1 < MAX_ATTEMPTS:
            run("UPDATE image_prompts SET status = 'queued', error = ?, next_attempt_at = ?, updated_at = ? WHERE article_id = ?",
                s(str(e), 500), _in(e.retry_after or 60 * 2 ** job["attempts"]), now(), a["id"])
            return "retry"
        _fail(a["id"], str(e))
        return "failed"
    refs = [{"title": p["title"], "url": p["url"], "product_url": p["product_url"]} for p in r["refs"]]
    run("""UPDATE image_prompts SET status = 'ready', prompt = ?, pin_prompt = ?, payoff = ?, concept = ?, references_json = ?, alt_text = ?, file_name = ?,
           article_version = ?, error = NULL, next_attempt_at = NULL, updated_at = ?, finished_at = ? WHERE article_id = ?""",
        compose(a["brand_id"], r["scene"], refs), compose(a["brand_id"], r["pin_scene"], refs, pin=True) if r["pin_scene"] else "", r["payoff"], r["concept"], json.dumps(refs, ensure_ascii=False), r["alt_text"], r["file_name"],
        a["version"], now(), now(), a["id"])
    from . import ai_images
    ai_images.queue(a["id"])   # the picture itself, when an image API key is set (services/ai_images.py)
    return "done"


def _fail(article_id: int, message: str) -> None:
    run("UPDATE image_prompts SET status = 'failed', error = ?, next_attempt_at = NULL, updated_at = ?, finished_at = ? WHERE article_id = ?",
        s(message, 500), now(), now(), article_id)


def _drain() -> None:
    """Prompts first, then pictures, one at a time, until both queues are empty or waiting for a limit."""
    global _rest_until
    from . import ai_images
    try:
        while True:
            r = process_next()
            if r in ("done", "failed", "retry"):
                continue
            r2 = ai_images.process_next()
            if r2 in ("done", "failed", "retry"):
                continue
            if "wait" in (r, r2):
                _rest_until = time.monotonic() + WAIT_SECONDS
            return
    except Exception:  # noqa: BLE001 - a background thread must not die silently
        log.exception("Image prompt worker stopped")
        _rest_until = time.monotonic() + WAIT_SECONDS


def start() -> None:
    """Allow the background worker (called when the AI job runner starts) and look for work."""
    global _enabled
    _enabled = True
    _recover()
    kick()


def kick() -> None:
    """Start the background worker if there may be work and it is not running. Cheap; the AI job runner calls it every tick."""
    global _thread
    if not _enabled or not claude.configured() or time.monotonic() < _rest_until:
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        t = now()
        if not get("""SELECT 1 FROM image_prompts WHERE (status = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                      OR (status = 'ready' AND image_status = 'queued' AND (image_next_at IS NULL OR image_next_at <= ?)) LIMIT 1""", t, t):
            return
        _thread = threading.Thread(target=_drain, name="image-prompts", daemon=True)
        _thread.start()


def wake() -> None:
    """Forget a rest (a person just changed the budget or asked for work) and start the worker."""
    global _rest_until
    _rest_until = 0.0
    kick()


# ---------------------------------------------------------------- what the dashboard sees

def guide(brand_id: str) -> dict:
    f = FORMAT[brand_id]
    return {"tool": TOOL, "format": {k: f[k] for k in ("shape", "ratio", "width", "height", "preview", "theme")},
            "pin": {k: PIN[k] for k in ("shape", "ratio", "width", "height")},
            "steps": [f"Open {TOOL['name']} (or {TOOL['also']}).",
                      f"Set the image shape (aspect ratio) to {f['ratio']} in the tool's settings: image tools often copy the shape of the "
                      "attached photo instead of following the prompt.",
                      "Attach the reference photos shown here, if there are any (download them first).",
                      "Paste the prompt and generate. Make a few and keep the best.",
                      f"Check the picture is {f['ratio']} and at least {f['width'] * 3 // 4} pixels wide, then upload it with “From your computer” below."]}


def state(article_id: int) -> dict:
    a = get("SELECT id, brand_id, version FROM articles WHERE id = ?", article_id)
    if not a:
        raise HttpError(404, "Article not found.")
    p = get("SELECT * FROM image_prompts WHERE article_id = ?", article_id)
    paused = bool(get("SELECT 1 FROM automation_state WHERE brand_id = ? AND paused = 1", a["brand_id"]))
    base = {"articleId": article_id, "brand": a["brand_id"], "brandPaused": paused, "configured": claude.configured(), "estimateUsd": ai_budget.ESTIMATE_USD["image_prompt"], **guide(a["brand_id"])}
    from . import ai_images
    if not p:
        return {**base, "status": "none", **ai_images.state_part(None)}
    return {**base, "status": p["status"], "reason": p["reason"], "prompt": p["prompt"], "pinPrompt": p["pin_prompt"], "payoff": p["payoff"],
            "concept": p["concept"],
            "references": json.loads(p["references_json"] or "[]"), "altText": p["alt_text"], "fileName": p["file_name"],
            "error": p["error"], "retryAt": p["next_attempt_at"], "costUsd": round(p["cost_usd"], 4), "updatedAt": p["updated_at"],
            "finishedAt": p["finished_at"], "position": _position(p) if p["status"] == "queued" else None, **ai_images.state_part(p)}


def _position(p: Row) -> int:
    ahead = get("""SELECT COUNT(*) n FROM image_prompts WHERE status IN ('queued','working') AND (priority < ? OR (priority = ? AND created_at < ?))""",
                p["priority"], p["priority"], p["created_at"])
    return int(ahead["n"]) + 1 if ahead else 1


def summary(brand_id: str | None) -> dict:
    where, args = ("WHERE brand_id = ?", [brand_id]) if brand_id else ("", [])
    counts = {k: 0 for k in STATUSES}
    for r in all_rows(f"SELECT status, COUNT(*) n FROM image_prompts {where} GROUP BY status", *args):
        counts[r["status"]] = r["n"]
    waiting_backfill = get(f"SELECT COUNT(*) n FROM image_prompts {where}{' AND' if where else 'WHERE'} status = 'queued' AND reason = 'backfill'", *args)
    brands = [brand_id] if brand_id else list(FORMAT)
    without: dict[str, int] = {}
    for scope, st in (("drafts", SCOPES["drafts"]), ("published", SCOPES["published"])):
        q = f"""SELECT COUNT(*) n FROM articles a LEFT JOIN image_prompts p ON p.article_id = a.id
                WHERE a.status IN ({','.join('?' for _ in st)}) AND p.article_id IS NULL{' AND a.brand_id = ?' if brand_id else ''}"""
        without[scope] = int((get(q, *st, *args) or {"n": 0})["n"])
    styles = {}
    for b in brands:
        v = style_of(b)
        styles[b] = {"builtAt": v.get("builtAt"), "photos": v.get("photos"), "style": v.get("style")} if v else None
    paused = [r["brand_id"] for r in all_rows("SELECT brand_id FROM automation_state WHERE paused = 1") if r["brand_id"] in brands]
    from . import ai_images
    return {"counts": counts, "pausedBrands": paused, "backfillWaiting": int((waiting_backfill or {"n": 0})["n"]), "withoutPrompt": without,
            "estimateUsd": ai_budget.ESTIMATE_USD["image_prompt"], "configured": claude.configured(), "styles": styles,
            "tool": TOOL, "formats": {b: guide(b)["format"] for b in brands}, "resting": time.monotonic() < _rest_until, **ai_images.summary_part()}


def refresh_style(user: dict, brand_id: str) -> dict:
    """A person asks Claude to read the store's photos again (after new products or a new look)."""
    if not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    if not claude.configured():
        raise HttpError(412, "ANTHROPIC_API_KEY is not set on the server.", "pending_setup")
    try:
        v = build_style(brand_id)
    except claude.ClaudeError as e:
        raise HttpError(502 if e.retryable else 422, str(e), e.kind) from None
    audit(user, "image_prompt.style", "app_settings", _style_key(brand_id), brand_id, f"{v['photos']} photos read")
    return summary(brand_id)
