"""Operator commands for checking and repairing stored data. Run from the repository root with the project's Python:

    python -m flowmerce.modules.seo.maintenance db-report
        Read-only summary of the database: integration status, articles by origin/status, stored Search Console and
        GA4 coverage by source. Opens the file read-only; changes nothing (not even migrations).

    python -m flowmerce.modules.seo.maintenance backup
        Verified copy of the database into backups/.

    python -m flowmerce.modules.seo.maintenance resync-preview --source gsc --brand ridhi --from 2025-08-01 --to 2026-11-10
        Reads that range from Google and shows what a re-sync would change. Writes nothing.

    python -m flowmerce.modules.seo.maintenance resync-apply --source gsc --brand ridhi --from ... --to ... --confirm
        Makes a verified backup, then replaces the live-API rows of that range. Demo and imported rows are untouched.
        Only run this after the preview has been reviewed and approved.

Output is JSON so it can be pasted into a review. No secrets are printed."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .config import config


def db_report(path: str | None = None) -> dict[str, Any]:
    """Read-only report. Uses a read-only SQLite connection, so it cannot change the database or run migrations."""
    target = path or str(config.data_dir / "blog-ops.sqlite")
    if not Path(target).exists():
        raise FileNotFoundError(f"No database at {target}")
    conn = sqlite3.connect(f"{Path(target).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    def rows(sql: str) -> list[dict[str, Any]]:
        try:
            return [dict(r) for r in conn.execute(sql).fetchall()]
        except sqlite3.OperationalError as e:   # a table that does not exist in an older database
            return [{"error": str(e)}]

    try:
        return {
            "database": target,
            "schemaVersion": conn.execute("PRAGMA user_version").fetchone()[0],
            "integrations": rows("SELECT key, brand_id, status, mode, last_attempt_at, last_success_at, last_error, details_json FROM integration_status ORDER BY key, brand_id"),
            "articles": rows("""SELECT brand_id, origin, status, shopify_published, (shopify_article_id IS NOT NULL) has_shopify_id, COUNT(*) n
                                FROM articles GROUP BY 1,2,3,4,5 ORDER BY 1,2,3"""),
            "hiddenInShopify": rows("""SELECT brand_id, origin, status, COUNT(*) n FROM articles
                                       WHERE shopify_article_id IS NOT NULL AND shopify_published = 0 GROUP BY 1,2,3 ORDER BY 1,2,3"""),
            "gscCoverage": rows("SELECT brand_id, source, COUNT(*) rows, MIN(date) first, MAX(date) last, SUM(clicks) clicks FROM gsc_page_daily GROUP BY 1,2 ORDER BY 1,2"),
            "ga4Coverage": rows("SELECT brand_id, source, COUNT(*) rows, MIN(date) first, MAX(date) last, SUM(sessions) sessions FROM ga4_page_daily GROUP BY 1,2 ORDER BY 1,2"),
            "gscQueryPeriods": rows("SELECT brand_id, source, start_date, end_date, COUNT(*) rows FROM gsc_query_period GROUP BY 1,2,3,4 ORDER BY 1,2,4"),
            "products": rows("SELECT brand_id, source, COUNT(*) n, MAX(synced_at) last FROM products GROUP BY 1,2"),
            "recentRuns": rows("SELECT brand_id, stage, status, trigger_kind, started_at, substr(COALESCE(error, message), 1, 200) note FROM workflow_runs ORDER BY id DESC LIMIT 15"),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m flowmerce.modules.seo.maintenance", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-report")
    sub.add_parser("backup")
    for name in ("resync-preview", "resync-apply"):
        s = sub.add_parser(name)
        s.add_argument("--source", choices=["gsc", "ga4"], required=True)
        s.add_argument("--brand", required=True)
        s.add_argument("--from", dest="frm", required=True)
        s.add_argument("--to", required=True)
        if name == "resync-apply":
            s.add_argument("--confirm", action="store_true", help="required: confirms the preview was reviewed and approved")
    a = p.parse_args(argv)
    try:
        return _run(a)
    except Exception as e:  # noqa: BLE001 — command-line boundary: show the message, not a traceback
        print(f"Failed: {getattr(e, 'message', None) or e}", file=sys.stderr)
        return 1


def _run(a: argparse.Namespace) -> int:
    if a.cmd == "db-report":
        out: Any = db_report()
    else:
        from .db import backup_database, open_db
        open_db()
        if a.cmd == "backup":
            out = backup_database(label="manual")
        else:
            from .config import is_brand
            from .services import resync
            if not is_brand(a.brand):
                print("Unknown brand.", file=sys.stderr)
                return 2
            if a.cmd == "resync-preview":
                out = resync.preview(a.source, a.brand, a.frm, a.to)
            else:
                if not a.confirm:
                    print("resync-apply changes stored data. Review resync-preview first, then add --confirm.", file=sys.stderr)
                    return 2
                out = resync.apply(a.source, a.brand, a.frm, a.to)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
