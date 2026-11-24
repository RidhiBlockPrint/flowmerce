"""The automatic blog pipeline: blogs with no person involved, up to an approved blog with a publish request on the
calendar. Owner request and decisions of 2026-11-20 (two blogs a week per brand); since 2026-11-24 the written blog stays in
Flowmerce and reaches Shopify only when a reviewer authorizes its publish request (hidden until its publish time).

Every 15 minutes (services/scheduler.py) and whenever a Claude job finishes (services/ai_jobs.py runner):
  plan       keeps the calendar filled: one slot per brand on each publishing weekday (Tuesday and Friday) for the next
             4 weeks. A slot is the day the blog should go live, at 10:00 business time.
  start      5 days before a slot, "Write a blog" (services/autopilot.py) starts for it: Claude researches topics with the
             brand's upcoming events in mind, Flowmerce picks the best new topic (its primary and secondary keywords come
             with it) and Claude writes the draft with every field filled.
  images     a featured image and up to 3 product photos inside the body, each with alt text (no Claude cost).
  check      services/answer_checks.py: required fields, SEO, AEO, GEO and LLMO. What Claude can fix goes back to Claude
             once as a revision request.
  schedule   the draft is approved as "Flowmerce (auto)" (it stays in Flowmerce) and a publish request for the slot's day
             is placed on the content calendar. It goes to Shopify only when a reviewer authorizes that request.

A slot whose day passes before its blog was written (Claude limit used up, automation paused) is marked missed. A person
can cancel a slot (cancel()): one not started yet is skipped, one being written is stopped (autopilot.stop) and skipped.
Nothing else is ever deleted. Pausing automation for a brand stops new slots from starting.

The pipeline is OFF until an admin switches it on (SEO & Blog overview, "Start automatic blogs"): this computer's copy and
the hosted copy each keep their own database, and only one of them should write blogs.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from ..audit import audit
from ..config import BRAND_IDS, is_brand
from ..db import all_rows, get, now, run
from ..util import HttpError, norm_keyword, page_path, s, similarity
from . import ai_budget, answer_checks
from .articles import content_of, hash_content
from .brands import brand

log = logging.getLogger(__name__)

Row = dict[str, Any]
# Off until an admin switches it on (owner decision 2026-11-20): each copy of Flowmerce (this computer, the hosted copy)
# has its own database, so only the one copy that should write blogs is switched on; otherwise drafts would be doubled.
DEFAULTS: dict[str, Any] = {"enabled": False, "weekdays": [1, 4], "weeksAhead": 4, "leadDays": 5, "inlineImages": 3}
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SLOT_STATUSES = ("planned", "writing", "ready", "failed", "skipped", "missed")
# What one automatic blog is expected to cost: research + draft + one revision.
BLOG_ESTIMATE_USD = ai_budget.ESTIMATE_USD["topic_research"] + ai_budget.ESTIMATE_USD["content_generation"] + ai_budget.ESTIMATE_USD["content_revision"]


# ---------------------------------------------------------------- settings

def settings() -> dict[str, Any]:
    row = get("SELECT value_json FROM app_settings WHERE key = 'auto_blog'")
    try:
        saved = json.loads(row["value_json"]) if row else {}
    except ValueError:
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in (saved if isinstance(saved, dict) else {}).items() if k in DEFAULTS}}


def update_settings(user: Row, patch: dict[str, Any]) -> dict[str, Any]:
    cur = settings()
    if "enabled" in patch:
        cur["enabled"] = bool(patch["enabled"])
    if "weekdays" in patch:
        days = patch["weekdays"]
        if not isinstance(days, list) or not days or len(days) > 7 or any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
            raise HttpError(400, "weekdays must be a list of 1-7 day numbers (0 = Monday ... 6 = Sunday).")
        cur["weekdays"] = sorted(set(days))
    run("""INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES ('auto_blog', ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        json.dumps(cur), now(), user.get("id"))
    audit(user, "auto_blog.settings", "app_settings", "auto_blog", "", json.dumps(cur))
    return cur


