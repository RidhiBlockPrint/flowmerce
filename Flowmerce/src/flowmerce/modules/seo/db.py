"""SQLite storage. One shared connection guarded by a re-entrant lock, so the FastAPI worker threads
and the scheduler never interleave statements. Migrations are append-only: add a new entry to
MIGRATIONS, never edit an old one. The schema is identical to the earlier Node build, so an existing
data/blog-ops.sqlite keeps working."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import config

Row = dict[str, Any]

MIGRATIONS: list[str] = [
    # 1 — initial schema
    """
    CREATE TABLE users (
      id INTEGER PRIMARY KEY,
      email TEXT NOT NULL UNIQUE COLLATE NOCASE,
      name TEXT NOT NULL,
      role TEXT NOT NULL CHECK (role IN ('admin','seo_manager','reviewer')),
      password_hash TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      last_login_at TEXT
    );
    CREATE TABLE sessions (
      id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE brand_settings (
      brand_id TEXT PRIMARY KEY,
      settings_json TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT,
      updated_by INTEGER
    );
    CREATE TABLE topics (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      title TEXT NOT NULL,
      primary_keyword TEXT NOT NULL,
      keyword_norm TEXT NOT NULL,
      secondary_keywords TEXT NOT NULL DEFAULT '',
      intent TEXT NOT NULL DEFAULT 'informational',
      search_volume INTEGER,
      keyword_difficulty INTEGER,
      volume_source TEXT,
      rationale TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      validation_note TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'proposed',
      source TEXT NOT NULL DEFAULT 'manual',
      owner_id INTEGER,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      source_updated_at TEXT,
      UNIQUE (brand_id, keyword_norm)
    );
    CREATE TABLE keywords (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      keyword TEXT NOT NULL,
      keyword_norm TEXT NOT NULL,
      search_volume INTEGER,
      keyword_difficulty INTEGER,
      intent TEXT,
      source_tool TEXT NOT NULL DEFAULT 'manual',
      source_date TEXT,
      notes TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT 'manual',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (brand_id, keyword_norm)
    );
    CREATE TABLE articles (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
      title TEXT NOT NULL,
      handle TEXT NOT NULL,
      primary_keyword TEXT NOT NULL DEFAULT '',
      meta_title TEXT NOT NULL DEFAULT '',
      meta_description TEXT NOT NULL DEFAULT '',
      summary_html TEXT NOT NULL DEFAULT '',
      body_html TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '',
      author TEXT NOT NULL DEFAULT '',
      image_url TEXT NOT NULL DEFAULT '',
      image_alt TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'draft',
      assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
      version INTEGER NOT NULL DEFAULT 1,
      content_hash TEXT NOT NULL DEFAULT '',
      approved_hash TEXT,
      approved_by INTEGER,
      approved_at TEXT,
      review_note TEXT NOT NULL DEFAULT '',
      shopify_blog_id TEXT,
      shopify_article_id TEXT,
      shopify_published INTEGER NOT NULL DEFAULT 0,
      live_hash TEXT,
      live_url TEXT,
      publish_at TEXT,
      published_at TEXT,
      shopify_synced_at TEXT,
      origin TEXT NOT NULL DEFAULT 'app',
      last_error TEXT,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (brand_id, handle)
    );
    CREATE INDEX articles_status ON articles(brand_id, status);
    CREATE TABLE article_revisions (
      id INTEGER PRIMARY KEY,
      article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
      version INTEGER NOT NULL,
      data_json TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      user_id INTEGER,
      note TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE INDEX revisions_article ON article_revisions(article_id, version);
    CREATE TABLE review_notes (
      id INTEGER PRIMARY KEY,
      article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
      user_id INTEGER,
      reviewer_name TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      version INTEGER,
      source TEXT NOT NULL DEFAULT 'app',
      created_at TEXT NOT NULL
    );
    CREATE TABLE publish_requests (
      id INTEGER PRIMARY KEY,
      article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
      brand_id TEXT NOT NULL,
      mode TEXT NOT NULL CHECK (mode IN ('publish_now','schedule','update_live')),
      publish_at TEXT,
      content_hash TEXT NOT NULL,
      version INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      requested_by INTEGER,
      requested_at TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      decided_by INTEGER,
      decided_at TEXT,
      decision_note TEXT NOT NULL DEFAULT '',
      executed_at TEXT,
      attempts INTEGER NOT NULL DEFAULT 0,
      error TEXT
    );
    CREATE TABLE workflow_runs (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      stage TEXT NOT NULL,
      status TEXT NOT NULL,
      trigger_kind TEXT NOT NULL DEFAULT 'manual',
      message TEXT NOT NULL DEFAULT '',
      error TEXT,
      details_json TEXT NOT NULL DEFAULT '{}',
      user_id INTEGER,
      retry_of INTEGER,
      started_at TEXT NOT NULL,
      finished_at TEXT
    );
    CREATE INDEX runs_stage ON workflow_runs(brand_id, stage, started_at);
    CREATE TABLE automation_state (
      brand_id TEXT PRIMARY KEY,
      paused INTEGER NOT NULL DEFAULT 0,
      paused_by INTEGER,
      paused_at TEXT,
      reason TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE integration_status (
      key TEXT NOT NULL,
      brand_id TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      mode TEXT NOT NULL DEFAULT '',
      last_attempt_at TEXT,
      last_success_at TEXT,
      last_error TEXT,
      details_json TEXT NOT NULL DEFAULT '{}',
      PRIMARY KEY (key, brand_id)
    );
    CREATE TABLE gsc_page_daily (
      brand_id TEXT NOT NULL,
      date TEXT NOT NULL,
      page TEXT NOT NULL,
      clicks INTEGER NOT NULL,
      impressions INTEGER NOT NULL,
      ctr REAL NOT NULL,
      position REAL NOT NULL,
      source TEXT NOT NULL,
      source_timestamp TEXT,
      imported_at TEXT NOT NULL,
      PRIMARY KEY (brand_id, source, date, page)
    );
    CREATE TABLE gsc_query_period (
      brand_id TEXT NOT NULL,
      start_date TEXT NOT NULL,
      end_date TEXT NOT NULL,
      page TEXT NOT NULL DEFAULT '',
      query TEXT NOT NULL,
      clicks INTEGER NOT NULL,
      impressions INTEGER NOT NULL,
      ctr REAL NOT NULL,
      position REAL NOT NULL,
      source TEXT NOT NULL,
      source_timestamp TEXT,
      imported_at TEXT NOT NULL,
      PRIMARY KEY (brand_id, source, start_date, end_date, page, query)
    );
    CREATE TABLE ga4_page_daily (
      brand_id TEXT NOT NULL,
      date TEXT NOT NULL,
      page_path TEXT NOT NULL,
      sessions INTEGER NOT NULL,
      engaged_sessions INTEGER NOT NULL,
      engagement_rate REAL NOT NULL,
      avg_engagement_seconds REAL NOT NULL,
      key_events REAL NOT NULL,
      source TEXT NOT NULL,
      source_timestamp TEXT,
      imported_at TEXT NOT NULL,
      PRIMARY KEY (brand_id, source, date, page_path)
    );
    CREATE TABLE products (
      brand_id TEXT NOT NULL,
      handle TEXT NOT NULL,
      title TEXT NOT NULL,
      url TEXT NOT NULL,
      image_url TEXT NOT NULL DEFAULT '',
      product_type TEXT NOT NULL DEFAULT '',
      synced_at TEXT NOT NULL,
      source TEXT NOT NULL,
      PRIMARY KEY (brand_id, handle)
    );
    CREATE TABLE audit_log (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      user_id INTEGER,
      user_email TEXT,
      action TEXT NOT NULL,
      entity_type TEXT NOT NULL DEFAULT '',
      entity_id TEXT NOT NULL DEFAULT '',
      brand_id TEXT NOT NULL DEFAULT '',
      summary TEXT NOT NULL DEFAULT '',
      details_json TEXT NOT NULL DEFAULT '{}',
      ip TEXT
    );
    CREATE INDEX audit_ts ON audit_log(ts);
    CREATE TABLE imports (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL,
      filename TEXT NOT NULL,
      user_id INTEGER,
      created_at TEXT NOT NULL,
      rows_total INTEGER NOT NULL,
      inserted INTEGER NOT NULL,
      updated INTEGER NOT NULL,
      duplicates INTEGER NOT NULL,
      rejected INTEGER NOT NULL,
      errors_json TEXT NOT NULL DEFAULT '[]'
    );
    """,
    # 2 — AI jobs (additive only: two new tables and their indexes, no existing table is touched)
    """
    CREATE TABLE ai_jobs (
      id TEXT PRIMARY KEY,
      brand_id TEXT NOT NULL,
      stage TEXT NOT NULL,
      task_type TEXT NOT NULL,
      input_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','queued','running','succeeded','failed','cancelled')),
      provider TEXT NOT NULL,
      worker_id TEXT,
      external_id TEXT,
      retry_count INTEGER NOT NULL DEFAULT 0,
      max_retries INTEGER NOT NULL DEFAULT 3,
      attempts INTEGER NOT NULL DEFAULT 0,
      run_number INTEGER NOT NULL DEFAULT 1,
      progress INTEGER NOT NULL DEFAULT 0,
      message TEXT NOT NULL DEFAULT '',
      error TEXT,
      error_kind TEXT,
      result_json TEXT,
      workflow_run_id INTEGER,
      idempotency_key TEXT UNIQUE,
      dedupe_key TEXT,
      last_sequence INTEGER NOT NULL DEFAULT 0,
      lease_owner TEXT,
      lease_expires_at TEXT,
      next_attempt_at TEXT,
      accepted_at TEXT,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      started_at TEXT,
      last_progress_at TEXT,
      finished_at TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX ai_jobs_queue ON ai_jobs(status, provider, next_attempt_at);
    CREATE INDEX ai_jobs_brand ON ai_jobs(brand_id, created_at);
    CREATE UNIQUE INDEX ai_jobs_active_dedupe ON ai_jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending','queued','running');
    CREATE TABLE ai_job_events (
      id INTEGER PRIMARY KEY,
      job_id TEXT NOT NULL REFERENCES ai_jobs(id),
      event_id TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'worker',
      sequence INTEGER,
      event_type TEXT NOT NULL,
      status TEXT,
      progress INTEGER,
      message TEXT NOT NULL DEFAULT '',
      agent TEXT,
      external_id TEXT,
      created_at TEXT NOT NULL,
      UNIQUE (job_id, event_id)
    );
    CREATE INDEX ai_job_events_job ON ai_job_events(job_id, id);
    """,
    # Shipping: the team's own marks on an order (checked, flagged for escalation) and short notes. The parcels
    # themselves live in Supabase; these rows only refer to an order by store + Shopify order id.
    """
    CREATE TABLE shipping_order_marks (
      store TEXT NOT NULL,
      order_id INTEGER NOT NULL,
      reviewed_at TEXT,
      reviewed_by TEXT,
      flagged INTEGER NOT NULL DEFAULT 0,
      flagged_at TEXT,
      flagged_by TEXT,
      PRIMARY KEY (store, order_id)
    );
    CREATE TABLE shipping_order_notes (
      id INTEGER PRIMARY KEY,
      store TEXT NOT NULL,
      order_id INTEGER NOT NULL,
      at TEXT NOT NULL,
      by TEXT NOT NULL,
      text TEXT NOT NULL
    );
    CREATE INDEX shipping_order_notes_order ON shipping_order_notes(store, order_id, id);
    """,
    # Shipping: the team's outcome for an order Shopify does not know about (delivered, lost, returned, refunded).
    # An order with an outcome leaves Critical and every delay figure; it is listed under "Resolved".
    """
    ALTER TABLE shipping_order_marks ADD COLUMN outcome TEXT;
    ALTER TABLE shipping_order_marks ADD COLUMN outcome_at TEXT;
    ALTER TABLE shipping_order_marks ADD COLUMN outcome_by TEXT;
    """,
    # Blog: Claude's notes beside a draft (needs confirmation, recommendations, checks, sources); app-wide settings
    # (the monthly Claude budget); one row per Claude call for the daily limit; the content calendar and its schedule.
    """
    ALTER TABLE articles ADD COLUMN ai_notes_json TEXT NOT NULL DEFAULT '{}';
    CREATE TABLE app_settings (
      key TEXT PRIMARY KEY,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      updated_by INTEGER
    );
    CREATE TABLE claude_usage (
      id INTEGER PRIMARY KEY,
      ts TEXT NOT NULL,
      day TEXT NOT NULL,
      brand_id TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL,
      model TEXT NOT NULL DEFAULT '',
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      cache_write_tokens INTEGER NOT NULL DEFAULT 0,
      cache_read_tokens INTEGER NOT NULL DEFAULT 0,
      cost_usd REAL NOT NULL DEFAULT 0,
      job_id TEXT
    );
    CREATE INDEX claude_usage_day ON claude_usage(day);
    CREATE TABLE calendar_events (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL,
      date TEXT NOT NULL,
      lead_days INTEGER NOT NULL DEFAULT 30,
      note TEXT NOT NULL DEFAULT '',
      created_by INTEGER,
      created_at TEXT NOT NULL
    );
    CREATE TABLE content_schedule (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      action TEXT NOT NULL CHECK (action IN ('research','draft','publish')),
      run_on TEXT NOT NULL,
      event_key TEXT NOT NULL DEFAULT '',
      event_name TEXT NOT NULL DEFAULT '',
      focus TEXT NOT NULL DEFAULT '',
      topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
      article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
      status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','done','skipped','failed')),
      job_id TEXT,
      message TEXT NOT NULL DEFAULT '',
      created_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX content_schedule_due ON content_schedule(status, run_on);
    """,
    # Blog: one-click "Write a blog" runs (research -> draft -> approve -> hidden Shopify draft), see services/autopilot.py.
    """
    CREATE TABLE autopilot_runs (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
      step TEXT NOT NULL,
      message TEXT NOT NULL DEFAULT '',
      focus TEXT NOT NULL DEFAULT '',
      research_job_id TEXT,
      topic_id INTEGER REFERENCES topics(id) ON DELETE SET NULL,
      draft_job_id TEXT,
      article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
      source TEXT NOT NULL DEFAULT 'button',
      created_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      finished_at TEXT
    );
    CREATE INDEX autopilot_runs_brand ON autopilot_runs(brand_id, status);
    """,
    # Blog: the automatic blog pipeline (services/auto_blog.py). One slot per brand and publishing day; an autopilot run
    # writes it, a quality check (AEO/GEO/LLMO) may send it back to Claude once (revise_job_id), and the slot ends ready
    # as a hidden Shopify draft with a publish request a reviewer must authorize.
    """
    CREATE TABLE auto_blogs (
      id INTEGER PRIMARY KEY,
      brand_id TEXT NOT NULL,
      publish_on TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','writing','ready','failed','skipped','missed')),
      run_id INTEGER REFERENCES autopilot_runs(id) ON DELETE SET NULL,
      article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
      checks_json TEXT NOT NULL DEFAULT '{}',
      message TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (brand_id, publish_on)
    );
    CREATE INDEX auto_blogs_due ON auto_blogs(status, publish_on);
    ALTER TABLE autopilot_runs ADD COLUMN slot_id INTEGER REFERENCES auto_blogs(id) ON DELETE SET NULL;
    ALTER TABLE autopilot_runs ADD COLUMN revise_job_id TEXT;
    """,
]

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()
_local = threading.local()


def open_db(file: str | None = None) -> sqlite3.Connection:
    global _conn
    target = file or str(config.data_dir / "blog-ops.sqlite")
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode = WAL")
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.execute("PRAGMA busy_timeout = 5000")
    _migrate()
    return _conn


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database is not open; call open_db() first.")
    return _conn


def _migrate() -> None:
    db = _db()
    current = db.execute("PRAGMA user_version").fetchone()[0]
    for v in range(current, len(MIGRATIONS)):
        db.execute("BEGIN")
        try:
            for stmt in [s.strip() for s in MIGRATIONS[v].split(";") if s.strip()]:
                db.execute(stmt)
            db.execute(f"PRAGMA user_version = {v + 1}")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise


def all_rows(sql: str, *params: Any) -> list[Row]:
    with _lock:
        return [dict(r) for r in _db().execute(sql, params).fetchall()]


def get(sql: str, *params: Any) -> Row | None:
    with _lock:
        r = _db().execute(sql, params).fetchone()
        return dict(r) if r else None


class RunResult:
    __slots__ = ("changes", "last_id")

    def __init__(self, changes: int, last_id: int):
        self.changes = changes
        self.last_id = last_id


def run(sql: str, *params: Any) -> RunResult:
    with _lock:
        cur = _db().execute(sql, params)
        return RunResult(cur.rowcount, cur.lastrowid or 0)


@contextmanager
def tx() -> Iterator[None]:
    """One transaction; nested calls on the same thread join the outer one."""
    with _lock:
        depth = getattr(_local, "depth", 0)
        if depth:
            _local.depth = depth + 1
            try:
                yield
            finally:
                _local.depth = depth
            return
        _local.depth = 1
        _db().execute("BEGIN IMMEDIATE")
        try:
            yield
            _db().execute("COMMIT")
        except BaseException:
            _db().execute("ROLLBACK")
            raise
        finally:
            _local.depth = 0


def backup_database(dest_dir: Path | None = None, label: str = "manual") -> dict[str, Any]:
    """Copy the open database to backups/ with SQLite's online backup API (consistent even while the app runs),
    then verify the copy: PRAGMA integrity_check must say ok and every table must have the same row count as the
    original. Raises RuntimeError if the copy cannot be verified; the caller must then not change any data."""
    src = _db()
    folder = dest_dir or (config.root / "backups")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)[:60] or "manual"
    path = folder / f"blog-ops-{stamp}-{safe_label}.sqlite"
    with _lock:
        dst = sqlite3.connect(str(path))
        try:
            src.backup(dst)
        finally:
            dst.close()
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        expected = {t: src.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    check = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        actual = {t: check.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        check.close()
    if integrity != "ok" or actual != expected:
        raise RuntimeError(f"The backup at {path} could not be verified (integrity: {integrity}); no data was changed.")
    return {"path": str(path), "bytes": path.stat().st_size, "tables": len(tables), "rows": sum(expected.values()), "integrity": integrity}


def now() -> str:
    """ISO-8601 UTC with milliseconds and Z, the same format the earlier build stored."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
