"""AI jobs: the persistent record of work handed to Claude, directly or through an external worker.

The database is the source of truth. A job row is written before anything runs, so a restart never loses work.
Status vocabulary (identical in the database, the API and the dashboard):

  pending     saved, not yet taken by an executor (also: waiting for a retry, or for a worker that is unavailable)
  queued      an external worker accepted it (event "accepted"); never used for an unavailable provider
  running     an executor is working on it
  succeeded / failed / cancelled   final; nothing can change a final job except a person retrying a failed one

"pending_setup" is not a job status: when no execution method is configured, creating a job is refused with
HTTP 412 / code pending_setup and no job is created. "accepted" is an event, not a status.

Executors: the local runner (anthropic_api mode) claims a pending job atomically, holds a lease while it works,
and writes the outcome only if it still holds that lease. In external_worker mode the same runner dispatches the
job over HTTP and the worker reports back through apply_event(). Concurrency is bounded. This is built for ONE
Flowmerce process on one SQLite file (the local-operator setup): the claim is atomic inside this process's
database lock, not across several servers. Do not run two instances against the same database.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from ..audit import audit
from ..config import config, is_brand
from ..db import all_rows, get, now, run, tx
from ..integrations import ai_worker, claude
from ..integrations.status import mark_error, mark_success, status_of
from ..util import HttpError, s
from . import ai_budget, ai_results, calendar_plan, workflow
from .brands import brand, brand_settings

log = logging.getLogger(__name__)

Job = dict[str, Any]   # a database row or its public view

# task type -> workflow stage. A revision is content work on an existing draft, so it runs in the content stage.
TASKS = {"topic_research": "topic_research", "content_generation": "content_generation", "content_revision": "content_generation"}
MAX_INSTRUCTIONS = 4000
TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"queued", "running", "failed", "cancelled"}),
    "queued": frozenset({"running", "succeeded", "failed", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "pending"}),   # running -> pending: interrupted or retrying, internal only
    "failed": frozenset({"pending"}),                                         # a person retried it
    "succeeded": frozenset(),
    "cancelled": frozenset(),
}
ACTIVE = ("pending", "queued", "running")
EVENT_STATUS = {"accepted": "queued", "started": "running", "progress": "running", "succeeded": "succeeded", "failed": "failed"}
WEBHOOK_MAX_BYTES = 64 * 1024
EVENT_KEYS = {"event_id", "job_id", "event_type", "status", "sequence", "run_number", "message", "agent", "external_id", "progress",
              "result", "error", "brand", "stage", "occurred_at", "callback_reference"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")
CLOCK_SKEW = timedelta(minutes=5)
MAX_EVENTS_PER_JOB = 2000   # a leaked secret cannot grow one job's history (or keep extending its deadline) without limit
OWNER = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"   # identifies this process / runner; every claim adds its own unique token to it


def _new_token(owner: str) -> str:
    """A lease token that exists for exactly one claim of one job: runner identity + a random value."""
    return f"{owner}:{uuid.uuid4().hex}"


def _holds(job: Job | None, token: str | None) -> bool:
    """True only if `token` is the job's current lease token AND that lease has not expired. Every write made by an executor
    is gated on this, so an execution that outlived its lease (or whose job was reclaimed) can never change the job."""
    return bool(job and token and job["lease_owner"] == token and job["lease_expires_at"] and job["lease_expires_at"] > now())


class JobError(RuntimeError):
    """A job cannot run for a reason retrying will not fix."""


# ---------------------------------------------------------------- helpers

def _in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def lease_seconds() -> int:
    """How long a running job may hold its lease: AI_LEASE_SECONDS, but never less than the worst case of one Claude call
    (timeout x (retries + 1), plus backoff and two minutes of margin), so a slow call is not mistaken for a dead executor."""
    worst = config.claude_timeout * (config.claude_max_retries + 1) + 120
    return max(config.ai_lease_seconds, worst)


def dispatch_lease_seconds() -> int:
    """How long a job is reserved while it is being sent to the worker: longer than the worker request can take."""
    return max(120, config.ai_worker_timeout * 2 + 30)


def can_transition(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())


def _event(job_id: str, kind: str, message: str, status: str | None = None, progress: int | None = None) -> None:
    run("INSERT INTO ai_job_events (job_id, event_id, source, event_type, status, progress, message, created_at) VALUES (?,?,?,?,?,?,?,?)",
        job_id, f"local:{uuid.uuid4().hex}", "system", kind, status, progress, s(message, 1000), now())


def _sync_run(job: Job) -> None:
    """Keep the job's single workflow_runs row in step (one row per job, never one per callback)."""
    if not job.get("workflow_run_id"):
        return
    st = job["status"]
    run_status = {"succeeded": "succeeded", "failed": "failed", "cancelled": "skipped"}.get(st, "running")
    done = st in ("succeeded", "failed", "cancelled")
    run("UPDATE workflow_runs SET status=?, message=?, error=?, details_json=?, finished_at=? WHERE id=?",
        run_status, s(job["message"] or st, 1000), s(job["error"], 2000) if st == "failed" else None,
        json.dumps({"jobId": job["id"], "provider": job["provider"], "progress": job["progress"], "externalId": job["external_id"], "workerId": job["worker_id"]}),
        job["finished_at"] if done else None, job["workflow_run_id"])


_COLUMNS = {"worker_id", "external_id", "progress", "message", "error", "error_kind", "result_json", "last_sequence", "lease_owner", "lease_expires_at",
            "next_attempt_at", "accepted_at", "started_at", "last_progress_at", "finished_at", "retry_count", "run_number", "attempts"}


