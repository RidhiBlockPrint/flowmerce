"""Amazon Multi-Channel Fulfillment (MCF) data on the Shipping board.

Amazon does not tell Shopify when it ships or delivers an MCF order. Flowmerce reads Amazon's data only from
Supabase, the flattened view ops.amazon_mcf_packages (109 + 111): the team's MCF tracking Google Sheet is copied there
every morning by mcf_sync.py. It lays that data over the board rows before the rules run:

  * a parcel whose tracking number Amazon knows takes Amazon's status (Amazon wins over Shopify, which never hears
    from Amazon): DELIVERED means delivered, with Amazon's time, source "amazon";
  * an order Shopify shows as unfulfilled, with an MCF order for it, becomes one parcel per Amazon package (or one
    "with Amazon, not shipped yet" row), replacing the hub's older copy of the same thing;
  * a second MCF order sent RESHIP_GAP_DAYS or more after the first marks the first one's undelivered parcels as
    reshipped (MCF orders created on the same day are one order split into several parcels, not a reship);
  * an Amazon parcel for an order Shopify already shows fulfilled with other tracking numbers is added as an extra
    parcel ("amazon_extra"): its tracking number is missing from the Shopify order.

The view holds no names, street addresses, phone numbers or e-mails.
"""
from __future__ import annotations

import re
from typing import Any

from datetime import date, timedelta

from .supabase import SupabaseError, client

COLUMNS = ("sfo_id,store,displayable_order_id,order_status,received_at,order_status_at,amazon_shipment_id,shipment_status,"
           "shipped_at,package_number,tracking_number,carrier_code,estimated_arrival,tracking_status,tracking_status_text,"
           "delivered_at,last_event_at,last_event_text,last_event_city,last_event_state,events,fetched_at")

# Amazon's package status -> Flowmerce tracking status
STATUS = {"DELIVERED": "delivered", "IN_TRANSIT": "in_transit", "AVAILABLE_FOR_PICKUP": "out_for_delivery",
          "OUT_FOR_DELIVERY": "out_for_delivery",
          "DELAYED": "exception", "UNDELIVERABLE": "exception", "CUSTOMER_ACTION": "exception",
          "RETURNING": "returned", "RETURNED": "returned"}
CLOSED_ORDER = {"cancelled", "invalid", "unfulfillable"}
RESHIP_GAP_DAYS = 3
CARRIER = {"USPS": "USPS", "UPS": "UPS", "FEDEX": "FedEx", "DHL": "DHL Express", "AMZL": "Amazon Logistics US",
           "AMZL_US": "Amazon Logistics US", "AMAZON": "Amazon Logistics US", "AMAZON LOGISTICS": "Amazon Logistics US",
           "ONTRAC": "OnTrac"}


def load() -> list[dict[str, Any]] | None:
    """All Amazon MCF packages from Supabase, or None when 109 has not been run (the page works without them).
    With 111 run, each row says where it came from (source: 'sheet' or 'amazon_api')."""
    try:
        return _read(COLUMNS + ",source,synced_at")
    except SupabaseError:
        pass
    try:
        return _read(COLUMNS)                      # 111 not run yet
    except SupabaseError:
        return None


def _read(columns: str) -> list[dict[str, Any]]:
    c = client()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = c.select("amazon_mcf_packages", [("select", columns), ("order", "sfo_id.asc,package_number.asc.nullsfirst")],
                        offset=offset, limit=1000).rows
        rows += page
        if len(page) < 1000:
            return [dict(p, _source=p.get("source") or "amazon_api") for p in rows]
        offset += 1000


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


def _digits(text: str | None) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())


def _store_of(p: dict[str, Any]) -> str | None:
    if p.get("store"):
        return p["store"]
    text = f"{p.get('displayable_order_id') or ''} {p.get('sfo_id') or ''}".upper()
    return "RBP" if re.search(r"RBP|SHOP-R", text) else None


def _carrier(code: str | None) -> str:
    c = (code or "").strip().upper()
    return CARRIER.get(c, code or "Amazon Logistics US")


