"""Autopilot: one click to a finished, hidden Shopify draft, and the 6-hour rule. Owner decision of 2026-11-19.

"Write a blog" runs this chain with no stops, as one autopilot run:
  research   Claude proposes 3 topics (for the next upcoming event, or the brand's usual focus)
  draft      Flowmerce approves the best new topic and Claude writes the draft (SEO fields, product image, notes)
  shopify    a featured image is picked if Claude chose none, the draft is approved and saved as a HIDDEN Shopify draft
A calendar drafting task runs the same chain from its topic.

The 6-hour rule: an article scheduled on the content calendar that nobody has approved by 6 hours before its publish time
is approved automatically and saved as a hidden Shopify draft.

Nothing here publishes. Going live always takes a person: a publish request that a reviewer authorizes. Every automatic
approval is recorded as "Auto-approved by Flowmerce" in the article's review history, the topic's notes and the audit log."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..audit import audit
from ..config import is_brand
from ..db import all_rows, get, now, run
from ..integrations import shopify
from ..util import HttpError, s, similarity
from . import ai_budget
from .brands import brand, brand_settings

log = logging.getLogger(__name__)

Row = dict[str, Any]
AUTO_NAME = "Flowmerce (auto)"
DEADLINE_HOURS = 6
ACTIVE_STEPS = ("research", "draft", "revise")


# ---------------------------------------------------------------- automatic approvals (recorded as such)

def approve_topic(topic: Row, reason: str) -> None:
    """Approve a topic on nobody's behalf. Only a proposed or validated topic; a rejected one stays rejected."""
    if topic["status"] not in ("proposed", "validated"):
        return
    run("UPDATE topics SET status = 'approved', notes = ?, updated_at = ? WHERE id = ?",
        (topic["notes"] + "\n" if topic["notes"] else "") + f"[{AUTO_NAME}] Auto-approved: {reason}", now(), topic["id"])
    audit(None, "topic.auto_approve", "topic", topic["id"], topic["brand_id"], f"{topic['title']}: {reason}")


def approve_article(article_id: int, reason: str) -> bool:
    """Approve the current version of an article on nobody's behalf. Only a draft or one waiting for review: an article a
    reviewer sent back with changes requested is a decision a person made, so it is left alone. Returns True if approved."""
    a = get("SELECT * FROM articles WHERE id = ?", article_id)
    if not a or a["status"] not in ("draft", "in_review") or not (a["body_html"] or "").strip():
        return False
    run("UPDATE articles SET status = 'approved', approved_hash = content_hash, approved_by = NULL, approved_at = ?, review_note = ?, updated_at = ? WHERE id = ?",
        now(), s(f"Auto-approved by Flowmerce: {reason}", 2000), now(), article_id)
    run("INSERT INTO review_notes (article_id, user_id, reviewer_name, kind, note, version, source, created_at) VALUES (?,?,?,?,?,?,?,?)",
        article_id, None, AUTO_NAME, "approved", s(f"Auto-approved by Flowmerce: {reason}", 2000), a["version"], "auto", now())
    audit(None, "article.auto_approve", "article", article_id, a["brand_id"], f"v{a['version']}: {reason}")
    return True


def _acting_user(user_id: int | None) -> Row | None:
    """Shopify saves are recorded against a person: the one who started the run, else the first active admin."""
    u = get("SELECT * FROM users WHERE id = ? AND active = 1", user_id) if user_id else None
    return u or get("SELECT * FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1")


def save_hidden_draft(article_id: int, user_id: int | None) -> str:
    """Save an approved article to Shopify as a hidden draft. Returns what happened, in words."""
    from . import publishing   # imported here: it imports modules that import this one
    a = get("SELECT * FROM articles WHERE id = ?", article_id)
    if not a:
        return "The article no longer exists."
    if not shopify.configured(brand(a["brand_id"])):
        return "Shopify is not connected for this brand, so the draft is in Articles only."
    user = _acting_user(user_id)
    if not user:
        return "No active admin to record the Shopify save against; save it from the article."
    try:
        publishing.save_shopify_draft(user, article_id)
    except HttpError as e:
        return f"Approved, but the Shopify draft was not saved: {e.message}"
    except Exception as e:  # noqa: BLE001 — recorded on the article (last_error) by save_shopify_draft
        return f"Approved, but the Shopify draft was not saved: {getattr(e, 'message', None) or e}"
    return "Saved as a hidden Shopify draft."


