"""The blogging pipeline, stage by stage. Each stage is either run by this server (Claude calls, checks,
analytics syncs) or waits on a person. Stage health comes from real records: the last run, its error, and how
many items are waiting at that stage. There is no Shopify draft stage: drafts stay in Flowmerce until a publish
request is authorized (owner decision 2026-11-24; runs recorded under the old "shopify_draft" stage stay in history)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

from ..audit import audit
from ..config import config
from ..db import all_rows, get, now, run, tx
from ..integrations import claude
from ..integrations.google import ga4_configured, gsc_configured
from ..util import HttpError, norm_keyword, s, similarity
from .articles import content_of, create_article, hash_content
from .brands import brand, brand_settings
from .runs import last_run, record_run
from .sync import sync_ga4, sync_gsc, sync_shopify

STAGES = [
    {"key": "topic_research", "label": "Topic research", "kind": "automated", "owner": "Claude", "description": "Claude proposes topics from the catalogue, existing articles and Search Console queries."},
    {"key": "keyword_validation", "label": "Keyword validation", "kind": "automated", "owner": "Dashboard", "description": "Checks each proposed keyword against imported keyword data, Search Console and existing articles for overlap."},
    {"key": "topic_approval", "label": "Topic approval", "kind": "human", "owner": "SEO Manager", "description": "A person approves or rejects validated topics."},
    {"key": "content_generation", "label": "Content generation", "kind": "automated", "owner": "Claude", "description": "Claude writes a first draft for approved topics, with internal links to real products."},
    {"key": "content_approval", "label": "Content approval", "kind": "human", "owner": "Reviewer", "description": "A reviewer approves the draft or sends it back with notes."},
    {"key": "image_selection", "label": "Image selection", "kind": "automated", "owner": "Dashboard", "description": "Picks a featured image from the product a draft links to; editors can change it."},
    {"key": "publication_approval", "label": "Publication approval", "kind": "human", "owner": "Reviewer / Admin", "description": "An authorized person approves the publish request and confirms it."},
    {"key": "performance_tracking", "label": "Performance tracking", "kind": "automated", "owner": "Dashboard", "description": "Refreshes Shopify, Search Console and GA4 data."},
]

HUMAN_ACTION = {
    "keyword_validation": "Import keyword volumes for topics the check could not size",
    "topic_approval": "Approve or reject validated topics",
    "content_generation": "Generate drafts for approved topics",
    "content_approval": "Review drafts waiting for approval",
    "image_selection": "Choose featured images",
    "publication_approval": "Authorize or reject publish requests",
}


AI_STAGES = ("topic_research", "content_generation")   # stages that call Claude: they only ever run as background AI jobs


def is_paused(brand_id: str) -> bool:
    return bool(get("SELECT paused FROM automation_state WHERE brand_id = ? AND paused = 1", brand_id))


def set_paused(user: dict, brand_id: str, paused: bool, reason: str) -> None:
    run("""INSERT INTO automation_state (brand_id, paused, paused_by, paused_at, reason) VALUES (?,?,?,?,?)
           ON CONFLICT(brand_id) DO UPDATE SET paused=excluded.paused, paused_by=excluded.paused_by, paused_at=excluded.paused_at, reason=excluded.reason""",
        brand_id, 1 if paused else 0, user["id"], now(), s(reason, 500))
    audit(user, "automation.pause" if paused else "automation.resume", "automation", brand_id, brand_id, reason)


def _setup_gap(stage: str, brand_id: str) -> str | None:
    brand(brand_id)   # an unknown brand raises here
    if stage in AI_STAGES:
        from . import ai_jobs   # imported here: ai_jobs imports this module
        ps = ai_jobs.provider_status()
        return None if ps["state"] in ("ready", "unavailable") else ps["reason"]
    return None


def _pending(stage: str, brand_id: str) -> int:
    q = {
        "keyword_validation": "SELECT COUNT(*) n FROM topics WHERE brand_id = ? AND status = 'proposed'",
        "topic_approval": "SELECT COUNT(*) n FROM topics WHERE brand_id = ? AND status = 'validated'",
        "content_generation": "SELECT COUNT(*) n FROM topics t WHERE brand_id = ? AND status = 'approved' AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.topic_id = t.id)",
        "content_approval": "SELECT COUNT(*) n FROM articles WHERE brand_id = ? AND status = 'in_review'",
        "image_selection": "SELECT COUNT(*) n FROM articles WHERE brand_id = ? AND status IN ('draft','changes_requested','in_review','approved') AND image_url = ''",
        "publication_approval": "SELECT COUNT(*) n FROM publish_requests WHERE brand_id = ? AND status IN ('pending','failed')",
    }.get(stage)
    return int(get(q, brand_id)["n"]) if q else 0


def pipeline(brand_id: str) -> list[dict]:
    paused = is_paused(brand_id)
    out = []
    for st in STAGES:
        last = last_run(brand_id, st["key"])
        pending = _pending(st["key"], brand_id)
        gap = _setup_gap(st["key"], brand_id)
        if gap:
            state = "pending_setup"
        elif last and last["status"] == "running":
            state = "running"
        elif last and last["status"] == "failed":
            state = "failed"
        elif paused and st["kind"] == "automated":
            state = "paused"
        elif pending > 0:
            state = "needs_action"
        elif last:
            state = "ok"
        else:
            state = "idle"
        out.append({
            **st, "state": state, "pending": pending, "setupGap": gap,
            "humanAction": HUMAN_ACTION.get(st["key"]) if pending > 0 else None,
            "lastRun": {"id": last["id"], "status": last["status"], "started_at": last["started_at"], "finished_at": last["finished_at"],
                        "message": last["message"], "error": last["error"], "trigger": last["trigger_kind"]} if last else None,
        })
    return out


# ---------------- stage runners ----------------

def topic_research_context(brand_id: str) -> dict:
    """What topic research is given: existing titles to avoid, products worth linking, and queries that already bring visitors."""
    return {
        "existing_titles": [r["title"] for r in all_rows("SELECT title FROM articles WHERE brand_id = ? UNION SELECT title FROM topics WHERE brand_id = ?", brand_id, brand_id)],
        "products": [r["title"] for r in all_rows("SELECT title FROM products WHERE brand_id = ? LIMIT 80", brand_id)],
        "queries": [r["query"] for r in all_rows("SELECT query, SUM(impressions) imp FROM gsc_query_period WHERE brand_id = ? AND source != 'demo' GROUP BY query ORDER BY imp DESC LIMIT 40", brand_id)],
    }


def draft_links(brand_id: str, about: str = "") -> list[dict]:
    """Real internal-link targets a draft may use: synced products (with their images) and already published articles.
    With `about` (the topic's title and keywords), the products whose titles share the most words with it come first."""
    words = {w for w in re.findall(r"[a-z0-9]+", about.lower()) if len(w) > 2}
    products = all_rows("SELECT title, url, image_url FROM products WHERE brand_id = ?", brand_id)
    if words:
        products.sort(key=lambda p: -len(words & set(re.findall(r"[a-z0-9]+", p["title"].lower()))))
    return [{**p, "kind": "product"} for p in products[:60]] + [
        {**a, "kind": "article"} for a in
        all_rows("SELECT title, live_url AS url FROM articles WHERE brand_id = ? AND shopify_published = 1 AND live_url IS NOT NULL LIMIT 20", brand_id)]


def _keyword_validation(brand_id: str) -> dict:
    topics = all_rows("SELECT * FROM topics WHERE brand_id = ? AND status = 'proposed'", brand_id)
    arts = all_rows("SELECT id, title, primary_keyword FROM articles WHERE brand_id = ?", brand_id)
    validated = unsized = overlaps = 0
    with tx():
        for t in topics:
            kw = get("SELECT * FROM keywords WHERE brand_id = ? AND keyword_norm = ?", brand_id, t["keyword_norm"])
            g = get("SELECT SUM(impressions) imp, SUM(clicks) clk FROM gsc_query_period WHERE brand_id = ? AND source != 'demo' AND lower(query) = lower(?)", brand_id, t["primary_keyword"])
            clash = max(((a, max(similarity(a["title"], t["title"]), similarity(a["primary_keyword"] or a["title"], t["primary_keyword"]))) for a in arts),
                        key=lambda x: x[1], default=(None, 0.0))
            notes: list[str] = []
            vol, kd, vsrc = t["search_volume"], t["keyword_difficulty"], t["volume_source"]
            if kw and kw["search_volume"] is not None:
                vol, kd = kw["search_volume"], kw["keyword_difficulty"]
                vsrc = kw["source_tool"] + (f" · {kw['source_date']}" if kw["source_date"] else "")
                notes.append(f"Volume {kw['search_volume']}/mo from {kw['source_tool']}.")
            if g and g["imp"]:
                notes.append(f"Search Console: {g['imp']} impressions, {g['clk']} clicks in the last 28 days already.")
            overlapping = clash[0] is not None and clash[1] >= 0.5
            if overlapping:
                notes.append(f"Overlaps “{clash[0]['title']}” (similarity {round(clash[1] * 100)}%). Consider updating that article instead.")
                overlaps += 1
            sized = vol is not None or bool(g and g["imp"])
            if not sized:
                notes.append("No volume data yet: import it from your keyword tool (Data & Reports → Keywords).")
                unsized += 1
            status = "validated" if sized and not overlapping else "proposed"
            validated += status == "validated"
            run("UPDATE topics SET status=?, search_volume=?, keyword_difficulty=?, volume_source=?, validation_note=?, updated_at=? WHERE id=?",
                status, vol, kd, vsrc, " ".join(notes), now(), t["id"])
    msg = (f"{validated} of {len(topics)} validated · {unsized} need volume data · {overlaps} overlap existing articles"
           if topics else "No proposed topics to check")
    return {"message": msg, "details": {"checked": len(topics), "validated": validated, "unsized": unsized, "overlaps": overlaps},
            "status": "waiting" if topics and validated < len(topics) else "succeeded"}


def _image_selection(brand_id: str) -> dict:
    """Only drafts are touched: an image is part of the content, so picking one for an article under
    review or approved would void that review. Those are left for a person to choose."""
    arts = all_rows("SELECT * FROM articles WHERE brand_id = ? AND status IN ('draft','changes_requested') AND image_url = ''", brand_id)
    products = all_rows("SELECT title, url, image_url FROM products WHERE brand_id = ? AND image_url != ''", brand_id)
    if not products:
        return {"message": "No product images synced yet — run Performance tracking (Shopify sync) first", "status": "waiting"}
    picked = 0
    with tx():
        for a in arts:
            best = next((p for p in products if p["url"] in a["body_html"] or urlparse(p["url"]).path in a["body_html"]), None)
            if not best:
                scored = sorted(((p, similarity(p["title"], a["primary_keyword"] + " " + a["title"])) for p in products), key=lambda x: -x[1])
                best = scored[0][0] if scored and scored[0][1] > 0.15 else None
            if not best:
                continue
            c = {**content_of(a), "image_url": best["image_url"], "image_alt": a["image_alt"] or best["title"]}
            h, v = hash_content(c), a["version"] + 1
            run("UPDATE articles SET image_url=?, image_alt=?, content_hash=?, version=?, updated_at=? WHERE id=?", c["image_url"], c["image_alt"], h, v, now(), a["id"])
            run("INSERT INTO article_revisions (article_id, version, data_json, content_hash, user_id, note, created_at) VALUES (?,?,?,?,?,?,?)",
                a["id"], v, json.dumps(c, ensure_ascii=False), h, None, f"Featured image picked from “{best['title']}”", now())
            picked += 1
    waiting = _pending("image_selection", brand_id)
    return {"message": f"{picked} of {len(arts)} drafts given an image" + (f" · {waiting} still need one chosen by an editor" if waiting else ""),
            "details": {"picked": picked, "considered": len(arts)}, "status": "waiting" if waiting else "succeeded"}


def _performance_tracking(brand_id: str) -> dict:
    b = brand(brand_id)
    parts, errors = [], []

    def attempt(label: str, fn) -> None:
        try:
            fn(brand_id)
            parts.append(f"{label} ✓")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {getattr(e, 'message', None) or e}")

    attempt("Shopify", sync_shopify)
    if gsc_configured(b):
        attempt("Search Console", sync_gsc)
    else:
        parts.append("Search Console not set up")
    if ga4_configured(b):
        attempt("GA4", sync_ga4)
    else:
        parts.append("GA4 not set up")
    if errors and not any(p.endswith("✓") for p in parts):
        raise RuntimeError(" · ".join(errors))
    return {"message": " · ".join(parts + errors), "details": {"errors": errors}, "status": "failed" if errors else "succeeded"}


def _queue_ai_stage(stage: str, brand_id: str, user: dict | None, topic_id: int | None) -> dict:
    """Run an AI stage as database-backed AI job(s) instead of calling Claude inside the request. Permissions, brand, pause and
    setup checks were already done by run_stage; ai_jobs.create_job repeats the brand/pause/setup checks and validates the input.
    Content generation makes one job per approved topic (the one asked for, or up to the brand's drafts-per-run). Returns at once:
    status "queued" with the job(s), or "skipped" when there is nothing to do. Nothing here approves or publishes."""
    from . import ai_jobs
    if stage == "topic_research":
        pairs = [ai_jobs.create_job(user, brand_id, "topic_research", None)]
    else:
        if topic_id:
            ids = [int(topic_id)]
        else:
            ids = [t["id"] for t in all_rows("""SELECT id FROM topics t WHERE brand_id = ? AND status = 'approved' AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.topic_id = t.id)
                                                ORDER BY COALESCE(search_volume, 0) DESC LIMIT ?""", brand_id, brand_settings(brand_id)["draftsPerRun"])]
        if not ids:
            return {"id": None, "status": "skipped", "message": "No approved topics waiting for a draft"}
        pairs = [ai_jobs.create_job(user, brand_id, "content_generation", {"topic_id": tid}) for tid in ids]
    new = sum(1 for _, existing in pairs if not existing)
    msg = (f"{new} AI job{'' if new == 1 else 's'} queued" if new else "Already queued") + (f" ({len(pairs) - new} already queued)" if new and len(pairs) > new else "")
    first = pairs[0][0]
    return {"id": first["workflow_run_id"], "status": "queued", "message": msg, "job": ai_jobs.public(first), "jobs": [ai_jobs.public(j) for j, _ in pairs]}


def run_stage(stage: str, brand_id: str, user: dict | None, trigger: str, topic_id: int | None = None, retry_of: int | None = None) -> dict:
    d = next((x for x in STAGES if x["key"] == stage), None)
    if not d:
        raise HttpError(404, "Unknown stage.")
    if d["kind"] == "human":
        raise HttpError(400, f"{d['label']} is done by a person, not run.")
    if is_paused(brand_id):
        raise HttpError(423, "Automation is paused for this brand. Resume it to run stages.", "paused")
    gap = _setup_gap(stage, brand_id)
    if gap:
        raise HttpError(412, gap, "pending_setup")
    if stage in AI_STAGES:
        if user:
            audit(user, "workflow.retry" if trigger == "retry" else "workflow.run", "stage", stage, brand_id, d["label"])
        return _queue_ai_stage(stage, brand_id, user, topic_id)
    if get("SELECT id FROM workflow_runs WHERE brand_id = ? AND stage = ? AND status = 'running'", brand_id, stage):
        raise HttpError(409, "This stage is already running.")
    if user:
        audit(user, "workflow.retry" if trigger == "retry" else "workflow.run", "stage", stage, brand_id, d["label"])
    runners = {
        "keyword_validation": lambda: _keyword_validation(brand_id),
        "image_selection": lambda: _image_selection(brand_id),
        "performance_tracking": lambda: _performance_tracking(brand_id),
    }
    return record_run(brand_id, stage, trigger, user, runners[stage], retry_of)


def retry_run(user: dict, run_id: int) -> dict:
    r = get("SELECT * FROM workflow_runs WHERE id = ?", run_id)
    if not r:
        raise HttpError(404, "Run not found.")
    if r["status"] != "failed":
        raise HttpError(409, "Only failed runs can be retried.")
    if r["trigger_kind"] == "ai_job":
        raise HttpError(409, "This run belongs to an AI job. Retry it from the AI jobs list.", "ai_job_run")
    return run_stage(r["stage"], r["brand_id"], user, "retry", retry_of=run_id)


def list_runs(brand_id: str | None, stage: str, status: str, limit: int = 100) -> list[dict]:
    where, args = [], []
    if brand_id:
        where.append("r.brand_id = ?"); args.append(brand_id)
    if stage:
        where.append("r.stage = ?"); args.append(stage)
    if status:
        where.append("r.status = ?"); args.append(status)
    return all_rows(f"""SELECT r.*, u.name AS user_name FROM workflow_runs r LEFT JOIN users u ON u.id = r.user_id
                        {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY r.id DESC LIMIT ?""", *args, min(limit, 500))


LEGACY_STATUSES = ("running", "succeeded", "failed", "waiting", "skipped")


def _iso_or_now(v: object) -> str:
    """A caller-supplied timestamp is kept only if it is a real ISO-8601 time; otherwise the server's clock is used."""
    if isinstance(v, str) and len(v) <= 40:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            pass
    return now()


def ingest_webhook(body: dict) -> dict:
    """LEGACY callback (no job_id): an external agent reports a stage status and Flowmerce logs one run row per call.
    Kept for existing integrations and due to be retired in favour of AI job callbacks (apply_event in ai_jobs.py).
    It can only append a log row: it cannot carry a result, create records or touch any other table. The status must
    be one of LEGACY_STATUSES; an invalid or missing status is rejected, never turned into "succeeded"."""
    b, stage = body.get("brand"), body.get("stage")
    if b not in ("ridhi", "cpc"):
        raise HttpError(400, "brand must be ridhi or cpc")
    if not any(x["key"] == stage for x in STAGES):
        raise HttpError(400, "unknown stage")
    if "result" in body:
        raise HttpError(400, "Results are only accepted for AI jobs: create a job and report with its job_id.", "result_requires_job")
    status = body.get("status")
    if status not in LEGACY_STATUSES:
        raise HttpError(400, f"status must be one of: {', '.join(LEGACY_STATUSES)}", "invalid_status")
    t = _iso_or_now(body.get("finished_at"))
    rid = run("""INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, message, error, details_json, started_at, finished_at)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
              b, stage, status, "webhook", s(body.get("message"), 1000), s(body.get("error"), 2000) or None,
              json.dumps({"agent": s(body.get("agent"), 120), "externalId": s(body.get("external_id"), 200), "legacy": True}),
              _iso_or_now(body.get("started_at")) if body.get("started_at") else t, None if status == "running" else t).last_id
    audit(None, "workflow.webhook", "stage", stage, b, f"{status}: {s(body.get('message'), 200)}")
    return {"id": rid}


def automation_configured() -> dict:
    return {"claude": claude.configured(), "webhook": bool(config.workflow_webhook_secret)}
