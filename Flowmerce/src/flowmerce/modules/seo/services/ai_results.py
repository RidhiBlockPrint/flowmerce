"""Validation and storage of what an AI job produced. Nothing a worker or Claude returns is trusted: the result
must match the job's task type exactly (known fields only, size and length limits, no script markup) and it
may only create records of the kind that task is allowed to create:

  topic_research      -> new topics with status "proposed" (a person still validates and approves them)
  content_generation  -> one article with status "draft", linked to the already approved topic named in the job

A result never approves, publishes, schedules, or changes an existing record. validate() has no side effects;
store() writes, and is called inside the caller's transaction so the job and its result change together."""
from __future__ import annotations

import json
import re
from typing import Any

from ..db import all_rows, get, now, run
from ..util import norm_keyword, s, strip_html
from .articles import create_article
from .brands import brand_settings

Job = dict[str, Any]
MAX_RESULT_BYTES = 256 * 1024
MAX_TOPICS = 50          # absolute ceiling; a job is held to the count it asked for (at most MAX_REQUESTED)
MAX_REQUESTED = 20       # the most topics one research job may ask for
INTENTS = ("informational", "commercial", "transactional", "navigational")
TOPIC_FIELDS = {"title", "primary_keyword", "secondary_keywords", "intent", "rationale"}
DRAFT_FIELDS = {"title", "handle", "meta_title", "meta_description", "summary_html", "body_html", "tags", "image_alt"}
_DANGEROUS = re.compile(r"<\s*/?\s*(script|iframe|object|embed|form|svg|math|style|link|meta|base)\b|<[^>]*\bon\w+\s*=|javascript\s*:|data\s*:\s*text/html", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HANDLE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ResultError(ValueError):
    """The result is not acceptable for this job. The message is safe to show to staff and to return to the worker."""


def _text(d: Job, key: str, max_len: int, required: bool = True) -> str:
    v = d.get(key)
    if v is None and not required:
        return ""
    if not isinstance(v, str):
        raise ResultError(f"{key} must be text.")
    v = v.strip()
    if required and not v:
        raise ResultError(f"{key} is required.")
    if len(v) > max_len:
        raise ResultError(f"{key} is longer than {max_len} characters.")
    if _CONTROL.search(v):
        raise ResultError(f"{key} contains control characters.")
    if _DANGEROUS.search(v):
        raise ResultError(f"{key} contains markup that is not allowed (script, frames, forms or event handlers).")
    return v


def _text_list(d: Job, key: str, max_items: int, max_len: int, required: bool = False) -> list[str]:
    v = d.get(key)
    if v is None and not required:
        return []
    if not isinstance(v, list) or len(v) > max_items:
        raise ResultError(f"{key} must be a list of at most {max_items} items.")
    return [_text({key: x}, key, max_len) for x in v]


def _exact_keys(d: Any, allowed: set[str], where: str) -> Job:
    if not isinstance(d, dict):
        raise ResultError(f"{where} must be an object.")
    extra = set(d) - allowed
    if extra:
        raise ResultError(f"{where} has fields that are not allowed: {', '.join(sorted(map(str, extra))[:5])}.")
    return d


def default_count(brand_id: str) -> int:
    """The brand's configured topics-per-run, kept within what a job may ask for."""
    try:
        n = int(brand_settings(brand_id)["topicsPerRun"])
    except (KeyError, TypeError, ValueError):
        n = 5
    return max(1, min(MAX_REQUESTED, n))


def requested_count(job: Job) -> int | None:
    """How many topics this job asked for (None for tasks that do not return a list). It is the count recorded on the job; a job
    without one (created before counts were recorded) falls back to the brand's configured default."""
    if job["task_type"] != "topic_research":
        return None
    c = json.loads(job["input_json"] or "{}").get("count")
    return c if isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= MAX_REQUESTED else default_count(job["brand_id"])


def validate(task_type: str, result: Any, limit: int | None = None) -> Job:
    """The cleaned result for task_type, or ResultError. Pure: writes nothing. `limit` is the most topics a topic research
    result may hold (the job's requested count); a longer list is rejected whole, so no topic is created."""
    if not isinstance(result, dict):
        raise ResultError("The result must be an object.")
    try:
        size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as e:
        raise ResultError("The result is not valid JSON data.") from e
    if size > MAX_RESULT_BYTES:
        raise ResultError(f"The result is larger than {MAX_RESULT_BYTES // 1024} KB.")
    if task_type == "topic_research":
        return _validate_topics(result, limit)
    if task_type == "content_generation":
        return _validate_draft(result)
    raise ResultError(f"Task type {task_type!r} does not accept results.")


def _validate_topics(result: Job, limit: int | None = None) -> Job:
    _exact_keys(result, {"topics"}, "The result")
    topics = result.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ResultError("topics must be a non-empty list.")
    cap = min(MAX_TOPICS, limit) if limit else MAX_TOPICS
    if len(topics) > cap:
        raise ResultError(f"{len(topics)} topics were returned but only {cap} {'was' if cap == 1 else 'were'} requested.")
    out = []
    for i, t in enumerate(topics, 1):
        t = _exact_keys(t, TOPIC_FIELDS, f"Topic {i}")
        intent = t.get("intent")
        if intent not in INTENTS:
            raise ResultError(f"Topic {i}: intent must be one of {', '.join(INTENTS)}.")
        out.append({"title": _text(t, "title", 255), "primary_keyword": _text(t, "primary_keyword", 200),
                    "secondary_keywords": _text_list(t, "secondary_keywords", 10, 100), "intent": intent,
                    "rationale": _text(t, "rationale", 2000, required=False)})
    return {"topics": out}


def _validate_draft(result: Job) -> Job:
    _exact_keys(result, DRAFT_FIELDS, "The result")
    missing = [f for f in ("title", "body_html") if not result.get(f)]
    if missing:
        raise ResultError(f"{', '.join(missing)} is required.")
    handle = _text(result, "handle", 120, required=False)
    if handle and not _HANDLE.match(handle):
        raise ResultError("handle must be lowercase letters, digits and hyphens.")
    body = _text(result, "body_html", 200_000)
    if len(strip_html(body)) < 100:
        raise ResultError("body_html has too little text to be an article.")
    return {"title": _text(result, "title", 255), "handle": handle, "meta_title": _text(result, "meta_title", 120, required=False),
            "meta_description": _text(result, "meta_description", 400, required=False), "summary_html": _text(result, "summary_html", 5000, required=False),
            "body_html": body, "tags": _text_list(result, "tags", 30, 60), "image_alt": _text(result, "image_alt", 300, required=False)}


def store(job: Job, clean: Job) -> Job:
    """Write a validated result and return a small summary for the job record. Call inside a transaction.
    Raises ResultError, before writing anything, when the business state no longer fits the job."""
    if job["task_type"] == "topic_research":
        return _store_topics(job, clean)
    if job["task_type"] == "content_generation":
        return _store_draft(job, clean)
    raise ResultError("This task type does not accept results.")


def _store_topics(job: Job, clean: Job) -> Job:
    ids: list[int] = []
    dupes = 0
    for t in clean["topics"]:
        norm = norm_keyword(t["primary_keyword"])
        if not norm or get("SELECT 1 FROM topics WHERE brand_id = ? AND keyword_norm = ?", job["brand_id"], norm):
            dupes += 1
            continue
        ids.append(run("""INSERT INTO topics (brand_id, title, primary_keyword, keyword_norm, secondary_keywords, intent, rationale, status, source, created_by, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,?, 'proposed', 'claude', NULL, ?, ?)""",
                       job["brand_id"], s(t["title"], 255), s(t["primary_keyword"], 200), norm, ", ".join(t["secondary_keywords"]),
                       t["intent"], s(t["rationale"], 2000), now(), now()).last_id)
    return {"kind": "topics", "topicIds": ids, "added": len(ids), "duplicatesSkipped": dupes,
            "summary": f"{len(ids)} topic{'' if len(ids) == 1 else 's'} proposed" + (f", {dupes} duplicate{'' if dupes == 1 else 's'} skipped" if dupes else "")}


def _store_draft(job: Job, clean: Job) -> Job:
    topic_id = json.loads(job["input_json"]).get("topic_id")
    topic = get("SELECT * FROM topics WHERE id = ? AND brand_id = ?", topic_id, job["brand_id"]) if topic_id else None
    if not topic or topic["status"] != "approved":
        raise ResultError("The topic is not approved any more, so the draft was not saved.")
    if all_rows("SELECT id FROM articles WHERE topic_id = ? LIMIT 1", topic["id"]):
        raise ResultError("This topic already has an article, so the draft was not saved.")
    st = brand_settings(job["brand_id"])
    a = create_article(None, job["brand_id"], {
        **clean, "primary_keyword": topic["primary_keyword"], "tags": clean["tags"], "author": st["defaultAuthor"], "topic_id": topic["id"],
    }, "claude", "draft")
    run("UPDATE topics SET status='in_production', updated_at=? WHERE id=?", now(), topic["id"])
    run("UPDATE article_revisions SET note=? WHERE article_id=? AND version=1", f"First draft by an AI job ({job['id']})", a["id"])
    return {"kind": "article", "articleId": a["id"], "topicId": topic["id"], "summary": f"Draft saved: {a['title']}"}