# ---------------------------------------------------------------- the one-click run

def _focus(brand_id: str) -> str:
    """The next event whose article can still be live in time, else the brand's usual research focus."""
    from .calendar_plan import upcoming_for_prompt
    today = ai_budget.today()
    for e in upcoming_for_prompt(brand_id):
        if e["publish_by"] >= today:
            return f"Upcoming: {e['name']} on {e['date']} (article live by {e['publish_by']}). {e.get('note') or ''}".strip()
    return brand_settings(brand_id).get("researchFocus") or ""


def _check_money(kinds: tuple[str, ...]) -> None:
    st = ai_budget.status()
    need = sum(ai_budget.ESTIMATE_USD[k] for k in kinds)
    if st["todayUsd"] + need > st["dailyLimitUsd"]:
        raise HttpError(429, f"A full blog needs about ${need:.2f} of Claude time and only ${st['remainingTodayUsd']:.2f} is left today. "
                             "It resets at midnight.", "daily_limit")


def _insert(brand_id: str, user: Row | None, step: str, message: str, **cols: Any) -> Row:
    t = now()
    rid = run("""INSERT INTO autopilot_runs (brand_id, status, step, message, focus, research_job_id, topic_id, draft_job_id, article_id, source,
                                             created_by, created_at, updated_at) VALUES (?, 'running', ?,?,?,?,?,?,?,?,?,?,?)""",
              brand_id, step, message, cols.get("focus", ""), cols.get("research_job_id"), cols.get("topic_id"), cols.get("draft_job_id"),
              cols.get("article_id"), cols.get("source", "button"), user["id"] if user else None, t, t).last_id
    return get_run(rid)


def start(user: Row, brand_id: str, focus: str = "", source: str = "button") -> Row:
    """Write a blog: research, pick, draft, approve and save as a hidden Shopify draft, with no stops. `source` "auto" is
    the automatic blog pipeline (services/auto_blog.py), which adds images and a quality check before approval."""
    from . import ai_jobs, workflow
    if not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    if workflow.is_paused(brand_id):
        raise HttpError(423, "Automation is paused for this brand. Resume it first.", "paused")
    if get("SELECT 1 FROM autopilot_runs WHERE brand_id = ? AND status = 'running'", brand_id):
        raise HttpError(409, "A blog is already being written for this brand. Wait for it to finish.", "already_running")
    _check_money(("topic_research", "content_generation"))
    focus = s(focus, 500).strip() or _focus(brand_id)
    job, _ = ai_jobs.create_job(user, brand_id, "topic_research", {"count": 3, **({"focus": focus} if focus else {})})
    r = _insert(brand_id, user, "research", "Claude is choosing topics", focus=focus, research_job_id=job["id"], source=source)
    audit(user, "autopilot.start", "autopilot_run", r["id"], brand_id, focus[:200])
    return r


def start_from_topic(user_id: int | None, brand_id: str, topic_id: int, reason: str, source: str = "calendar") -> Row:
    """The same chain from a chosen topic (used by calendar drafting tasks): approve it if needed, then draft."""
    from . import ai_jobs
    t = get("SELECT * FROM topics WHERE id = ? AND brand_id = ?", topic_id, brand_id)
    if not t:
        raise HttpError(404, "That topic does not exist for this brand.")
    approve_topic(t, reason)
    job, _ = ai_jobs.create_job(None, brand_id, "content_generation", {"topic_id": topic_id})
    user = get("SELECT * FROM users WHERE id = ?", user_id) if user_id else None
    return _insert(brand_id, user, "draft", "Claude is writing the draft", topic_id=topic_id, draft_job_id=job["id"], source=source)