def overlay(rows: list[dict[str, Any]], packages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The board rows with Amazon's word applied. Returns a new list; input rows are not changed."""
    if not packages:
        return rows
    by_tracking = {str(p["tracking_number"]).strip().upper(): p for p in packages if p.get("tracking_number")}

    # which Shopify order each MCF order belongs to: store + order number digits (store guessed when not loaded)
    orders: dict[tuple[str, str], list[dict[str, Any]]] = {}
    numbers_per_store: dict[str, set[str]] = {}
    for r in rows:
        numbers_per_store.setdefault(r.get("store") or "", set()).add(_digits(r.get("order_name")))
    for p in packages:
        d = _digits(p.get("displayable_order_id"))
        if not d:
            continue
        store = _store_of(p)
        if store is None:   # no store given: use it only if exactly one store has this order number
            owners = [s for s, nums in numbers_per_store.items() if d in nums]
            if len(owners) != 1:
                continue
            store = owners[0]
        orders.setdefault((store, d), []).append(p)

    out: list[dict[str, Any]] = []
    replaced: set[tuple[str, str]] = set()
    for r in rows:
        key = (r.get("store") or "", _digits(r.get("order_name")))
        if r["row_kind"] in ("order", "amazon") and key in orders:
            replaced.add(key)                      # rebuilt from Amazon's own data below
            continue
        r2 = dict(r)
        pkg = by_tracking.get(str(r.get("tracking_number") or "").strip().upper())
        if pkg and r["row_kind"] == "tracking":
            _apply(r2, pkg)
        out.append(r2)

    template = {(r.get("store") or "", _digits(r.get("order_name"))): r for r in rows if r["row_kind"] in ("order", "amazon")}
    for key in replaced:
        base = template[key]
        mcf = sorted(orders[key], key=lambda p: (p.get("received_at") or "", p.get("package_number") or ""))
        live = [p for p in mcf if (p.get("order_status") or "").lower() not in CLOSED_ORDER]
        for p in live:
            row = _amazon_row(base, p)
            later = _reshipped_by(p, live)
            if later and row["status"] != "delivered":
                row["_mcf_superseded"] = {"order": base.get("order_name"), "tracking": later.get("tracking_number"),
                                          "carrier": _carrier(later.get("carrier_code")), "at": later.get("received_at"),
                                          "ref": later.get("sfo_id")}
            out.append(row)
        if not live:   # every MCF order cancelled or unfulfillable: the order is back to "not dispatched"
            why = {(p.get("order_status") or "").lower() for p in mcf}
            out.append(dict(base, row_kind="order", amazon_status="Amazon cannot ship it (unfulfillable)"
                            if "unfulfillable" in why else "Amazon order cancelled"))

    # Amazon parcels the Shopify order does not list: Shopify shows it fulfilled, but with other tracking numbers
    on_board = set(by_tracking) & {str(r.get("tracking_number") or "").strip().upper() for r in rows}
    shopify: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if r["row_kind"] in ("tracking", "shipment"):
            shopify.setdefault((r.get("store") or "", _digits(r.get("order_name"))), []).append(r)
    for key, mcf in orders.items():
        if key in replaced or key not in shopify:
            continue
        base = shopify[key][0]
        live = [p for p in mcf if (p.get("order_status") or "").lower() not in CLOSED_ORDER]
        for p in mcf:
            t = str(p.get("tracking_number") or "").strip().upper()
            if not t or t in on_board or (p.get("order_status") or "").lower() in CLOSED_ORDER:
                continue
            row = _amazon_row(base, p)
            later = _reshipped_by(p, live)       # a second MCF order re-sent it (e.g. #7254: 29 Sep, again 16 Oct)
            if later and row["status"] != "delivered":
                row["_mcf_superseded"] = {"order": base.get("order_name"), "tracking": later.get("tracking_number"),
                                          "carrier": _carrier(later.get("carrier_code")), "at": later.get("received_at"),
                                          "ref": later.get("sfo_id")}
            row["row_id"] = f"{base.get('order_id')}:mcf-extra:{p.get('sfo_id')}:{p.get('package_number') or 0}"
            row["amazon_extra"] = sorted({f"{x.get('carrier_name') or 'Unknown'} {x.get('tracking_number') or ''}".strip()
                                          for x in shopify[key]})
            out.append(row)
    return out


def _reshipped_by(p: dict[str, Any], live: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The MCF order that re-sent this one: a later MCF order for the same Shopify order received RESHIP_GAP_DAYS or
    more after it. Same-day MCF orders are a split shipment."""
    mine = _day(p.get("received_at"))
    if not mine:
        return None
    later = [x for x in live if (_day(x.get("received_at")) or mine) - mine >= timedelta(days=RESHIP_GAP_DAYS)]
    return max(later, key=lambda x: x.get("received_at") or "") if later else None


def _apply(r: dict[str, Any], p: dict[str, Any]) -> None:
    """Amazon's package status on a Shopify parcel with the same tracking number."""
    status = STATUS.get((p.get("tracking_status") or "").upper())
    r["amazon_status"] = p.get("tracking_status_text") or p.get("tracking_status") or p.get("shipment_status") or p.get("order_status")
    r["amazon_at"] = p.get("last_event_at") or p.get("order_status_at")
    r["amazon_ref"] = p.get("sfo_id")
    r["amazon_tracking"] = p.get("tracking_number")
    r["amazon_events"] = p.get("events") or []
    if not status:
        return
    newer = not r.get("last_scan_at") or (p.get("last_event_at") or "") >= (r.get("last_scan_at") or "")
    if status == "delivered" or newer or (r.get("status") or "pending") in ("pending", "info_received"):
        r["status"] = status
        r["raw_status"] = p.get("tracking_status")
        r["source"] = "amazon"
        r["last_scan_at"] = p.get("last_event_at") or r.get("last_scan_at")
        r["last_scan_text"] = p.get("last_event_text") or p.get("tracking_status_text") or r.get("last_scan_text")
        place = ", ".join(x for x in (p.get("last_event_city"), p.get("last_event_state")) if x)
        r["last_scan_place"] = place or r.get("last_scan_place")
        if status == "delivered":
            r["delivered_at"] = p.get("delivered_at") or p.get("last_event_at")
        if p.get("estimated_arrival") and not r.get("eta"):
            r["eta"] = str(p["estimated_arrival"])[:10]


def track_url(number: str | None) -> str | None:
    n = (number or "").strip()
    if not n:
        return None
    if n.upper().startswith("TBA"):
        return f"https://track.amazon.com/tracking/{n}"
    if re.fullmatch(r"9[2-5]\d{18,24}", n):
        return f"https://tools.usps.com/go/TrackConfirmAction?tLabels={n}"
    if n.upper().startswith("1Z"):
        return f"https://www.ups.com/track?tracknum={n}"
    return None


def _amazon_row(base: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """One parcel built from Amazon's data for an order Shopify shows as unfulfilled."""
    shipped = p.get("shipped_at") if (p.get("shipment_status") or "").upper() == "SHIPPED" or p.get("tracking_number") else None
    row = dict(base)
    row.update({
        "row_kind": "amazon", "row_id": f"{base.get('order_id')}:mcf:{p.get('sfo_id')}:{p.get('package_number') or 0}",
        "tracking_id": None, "shipment_id": None, "kind": "mcf",
        "carrier_name": _carrier(p.get("carrier_code")) if p.get("tracking_number") or p.get("carrier_code") else "Amazon Logistics US",
        "tracking_number": p.get("tracking_number"), "track_url": track_url(p.get("tracking_number")),
        "status": "pending", "raw_status": p.get("order_status"), "source": "amazon",
        "shipped_at": shipped, "last_scan_at": None, "last_scan_place": None,
        "last_scan_text": f"Amazon: {p.get('shipment_status') or p.get('order_status') or 'order received'}",
        "delivered_at": None, "eta": str(p["estimated_arrival"])[:10] if p.get("estimated_arrival") else None,
        "last_check_ok_at": p.get("fetched_at"), "team_mark": None, "team_mark_at": None, "open_exceptions": 0,
        "amazon_status": p.get("order_status"), "amazon_at": p.get("order_status_at") or p.get("received_at"),
        "amazon_ref": p.get("sfo_id"), "amazon_tracking": p.get("tracking_number"), "amazon_checked_at": p.get("fetched_at"),
    })
    if p.get("tracking_number"):
        _apply(row, p)
    return row