def _update(job_id: str, to: str, *, owner: str | None = None, event: tuple[str, str] | None = None, **fields: Any) -> Job | None:
    """Move a job to `to` and set `fields`, in one transaction, together with its workflow run. Returns the new row.
    `owner` is a lease token: returns None (and writes nothing) unless it is the job's current, unexpired lease token.
    Raises HttpError(409, invalid_transition) when the move is not allowed."""
    unknown = set(fields) - _COLUMNS
    if unknown:
        raise ValueError(f"unknown job columns: {unknown}")
    with tx():
        cur = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
        if not cur:
            raise HttpError(404, "Job not found.", "unknown_job")
        if owner is not None and not _holds(cur, owner):
            return None
        final = cur["status"] in ("succeeded", "failed", "cancelled")
        if (to != cur["status"] or final) and not can_transition(cur["status"], to):   # a final job cannot even be "updated in place"
            raise HttpError(409, f"A {cur['status']} job cannot become {to}.", "invalid_transition")
        t = now()
        if to in ("succeeded", "failed", "cancelled"):
            fields.setdefault("finished_at", t)
        if to == "running" and not cur["started_at"]:
            fields.setdefault("started_at", t)
        cols = ", ".join(f"{k} = ?" for k in fields)
        run(f"UPDATE ai_jobs SET status = ?, updated_at = ?{', ' + cols if cols else ''} WHERE id = ?", to, t, *fields.values(), job_id)
        row = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
        assert row is not None
        _sync_run(row)
        if event:
            _event(job_id, event[0], event[1], to, row["progress"])
        return row


def transition(job_id: str, to: str, **fields: Any) -> Job:
    """Public, checked status change (used by tests and tools). See _update for the rules."""
    row = _update(job_id, to, **fields)
    assert row is not None
    return row


# ---------------------------------------------------------------- provider status

def provider_status() -> Job:
    """Which execution method is configured and whether it can take work. state: ready, pending_setup, unavailable, disabled.
    `missing` is the main thing to fix (anthropic_api_key, worker_config, webhook_secret or callback_url) and `missingAll` lists
    every missing item (worker_url, worker_token, webhook_secret, callback_url), so the dashboard can say exactly what is wrong.
    External-worker mode also needs WORKFLOW_WEBHOOK_SECRET: without it Flowmerce cannot authenticate the worker's callbacks."""
    mode = config.ai_execution_mode
    base: Job = {"mode": mode, "state": "disabled", "missing": None, "missingAll": [], "notes": [], "model": None,
                 "reason": "AI execution is switched off (AI_EXECUTION_MODE=disabled).",
                 "callbackConfigured": bool(ai_worker.callback_url()), "webhookConfigured": bool(config.workflow_webhook_secret)}
    if mode == "anthropic_api":
        if not claude.configured():
            return {**base, "state": "pending_setup", "missing": "anthropic_api_key", "missingAll": ["anthropic_api_key"],
                    "reason": "ANTHROPIC_API_KEY is not set on the server.", "model": config.claude_model}
        return {**base, "state": "ready", "reason": "Claude is called directly from this server.", "model": config.claude_model}
    if mode == "external_worker":
        why = {"worker_url": "AI_WORKER_URL is not set or is not https (a loopback address may use http)",
               "worker_token": "AI_WORKER_TOKEN is not set",
               "webhook_secret": "WORKFLOW_WEBHOOK_SECRET is not set, so Flowmerce cannot authenticate the worker's callbacks",
               "callback_url": "AI_CALLBACK_URL is not a valid https URL (a loopback address may use http)"}
        missing = [k for k, bad in (("worker_url", not ai_worker.base_url()), ("worker_token", not config.ai_worker_token),
                                    ("webhook_secret", not config.workflow_webhook_secret),
                                    ("callback_url", bool(config.ai_callback_url) and not ai_worker.callback_url())) if bad]
        if missing:
            main = "worker_config" if ("worker_url" in missing or "worker_token" in missing) else missing[0]
            return {**base, "state": "pending_setup", "missing": main, "missingAll": missing, "reason": "; ".join(why[k] for k in missing) + "."}
        notes = [] if ai_worker.callback_url() else ["AI_CALLBACK_URL is not set: the worker must already be configured with where to send its callbacks."]
        last = status_of("ai_worker", "")
        if last and last["status"] == "error":
            return {**base, "state": "unavailable", "notes": notes, "reason": f"The last attempt to reach the worker failed: {last['last_error']}"}
        return {**base, "state": "ready", "notes": notes, "reason": "Jobs are sent to the configured worker, which reports back to the webhook."}
    if mode != "disabled":   # a typo must not look like a deliberate "off"
        return {**base, "state": "pending_setup", "missing": "execution_mode", "missingAll": ["execution_mode"],
                "reason": f"AI_EXECUTION_MODE={mode!r} is not recognised. Use anthropic_api, external_worker or disabled."}
    return base


# ---------------------------------------------------------------- creating jobs