def get_run(rid: int) -> Row:
    r = get("""SELECT r.*, t.title AS topic_title, a.title AS article_title, a.status AS article_status, a.shopify_article_id
               FROM autopilot_runs r LEFT JOIN topics t ON t.id = r.topic_id LEFT JOIN articles a ON a.id = r.article_id WHERE r.id = ?""", rid)
    if not r:
        raise HttpError(404, "Run not found.")
    return r


def list_runs(brand_id: str | None, limit: int = 10) -> list[Row]:
    where, args = ("WHERE r.brand_id = ?", [brand_id]) if brand_id else ("", [])
    return all_rows(f"""SELECT r.*, t.title AS topic_title, a.title AS article_title, a.status AS article_status, a.shopify_article_id
                        FROM autopilot_runs r LEFT JOIN topics t ON t.id = r.topic_id LEFT JOIN articles a ON a.id = r.article_id
                        {where} ORDER BY r.id DESC LIMIT ?""", *args, limit)


def _set(rid: int, **cols: Any) -> None:
    if cols.get("status") in ("done", "failed"):
        cols["finished_at"] = now()
    cols["updated_at"] = now()
    run(f"UPDATE autopilot_runs SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", *cols.values(), rid)


def _pick_topic(brand_id: str, topic_ids: list[int]) -> Row | None:
    """Claude's topics in Claude's order, skipping any that overlap an existing article."""
    arts = all_rows("SELECT title, primary_keyword FROM articles WHERE brand_id = ?", brand_id)
    for tid in topic_ids:
        t = get("SELECT * FROM topics WHERE id = ? AND brand_id = ? AND status IN ('proposed','validated')", tid, brand_id)
        if not t or get("SELECT 1 FROM articles WHERE topic_id = ?", tid):
            continue
        if any(max(similarity(a["title"], t["title"]), similarity(a["primary_keyword"] or a["title"], t["primary_keyword"])) >= 0.5 for a in arts):
            continue
        return t
    return None


def _advance(r: Row) -> None:
    from . import ai_jobs, workflow
    job_id = {"research": r["research_job_id"], "revise": r.get("revise_job_id")}.get(r["step"], r["draft_job_id"])
    job = get("SELECT * FROM ai_jobs WHERE id = ?", job_id) if job_id else None
    if not job:
        _set(r["id"], status="failed", message="Its Claude job is missing.")
        return
    if job["status"] in ("pending", "queued", "running"):
        if job["status"] == "pending" and (job["message"] or "").startswith("Waiting for tomorrow"):
            _set(r["id"], message="Waiting for tomorrow's Claude limit")
        return
    if job["status"] != "succeeded" and r["step"] == "revise":
        _finish_auto(r, int(r["article_id"]), f"Claude's revision {job['status']}; the draft is kept as it was.")
        return
    if job["status"] != "succeeded":
        _set(r["id"], status="failed", message=f"Claude {job['status']}: {s(job['error'] or '', 300)}")
        if r.get("source") == "auto":
            from . import auto_blog
            auto_blog.run_failed(r, f"Claude {job['status']}: {s(job['error'] or '', 300)}")
        return
    result = json.loads(job["result_json"] or "{}")
    if r["step"] == "research":
        t = _pick_topic(r["brand_id"], [int(x) for x in result.get("topicIds", [])])
        if not t:
            _set(r["id"], status="failed", message="Claude's topics all overlap existing articles. Try again with a different focus.")
            if r.get("source") == "auto":
                from . import auto_blog
                auto_blog.run_failed(r, "Claude's topics all overlap existing articles; the next slot tries again.")
            return
        approve_topic(t, "picked by Write a blog" if r.get("source") != "auto" else "picked by the automatic blog pipeline")
        draft, _ = ai_jobs.create_job(None, r["brand_id"], "content_generation", {"topic_id": t["id"]})
        _set(r["id"], step="draft", topic_id=t["id"], draft_job_id=draft["id"], message="Claude is writing the draft")
        return
    if r["step"] == "revise":
        _finish_auto(r, int(r["article_id"]), "Claude fixed the points the quality check found.")
        return
    aid = result.get("articleId")
    if not aid:
        _set(r["id"], status="failed", message="The draft job finished without an article.")
        return
    if r.get("source") == "auto":
        from . import auto_blog
        revise = auto_blog.after_draft(r, int(aid))
        if revise:
            _set(r["id"], step="revise", article_id=aid, revise_job_id=revise, message="Claude is fixing what the quality check found")
            return
        _finish_auto({**r, "article_id": aid}, int(aid), "The draft passed the quality check.")
        return
    a = get("SELECT image_url FROM articles WHERE id = ?", aid)
    if a and not a["image_url"]:
        workflow._image_selection(r["brand_id"])   # same rule as the Image selection stage
    approved = approve_article(aid, "written by Write a blog" if r["source"] == "button" else "written by a calendar task")
    outcome = save_hidden_draft(aid, r["created_by"]) if approved else "Draft saved; it was not approved automatically because its status changed."
    _set(r["id"], status="done", step="done", article_id=aid, message=outcome)
    audit(None, "autopilot.done", "autopilot_run", r["id"], r["brand_id"], outcome)


