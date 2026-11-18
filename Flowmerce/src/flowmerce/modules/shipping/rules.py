"""Pure display and freshness rules for shipping data (no I/O, fully unit-tested).

The database decides the facts (status, source, delivery confirmation, age band). These rules only decide
how honestly to *describe* them, so the same words are used on every screen."""
from __future__ import annotations

from datetime import datetime, timezone

STATUS_LABELS = {
    "pending": "Unverified",
    "info_received": "Label created",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "exception": "Delivery problem",
    "returned": "Returned",
    "expired": "Tracking expired",
}
STATUS_TONES = {
    "pending": "neutral", "info_received": "info", "in_transit": "info", "out_for_delivery": "info",
    "delivered": "ok", "exception": "crit", "returned": "warn", "expired": "neutral",
}
SOURCE_LABELS = {
    "shopify": "Shopify", "tracker_import": "Shopify (old tracker import)", "amazon": "Amazon",
    "aggregator": "Tracking service", "carrier_api": "Carrier", "manual": "Entered by hand",
}
# Sources that can confirm a delivery. Shopify alone cannot.
CONFIRMING_SOURCES = {"amazon", "aggregator", "carrier_api"}

ALLOWED_SORTS = {
    "days": "days_since_dispatch", "shipped": "shipped_at", "scan": "last_scan_at",
    "order": "order_name", "carrier": "carrier_id", "status": "status",
}
ALLOWED_FILTERS = {
    "status": {"pending", "info_received", "in_transit", "out_for_delivery", "delivered", "exception", "returned", "expired"},
    "band": {"green", "yellow", "orange", "red", "delivered", "closed"},
}
TEAM_MARKS = ("delivered", "lost", "failed", "in_transit", "checked")


def status_view(status: str | None, source: str | None, delivery_confirmed: bool | None) -> dict:
    """Label, tone and an honest qualifier for one tracking status."""
    s = status or "pending"
    label = STATUS_LABELS.get(s, s.replace("_", " ").capitalize())
    qualifier = ""
    if s == "delivered" and not delivery_confirmed:
        qualifier = "not carrier-confirmed"
    elif s == "pending":
        qualifier = "no carrier evidence yet"
    return {
        "label": label,
        "tone": STATUS_TONES.get(s, "neutral"),
        "qualifier": qualifier,
        "source": SOURCE_LABELS.get(source or "", source or "unknown"),
        "confirmed": bool(delivery_confirmed) and s == "delivered",
    }


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def freshness(last_ok_at: str | None, last_status: str | None, now: datetime | None = None,
              warn_hours: float = 3, stale_hours: float = 26) -> dict:
    """How current a feed is. Never calls old data 'live'."""
    now = now or datetime.now(timezone.utc)
    ok = parse_ts(last_ok_at)
    if ok is None:
        return {"level": "none", "label": "Never synced", "hours": None}
    hours = (now - ok).total_seconds() / 3600
    if last_status == "failed":
        level = "crit"
    elif hours >= stale_hours:
        level = "crit"
    elif hours >= warn_hours:
        level = "warn"
    else:
        level = "ok"
    label = "Last success " + ("under an hour ago" if hours < 1 else f"{int(hours)} h ago" if hours < 48 else f"{int(hours // 24)} days ago")
    if last_status == "failed":
        label += " · latest attempt failed"
    return {"level": level, "label": label, "hours": round(hours, 1)}


def clamp_int(value: str | int | None, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def search_filter(q: str) -> str | None:
    """PostgREST `or=` filter for order number or tracking number. Keeps only letters, digits, - and _ so no
    PostgREST syntax character (comma, dot, brackets, quotes, spaces) can reach the query."""
    q = "".join(ch for ch in (q or "") if ch.isalnum() or ch in "-_")
    if len(q) < 2:
        return None
    q = q[:40]
    return f"(order_name.ilike.*{q}*,tracking_number.ilike.*{q}*)"