def _shape_input(brand_id: str, task_type: str, raw: Any) -> Job:
    """The job's input, validated for shape only (no business state) and normalised: this is what is fingerprinted for
    idempotency. A topic research job always records its topic count: the requested one, or the brand's configured default."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HttpError(400, "input must be an object.")
    if task_type == "topic_research":
        extra = set(raw) - {"count", "focus"}
        if extra:
            raise HttpError(400, f"input has fields this task does not accept: {', '.join(sorted(extra))}.")
        count = raw.get("count")
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= ai_results.MAX_REQUESTED):
            raise HttpError(400, f"count must be a whole number from 1 to {ai_results.MAX_REQUESTED}.")
        out: Job = {"count": count or ai_results.default_count(brand_id)}
        if raw.get("focus"):
            out["focus"] = s(raw["focus"], 500).strip()
        return out
    if task_type == "content_revision":
        extra = set(raw) - {"article_id", "instructions", "base_version"}
        if extra:
            raise HttpError(400, f"input has fields this task does not accept: {', '.join(sorted(extra))}.")
        aid, ver = raw.get("article_id"), raw.get("base_version")
        if isinstance(aid, bool) or not isinstance(aid, int) or isinstance(ver, bool) or not isinstance(ver, int):
            raise HttpError(400, "article_id and base_version are required.")
        text = raw.get("instructions")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "Say what Claude should change.")
        if len(text) > MAX_INSTRUCTIONS:
            raise HttpError(400, f"The change request is longer than {MAX_INSTRUCTIONS} characters.")
        return {"article_id": aid, "base_version": ver, "instructions": text.strip()}
    extra = set(raw) - {"topic_id"}
    if extra:
        raise HttpError(400, f"input has fields this task does not accept: {', '.join(sorted(extra))}.")
    tid = raw.get("topic_id")
    if isinstance(tid, bool) or not isinstance(tid, int):
        raise HttpError(400, "topic_id is required.")
    return {"topic_id": tid}


def _check_state(brand_id: str, task_type: str, clean: Job) -> None:
    """Business-state checks that depend on the database (not part of the idempotency fingerprint)."""
    if task_type == "content_revision":
        a = get("SELECT id, version, status FROM articles WHERE id = ? AND brand_id = ?", clean["article_id"], brand_id)
        if not a:
            raise HttpError(404, "That article does not exist for this brand.")
        if a["status"] == "scheduled":
            raise HttpError(409, "This article is scheduled on Shopify. Cancel the schedule before asking for changes.", "scheduled")
        if a["version"] != clean["base_version"]:
            raise HttpError(409, f"The article is now at version {a['version']}. Save or reload before asking Claude for changes.", "version_conflict")
        return
    if task_type != "content_generation":
        return
    t = get("SELECT * FROM topics WHERE id = ? AND brand_id = ?", clean["topic_id"], brand_id)
    if not t:
        raise HttpError(404, "That topic does not exist for this brand.")
    if t["status"] != "approved":
        raise HttpError(409, "Only an approved topic can get a draft.", "topic_not_approved")
    if get("SELECT 1 FROM articles WHERE topic_id = ?", clean["topic_id"]):
        raise HttpError(409, "This topic already has an article.", "topic_has_article")


def _replay(prior: Job, brand_id: str, task_type: str, dedupe: str) -> tuple[Job, bool]:
    """A request that reuses an idempotency key: the same logical request gets the existing job; anything else is a conflict.
    "Same" means same brand, same task type and the same normalised input (compared by fingerprint)."""
    if (prior["brand_id"], prior["task_type"], prior["dedupe_key"]) != (brand_id, task_type, dedupe):
        raise HttpError(409, "That idempotency_key was already used for a different request (brand, task type or input differs).", "idempotency_conflict")
    return prior, True


def create_job(user: Job | None, brand_id: str, task_type: str, job_input: Any = None, idempotency_key: str | None = None) -> tuple[Job, bool]:
    """Validate, persist and return (job, already_existed). The same request repeated returns the same job: by idempotency_key
    when the caller gives one (even after the job finished; a key reused with a different brand, task or input is a 409),
    otherwise while an identical (brand, task, input) job is still active. Nothing is dispatched here; the runner picks the job
    up. Raises 412 pending_setup when no executor is configured."""
    if not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    if task_type not in TASKS:
        raise HttpError(400, f"Unsupported task type. Supported: {', '.join(TASKS)}.", "unsupported_task")
    stage = TASKS[task_type]
    d = next((x for x in workflow.STAGES if x["key"] == stage), None)
    if not d or d["kind"] != "automated":
        raise HttpError(400, "That workflow stage cannot run AI jobs.", "unsupported_stage")
    if idempotency_key is not None and not (isinstance(idempotency_key, str) and _KEY.match(idempotency_key)):
        raise HttpError(400, "idempotency_key must be 6-128 letters, digits or . _ : -")
    clean = _shape_input(brand_id, task_type, job_input)
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    dedupe = hashlib.sha256(f"{brand_id}|{task_type}|{canonical}".encode()).hexdigest()
    if idempotency_key:   # a replay is answered before any state check, so it still works after the job's topic was used up
        prior = get("SELECT * FROM ai_jobs WHERE idempotency_key = ?", idempotency_key)
        if prior:
            return _replay(prior, brand_id, task_type, dedupe)
    if workflow.is_paused(brand_id):
        raise HttpError(423, "Automation is paused for this brand. Resume it to run AI jobs.", "paused")
    ps = provider_status()
    if ps["state"] in ("pending_setup", "disabled"):
        raise HttpError(412, ps["reason"], "pending_setup")
    _check_state(brand_id, task_type, clean)
    if ps["mode"] == "anthropic_api":
        ai_budget.check(task_type)
    try:
        with tx():
            if idempotency_key:
                prior = get("SELECT * FROM ai_jobs WHERE idempotency_key = ?", idempotency_key)
                if prior:
                    return _replay(prior, brand_id, task_type, dedupe)
            active = get(f"SELECT * FROM ai_jobs WHERE dedupe_key = ? AND status IN ({','.join('?' for _ in ACTIVE)})", dedupe, *ACTIVE)
            if active:
                return active, True
            t, job_id = now(), str(uuid.uuid4())
            rid = run("""INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, message, details_json, user_id, started_at)
                         VALUES (?,?,?,?,?,?,?,?)""", brand_id, stage, "running", "ai_job", "AI job created", json.dumps({"jobId": job_id}), user["id"] if user else None, t).last_id
            run("""INSERT INTO ai_jobs (id, brand_id, stage, task_type, input_json, status, provider, max_retries, workflow_run_id, idempotency_key, dedupe_key,
                                        message, created_by, created_at, updated_at) VALUES (?,?,?,?,?, 'pending', ?,?,?,?,?, ?,?,?,?)""",
                job_id, brand_id, stage, task_type, canonical, ps["mode"], config.ai_max_retries, rid, idempotency_key, dedupe, "Waiting for an executor",
                user["id"] if user else None, t, t)
            _event(job_id, "created", f"{task_type} job created")
            audit(user, "ai_job.create", "ai_job", job_id, brand_id, f"{task_type} via {ps['mode']}")
            row = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
            assert row is not None
    except sqlite3.IntegrityError:   # a concurrent request won the race: answer from what it stored
        found = get("SELECT * FROM ai_jobs WHERE idempotency_key = ?", idempotency_key) if idempotency_key else None
        if found:
            return _replay(found, brand_id, task_type, dedupe)
        active = get(f"SELECT * FROM ai_jobs WHERE dedupe_key = ? AND status IN ({','.join('?' for _ in ACTIVE)}) ORDER BY created_at DESC", dedupe, *ACTIVE)
        if not active:
            raise
        return active, True
    kick()
    return row, False


def retry_job(user: Job | None, job_id: str) -> Job:
    """A person retries a failed job: it becomes pending again with a new run_number, so events from the earlier
    attempt are recognised as stale. The retry counter and progress start over."""
    ps = provider_status()
    if ps["state"] in ("pending_setup", "disabled"):
        raise HttpError(412, ps["reason"], "pending_setup")
    try:
        with tx():
            cur = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
            if not cur:
                raise HttpError(404, "Job not found.", "unknown_job")
            if cur["status"] != "failed":
                raise HttpError(409, "Only a failed job can be retried.", "invalid_transition")
            if workflow.is_paused(cur["brand_id"]):
                raise HttpError(423, "Automation is paused for this brand. Resume it to retry AI jobs.", "paused")
            _update(job_id, "pending", run_number=cur["run_number"] + 1, retry_count=0, progress=0, last_sequence=0, error=None, error_kind=None,
                          worker_id=None, external_id=None, accepted_at=None, started_at=None, finished_at=None, result_json=None, next_attempt_at=None,
                          lease_owner=None, lease_expires_at=None, last_progress_at=None, message="Retry requested", event=("retry", f"Retried by {(user or {}).get('email', 'system')}"))
            run("UPDATE ai_jobs SET provider = ? WHERE id = ?", ps["mode"], job_id)
            audit(user, "ai_job.retry", "ai_job", job_id, cur["brand_id"], f"run {cur['run_number'] + 1}")
    except sqlite3.IntegrityError as e:
        raise HttpError(409, "An identical job is already active.", "duplicate_active_job") from e
    kick()
    return get("SELECT * FROM ai_jobs WHERE id = ?", job_id)  # type: ignore[return-value]


def cancel_job(user: Job | None, job_id: str) -> Job:
    """Stop a pending, queued or running job. A local Claude call already in flight cannot be interrupted, but its result is
    discarded (the job no longer holds the lease). Flowmerce does not call a worker to cancel; the worker's later events are rejected."""
    row = _update(job_id, "cancelled", lease_owner=None, lease_expires_at=None, next_attempt_at=None, message="Cancelled",
                  event=("cancelled", f"Cancelled by {(user or {}).get('email', 'system')}"))
    assert row is not None
    audit(user, "ai_job.cancel", "ai_job", job_id, row["brand_id"], "")
    return row


