"""Amazon MCF tracking from the team's Google Sheet ("Sellora MCF Tracking", tab "Tracking").

The sheet is kept up to date from Amazon by the team's own tool: one row per MCF order with Amazon's order status,
the package's tracking number, carrier, dates and Amazon's latest tracking status. Flowmerce reads it server side
through the Google service account it already uses for Search Console / GA4 (scope spreadsheets.readonly), so the
sheet must be shared with that account as a Viewer and the Google Sheets API enabled in its Cloud project.

Rows come back in the package shape of ops.amazon_mcf_packages (109), so amazon_mcf.overlay() treats both the same.
Privacy: the Order column is sometimes a customer's name instead of an order number. Only order numbers are kept
(RBP1234, #1234, Shopify #1234 1, SHOP-RBP1234, or a plain 3-6 digit number); names, street addresses and links are
never kept. "Where" is the city / state of Amazon's last scan.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
DEFAULT_SHEET_ID = "1xVradFTHDhL1bvyCnxUtg_9N2p49ift9dUKTGVoqYNY"
IST = timedelta(hours=5, minutes=30)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
ORDER_PATTERNS = (re.compile(r"^\s*(?:SHOP-)?RBP\s*-?(\d{3,6})\b", re.I),     # RBP8870, SHOP-RBP8862-1
                  re.compile(r"#\s*(?:RBP)?\s*(\d{3,6})\b", re.I),           # #8306, Shopify #8608 1, Shopify # RBP8000 1
                  re.compile(r"^\s*SHOP-(\d{3,6})\b", re.I),                  # SHOP-8306
                  re.compile(r"^\s*(\d{3,6})\s*$"))                           # 8306

_state_lock = threading.Lock()
_last: dict[str, Any] = {"ok": None, "error": None, "at": None, "rows": 0}


def sheet_id() -> str:
    return (os.environ.get("AMAZON_MCF_SHEET_ID") or DEFAULT_SHEET_ID).strip()


def sheet_tabs() -> list[str] | None:
    """The tabs to read: AMAZON_MCF_SHEET_TABS (comma list) or AMAZON_MCF_SHEET_TAB; None = every tab that has the MCF
    columns (e.g. "Tracking" plus a "History" tab the ERP team adds for older MCF orders)."""
    raw = os.environ.get("AMAZON_MCF_SHEET_TABS") or os.environ.get("AMAZON_MCF_SHEET_TAB") or ""
    tabs = [t.strip() for t in raw.split(",") if t.strip()]
    return tabs or None


def merge(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One package per MCF id + parcel across tabs: the copy Amazon checked most recently wins."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for p in packages:
        k = (p["sfo_id"], p.get("package_number") or "")
        if k not in best or (p.get("fetched_at") or "") >= (best[k].get("fetched_at") or ""):
            best[k] = p
    return list(best.values())


def status() -> dict[str, Any]:
    """The last read's outcome, for the page's Data source card (no sheet contents)."""
    with _state_lock:
        return dict(_last)


def _remember(ok: bool, error: str | None = None, rows: int = 0) -> None:
    with _state_lock:
        _last.update(ok=ok, error=error, at=datetime.now(UTC).isoformat(timespec="seconds"), rows=rows)


def order_number(*texts: str | None) -> str | None:
    """The Shopify order number's digits from the Order / MCF id cells, or None (a customer name, another channel's
    long order id, or nothing)."""
    for text in texts:
        for rx in ORDER_PATTERNS:
            m = rx.search(text or "")
            if m:
                return m.group(1)
    return None


def _ist(text: str | None, now: datetime) -> str | None:
    """'18 Nov 03:48' (IST, no year) -> UTC ISO; the year is the one that puts it closest before now."""
    m = re.match(r"^\s*(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{1,2}):(\d{2})", text or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    day, mon, hh, mm = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)), int(m.group(4))
    for year in (now.year, now.year - 1):
        try:
            t = datetime(year, mon, day, hh, mm, tzinfo=UTC) - IST
        except ValueError:
            return None
        if t <= now + timedelta(days=1):
            return t.isoformat(timespec="seconds")
    return None


def _date(text: str | None) -> str | None:
    t = (text or "").strip()
    return t[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", t) else None


def _iso(text: str | None) -> str | None:
    t = (text or "").strip()
    return t if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", t) else None


def parse(values: list[list[Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Sheet rows (first row = headers) -> package dicts. Columns are found by header name, so their order may change."""
    now = now or datetime.now(UTC)
    if not values:
        return []
    head = [str(h).strip().lower() for h in values[0]]

    def col(*names: str) -> int | None:
        for n in names:
            if n.lower() in head:
                return head.index(n.lower())
        return None

    ix = {k: col(*v) for k, v in {
        "brand": ("Brand",), "order": ("Order",), "mcf": ("MCF id", "MCF ID"), "status": ("Order status",),
        "received": ("Received",), "speed": ("Speed",), "parcel": ("Parcel",), "carrier": ("Carrier",),
        "tracking": ("Tracking",), "shipped": ("Shipped",), "arrives": ("Arrives by",), "now": ("Now",),
        "last": ("Last scan",), "where": ("Where",), "delivered": ("Delivered (IST)",), "checked": ("Checked (IST)",),
        "last_iso": ("_lastIso",), "flag": ("Flag",)}.items()}
    if ix["mcf"] is None or ix["brand"] is None:
        raise ValueError("The sheet has no 'MCF id' or 'Brand' column.")

    out: list[dict[str, Any]] = []
    for raw in values[1:]:
        def cell(k: str) -> str:
            i = ix[k]
            return str(raw[i]).strip() if i is not None and i < len(raw) and raw[i] is not None else ""

        sfo = cell("mcf")
        if not sfo:
            continue
        brand = cell("brand").lower()
        store = "RBP" if brand.startswith("ridhi") or brand == "rbp" else "CPC" if brand.startswith("cpc") else None
        now_status = cell("now").upper() or None
        last_iso = _iso(cell("last_iso"))
        where = [p.strip() for p in cell("where").split(",") if p.strip()]
        delivered = None
        if now_status == "DELIVERED":
            delivered = last_iso or _ist(cell("delivered"), now)
        tracking = cell("tracking") or None
        out.append({
            "sfo_id": sfo, "store": store, "displayable_order_id": order_number(cell("order"), sfo),
            "order_status": cell("status") or None, "received_at": _date(cell("received")), "order_status_at": None,
            "speed": cell("speed") or None,
            "amazon_shipment_id": None, "shipment_status": "SHIPPED" if tracking or _date(cell("shipped")) else None,
            "shipped_at": _date(cell("shipped")), "package_number": cell("parcel") or None,
            "tracking_number": tracking, "carrier_code": cell("carrier") or None,
            "estimated_arrival": _date(cell("arrives")),
            "tracking_status": now_status, "tracking_status_text": cell("last") or None,
            "delivered_at": delivered, "last_event_at": last_iso, "last_event_text": cell("last") or None,
            "last_event_city": where[0] if where else None, "last_event_state": where[1] if len(where) > 1 else None,
            "events": [], "fetched_at": _ist(cell("checked"), now), "sheet_flag": cell("flag") or None,
            "_source": "sheet",
        })
    return out


