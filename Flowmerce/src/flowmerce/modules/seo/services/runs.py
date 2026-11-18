from __future__ import annotations

import json
from typing import Callable

from ..db import Row, get, now, run


def record_run(brand_id: str, stage: str, trigger: str, user: dict | None, fn: Callable[[], dict], retry_of: int | None = None) -> dict:
    """Record a workflow stage execution around fn. The row is written before fn starts so a crash
    still leaves a visible "running" entry, which the startup sweep marks failed.
    fn returns {"message": str, "details": dict?, "status": str?}."""
    rid = run("INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, user_id, retry_of, started_at) VALUES (?,?,?,?,?,?,?)",
              brand_id, stage, "running", trigger, user["id"] if user else None, retry_of, now()).last_id
    try:
        r = fn()
        status = r.get("status", "succeeded")
        run("UPDATE workflow_runs SET status=?, message=?, details_json=?, finished_at=? WHERE id=?",
            status, r["message"][:1000], json.dumps(r.get("details") or {}, default=str), now(), rid)
        return {"id": rid, "status": status, "message": r["message"]}
    except Exception as e:  # noqa: BLE001 — every failure is recorded on the run
        msg = getattr(e, "message", None) or str(e)
        run("UPDATE workflow_runs SET status=?, error=?, message=?, finished_at=? WHERE id=?", "failed", msg[:2000], "Failed", now(), rid)
        return {"id": rid, "status": "failed", "message": "Failed", "error": msg}


def sweep_interrupted_runs() -> int:
    """Runs left "running" by a server that stopped mid-way can never finish; mark them failed.
    A run that belongs to an AI job that is still active is skipped: the job is the source of truth for it, and
    ai_jobs.recover_on_startup() requeues or fails the job (which then settles its run)."""
    return run("""UPDATE workflow_runs SET status='failed', error='Interrupted: the server stopped while this was running.', finished_at=?
                  WHERE status='running' AND id NOT IN (SELECT workflow_run_id FROM ai_jobs WHERE workflow_run_id IS NOT NULL AND status IN ('pending','queued','running'))""", now()).changes


def last_run(brand_id: str, stage: str) -> Row | None:
    return get("SELECT * FROM workflow_runs WHERE brand_id = ? AND stage = ? ORDER BY id DESC LIMIT 1", brand_id, stage)


def last_successful_run(brand_id: str, stage: str) -> Row | None:
    return get("SELECT * FROM workflow_runs WHERE brand_id = ? AND stage = ? AND status = 'succeeded' ORDER BY id DESC LIMIT 1", brand_id, stage)


def failures_since_success(brand_id: str, stage: str) -> int:
    """Finished runs that failed after the last successful one (all of them if none ever succeeded)."""
    ok = last_successful_run(brand_id, stage)
    r = get("SELECT COUNT(*) n FROM workflow_runs WHERE brand_id = ? AND stage = ? AND status = 'failed' AND id > ?",
            brand_id, stage, ok["id"] if ok else 0)
    return int((r or {}).get("n") or 0)