def _finish_auto(r: Row, aid: int, note: str) -> None:
    """The end of an automatic run: approve, hidden Shopify draft, publish request on the calendar (auto_blog.finish)."""
    from . import auto_blog
    outcome = auto_blog.finish(r, aid)
    _set(r["id"], status="done", step="done", article_id=aid, message=f"{note} {outcome}")
    audit(None, "autopilot.done", "autopilot_run", r["id"], r["brand_id"], outcome)


def advance_all() -> int:
    """Move every running autopilot run on by one step where its Claude job has finished. Safe to call often."""
    moved = 0
    for r in all_rows("SELECT * FROM autopilot_runs WHERE status = 'running' ORDER BY id"):
        try:
            _advance(r)
            moved += 1
        except HttpError as e:
            if e.code == "daily_limit":
                _set(r["id"], message="Waiting for tomorrow's Claude limit")
            else:
                _set(r["id"], status="failed", message=e.message)
        except Exception as e:  # noqa: BLE001 — one broken run must not stop the others; it is recorded on the run
            log.exception("Autopilot run %s failed", r["id"])
            _set(r["id"], status="failed", message=f"Unexpected error: {type(e).__name__}")
    return moved


# ---------------------------------------------------------------- the 6-hour rule

def enforce_deadlines(now_utc: datetime | None = None) -> int:
    """Approve, and save as hidden Shopify drafts, calendar-scheduled articles nobody approved by 6 hours before publish time."""
    from .calendar_plan import _publish_at
    t = now_utc or datetime.now(timezone.utc)
    done = 0
    for e in all_rows("""SELECT cs.*, a.status AS article_status FROM content_schedule cs JOIN articles a ON a.id = cs.article_id
                         WHERE cs.action = 'publish' AND cs.status = 'planned' AND a.status IN ('draft','in_review')"""):
        publish_at = datetime.fromisoformat(_publish_at(e["run_on"]).replace("Z", "+00:00"))
        if t < publish_at - timedelta(hours=DEADLINE_HOURS) or t >= publish_at:
            continue
        if approve_article(e["article_id"], f"nobody approved it by {DEADLINE_HOURS} hours before its scheduled publish time ({e['run_on']})"):
            outcome = save_hidden_draft(e["article_id"], e["created_by"])
            run("UPDATE content_schedule SET message = ?, updated_at = ? WHERE id = ?",
                f"Auto-approved 6 hours before publish time. {outcome} Publishing still needs a reviewer.", now(), e["id"])
            done += 1
    return done