# ---------------------------------------------------------------- plan

def _today() -> date:
    return date.fromisoformat(ai_budget.today())


def plan(today: date | None = None) -> int:
    """Add the missing slots for the next weeks. Returns how many were added. Never moves or removes a slot. Slots are
    planned (no cost) even while the pipeline is off, so the calendar shows what would be written."""
    st = settings()
    t = today or _today()
    added = 0
    for b in BRAND_IDS:
        for i in range(1, 7 * int(st["weeksAhead"]) + 1):
            d = t + timedelta(days=i)
            if d.weekday() not in st["weekdays"]:
                continue
            ts = now()
            r = run("INSERT OR IGNORE INTO auto_blogs (brand_id, publish_on, status, message, created_at, updated_at) VALUES (?,?, 'planned', '', ?, ?)",
                    b, d.isoformat(), ts, ts)
            added += r.changes if hasattr(r, "changes") else 0
    return added


def _set(slot_id: int, **cols: Any) -> None:
    cols["updated_at"] = now()
    run(f"UPDATE auto_blogs SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", *cols.values(), slot_id)


# ---------------------------------------------------------------- start

def start_due(today: date | None = None) -> int:
    """Start writing the next slot of each brand whose writing day has come. One blog per brand at a time; a slot that
    does not fit today's Claude limit waits for a later tick. Returns how many started.

    Two kinds of slot: an automatic one (no topic: Claude researches and picks one; runs only while automatic blogs are
    switched on) and one a person put on the calendar for a topic (topic_id set; runs whatever that switch says, since a
    person asked for it). Both wait while automation is paused for the brand."""
    from . import autopilot, workflow   # imported here: autopilot imports this module
    st = settings()
    t = today or _today()
    for r in all_rows("SELECT id FROM auto_blogs WHERE status = 'planned' AND publish_on <= ?", t.isoformat()):
        _set(r["id"], status="missed", message="Not written in time (the Claude limit was used up or automation was paused).")
    started = 0
    for b in BRAND_IDS:
        if workflow.is_paused(b) or get("SELECT 1 FROM auto_blogs WHERE brand_id = ? AND status = 'writing'", b):
            continue
        slot = get(f"""SELECT * FROM auto_blogs WHERE brand_id = ? AND status = 'planned' AND publish_on > ? AND publish_on <= ?
                      {'' if st['enabled'] else 'AND topic_id IS NOT NULL'} ORDER BY publish_on LIMIT 1""",
                   b, t.isoformat(), (t + timedelta(days=int(st["leadDays"]))).isoformat())
        if not slot:
            continue
        user = autopilot._acting_user(None)
        if not user:
            _set(slot["id"], message="Waiting: no active admin to record the work against.")
            continue
        try:
            r = _start_topic(slot, user) if slot["topic_id"] else autopilot.start(user, b, "", source="auto")
        except HttpError as e:
            _set(slot["id"], message=f"Waiting: {e.message}")
            continue
        if r is None:   # the topic already had an article: put forward for this day instead of written again
            continue
        run("UPDATE autopilot_runs SET slot_id = ? WHERE id = ?", slot["id"], r["id"])
        _set(slot["id"], status="writing", run_id=r["id"],
             message="Claude is writing the draft." if slot["topic_id"] else "Claude is choosing a topic.")
        audit(None, "auto_blog.start", "auto_blog", slot["id"], b, f"for {slot['publish_on']}")
        started += 1
    return started