# ---------------------------------------------------------------- reading jobs

def public(job: Job) -> Job:
    """The job as the API and dashboard see it. No lease owner, no worker token, no raw input of other fields."""
    result = json.loads(job["result_json"]) if job.get("result_json") else None
    failed = job["status"] == "failed"
    paused = workflow.is_paused(job["brand_id"])
    waiting = job["status"] == "pending" and bool(job.get("error"))
    return {
        "id": job["id"], "brand": job["brand_id"], "stage": job["stage"], "taskType": job["task_type"], "status": job["status"],
        "provider": job["provider"], "progress": job["progress"], "message": job["message"], "error": job["error"], "errorKind": job["error_kind"],
        "workerId": job["worker_id"], "externalId": job["external_id"], "runNumber": job["run_number"], "retryCount": job["retry_count"],
        "maxRetries": job["max_retries"], "attempts": job["attempts"], "workflowRunId": job["workflow_run_id"],
        "createdAt": job["created_at"], "acceptedAt": job["accepted_at"], "startedAt": job["started_at"], "lastProgressAt": job["last_progress_at"],
        "finishedAt": job["finished_at"], "updatedAt": job["updated_at"], "nextAttemptAt": job["next_attempt_at"] if job["status"] == "pending" else None,
        "input": json.loads(job["input_json"] or "{}"), "result": result, "resultAvailable": result is not None,
        "retryAvailable": failed, "brandPaused": paused, "waitingForResume": job["status"] == "pending" and paused, "cancellable": job["status"] in ACTIVE, "waitingOnProvider": waiting,
    }


def list_jobs(brand_id: str | None = None, status: str = "", limit: int = 100) -> list[Job]:
    where, args = [], []
    if brand_id:
        where.append("brand_id = ?")
        args.append(brand_id)
    if status:
        where.append("status = ?")
        args.append(status)
    rows = all_rows(f"SELECT * FROM ai_jobs {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY created_at DESC LIMIT ?", *args, min(limit, 500))
    return [public(r) for r in rows]


def get_job(job_id: str) -> Job:
    row = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
    if not row:
        raise HttpError(404, "Job not found.", "unknown_job")
    events = all_rows("SELECT source, sequence, event_type, status, progress, message, agent, created_at FROM ai_job_events WHERE job_id = ? ORDER BY id", job_id)
    return {**public(row), "events": events}


# ---------------------------------------------------------------- what an executor is given

def build_input(job: Job) -> Job:
    """The task context sent to Claude or to a worker: brand voice plus the current catalogue data. No credentials."""
    b, st = brand(job["brand_id"]), brand_settings(job["brand_id"])
    own = json.loads(job["input_json"] or "{}")
    base: Job = {"brand": {"id": b.id, "name": b.name, "domain": b.storefront_domain, "voice": st.get("voice", ""), "audience": st.get("audience", ""), "avoid": st.get("avoid", "")}}
    if job["task_type"] == "topic_research":
        return {**base, "count": own.get("count") or st["topicsPerRun"], "focus": own.get("focus") or st["researchFocus"],
                "events": calendar_plan.upcoming_for_prompt(job["brand_id"]), **workflow.topic_research_context(job["brand_id"])}
    if job["task_type"] == "content_revision":
        a = get("SELECT * FROM articles WHERE id = ? AND brand_id = ?", own.get("article_id"), job["brand_id"])
        if not a:
            raise JobError("The article does not exist any more.")
        if a["version"] != own.get("base_version"):
            raise JobError(f"The article was edited (now version {a['version']}) after the change request, so Claude did not revise it. Ask again.")
        return {**base, "article": {k: a[k] for k in claude.REVISABLE}, "instructions": own["instructions"],
                "links": workflow.draft_links(job["brand_id"], f"{a['title']} {a['primary_keyword']}")}
    t = get("SELECT * FROM topics WHERE id = ? AND brand_id = ?", own.get("topic_id"), job["brand_id"])
    if not t or t["status"] != "approved":
        raise JobError("The topic is not approved any more.")
    return {**base, "topic": {k: t[k] for k in ("title", "primary_keyword", "secondary_keywords", "intent", "notes")},
            "links": workflow.draft_links(job["brand_id"], f"{t['title']} {t['primary_keyword']} {t['secondary_keywords']}")}


