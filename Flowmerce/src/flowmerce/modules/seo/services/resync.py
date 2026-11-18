"""Reviewed re-reads of stored Search Console / GA4 history: fill gaps left while the computer was off, or rewrite
older days with the corrected URL-variant totals.

Two steps, on purpose:
  preview() reads from Google and compares with what is stored. It writes nothing.
  apply()   first makes a verified database backup (db.backup_database), then replaces ONLY the live-API rows of the
            range in one transaction and writes an audit line. Demo and manually imported rows are never touched.
Neither runs on its own: they are started from the command line (flowmerce.modules.seo.maintenance) by a person."""
from __future__ import annotations

from typing import Any

from ..audit import audit
from ..db import all_rows, backup_database, now, tx
from ..integrations.google import ga4_configured, gsc_configured
from ..util import HttpError, add_days, days_between, today
from .brands import brand
from .sync import FIRST_SYNC_DAYS, exclusive, fetch_ga4_pages, fetch_gsc_pages, write_ga4_pages, write_gsc_pages

TABLE = {"gsc": ("gsc_page_daily", "page", "clicks", "impressions"), "ga4": ("ga4_page_daily", "page_path", "sessions", "engaged_sessions")}
LAG = {"gsc": 3, "ga4": 1}


def _validate(source: str, brand_id: str, frm: str, to: str) -> None:
    if source not in TABLE:
        raise HttpError(400, "source must be gsc or ga4")
    b = brand(brand_id)
    if not (gsc_configured(b) if source == "gsc" else ga4_configured(b)):
        raise HttpError(412, f"{source.upper()} is not set up for {brand_id}.", "pending_setup")
    try:
        span = days_between(frm, to)
    except ValueError as e:
        raise HttpError(400, "Dates must be YYYY-MM-DD.") from e
    if span < 0:
        raise HttpError(400, "The start date is after the end date.")
    latest = add_days(today(), -LAG[source])
    if to > latest:
        raise HttpError(400, f"The end date can be {latest} at the latest (newer {source.upper()} data is not final yet).")
    if frm < add_days(latest, -FIRST_SYNC_DAYS):
        raise HttpError(400, f"The start date can be {add_days(latest, -FIRST_SYNC_DAYS)} at the earliest.")


def _stored(source: str, brand_id: str, frm: str, to: str) -> dict[str, dict]:
    table, _, m1, m2 = TABLE[source]
    return {r["date"]: r for r in all_rows(f"""SELECT date, COUNT(*) rows, SUM({m1}) m1, SUM({m2}) m2 FROM {table}
                                             WHERE brand_id = ? AND source = 'api' AND date BETWEEN ? AND ? GROUP BY date""", brand_id, frm, to)}


def _incoming(source: str, rows: dict[tuple[str, str], dict]) -> dict[str, dict]:
    k1, k2 = ("clicks", "impressions") if source == "gsc" else ("s", "e")
    out: dict[str, dict] = {}
    for (day, _), m in rows.items():
        d = out.setdefault(day, {"rows": 0, "m1": 0.0, "m2": 0.0})
        d["rows"] += 1
        d["m1"] += m[k1]
        d["m2"] += m[k2]
    return out


def _compare(source: str, brand_id: str, frm: str, to: str, rows: dict[tuple[str, str], dict]) -> dict[str, Any]:
    _, _, n1, n2 = TABLE[source]
    stored, incoming = _stored(source, brand_id, frm, to), _incoming(source, rows)
    untouched = {r["source"]: r["n"] for r in all_rows(f"SELECT source, COUNT(*) n FROM {TABLE[source][0]} WHERE brand_id = ? AND source != 'api' AND date BETWEEN ? AND ? GROUP BY source",
                                                     brand_id, frm, to)}

    def total(d: dict[str, dict]) -> dict[str, Any]:
        return {"rows": sum(int(x["rows"]) for x in d.values()), n1: round(sum(float(x["m1"] or 0) for x in d.values()), 2),
                n2: round(sum(float(x["m2"] or 0) for x in d.values()), 2), "days": len(d)}

    added = sorted(set(incoming) - set(stored))
    removed = sorted(set(stored) - set(incoming))
    changed = sorted(d for d in set(stored) & set(incoming)
                     if int(stored[d]["rows"]) != incoming[d]["rows"] or round(float(stored[d]["m1"] or 0), 2) != round(incoming[d]["m1"], 2)
                     or round(float(stored[d]["m2"] or 0), 2) != round(incoming[d]["m2"], 2))
    return {"source": source, "brand": brand_id, "range": {"from": frm, "to": to},
            "stored": total(stored), "incoming": total(incoming),
            "daysAdded": len(added), "daysChanged": len(changed), "daysEmptiedByGoogle": len(removed),
            "examples": {"added": added[:10], "changed": changed[:10], "emptied": removed[:10]},
            "untouchedRows": untouched, "rowsDeleted": total(stored)["rows"], "rowsWritten": len(rows)}


def preview(source: str, brand_id: str, frm: str, to: str) -> dict[str, Any]:
    """What apply() would change for this range. Reads from Google; writes nothing to the database."""
    _validate(source, brand_id, frm, to)
    b = brand(brand_id)
    rows, _ = fetch_gsc_pages(b, frm, to) if source == "gsc" else fetch_ga4_pages(b, frm, to)
    return {**_compare(source, brand_id, frm, to, rows), "writes": False}


def apply(source: str, brand_id: str, frm: str, to: str, user: dict | None = None) -> dict[str, Any]:
    """Back up the database (verified), then replace the live-API rows of the range with a fresh read from Google.
    If the backup cannot be verified nothing is written."""
    _validate(source, brand_id, frm, to)
    b = brand(brand_id)
    with exclusive(source, brand_id):
        backup = backup_database(label=f"before-{source}-resync-{brand_id}")
        rows, _ = fetch_gsc_pages(b, frm, to) if source == "gsc" else fetch_ga4_pages(b, frm, to)
        summary = _compare(source, brand_id, frm, to, rows)
        with tx():
            (write_gsc_pages if source == "gsc" else write_ga4_pages)(brand_id, frm, to, rows, now())
        audit(user, f"{source}.resync", "integration", source, brand_id,
              f"{frm}..{to}: {summary['rowsDeleted']} live-API rows replaced by {summary['rowsWritten']}",
              {"backup": backup["path"], "daysAdded": summary["daysAdded"], "daysChanged": summary["daysChanged"]})
    return {**summary, "writes": True, "backup": backup}