def _start_topic(slot: Row, user: Row) -> Row | None:
    """Write the blog for a slot a person scheduled for a topic: the same chain as an automatic blog (draft, images,
    quality check, one revision, approval, publish request for the slot's day), starting from that topic. If the topic
    already has an article (someone drafted it by hand meanwhile), that article is put forward for this day instead."""
    from . import autopilot, calendar_plan
    a = get("SELECT * FROM articles WHERE topic_id = ? ORDER BY id LIMIT 1", slot["topic_id"])
    if a:
        if not get("SELECT 1 FROM content_schedule WHERE article_id = ? AND action = 'publish' AND status = 'planned'", a["id"]):
            calendar_plan.add_entry(user, {"brand": slot["brand_id"], "action": "publish", "run_on": slot["publish_on"], "article_id": a["id"]})
        _set(slot["id"], status="ready", article_id=a["id"],
             message="This topic was already written; it is put forward for this day once approved, and a reviewer authorizes it.")
        return None
    if get("SELECT 1 FROM autopilot_runs WHERE brand_id = ? AND status = 'running'", slot["brand_id"]):
        raise HttpError(409, "another blog is being written for this brand; this one starts after it.", "already_running")
    autopilot._check_money(("content_generation",))
    return autopilot.start_from_topic(user["id"], slot["brand_id"], int(slot["topic_id"]),
                                      f"scheduled on the content calendar for {slot['publish_on']}", source="auto")


# ---------------------------------------------------------------- a person schedules a topic for a day

def schedule_topic(user: Row, body: dict[str, Any]) -> Row:
    """Put a blog on the calendar: a topic (an existing one, or a new title and keyword) and the day it should go live.
    Flowmerce writes it `leadDays` before that day (at once if the day is sooner), checks and approves it, and makes a
    publish request for 10:00 that day; a reviewer authorizes it (owner decision 2026-11-24: one click, not automatic)."""
    brand_id = str(body.get("brand") or "")
    if not is_brand(brand_id):
        raise HttpError(400, "Pick a brand.")
    day = str(body.get("publish_on") or "")[:10]
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HttpError(400, "Pick the day the blog should go live.") from None
    if d <= _today():
        raise HttpError(400, "Pick tomorrow or a later day: Flowmerce needs time to write and check the blog.")
    topic = _topic_for(user, brand_id, body)
    if get("SELECT 1 FROM articles WHERE topic_id = ? AND status IN ('publish_requested','scheduled','published')", topic["id"]):
        raise HttpError(409, "This topic's article is already scheduled or live.", "already_published")
    other = get("SELECT publish_on FROM auto_blogs WHERE topic_id = ? AND status IN ('planned','writing','ready')", topic["id"])
    if other:
        raise HttpError(409, f"This topic is already on the calendar for {other['publish_on']}.", "already_scheduled")
    slot = get("SELECT * FROM auto_blogs WHERE brand_id = ? AND publish_on = ?", brand_id, day)
    if slot and (slot["status"] in ("writing", "ready") or (slot["topic_id"] and slot["status"] == "planned")):
        raise HttpError(409, f"{day} already has a blog for this brand. Pick another day, or cancel that one first.", "day_taken")
    ts = now()
    msg = f"Scheduled by {user.get('name') or user.get('email') or 'a person'}."
    if slot:   # an automatic slot (planned, skipped, missed or failed) becomes this topic's day
        run("""UPDATE auto_blogs SET topic_id = ?, status = 'planned', run_id = NULL, article_id = NULL, checks_json = '{}',
               message = ?, updated_at = ? WHERE id = ?""", topic["id"], msg, ts, slot["id"])
        sid = slot["id"]
    else:
        sid = run("""INSERT INTO auto_blogs (brand_id, publish_on, status, topic_id, message, created_at, updated_at)
                     VALUES (?, ?, 'planned', ?, ?, ?, ?)""", brand_id, day, topic["id"], msg, ts, ts).last_id
    audit(user, "auto_blog.schedule_topic", "auto_blog", sid, brand_id, f"{topic['title']} on {day}")
    if d <= _today() + timedelta(days=int(settings()["leadDays"])):
        try:
            start_due()   # due already: start writing now instead of at the next 15-minute tick
        except Exception:  # noqa: BLE001 — the scheduler tries again on its next tick; the slot shows why it waits
            log.exception("Starting the scheduled blog at once failed")
    return slots_by_id([sid])[0]