# ---------------------------------------------------------------- failure and retry policy

def _wait_for_budget(job_id: str, owner: str | None, message: str) -> Job | None:
    """Today's Claude limit is used up: the job goes back to pending until the limit resets. This is not a failed attempt,
    so it does not use one of the job's retries."""
    with tx():
        cur = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
        if not cur or cur["status"] != "running" or (owner is not None and not _holds(cur, owner)):
            return None
        return _update(job_id, "pending", next_attempt_at=_in(ai_budget.seconds_until_reset()), lease_owner=None, lease_expires_at=None,
                       message="Waiting for tomorrow's Claude limit", event=("retry_scheduled", s(message, 300)))


def _after_failure(job_id: str, owner: str | None, message: str, kind: str, retryable: bool, retry_after: float | None = None) -> Job | None:
    """Apply the retry policy to a failed attempt: a retryable failure goes back to pending with exponential backoff (or the
    server's Retry-After) until max_retries is used up; anything else, or an exhausted budget, makes the job failed."""
    with tx():
        cur = get("SELECT * FROM ai_jobs WHERE id = ?", job_id)
        if not cur or cur["status"] not in ("pending", "running") or (owner is not None and not _holds(cur, owner)):
            return None
        msg = s(message, 2000)
        if retryable and cur["retry_count"] < cur["max_retries"]:
            n = cur["retry_count"] + 1
            delay = ai_worker.backoff_seconds(n, retry_after)
            return _update(job_id, "pending", retry_count=n, next_attempt_at=_in(delay), lease_owner=None, lease_expires_at=None, error=msg, error_kind=kind,
                           message=f"Attempt failed ({kind}); retry {n} of {cur['max_retries']} in {int(delay)}s", event=("retry_scheduled", f"{kind}: {msg[:300]}"))
        return _update(job_id, "failed", lease_owner=None, lease_expires_at=None, next_attempt_at=None, error=msg, error_kind=kind, message="Failed",
                       event=("failed", f"{kind}: {msg[:300]}"))


def recover(*, startup: bool = False) -> Job:
    """Settle jobs nobody is working on any more. Safe to call repeatedly.
    - anthropic_api jobs still "running" with an expired lease (or any, at startup: this is the only instance) were interrupted: requeued within the retry budget.
    - external_worker jobs queued or running whose worker has been silent past their deadline fail with a timeout (a person can retry).
    - Dispatch leases left by a process that died are cleared so the job is dispatched again (the worker de-duplicates by Idempotency-Key).
    - Pending jobs created for a different execution mode than the current one fail, so they are not stuck forever."""
    t, out = now(), {"requeued": 0, "timed_out": 0, "released": 0, "wrong_mode": 0}
    with tx():
        cond = "" if startup else " AND lease_expires_at < ?"
        args: tuple[str, ...] = () if startup else (t,)
        for j in all_rows(f"SELECT id FROM ai_jobs WHERE status = 'running' AND provider = 'anthropic_api'{cond}", *args):
            if _after_failure(j["id"], None, "Interrupted: the server stopped or the job ran past its lease.", "interrupted", True):
                out["requeued"] += 1
        for j in all_rows("SELECT id FROM ai_jobs WHERE status IN ('queued','running') AND provider = 'external_worker' AND lease_expires_at < ?", t):
            _update(j["id"], "failed", lease_owner=None, lease_expires_at=None, error="The worker reported nothing before the deadline, so the job was stopped.",
                    error_kind="timeout", message="Timed out", event=("timeout", "No worker activity before the deadline"))
            out["timed_out"] += 1
        out["released"] = run("UPDATE ai_jobs SET lease_owner = NULL, lease_expires_at = NULL WHERE status = 'pending' AND lease_owner IS NOT NULL" + (" AND lease_expires_at < ?" if not startup else ""),
                              *args).changes
        mode = config.ai_execution_mode
        if mode in ("anthropic_api", "external_worker"):
            for j in all_rows("SELECT id FROM ai_jobs WHERE status = 'pending' AND provider != ?", mode):
                _update(j["id"], "failed", error=f"The job was created for another execution mode than the current one ({mode}). Retry it.", error_kind="provider_changed",
                        message="Execution mode changed", event=("provider_changed", mode))
                out["wrong_mode"] += 1
    return out


def recover_on_startup() -> Job:
    return recover(startup=True)


# ---------------------------------------------------------------- claiming and executing

def claim_next(owner: str = OWNER) -> Job | None:
    """Atomically take the oldest pending job that is due and whose brand is not paused (a paused brand's jobs simply wait; work
    already running is left alone, and resuming makes them eligible again), and give this claim its own unique lease token (stored in
    `lease_owner`; the returned row shows it). `owner` only names the runner. For anthropic_api the job becomes running with
    a lease; for external_worker it stays pending (not accepted yet) but carries a dispatch lease so it is sent once.
    Nothing is claimed while the execution method is not fully configured (for a worker that includes the callback secret),
    so jobs wait instead of being dispatched into a setup that could not authenticate their results."""
    mode = config.ai_execution_mode
    if mode not in ("anthropic_api", "external_worker") or provider_status()["state"] in ("pending_setup", "disabled"):
        return None
    t = now()
    with tx():
        c = get("""SELECT id FROM ai_jobs WHERE status = 'pending' AND provider = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   AND (lease_owner IS NULL OR lease_expires_at < ?)
                   AND brand_id NOT IN (SELECT brand_id FROM automation_state WHERE paused = 1) ORDER BY created_at LIMIT 1""", mode, t, t)
        if not c:
            return None
        token = _new_token(owner)
        if mode == "anthropic_api":
            r = _update(c["id"], "running", lease_owner=token, lease_expires_at=_in(lease_seconds()), next_attempt_at=None, last_progress_at=t,
                        attempts=(get("SELECT attempts FROM ai_jobs WHERE id = ?", c["id"]) or {"attempts": 0})["attempts"] + 1, message="Running",
                        event=("started", "Claimed by the local runner"))
        else:
            run("UPDATE ai_jobs SET lease_owner = ?, lease_expires_at = ?, attempts = attempts + 1, next_attempt_at = NULL, updated_at = ? WHERE id = ?",
                token, _in(dispatch_lease_seconds()), t, c["id"])
            r = get("SELECT * FROM ai_jobs WHERE id = ?", c["id"])
        return r


