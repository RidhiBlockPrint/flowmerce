"""One row per integration (and brand): configured or not, mode, last attempt, last success, last error.
Failures are also written to the audit log so they are not lost when the next sync works.

Four separate facts are tracked, because one does not imply the next:
  1. authentication worked (a token was obtained),
  2. the API answered (a real request succeeded),
  3. a sync finished (status 'connected', last_success_at),
  4. data actually arrived (details.rows / details.dataThrough written by the sync).
1 and 2 come from the Test button and are kept in details.lastCheck; a later sync keeps that entry."""
from __future__ import annotations

import json

from ..audit import audit
from ..db import Row, all_rows, get, now, run
from ..util import safe_json

INTERRUPTED = "Interrupted: the server stopped while this sync was running."


def _details(key: str, brand_id: str) -> dict:
    r = get("SELECT details_json FROM integration_status WHERE key = ? AND brand_id = ?", key, brand_id)
    return safe_json(r["details_json"], {}) if r else {}


def mark_attempt(key: str, brand_id: str, mode: str) -> None:
    run("""INSERT INTO integration_status (key, brand_id, status, mode, last_attempt_at) VALUES (?,?,?,?,?)
           ON CONFLICT(key, brand_id) DO UPDATE SET status='syncing', mode=excluded.mode, last_attempt_at=excluded.last_attempt_at""",
        key, brand_id, "syncing", mode, now())


def mark_success(key: str, brand_id: str, mode: str, details: dict | None = None, at: str | None = None) -> bool:
    """Record a successful attempt. Without `at` it always writes (time = now), as before. With `at` (the moment the outcome was
    OBSERVED) the write is ordered: it applies only if no newer attempt has already been recorded, so a delayed, older result
    cannot overwrite a newer one. A tie goes to success. Returns whether the row was written.
    The latest connection test (details.lastCheck) is carried over so a sync does not erase it."""
    t = at or now()
    merged = dict(details or {})
    last_check = _details(key, brand_id).get("lastCheck")
    if last_check and "lastCheck" not in merged:
        merged["lastCheck"] = last_check
    guard = " WHERE integration_status.last_attempt_at IS NULL OR integration_status.last_attempt_at <= excluded.last_attempt_at" if at else ""
    return run(f"""INSERT INTO integration_status (key, brand_id, status, mode, last_attempt_at, last_success_at, last_error, details_json)
           VALUES (?,?,?,?,?,?,NULL,?)
           ON CONFLICT(key, brand_id) DO UPDATE SET status='connected', mode=excluded.mode, last_attempt_at=excluded.last_attempt_at,
             last_success_at=excluded.last_success_at, last_error=NULL, details_json=excluded.details_json{guard}""",
               key, brand_id, "connected", mode, t, t, json.dumps(merged, default=str)).changes > 0


def mark_error(key: str, brand_id: str, mode: str, err: object, at: str | None = None) -> bool:
    """Record a failed attempt (and audit it). Without `at` it always writes, as before. With `at` (the moment the failure was
    OBSERVED) it applies only if no attempt at the same time or later is recorded, so a delayed failure never overwrites a newer
    success; the audit line is written only when the row was. Returns whether the row was written.
    last_success_at and the details of the last good sync are kept: a failure never erases what was last known to work."""
    message = str(err)
    guard = " WHERE integration_status.last_attempt_at IS NULL OR integration_status.last_attempt_at < excluded.last_attempt_at" if at else ""
    applied = run(f"""INSERT INTO integration_status (key, brand_id, status, mode, last_attempt_at, last_error) VALUES (?,?,?,?,?,?)
           ON CONFLICT(key, brand_id) DO UPDATE SET status='error', mode=excluded.mode, last_attempt_at=excluded.last_attempt_at, last_error=excluded.last_error{guard}""",
                  key, brand_id, "error", mode, at or now(), message[:1000]).changes > 0
    if applied:
        audit(None, "integration.failure", "integration", key, brand_id, message[:300])
    return applied


def mark_pending(key: str, brand_id: str, reason: str) -> None:
    """Not set up. The history (last attempt, last success, last error) is kept; mode and details are replaced so a stale
    "admin_api" mode or an old row count is not shown next to "pending setup"."""
    run("""INSERT INTO integration_status (key, brand_id, status, mode, details_json) VALUES (?,?,?,?,?)
           ON CONFLICT(key, brand_id) DO UPDATE SET status='pending_setup', mode='', details_json=excluded.details_json""",
        key, brand_id, "pending_setup", "", json.dumps({"reason": reason}))


def record_check(key: str, brand_id: str, check: dict) -> None:
    """Store the result of a connection test (authentication, API access, rows seen) in details.lastCheck.
    It does not change status, last_success_at or last_error: those describe syncs, not tests."""
    d = _details(key, brand_id)
    d["lastCheck"] = {**check, "at": now()}
    run("""INSERT INTO integration_status (key, brand_id, status, mode, details_json) VALUES (?,?,?,?,?)
           ON CONFLICT(key, brand_id) DO UPDATE SET details_json=excluded.details_json""",
        key, brand_id, "not_synced", "", json.dumps(d, default=str))


def sweep_stuck_syncs() -> int:
    """A sync left 'syncing' by a server that stopped mid-way never finishes; mark it failed at startup.
    last_success_at and the last good details are kept."""
    return run("UPDATE integration_status SET status='error', last_error=? WHERE status='syncing'", INTERRUPTED).changes


def status_of(key: str, brand_id: str) -> Row | None:
    r = get("SELECT * FROM integration_status WHERE key = ? AND brand_id = ?", key, brand_id)
    return {**r, "details": safe_json(r["details_json"], {})} if r else None


def all_statuses() -> list[Row]:
    return [{**r, "details": safe_json(r["details_json"], {})} for r in all_rows("SELECT * FROM integration_status")]