def _topic_for(user: Row, brand_id: str, body: dict[str, Any]) -> Row:
    """The topic to write: the chosen one, or a new one from a title (and keyword) typed on the calendar. A typed title
    whose keyword matches an existing topic uses that topic. A topic put on the calendar is approved by that person."""
    if body.get("topic_id"):
        t = get("SELECT * FROM topics WHERE id = ? AND brand_id = ?", int(body["topic_id"]), brand_id)
        if not t:
            raise HttpError(404, "That topic does not exist for this brand.")
    else:
        title = s(body.get("title"), 200).strip()
        if len(title) < 5:
            raise HttpError(400, "Write the blog topic (its working title).")
        keyword = s(body.get("keyword"), 120).strip() or title
        norm = norm_keyword(keyword)
        t = get("SELECT * FROM topics WHERE brand_id = ? AND keyword_norm = ?", brand_id, norm)
        if not t:
            ts = now()
            tid = run("""INSERT INTO topics (brand_id, title, primary_keyword, keyword_norm, status, source, notes, created_by,
                                             created_at, updated_at, source_updated_at)
                         VALUES (?, ?, ?, ?, 'approved', 'manual', ?, ?, ?, ?, ?)""", brand_id, title, keyword.lower(), norm,
                      "Put on the content calendar.", user.get("id"), ts, ts, ts).last_id
            audit(user, "topic.create", "topic", tid, brand_id, f"{title} (from the content calendar)")
            return get("SELECT * FROM topics WHERE id = ?", tid)  # type: ignore[return-value]
    if t["status"] == "rejected":
        raise HttpError(409, "That topic was rejected. Reopen it under Topics & keywords first.")
    if t["status"] in ("proposed", "validated"):
        run("UPDATE topics SET status = 'approved', updated_at = ? WHERE id = ?", now(), t["id"])
        audit(user, "topic.decision", "topic", t["id"], brand_id, f"Approved {t['title']} by putting it on the calendar")
    return get("SELECT * FROM topics WHERE id = ?", t["id"])  # type: ignore[return-value]


# ---------------------------------------------------------------- images

def _figure(src: str, alt: str) -> str:
    alt = s(alt, 200).replace('"', "'")
    return f'<figure><img src="{src}" alt="{alt}" loading="lazy"><figcaption>{alt}</figcaption></figure>'


def add_inline_images(article_id: int, count: int = 3) -> int:
    """Put up to `count` product photos inside a draft's body: products it links to first, then the closest by name.
    Each goes at the end of a section (before the next <h2>). Only a draft is changed. Returns how many were added."""
    a = get("SELECT * FROM articles WHERE id = ?", article_id)
    if not a or a["status"] not in ("draft", "changes_requested"):
        return 0
    body = a["body_html"] or ""
    have = len(re.findall(r"<img\b", body, re.I))
    want = max(0, count - have)
    if not want:
        return 0
    products = all_rows("SELECT title, url, image_url FROM products WHERE brand_id = ? AND image_url != ''", a["brand_id"])
    used = {a["image_url"], *re.findall(r'<img\b[^>]*src="([^"]+)"', body, re.I)}
    linked = [p for p in products if p["url"] and (p["url"] in body or (urlparse(p["url"]).path and urlparse(p["url"]).path in body))]
    ranked = sorted(products, key=lambda p: -similarity(p["title"], f"{a['primary_keyword']} {a['title']}"))
    picks: list[Row] = []
    for p in linked + ranked:
        if p["image_url"] in used or any(p["image_url"] == q["image_url"] for q in picks):
            continue
        picks.append(p)
        if len(picks) >= want:
            break
    if not picks:
        return 0
    # Section ends: just before the 2nd, 3rd ... <h2>; any left go at the end of the body.
    starts = [m.start() for m in re.finditer(r"<h2\b", body, re.I)][1:]
    cuts = starts[:len(picks)]
    out, last = [], 0
    for cut, p in zip(cuts, picks):
        out += [body[last:cut], _figure(p["image_url"], p["title"])]
        last = cut
    out.append(body[last:])
    out += [_figure(p["image_url"], p["title"]) for p in picks[len(cuts):]]
    c = {**content_of(a), "body_html": "".join(out)}
    h, v = hash_content(c), a["version"] + 1
    run("UPDATE articles SET body_html = ?, content_hash = ?, version = ?, updated_at = ? WHERE id = ?", c["body_html"], h, v, now(), article_id)
    run("INSERT INTO article_revisions (article_id, version, data_json, content_hash, user_id, note, created_at) VALUES (?,?,?,?,?,?,?)",
        article_id, v, json.dumps(c, ensure_ascii=False), h, None, f"{len(picks)} product photo(s) added to the body by Flowmerce", now())
    return len(picks)