def execute(job: Job, token: str | None = None) -> None:
    """Run one claimed job to its next resting state, under that claim's lease token (default: the one on the claimed row).
    Never raises: every failure is recorded on the job, and only while the token is still the job's live lease."""
    token = token or job["lease_owner"]
    try:
        if job["provider"] == "external_worker":
            _dispatch(job, token)
        else:
            _run_direct(job, token)
    except Exception as e:  # noqa: BLE001 - process boundary: record it on the job instead of killing the runner thread
        log.exception("AI job %s crashed", job["id"])
        try:
            _after_failure(job["id"], token, f"Unexpected error: {type(e).__name__}", "internal", False)
        except Exception:  # noqa: BLE001
            log.exception("Could not record the failure of AI job %s", job["id"])


def _run_direct(job: Job, token: str) -> None:
    owner = token
    try:
        inp = build_input(job)
        b, st = brand(job["brand_id"]), brand_settings(job["brand_id"])
        ai_budget.check(job["task_type"])   # a job queued yesterday still waits for today's limit
        if job["task_type"] == "topic_research":
            data, _model = claude.research_topics(b, st, inp["existing_titles"], inp["products"], inp["queries"], inp["count"], inp["focus"],
                                                  events=inp.get("events"))
        elif job["task_type"] == "content_revision":
            data, _model = claude.revise_draft(b, st, inp["article"], inp["instructions"], inp["links"])
        else:
            data, _model = claude.generate_draft(b, st, inp["topic"], inp["links"])
    except claude.ClaudeError as e:
        ai_budget.record(claude.take_usage(), job["brand_id"], job["task_type"], job["id"])   # a call that ran is paid for even if its answer is unusable
        msg = str(e) + (" (it may have been processed; check before retrying)" if e.ambiguous else "")
        _after_failure(job["id"], owner, msg, e.kind, e.retryable, e.retry_after)
        return
    except HttpError as e:
        if getattr(e, "code", None) == "daily_limit":
            _wait_for_budget(job["id"], owner, e.message)
        else:
            _after_failure(job["id"], owner, e.message, "rejected", False)
        return
    except JobError as e:
        _after_failure(job["id"], owner, str(e), "rejected", False)
        return
    usage = claude.take_usage()
    ai_budget.record(usage, job["brand_id"], job["task_type"], job["id"])
    try:
        clean = ai_results.validate(job["task_type"], data, ai_results.requested_count(job))
    except ai_results.ResultError as e:
        _after_failure(job["id"], owner, f"Claude's answer was rejected: {e}", "invalid_result", False)
        return
    with tx():
        cur = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        if not cur or cur["status"] != "running" or not _holds(cur, owner):
            log.info("AI job %s finished after it was cancelled, expired or reclaimed; its result was discarded", job["id"])
            return
        try:
            summary = ai_results.store(cur, clean)
        except ai_results.ResultError as e:
            _after_failure(job["id"], owner, str(e), "invalid_result", False)
            return
        _update(job["id"], "succeeded", owner=owner, progress=100, lease_owner=None, lease_expires_at=None, message=summary["summary"],
                result_json=json.dumps({**summary, "usage": usage}), event=("succeeded", summary["summary"]))


def _dispatch(job: Job, token: str) -> None:
    owner = token
    try:
        ack = ai_worker.submit(job, build_input(job))
        observed = now()   # the worker answered at this moment
    except JobError as e:
        _after_failure(job["id"], owner, str(e), "rejected", False)
        return
    except ai_worker.WorkerError as e:
        observed = now()   # when the failure was seen: the health update is ordered by this, not by when it happens to be written
        # The dispatch lease token is the only authority. _after_failure() applies the failure (retry or fail) only if this dispatch
        # attempt still holds an unexpired lease on a pending job, and says so by returning the updated row. The job change and the
        # worker-health change happen in ONE transaction: both or neither. If a worker callback already took the job over or
        # finished it, nothing is applied, no retry is used, and the worker is not marked unavailable: it demonstrably answered.
        # Health writes are time-ordered, so a delayed failure can never overwrite a newer successful contact with the worker.
        with tx():
            if _after_failure(job["id"], owner, str(e), e.kind, e.retryable, e.retry_after) is not None:
                mark_error("ai_worker", "", "external_worker", e, at=observed)
            else:
                log.info("AI job %s: the dispatch request failed (%s) after the worker had already taken or finished the job; nothing applied", job["id"], e.kind)
        return
    mark_success("ai_worker", "", "external_worker", {"lastJob": job["id"]}, at=observed)
    with tx():
        cur = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        if not cur:
            return
        if cur["status"] == "pending" and _holds(cur, owner):
            _update(job["id"], "queued", accepted_at=cur["accepted_at"] or now(), error=None, error_kind=None, message="Accepted by the worker",
                    worker_id=cur["worker_id"] or ack.worker_id, external_id=cur["external_id"] or ack.external_id,
                    lease_owner=None, lease_expires_at=_in(config.ai_job_timeout_seconds),
                    event=("dispatched", "Worker accepted the job" + (" (already submitted before)" if ack.duplicate else "")))
        elif cur["status"] in ("queued", "running"):
            # A late acknowledgement: the worker's callbacks already moved the job on. Never touch status, progress, lease or deadline;
            # only fill identifiers the callbacks did not carry.
            run("UPDATE ai_jobs SET worker_id = COALESCE(worker_id, ?), external_id = COALESCE(external_id, ?) WHERE id = ? AND status IN ('queued', 'running')",
                ack.worker_id, ack.external_id, job["id"])


def run_pending(max_jobs: int = 100, owner: str = OWNER) -> list[str]:
    """Claim and execute due jobs one after another in the calling thread. The background runner does the same with a thread
    pool; this is used by tests and tools. Returns the ids it processed."""
    done: list[str] = []
    recover()
    while len(done) < max_jobs and (job := claim_next(owner)):
        execute(job)
        done.append(job["id"])
    return done


