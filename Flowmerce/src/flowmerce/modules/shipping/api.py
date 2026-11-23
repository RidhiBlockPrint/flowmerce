"""Shipping routes, mounted under /api/shipping. Every route checks the same `view` permission as the rest of
Flowmerce; writes (refresh, team mark) are recorded in the shared audit log.

Supabase problems become HTTP 503 with a `code` (not_configured, schema_missing, permission_denied,
connection_failed) so the page can explain what to do. /summary never fails: it reports the state instead,
so a Shipping outage cannot break Home."""
from __future__ import annotations

from fastapi import APIRouter, Body, Request, Response

from ..seo.audit import audit
from ..seo.auth import require_perm
from ..seo.util import HttpError
from . import board, mcf_sync, service
from .supabase import SupabaseError

shipping = APIRouter(prefix="/api/shipping")

_STATUS_FOR = {"not_configured": 503, "schema_missing": 503, "permission_denied": 503,
               "connection_failed": 503, "bad_request": 400, "not_found": 404, "error": 502}


def _fail(e: SupabaseError) -> HttpError:
    return HttpError(_STATUS_FOR.get(e.state, 502), e.message, e.state)


# ------------------------------------------------------------------------------- the Shipping page (board.py)
# Every read answers 200 with a `source` block. When Supabase can not be read, source.state says why
# (not_configured, connection_failed, permission_denied, schema_mismatch) and the data fields are absent: never zero.
_SOURCE_STATE = {"not_configured": "not_configured", "schema_missing": "schema_mismatch",
                 "permission_denied": "permission_denied", "connection_failed": "connection_failed"}


def _unavailable(brand: str, e: SupabaseError) -> dict:
    state = _SOURCE_STATE.get(e.state, "connection_failed")
    reason = e.message
    if e.state == "schema_missing":
        reason = ("The view ops.flow_board is missing or out of date. Run supabase/107_flow_board.sql in the Supabase "
                  "SQL editor, then reload this page.")
    return {"brand": brand, "scope": brand, "source": {"state": state, "reason": reason, "asOf": None, "parts": {}},
            "notConfigured": []}


def _dataset(brand: str, refresh: bool = False) -> board.Dataset:
    return board.dataset(brand, refresh=refresh)


def _int(v: str, default: int, low: int = 0, high: int = 10_000) -> int:
    try:
        return max(low, min(high, int(v)))
    except (TypeError, ValueError):
        return default