# ---------------------------------------------------------------- check, revise, schedule

def check_article(article_id: int) -> dict[str, Any]:
    a = get("SELECT * FROM articles WHERE id = ?", article_id)
    if not a:
        raise HttpError(404, "Article not found.")
    b = brand(a["brand_id"])
    return answer_checks.check(a, b.name, b.storefront_domain)


def after_draft(r: Row, article_id: int) -> str | None:
    """Called by autopilot when an automatic run's draft is written. Adds images, checks the draft, and either asks Claude
    for one revision (returns its job id) or returns None when the draft is ready to be approved and scheduled."""
    from . import ai_jobs, workflow
    a = get("SELECT image_url FROM articles WHERE id = ?", article_id)
    if a and not a["image_url"]:
        workflow._image_selection(r["brand_id"])
    add_inline_images(article_id, int(settings()["inlineImages"]))
    result = check_article(article_id)
    _record(r, article_id, result, "Checked")
    request = answer_checks.revision_request(result)
    if not request:
        return None
    art = get("SELECT version FROM articles WHERE id = ?", article_id)
    try:
        job, _ = ai_jobs.create_job(None, r["brand_id"], "content_revision", {"article_id": article_id, "base_version": art["version"], "instructions": request})
    except HttpError as e:
        log.info("Automatic revision not started for article %s: %s", article_id, e.message)
        return None
    return str(job["id"])


def finish(r: Row, article_id: int) -> str:
    """Approve (the blog stays in Flowmerce) and place the publish request for the slot's day on the calendar."""
    from . import autopilot, calendar_plan
    result = check_article(article_id)
    _record(r, article_id, result, "Final check")
    approved = autopilot.approve_article(article_id, f"written by the automatic blog pipeline (quality score {result['score']}/100)")
    outcome = "Approved and kept in Flowmerce." if approved else autopilot.NOT_APPROVED
    slot = get("SELECT * FROM auto_blogs WHERE id = ?", r.get("slot_id")) if r.get("slot_id") else None
    if slot and approved:
        user = autopilot._acting_user(r["created_by"])
        if user and not get("SELECT 1 FROM content_schedule WHERE article_id = ? AND action = 'publish' AND status = 'planned'", article_id):
            try:
                calendar_plan.add_entry(user, {"brand": slot["brand_id"], "action": "publish", "run_on": slot["publish_on"], "article_id": article_id})
            except HttpError as e:
                outcome += f" It could not be put on the calendar: {e.message}"
        open_ = len(result["failures"])
        _set(slot["id"], status="ready", article_id=article_id,
             message=f"{outcome} Publish request for {slot['publish_on']} waits for a reviewer." + (f" {open_} check(s) still open." if open_ else ""))
    elif slot:
        _set(slot["id"], status="failed", article_id=article_id, message=outcome)
    return outcome


def _record(r: Row, article_id: int, result: dict[str, Any], label: str) -> None:
    if r.get("slot_id"):
        _set(int(r["slot_id"]), article_id=article_id, checks_json=json.dumps(result), message=f"{label}: quality score {result['score']}/100.")


def run_failed(r: Row, message: str) -> None:
    """An automatic run stopped: its slot shows why (and stays visible on the calendar)."""
    if r.get("slot_id"):
        _set(int(r["slot_id"]), status="failed", message=s(message, 500))


def tick() -> None:
    """Plan and start (called by the scheduler)."""
    plan()
    start_due()