# ---------------------------------------------------------------- the background runner

class Runner:
    """Polls the database, claims due jobs and executes them on a bounded thread pool. stop() is graceful: it stops claiming,
    waits for work in flight, then hands unfinished jobs back to the queue (no retry is consumed)."""

    def __init__(self, owner: str = OWNER, poll_seconds: float = 2.0):
        self.owner, self.poll = owner, poll_seconds
        self._stop, self._wake = threading.Event(), threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=config.ai_max_concurrency, thread_name_prefix="ai-job")
        self._futures: set[Future[None]] = set()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="ai-job-runner", daemon=True)

    def start(self) -> None:
        recover_on_startup()
        self._thread.start()
        from . import image_prompts   # featured-image prompts run beside the job queue, on their own thread
        image_prompts.start()

    def kick(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the runner must survive a bad tick
                log.exception("AI job runner tick failed")
            self._wake.wait(self.poll)
            self._wake.clear()

    def tick(self) -> int:
        recover()
        try:
            from . import autopilot   # imported here: autopilot imports this module
            autopilot.advance_all()   # move "Write a blog" runs on as their jobs finish
        except Exception:  # noqa: BLE001 — the queue below must still run
            log.exception("Autopilot step failed")
        try:
            from . import image_prompts
            image_prompts.kick()      # cheap: starts the image prompt worker only when it may have work
        except Exception:  # noqa: BLE001
            log.exception("Image prompt step failed")
        started = 0
        while not self._stop.is_set():
            with self._lock:
                self._futures = {f for f in self._futures if not f.done()}
                if len(self._futures) >= config.ai_max_concurrency:
                    break
            job = claim_next(self.owner)
            if not job:
                break
            with self._lock:
                self._futures.add(self._pool.submit(execute, job))
            started += 1
        return started

    def stop(self, timeout: float = 20.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            futures = list(self._futures)
        deadline = datetime.now().timestamp() + timeout
        for f in futures:
            try:
                f.result(timeout=max(0.0, deadline - datetime.now().timestamp()))
            except Exception:  # noqa: BLE001 - timeout or job error: either way we move on
                pass
        self._pool.shutdown(wait=False, cancel_futures=True)
        release_owned(self.owner)


def release_owned(owner: str) -> int:
    """Give back the claims made by the runner named `owner` (shutdown): running jobs return to pending, dispatch leases are
    cleared. It matches the runner's tokens by their "<owner>:" prefix, so another runner's claims are never touched, and an
    execution that already lost its lease is unaffected (its token is no longer on any job)."""
    n = 0
    with tx():
        for j in all_rows("SELECT id, status FROM ai_jobs WHERE lease_owner LIKE ?", f"{owner}:%"):
            if j["status"] == "running":
                _update(j["id"], "pending", lease_owner=None, lease_expires_at=None, next_attempt_at=None, message="Returned to the queue: the server was stopping",
                        event=("released", "Server shutdown"))
            else:
                run("UPDATE ai_jobs SET lease_owner = NULL, lease_expires_at = NULL WHERE id = ?", j["id"])
            n += 1
    return n


_runner: Runner | None = None


def start_runner() -> Runner | None:
    """Start the background runner once. Does nothing when AI execution is disabled."""
    global _runner
    if config.ai_execution_mode not in ("anthropic_api", "external_worker"):
        recover_on_startup()   # even when switched off, jobs left running by a crash must not block their workflow stage forever
        return _runner
    if _runner is not None:
        return _runner
    _runner = Runner()
    _runner.start()
    return _runner


def stop_runner() -> None:
    global _runner
    if _runner is not None:
        _runner.stop()
        _runner = None


def kick() -> None:
    if _runner is not None:
        _runner.kick()


# ---------------------------------------------------------------- callbacks from an external worker

def parse_event(body: Job) -> Job:
    """Strict validation of a worker callback body. Unknown fields are rejected, not ignored."""
    extra = set(body) - EVENT_KEYS
    if extra:
        raise HttpError(400, f"Unknown fields: {', '.join(sorted(map(str, extra))[:5])}.", "invalid_event")

    def text(key: str, max_len: int, required: bool = False) -> str | None:
        v = body.get(key)
        if v is None:
            if required:
                raise HttpError(400, f"{key} is required.", "invalid_event")
            return None
        if not isinstance(v, str) or len(v) > max_len:
            raise HttpError(400, f"{key} must be text of at most {max_len} characters.", "invalid_event")
        return v

    def integer(key: str, lo: int, hi: int, required: bool = False) -> int | None:
        v = body.get(key)
        if v is None:
            if required:
                raise HttpError(400, f"{key} is required.", "invalid_event")
            return None
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise HttpError(400, f"{key} must be a whole number from {lo} to {hi}.", "invalid_event")
        return v

    event_id, job_id = text("event_id", 128, True), text("job_id", 64, True)
    if not _ID.match(event_id or ""):
        raise HttpError(400, "event_id must be 8-128 letters, digits or . _ : -", "invalid_event")
    etype = body.get("event_type")
    if not isinstance(etype, str) or etype not in EVENT_STATUS:   # a list or object would make the dict lookup raise TypeError
        raise HttpError(400, f"event_type must be one of: {', '.join(EVENT_STATUS)}.", "invalid_event")
    status = body.get("status")
    if status is not None and (not isinstance(status, str) or status != EVENT_STATUS[etype]):
        raise HttpError(400, f"status {status!r} does not match event_type {etype!r} (expected {EVENT_STATUS[etype]!r}).", "invalid_status")
    ev = {"event_id": event_id, "job_id": job_id, "event_type": etype, "status": EVENT_STATUS[etype],
          "sequence": integer("sequence", 1, 2**31 - 1, True), "run_number": integer("run_number", 1, 10_000),
          "progress": integer("progress", 0, 100), "message": text("message", 1000) or "", "agent": text("agent", 120),
          "external_id": text("external_id", 200), "error": text("error", 2000), "brand": text("brand", 20), "stage": text("stage", 60),
          "callback_reference": text("callback_reference", 64), "result": body.get("result"), "occurred_at": None}
    if ev["callback_reference"] not in (None, job_id):
        raise HttpError(400, "callback_reference does not match job_id.", "invalid_event")
    if ev["result"] is not None and etype != "succeeded":
        raise HttpError(400, "Only a succeeded event may carry a result.", "invalid_event")
    if etype == "succeeded" and not isinstance(ev["result"], dict):
        raise HttpError(400, "A succeeded event needs a result object.", "invalid_event")
    if ev["progress"] is not None and etype in ("succeeded", "failed"):
        raise HttpError(400, "progress is only for accepted, started and progress events.", "invalid_event")
    if body.get("occurred_at") is not None:
        raw = text("occurred_at", 40)
        try:
            when = datetime.fromisoformat((raw or "").replace("Z", "+00:00"))
        except ValueError as e:
            raise HttpError(400, "occurred_at must be an ISO-8601 time.", "invalid_event") from e
        if when.tzinfo is None:
            raise HttpError(400, "occurred_at needs a time zone.", "invalid_event")
        ev["occurred_at"] = when
    return ev


def apply_event(ev: Job) -> Job:
    """Apply one validated callback to its job, atomically with the workflow run and any stored result.
    Order of checks: unknown job, association, duplicate event_id (safe no-op), final job, run number, sequence, time,
    external id, transition, progress never backwards. Rejections change nothing."""
    rejection: HttpError | None = None
    with tx():
        job = get("SELECT * FROM ai_jobs WHERE id = ?", ev["job_id"])
        if not job:
            raise HttpError(404, "Unknown job.", "unknown_job")
        if ev["brand"] not in (None, job["brand_id"]) or ev["stage"] not in (None, job["stage"]):
            raise HttpError(409, "The event does not belong to this job's brand and stage.", "job_mismatch")
        if job["provider"] != "external_worker":
            raise HttpError(409, "This job is not executed by an external worker.", "job_mismatch")
        if get("SELECT 1 FROM ai_job_events WHERE job_id = ? AND event_id = ?", job["id"], ev["event_id"]):
            return {"ok": True, "duplicate": True, "jobId": job["id"], "status": job["status"]}
        if job["status"] in ("succeeded", "failed", "cancelled"):
            raise HttpError(409, f"The job is already {job['status']}.", "job_finished")
        if get("SELECT COUNT(*) n FROM ai_job_events WHERE job_id = ?", job["id"])["n"] >= MAX_EVENTS_PER_JOB:  # type: ignore[index]
            raise HttpError(429, "This job has received too many events.", "too_many_events")
        if (ev["run_number"] or (1 if job["run_number"] == 1 else None)) != job["run_number"]:
            raise HttpError(409, "The event belongs to an earlier attempt of this job.", "stale_run")
        if ev["sequence"] <= job["last_sequence"]:
            raise HttpError(409, f"Out of order: sequence {ev['sequence']} is not after {job['last_sequence']}.", "stale_event")
        if ev["occurred_at"]:
            created = datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
            if ev["occurred_at"] > datetime.now(timezone.utc) + CLOCK_SKEW or ev["occurred_at"] < created - CLOCK_SKEW:
                raise HttpError(400, "occurred_at is outside the job's lifetime.", "invalid_event")
        if job["external_id"] and ev["external_id"] and ev["external_id"] != job["external_id"]:
            raise HttpError(409, "external_id does not match this job's worker execution.", "job_mismatch")
        to = ev["status"]
        if to != job["status"] and not can_transition(job["status"], to):
            raise HttpError(409, f"A {job['status']} job cannot become {to}.", "invalid_transition")
        if ev["progress"] is not None and ev["progress"] < job["progress"]:
            raise HttpError(409, "Progress cannot go backwards.", "stale_progress")
        # A valid callback proves the worker has the job, so ownership moves from the dispatch request to the worker: the dispatch
        # lease token is released (lease_owner cleared) and only the worker's inactivity deadline (lease_expires_at) remains.
        # From here a slow or failed dispatch request cannot requeue or fail the job (its token no longer holds anything).
        fields: dict[str, Any] = dict(last_sequence=ev["sequence"], last_progress_at=now(), lease_expires_at=_in(config.ai_job_timeout_seconds),
                                      lease_owner=None, next_attempt_at=None,
                                      worker_id=job["worker_id"] or ev["agent"], external_id=job["external_id"] or ev["external_id"])
        if ev["progress"] is not None:
            fields["progress"] = ev["progress"]
        if ev["message"]:
            fields["message"] = ev["message"]
        if ev["event_type"] == "accepted":
            fields["accepted_at"] = job["accepted_at"] or now()
        if to in ("succeeded", "failed", "cancelled"):
            fields.update(lease_owner=None, lease_expires_at=None)
        if to == "succeeded":
            try:
                clean = ai_results.validate(job["task_type"], ev["result"], ai_results.requested_count(job))
                summary = ai_results.store(job, clean)
            except ai_results.ResultError as e:
                to, rejection = "failed", HttpError(422, f"Result rejected: {e}", "invalid_result")
                fields.update(error=f"Result rejected: {e}", error_kind="invalid_result", message="Result rejected", lease_owner=None, lease_expires_at=None)
            else:
                fields.update(progress=100, message=summary["summary"], result_json=json.dumps({**summary, "usage": None}))
        elif to == "failed":
            fields.update(error=ev["error"] or ev["message"] or "The worker reported a failure.", error_kind="worker_failed", message="Failed")
        run("INSERT INTO ai_job_events (job_id, event_id, source, sequence, event_type, status, progress, message, agent, external_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            job["id"], ev["event_id"], "worker", ev["sequence"], ev["event_type"], to, fields.get("progress"), s(ev["message"] or fields.get("error"), 1000),
            ev["agent"], ev["external_id"], now())
        row = _update(job["id"], to, **fields)
        audit(None, "ai_job.event" if not rejection else "ai_job.result_rejected", "ai_job", job["id"], job["brand_id"], f"{ev['event_type']}: {s(ev['message'], 150)}")
    if rejection:
        raise rejection
    assert row is not None
    return {"ok": True, "duplicate": False, "jobId": row["id"], "status": row["status"], "progress": row["progress"]}