@shipping.get("/summary")
def summary(request: Request, brand: str = "all"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        return _unavailable(brand, e)
    return board.envelope(ds, **board.summary(ds))


@shipping.get("/shipments")
def shipments(request: Request, brand: str = "all", q: str = "", carrier: str = "", cat: str = "", status: str = "",
              days: str = "", sort: str = "priority", page: str = "0", size: str = "25"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        return {**_unavailable(brand, e), "total": None, "rows": None}
    return board.envelope(ds, **board.list_rows(ds, page=_int(page, 0), size=_int(size, 25, 1, 200), q=q[:100],
                                                 carrier=carrier[:80], cat=cat[:20], status=status[:40],
                                                 days=_int(days, 0, 0, 3650), sort=sort))


@shipping.get("/shipments/{order}")
def shipment(request: Request, order: str, brand: str = "all"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
        d = board.order_detail(ds, order[:60])
    except SupabaseError as e:
        raise _fail(e) from None
    if d is None:
        raise HttpError(404, "No shipment found for that order.", "not_found")
    return board.envelope(ds, **d)


@shipping.post("/shipments/{order}/note")
def order_note(request: Request, order: str, brand: str = "all", body: dict = Body(default={})):
    user = require_perm(request, "view")
    action = body.get("action") if isinstance(body.get("action"), str) else ""
    text = body.get("text") if isinstance(body.get("text"), str) else ""
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        raise _fail(e) from None
    d = board.annotate(ds, order[:60], action, text, user.get("name") or user.get("email") or "team")
    audit(user, f"shipping.order_{action}", "order", order[:60], d.get("brand") or "",
          summary=f"Shipping: {action}{' ' + text.strip().lower()[:12] if action == 'outcome' else ''} on order {order[:60]}",
          details={"has_text": bool(text.strip())})
    return board.envelope(ds, **d)


@shipping.get("/analytics")
def analytics(request: Request, brand: str = "all", period: str = "30"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        return {**_unavailable(brand, e), "kpis": None}
    return board.envelope(ds, **board.analytics(ds, 90 if period == "90" else 30))


@shipping.get("/checks")
def checks(request: Request, brand: str = "all"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        return {**_unavailable(brand, e), "exceptions": None, "reshipped": None}
    return board.envelope(ds, **board.checks(ds))


@shipping.get("/export/{kind}")
def export_kind(request: Request, kind: str, brand: str = "all", q: str = "", carrier: str = "", cat: str = "",
                status: str = "", days: str = "", sort: str = "priority"):
    user = require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        raise _fail(e) from None
    if kind == "shipments":
        rows = board.select_rows(ds, q=q[:100], carrier=carrier[:80], cat=cat[:20], status=status[:40],
                                 days=_int(days, 0, 0, 3650), sort=sort)
        body, n, name = board.csv_shipments(rows), len(rows), "shipments.csv"
    elif kind == "escalation":
        (body, n), name = board.csv_escalation(ds), "escalation-list.csv"
    else:
        raise HttpError(404, "Unknown export.", "not_found")
    audit(user, "shipping.export", "shipping", kind, "" if brand == "all" else brand, summary=f"{n} rows")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@shipping.get("/import/sample")
def import_sample(request: Request, brand: str = "all"):
    require_perm(request, "view")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        raise _fail(e) from None
    return {"text": board.sample_sheet(ds), "carriers": board.import_carriers(ds)}


@shipping.post("/import/preview")
def import_preview(request: Request, brand: str = "all", body: dict = Body(default={})):
    require_perm(request, "view")
    text = body.get("text")
    if not isinstance(text, str):
        raise HttpError(400, "Send the sheet as text.", "bad_request")
    try:
        ds = _dataset(brand)
    except SupabaseError as e:
        raise _fail(e) from None
    return board.envelope(ds, **board.preview_import(ds, text))


@shipping.get("/parcel/{tracking_id}")
def parcel(request: Request, tracking_id: str):
    """One parcel by its tracking id (the earlier detail view)."""
    require_perm(request, "view")
    try:
        d = service.shipment_detail(tracking_id)
    except SupabaseError as e:
        raise _fail(e) from None
    if d is None:
        raise HttpError(404, "Shipment not found.", "not_found")
    return d


@shipping.post("/shipments/{tracking_id}/mark")
def mark(request: Request, tracking_id: str, body: dict = Body(default={})):
    user = require_perm(request, "view")
    mark_ = body.get("mark") if isinstance(body.get("mark"), str) else None
    note = body.get("note") if isinstance(body.get("note"), str) else None
    try:
        res = service.set_mark(tracking_id, mark_, note, user["email"])
        board.apply_mark(tracking_id, mark_)
    except SupabaseError as e:
        raise _fail(e) from None
    audit(user, "shipping.team_mark", "tracking_number", tracking_id,
          summary=f"Team mark {mark_ or '(note)'}", details={"mark": mark_, "has_note": bool(note)})
    return res


@shipping.get("/diagnostics")
def diagnostics(request: Request, brand: str = "all", problem: str = "", page: str = "1", size: str = "25"):
    require_perm(request, "view")
    try:
        return service.diagnostics(brand, problem, page, size)
    except SupabaseError as e:
        raise _fail(e) from None


@shipping.get("/carriers")
def carriers(request: Request, brand: str = "all"):
    require_perm(request, "view")
    try:
        return service.carriers(brand)
    except SupabaseError as e:
        raise _fail(e) from None


@shipping.post("/refresh")
def refresh(request: Request):
    user = require_perm(request, "view")
    try:
        res = service.refresh(user["email"])
        try:
            board.snapshot(force=True)       # the person pressing Refresh sees the new figures at once
        except SupabaseError:
            board.forget()
    except SupabaseError as e:
        audit(user, "shipping.refresh_failed", "sync_run", summary=e.message[:200])
        raise _fail(e) from None
    audit(user, "shipping.refresh", "sync_run", str((res.get("result") or {}).get("run_id", "")),
          summary="Refreshed shipping data from the Shopify orders in Supabase", details=res.get("result"))
    return res


@shipping.post("/amazon-mcf/sync")
def amazon_mcf_sync(request: Request):
    """Copy the Amazon MCF tracking sheet into Supabase now (the same copy that runs daily at 09:00 IST)."""
    user = require_perm(request, "view")
    try:
        res = mcf_sync.sync(user["email"])
    except SupabaseError as e:
        audit(user, "shipping.amazon_mcf_sync_failed", "sync_run", summary=e.message[:200])
        raise _fail(e) from None
    if res["state"] == "ok":
        try:
            board.snapshot(force=True)
        except SupabaseError:
            board.forget()
    audit(user, "shipping.amazon_mcf_sync" if res["state"] == "ok" else "shipping.amazon_mcf_sync_failed", "sync_run",
          summary=f"Copied {res['rows']} rows from the MCF sheet" if res["state"] == "ok" else (res.get("error") or "")[:200])
    return res


@shipping.get("/export.csv")
def export(request: Request, brand: str = "all", q: str = "", status: str = "", band: str = "",
           carrier: str = "", view: str = "open", flag: str = ""):
    user = require_perm(request, "view")
    try:
        body = service.export_csv(brand, q, status, band, carrier, view, flag)
    except SupabaseError as e:
        raise _fail(e) from None
    audit(user, "shipping.export", "shipment_list", summary="Exported shipments CSV",
          details={"view": view, "flag": flag, "band": band, "status": status})
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="flowmerce-shipments.csv"'})