# ---------------------------------------------------------------- reads for the SEO & Blog overview

def cancel(user: Row, slot_id: int) -> Row:
    """Cancel one automatic blog so Claude does not write it: a planned slot is skipped; a slot being written has its run
    stopped (its unfinished Claude jobs are cancelled) and is skipped. A written blog is not undone here: it is an article."""
    from . import autopilot
    slot = get("SELECT * FROM auto_blogs WHERE id = ?", slot_id)
    if not slot:
        raise HttpError(404, "That slot does not exist.")
    if slot["status"] == "writing" and slot["run_id"]:
        run_row = get("SELECT status FROM autopilot_runs WHERE id = ?", slot["run_id"])
        if run_row and run_row["status"] == "running":
            autopilot.stop(user, slot["run_id"])   # also marks this slot skipped
            audit(user, "auto_blog.cancel", "auto_blog", slot_id, slot["brand_id"], f"{slot['publish_on']} (stopped while writing)")
            return get("SELECT * FROM auto_blogs WHERE id = ?", slot_id)  # type: ignore[return-value]
    if slot["status"] not in ("planned", "writing"):
        raise HttpError(409, "Only a blog that is planned or being written can be cancelled.")
    _set(slot_id, status="skipped", message=f"Cancelled by {user.get('name') or user.get('email') or 'a person'}. No blog is written for this day.")
    audit(user, "auto_blog.cancel", "auto_blog", slot_id, slot["brand_id"], slot["publish_on"])
    return get("SELECT * FROM auto_blogs WHERE id = ?", slot_id)  # type: ignore[return-value]


def slots(brand_id: str | None, start: str, end: str) -> list[Row]:
    where, args = "s.publish_on BETWEEN ? AND ?", [start, end]
    if brand_id:
        where += " AND s.brand_id = ?"
        args.append(brand_id)
    return _slot_rows(where, args)


def slots_by_id(ids: list[int]) -> list[Row]:
    return _slot_rows(f"s.id IN ({','.join('?' for _ in ids)})", list(ids)) if ids else []


def _slot_rows(where: str, args: list[Any]) -> list[Row]:
    """Slots with what they are about: the article once written, else the topic (a person's scheduled topic, or the one
    Claude picked). `scheduled_topic` marks a slot a person put on the calendar for a topic."""
    rows = all_rows(f"""SELECT s.*, a.title AS article_title, a.status AS article_status, a.primary_keyword, a.shopify_article_id,
                               a.image_url, COALESCE(st.title, t.title) AS topic_title, r.step AS run_step, r.message AS run_message
                        FROM auto_blogs s LEFT JOIN articles a ON a.id = s.article_id LEFT JOIN autopilot_runs r ON r.id = s.run_id
                        LEFT JOIN topics t ON t.id = r.topic_id LEFT JOIN topics st ON st.id = s.topic_id
                        WHERE {where} ORDER BY s.publish_on, s.brand_id""", *args)
    for x in rows:
        try:
            chk = json.loads(x.pop("checks_json") or "{}")
        except ValueError:
            chk = {}
        x["scheduled_topic"] = bool(x.get("topic_id"))
        x["checks"] = {"score": chk.get("score"), "groups": {k: g.get("score") for k, g in (chk.get("groups") or {}).items()},
                       "open": [c["label"] for c in chk.get("failures", [])][:8], "words": chk.get("words"), "images": chk.get("images")}
    return rows


