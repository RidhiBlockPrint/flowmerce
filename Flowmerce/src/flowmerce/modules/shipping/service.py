"""Shipping business logic on top of the central Supabase database (schema `ops`).

All filtering, sorting, paging and counting happens in the database (views shipment_list, diagnostics_list,
shipping_summary, feed_freshness); this module only validates inputs, shapes answers and adds honest labels.
Nothing here writes to the hub's `public` tables. The only writes are: running ops.refresh_from_shopify_orders()
(which reads public.orders / public.sync_runs and fills ops.*), recording a failed refresh, and a person's team
mark (ops.set_team_mark)."""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from .rules import (ALLOWED_FILTERS, ALLOWED_SORTS, TEAM_MARKS, clamp_int, freshness, search_filter,
                    status_view)
from .supabase import SupabaseError, client

# The frontend's brand switch uses the SEO ids; the database uses store codes.
STORE_FOR_BRAND = {"ridhi": "RBP", "cpc": "CPC", "RBP": "RBP", "CPC": "CPC"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

LIST_COLUMNS = ("tracking_id,store,order_id,order_name,placed_at,shipment_id,seq,kind,kind_inferred,step,"
                "carrier_id,carrier_name,tracking_number,track_url,status,raw_status,status_detail,source,"
                "delivery_confirmed,shipped_at,last_scan_at,last_scan_place,delivered_at,eta,last_check_ok_at,"
                "last_check_error,active,team_mark,team_mark_by,team_mark_at,days_since_dispatch,hours_since_scan,"
                "open_exceptions,age_band,no_movement,unverified")

PROBLEM_LABELS = {
    "no_scans": "Tracking number but no scan yet",
    "no_movement": "No movement for 3+ days",
    "missing_carrier": "Carrier not identified",
    "delivery_unconfirmed": "Delivered per Shopify only (last 30 days)",
    "status_mismatch": "Status disagrees with newest scan",
    "sync_failing": "Status checks keep failing",
    "duplicate_tracking": "Same tracking number on several shipments",
    "shipped_without_tracking": "Shipped without a tracking number",
    "open_exception": "Open delivery problem",
    "kind_unconfirmed": "MCF / India not confirmed (imported)",
}


def _store(brand: str | None) -> str | None:
    return STORE_FOR_BRAND.get(brand or "")


def _store_param(brand: str | None) -> list[tuple[str, str]]:
    s = _store(brand)
    return [("store", f"eq.{s}")] if s else []


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    row["status_view"] = status_view(row.get("status"), row.get("source"), row.get("delivery_confirmed"))
    return row


def _source_ok() -> dict[str, str]:
    return {"state": "ok"}


def _source_error(e: SupabaseError) -> dict[str, str]:
    return {"state": e.state, "message": e.message}


# ---------------------------------------------------------------------------------------- summary
def summary(brand: str | None) -> dict[str, Any]:
    """Home / Overview numbers. Never raises for Supabase problems: returns source.state instead, so a
    Shipping outage never breaks the Home page."""
    try:
        c = client()
        per_store = c.select("shipping_summary", [("select", "*"), *_store_param(brand)]).rows
        fresh = c.select("feed_freshness", [("select", "*")]).rows
        problems = c.select("diagnostics_summary", [("select", "*"), *_store_param(brand)]).rows
    except SupabaseError as e:
        return {"source": _source_error(e), "totals": None, "freshness": [], "problems": []}

    keys = ("open_tracking", "in_transit", "out_for_delivery", "delivered_30d", "delivered_confirmed_30d",
            "exceptions", "unverified")
    totals: dict[str, Any] = {k: sum(int(r.get(k) or 0) for r in per_store) for k in keys}
    totals["stores"] = [r["store"] for r in per_store]

    feeds = []
    for f in fresh:
        if _store(brand) and f.get("store") not in (None, _store(brand)):
            continue
        feeds.append({**f, "view": freshness(f.get("last_ok_at"), f.get("last_status"))})

    merged: dict[str, dict[str, Any]] = {}
    for p in problems:
        m = merged.setdefault(p["problem"], {"problem": p["problem"], "label": PROBLEM_LABELS.get(p["problem"], p["problem"]),
                                             "severity": p["severity"], "n": 0})
        m["n"] += int(p["n"])
        if p["severity"] == "red":
            m["severity"] = "red"
    order = {"red": 0, "amber": 1}
    plist = sorted(merged.values(), key=lambda x: (order.get(x["severity"], 2), -x["n"]))
    return {"source": _source_ok(), "totals": totals, "freshness": feeds, "problems": plist}


BRAND_FOR_STORE = {"RBP": "ridhi", "CPC": "cpc"}


def home_snapshot(brand_ids: list[str]) -> dict[str, Any] | None:
    """Shipping figures for the Home page, read from the Shipping page's own cached board (board.home_figures), so
    Home costs no extra Supabase reads once Shipping data is loaded and shows the same numbers as Shipping.
    None when Supabase is not set up or not reachable, so Shipping can never break Home."""
    from . import board
    brands = [b for b in brand_ids if b in BRAND_FOR_STORE.values()]
    if not brands:
        return None
    if not board.loaded():
        # Right after start-up the first board read takes several seconds; Home never waits for it.
        board.reload_in_background()
        return {"loading": True}
    try:
        ds = board.dataset("all")    # the board Shipping already built; home_figures keeps only the selected brands
    except (SupabaseError, RuntimeError, ValueError, board.HttpError):
        return None
    return board.home_figures(ds, brands)


# ---------------------------------------------------------------------------------------- list
def _list_params(brand: str | None, q: str | None, status: str | None, band: str | None, carrier: str | None,
                 view: str | None, flag: str | None) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = [*_store_param(brand)]
    if view == "delivered":
        p.append(("status", "eq.delivered"))
    elif view != "all":
        p.append(("active", "is.true"))
    if status in ALLOWED_FILTERS["status"]:
        p.append(("status", f"eq.{status}"))
    if band in ALLOWED_FILTERS["band"]:
        p.append(("age_band", f"eq.{band}"))
    if carrier and re.fullmatch(r"[a-z0-9_]{1,40}", carrier):
        p.append(("carrier_id", f"eq.{carrier}"))
    if flag == "no_movement":
        p.append(("no_movement", "is.true"))
    elif flag == "unverified":
        p.append(("unverified", "is.true"))
    elif flag == "problems":
        p.append(("open_exceptions", "gt.0"))
    elif flag == "team_marked":
        p.append(("team_mark", "not.is.null"))
    elif flag == "unconfirmed_delivery":
        p += [("status", "eq.delivered"), ("delivery_confirmed", "is.false")]
    sf = search_filter(q or "")
    if sf:
        p.append(("or", sf))
    return p


def list_shipments(brand: str | None = None, q: str | None = None, status: str | None = None,
                   band: str | None = None, carrier: str | None = None, view: str | None = None,
                   flag: str | None = None, sort: str | None = None, direction: str | None = None,
                   page: Any = 1, size: Any = 25) -> dict[str, Any]:
    page_n = clamp_int(page, 1, 1, 100000)
    size_n = clamp_int(size, 25, 1, 200)
    col = ALLOWED_SORTS.get(sort or "days", "days_since_dispatch")
    d = "asc" if direction == "asc" else "desc"
    params = [("select", LIST_COLUMNS), *_list_params(brand, q, status, band, carrier, view, flag),
              ("order", f"{col}.{d}.nullslast,tracking_id.asc")]
    res = client().select("shipment_list", params, count=True, offset=(page_n - 1) * size_n, limit=size_n)
    return {"rows": [_decorate(r) for r in res.rows], "total": res.total, "page": page_n, "size": size_n,
            "sort": sort or "days", "dir": d}


# ---------------------------------------------------------------------------------------- detail
def shipment_detail(tracking_id: str) -> dict[str, Any] | None:
    if not UUID_RE.match(tracking_id or ""):
        return None
    c = client()
    rows = c.select("shipment_list", [("select", LIST_COLUMNS), ("tracking_id", f"eq.{tracking_id}")], limit=1).rows
    if not rows:
        return None
    row = _decorate(rows[0])
    scans = c.select("tracking_scans", [
        ("select", "id,scanned_at,received_at,status,raw_status,message,city,country,source,mapped_rule"),
        ("tracking_id", f"eq.{tracking_id}"), ("order", "scanned_at.desc,id.desc")], limit=200).rows
    events = c.select("events", [
        ("select", "id,at,type,by,title,data"), ("order_id", f"eq.{row['order_id']}"),
        ("order", "at.desc,id.desc")], limit=200).rows
    siblings = c.select("shipment_list", [
        ("select", "tracking_id,seq,carrier_name,tracking_number,status,source,delivery_confirmed,age_band"),
        ("order_id", f"eq.{row['order_id']}"), ("tracking_id", f"neq.{tracking_id}")], limit=50).rows
    exceptions = c.select("shipping_exceptions", [
        ("select", "id,kind,severity,source,detected_at,description,status,owner,resolution,closed_at"),
        ("shipment_id", f"eq.{row['shipment_id']}"), ("order", "detected_at.desc")], limit=50).rows
    for s in scans:
        s["status_view"] = status_view(s.get("status"), s.get("source"), False)
    return {"shipment": row, "scans": scans, "events": events,
            "siblings": [_decorate(s) for s in siblings], "exceptions": exceptions}


# ---------------------------------------------------------------------------------------- diagnostics
def diagnostics(brand: str | None = None, problem: str | None = None, page: Any = 1, size: Any = 25) -> dict[str, Any]:
    page_n = clamp_int(page, 1, 1, 100000)
    size_n = clamp_int(size, 25, 1, 200)
    p: list[tuple[str, str]] = [("select", "*"), *_store_param(brand)]
    if problem in PROBLEM_LABELS:
        p.append(("problem", f"eq.{problem}"))
    p.append(("order", "severity.desc,order_name.asc.nullslast"))
    res = client().select("diagnostics_list", p, count=True, offset=(page_n - 1) * size_n, limit=size_n)
    for r in res.rows:
        r["label"] = PROBLEM_LABELS.get(r.get("problem"), r.get("problem"))
    return {"rows": res.rows, "total": res.total, "page": page_n, "size": size_n, "labels": PROBLEM_LABELS}


# ---------------------------------------------------------------------------------------- carriers
def carriers(brand: str | None = None) -> dict[str, Any]:
    rows = client().select("carrier_performance", [("select", "*"), ("order", "month.desc,carrier_id.asc")],
                           limit=500).rows
    names = {r["id"]: r["name"] for r in client().select("carriers", [("select", "id,name")]).rows}
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by.setdefault(r["carrier_id"], {"carrier_id": r["carrier_id"], "name": names.get(r["carrier_id"], r["carrier_id"]),
                                            "shipments": 0, "delivered": 0, "with_problem": 0, "months": []})
        b["shipments"] += int(r.get("shipments") or 0)
        b["delivered"] += int(r.get("delivered") or 0)
        b["with_problem"] += int(r.get("with_problem") or 0)
        b["months"].append(r)
    out = sorted(by.values(), key=lambda x: -x["shipments"])
    for b in out:
        b["problem_pct"] = round(100 * b["with_problem"] / b["shipments"], 1) if b["shipments"] else None
    return {"carriers": out, "note": "Transit times count from dispatch until a carrier feed reports pickup."}


# ---------------------------------------------------------------------------------------- refresh
def refresh(triggered_by: str, read_shopify: bool = True) -> dict[str, Any]:
    """1. Read each store's changes straight from Shopify (keys from .env) into ops.shopify_orders; a store that
    fails is recorded on its own and does not stop the rest. 2. Run ops.refresh_from_shopify_orders(), which
    merges that with the hub's public.orders. On failure of step 2, record a failed run so the freshness badge
    shows it."""
    from . import shopify_source
    shopify = shopify_source.sync_all(triggered_by) if read_shopify else []
    c = client()
    try:
        result = c.rpc("refresh_from_shopify_orders", {})
    except SupabaseError as e:
        try:
            c.insert("sync_runs", {"source": "shopify", "kind": "import", "status": "failed",
                                   "error": e.message[:1000], "triggered_by": triggered_by[:120]})
        except SupabaseError:
            pass
        raise
    return {"ok": True, "result": result, "shopify": shopify}


# ---------------------------------------------------------------------------------------- team mark
def set_mark(tracking_id: str, mark: str | None, note: str | None, by: str) -> dict[str, Any]:
    if not UUID_RE.match(tracking_id or ""):
        raise SupabaseError("bad_request", "Unknown shipment.")
    mark = (mark or "").strip() or None
    if mark is not None and mark not in TEAM_MARKS:
        raise SupabaseError("bad_request", f"Mark must be one of: {', '.join(TEAM_MARKS)}.")
    note = (note or "").strip()[:1000] or None
    if mark is None and note is None:
        raise SupabaseError("bad_request", "Choose a mark or write a note.")
    return client().rpc("set_team_mark", {"p_tracking_id": tracking_id, "p_mark": mark, "p_note": note, "p_by": by})


# ---------------------------------------------------------------------------------------- CSV export
EXPORT_COLUMNS = ["order_name", "seq", "carrier_name", "tracking_number", "status", "raw_status", "source",
                  "delivery_confirmed", "age_band", "days_since_dispatch", "shipped_at", "last_scan_at",
                  "last_scan_place", "delivered_at", "no_movement", "open_exceptions", "team_mark", "track_url"]


def _cell(v: Any) -> str:
    s = "" if v is None else str(v)
    # Spreadsheet formula injection guard: a leading = + - @ (or tab/CR) is neutralised.
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(brand: str | None = None, q: str | None = None, status: str | None = None, band: str | None = None,
               carrier: str | None = None, view: str | None = None, flag: str | None = None) -> str:
    params = [("select", ",".join(EXPORT_COLUMNS)), *_list_params(brand, q, status, band, carrier, view, flag),
              ("order", "days_since_dispatch.desc.nullslast")]
    rows: list[dict[str, Any]] = []
    for offset in range(0, 10000, 1000):
        page = client().select("shipment_list", params, offset=offset, limit=1000).rows
        rows += page
        if len(page) < 1000:
            break
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)
    for r in rows:
        w.writerow([_cell(r.get(k)) for k in EXPORT_COLUMNS])
    return buf.getvalue()