def load() -> list[dict[str, Any]] | None:
    """All MCF packages from the sheet, or None when it cannot be read (not shared, API off, no Google key).
    The reason is kept for status(); the page works without the sheet."""
    try:
        from ..seo.integrations.google import _token
        headers = {"Authorization": f"Bearer {_token(SCOPE)}"}
        base = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id()}"
        tabs = sheet_tabs()
        if tabs is None:
            res = httpx.get(base, params={"fields": "sheets.properties.title"}, headers=headers, timeout=30)
            if res.status_code >= 300:
                _remember(False, _reason(res))
                return None
            tabs = [s["properties"]["title"] for s in res.json().get("sheets") or []]
        res = httpx.get(f"{base}/values:batchGet", params=[("ranges", "'" + t_.replace("'", "''") + "'") for t_ in tabs] +
                        [("majorDimension", "ROWS"), ("valueRenderOption", "FORMATTED_VALUE")], headers=headers, timeout=60)
        if res.status_code >= 300:
            _remember(False, _reason(res))
            return None
        rows: list[dict[str, Any]] = []
        used = []
        for title, vr in zip(tabs, res.json().get("valueRanges") or []):
            try:
                part = parse(vr.get("values") or [])
            except ValueError:          # a tab without the MCF columns (notes, a summary): not MCF data
                continue
            rows += part
            used.append(title)
        if not used:
            _remember(False, "No tab of the MCF sheet has the 'MCF id' and 'Brand' columns.")
            return None
        rows = merge(rows)
        _remember(True, None, len(rows))
        with _state_lock:
            _last["tabs"] = used
        return rows
    except Exception as e:   # no key file, network, a renamed column: show why, keep the page working
        msg = getattr(e, "message", None) or str(e)
        _remember(False, f"The MCF sheet could not be read: {msg[:160]}")
        return None


def _reason(res: httpx.Response) -> str:
    msg = ((res.json() if res.content else {}).get("error") or {}).get("message") or res.reason_phrase
    if "has not been used" in msg or "is disabled" in msg:
        return "The Google Sheets API is not enabled for Flowmerce's Google Cloud project."
    if res.status_code in (403, 404):
        return "The MCF sheet is not shared with Flowmerce's Google service account."
    return f"Google Sheets answered {res.status_code}."