def overview(brand_id: str | None) -> dict[str, Any]:
    """Everything the SEO & Blog overview shows: the next weeks' slots, how far each one is, and projected figures."""
    if brand_id and not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    st = settings()
    t = _today()
    start, end = (t - timedelta(days=14)).isoformat(), (t + timedelta(days=7 * int(st["weeksAhead"]) + 7)).isoformat()
    rows = slots(brand_id, start, end)
    upcoming = [x for x in rows if x["publish_on"] > t.isoformat()]
    bw, ba = ("AND brand_id = ?", [brand_id]) if brand_id else ("", [])
    since30 = (t - timedelta(days=30)).isoformat()
    live30 = get(f"SELECT COUNT(*) n FROM articles WHERE shopify_published = 1 AND published_at >= ? {bw}", since30, *ba)["n"]  # type: ignore[index]
    waiting = get(f"""SELECT COUNT(*) n FROM publish_requests p JOIN articles a ON a.id = p.article_id
                      WHERE p.status = 'pending' {bw.replace('brand_id', 'a.brand_id')}""", *ba)["n"]  # type: ignore[index]
    # Projection: the Search Console clicks a live article earns in a month today, times the blogs planned for the next
    # 4 weeks (what they would add each month once established, at today's rate).
    per = _clicks_per_article(brand_id, t)
    next4 = [x for x in upcoming if x["publish_on"] <= (t + timedelta(days=28)).isoformat() and x["status"] not in ("skipped", "missed", "failed")]
    scores = [x["checks"]["score"] for x in rows if x["checks"]["score"] is not None]
    by_status = {k: sum(1 for x in upcoming if x["status"] == k) for k in SLOT_STATUSES}
    budget = ai_budget.status()
    return {
        "brand": brand_id, "today": t.isoformat(), "from": start, "to": end, "settings": {**st, "weekdayNames": [WEEKDAY_NAMES[d] for d in st["weekdays"]]},
        "slots": rows,
        "counts": {**by_status, "upcoming": len(upcoming), "next4Weeks": len(next4), "liveLast30": live30, "waitingForReviewer": waiting},
        "projection": {
            "clicksPerArticleMonth": round(per["avg"], 1) if per["avg"] is not None else None, "basedOnArticles": per["n"],
            "monthlyClicksFromNext4Weeks": round(per["avg"] * len(next4)) if per["avg"] is not None else None,
            "claudeUsdNext4Weeks": round(BLOG_ESTIMATE_USD * len(next4), 2), "blogEstimateUsd": round(BLOG_ESTIMATE_USD, 2),
            "averageQuality": round(sum(scores) / len(scores)) if scores else None,
        },
        "budget": budget,
        "events": _events(brand_id, t.isoformat(), end),
    }


def _clicks_per_article(brand_id: str | None, t: date) -> dict[str, Any]:
    """Search Console clicks a live blog article earns in a month today: the clicks of every live article in the last 28
    days of Search Console data, divided by those articles. Search Console stores page paths and articles their full URL;
    per page the source with the most clicks counts (a day can be both in the API copy and in an import). Needs at least
    3 live articles and 28 days of data, otherwise there is no projection."""
    bw, ba = ("AND brand_id = ?", [brand_id]) if brand_id else ("", [])
    last = get(f"SELECT MAX(date) mx, MIN(date) mn FROM gsc_page_daily WHERE 1 = 1 {bw}", *ba)
    if not last or not last["mx"] or (date.fromisoformat(last["mx"]) - date.fromisoformat(last["mn"])).days < 27:
        return {"avg": None, "n": 0}
    start = (date.fromisoformat(last["mx"]) - timedelta(days=27)).isoformat()
    arts = all_rows(f"""SELECT brand_id, live_url FROM articles WHERE shopify_published = 1 AND live_url IS NOT NULL
                        AND (published_at IS NULL OR substr(published_at, 1, 10) <= ?) {bw}""", start, *ba)
    total = 0
    for a in arts:
        rows = all_rows("""SELECT SUM(clicks) c FROM gsc_page_daily WHERE brand_id = ? AND page = ? AND date BETWEEN ? AND ?
                           GROUP BY source""", a["brand_id"], page_path(a["live_url"]), start, last["mx"])
        total += max([int(r["c"] or 0) for r in rows] or [0])
    return {"avg": total / len(arts) if len(arts) >= 3 else None, "n": len(arts)}


def _events(brand_id: str | None, start: str, end: str) -> list[Row]:
    from .calendar_plan import events_between
    return [{"key": e["key"], "name": e["name"], "date": e["date"]} for e in events_between(brand_id, start, end)][:20]
