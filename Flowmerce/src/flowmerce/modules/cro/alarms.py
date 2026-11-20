"""CRO alarms: evaluate each active rule of a store and open or resolve its alert.

Kinds (cro.alarm_rules.kind):
  * cvr_drop: yesterday's conversion rate fell by `threshold` % or more against the day before. One
    alert per store-local day; the open alert is resolved by the next day that is back under the
    threshold.
  * no_product_orders: no non-cancelled order with a product matching `product_keyword` for
    `threshold` hours. Resolved as soon as such an order arrives. Not checked while the order copy
    is stale (a failed or late sync would otherwise look like "no orders").
The database refuses duplicates (one open alert per rule, one cvr_drop alert per day), so two
processes can run the check at once without double alerts. Alerts are shown in the app; no email is
sent.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import conversion, data, metrics
from .shopify import AnalyticsError

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=45)  # order copy older than this: product alarms wait


def evaluate_cvr(comparison: dict[str, Any], threshold: float) -> str:
    """'insufficient_data' | 'normal' | 'triggered' for a cvr_comparison() result."""
    drop = comparison.get("drop_percent")
    if drop is None:
        return "insufficient_data"
    return "triggered" if drop >= threshold else "normal"


def evaluate_gap(
    last_at: datetime | None, now: datetime, threshold_hours: float
) -> tuple[str, float | None]:
    """('no_matching_orders' | 'normal' | 'triggered', hours since the last matching order)."""
    if last_at is None:
        return "no_matching_orders", None
    hours = round((now - last_at).total_seconds() / 3600, 2)
    return ("triggered" if hours >= threshold_hours else "normal"), hours


def _fresh(state: dict[str, Any] | None, now: datetime) -> bool:
    if not state or state.get("last_status") != "ok":
        return False
    last = data.parse_ts(state.get("last_run_at"))
    return last is not None and now - last <= STALE_AFTER


def _check_cvr(rule: dict[str, Any], store: str, today: date, now: datetime) -> dict[str, Any]:
    threshold = float(rule["threshold"])
    try:
        cmp = conversion.cvr_comparison(conversion.daily(store, today, 7), today)
    except AnalyticsError as e:
        return {"status": "unavailable", "reason": e.state}
    status = evaluate_cvr(cmp, threshold)
    result = {"status": status, "threshold_percent": threshold, **cmp}
    opened = data.open_alert(int(rule["id"]))
    if status != "triggered":
        if opened and status == "normal":
            data.resolve_alert(int(opened["id"]), now)
            result["resolved_alert_id"] = opened["id"]
        return result
    if opened and opened.get("period_date") == cmp["yesterday_date"]:
        return {**result, "status": "alarm_active", "alert_id": opened["id"]}
    if opened:  # an older day's alert: this is a new drop
        data.resolve_alert(int(opened["id"]), now)
    message = (
        f"Conversion rate fell {cmp['drop_percent']}%: {cmp['previous_cvr']}% on "
        f"{cmp['previous_date']} "
        f"-> {cmp['yesterday_cvr']}% on {cmp['yesterday_date']} (alarm at {threshold:g}%)."
    )
    alert = data.insert_alert(
        {
            "rule_id": rule["id"],
            "store": store,
            "period_date": cmp["yesterday_date"],
            "message": message,
            "details": cmp,
        }
    )
    return {
        **result,
        "status": "alarm_triggered" if alert else "alarm_active",
        "alert_id": alert["id"] if alert else None,
    }


def gap_figures(rule: dict[str, Any], snap: data.Snapshot, now: datetime) -> dict[str, Any]:
    """A product alarm's state from the snapshot, without recording anything (pure)."""
    keyword = str(rule.get("product_keyword") or "")
    threshold = float(rule["threshold"])
    last = metrics.last_order_with(snap, keyword)
    status, hours = evaluate_gap(last.placed_at if last else None, now, threshold)
    return {
        "status": status,
        "threshold_hours": threshold,
        "keyword": keyword,
        "hours_elapsed": hours,
        "last_order": last.name if last else None,
        "last_order_at": last.placed_at.isoformat() if last else None,
        "_last_placed": last.placed_at if last else None,
    }


def _check_gap(rule: dict[str, Any], store: str, now: datetime) -> dict[str, Any]:
    if not _fresh(data.sync_state(store), now):
        return {"status": "data_stale"}
    result = gap_figures(rule, data.snapshot(store), now)
    last_placed: datetime | None = result.pop("_last_placed")
    status, keyword, threshold, hours = (
        result["status"],
        result["keyword"],
        result["threshold_hours"],
        result["hours_elapsed"],
    )
    opened = data.open_alert(int(rule["id"]))
    if opened and last_placed and last_placed > (data.parse_ts(opened.get("triggered_at")) or now):
        data.resolve_alert(int(opened["id"]), now)
        result["resolved_alert_id"] = opened["id"]
        opened = None
    if status != "triggered":
        return result
    if opened:
        return {**result, "status": "alarm_active", "alert_id": opened["id"]}
    message = (
        f"No order with a '{keyword}' product for {hours}h (alarm at {threshold:g}h). "
        f"Last one: {result['last_order'] or '-'}."
    )
    alert = data.insert_alert(
        {
            "rule_id": rule["id"],
            "store": store,
            "period_date": None,
            "message": message,
            "details": {k: result[k] for k in ("hours_elapsed", "last_order", "last_order_at")},
        }
    )
    return {
        **result,
        "status": "alarm_triggered" if alert else "alarm_active",
        "alert_id": alert["id"] if alert else None,
    }


def check_rule(
    rule: dict[str, Any], store: str, today: date, now: datetime | None = None
) -> dict[str, Any]:
    """Evaluate one rule and record the result. Inactive rules are not evaluated."""
    now = now or datetime.now(UTC)
    if not rule.get("is_active"):
        return {"status": "rule_inactive"}
    result = (
        _check_cvr(rule, store, today, now)
        if rule["kind"] == "cvr_drop"
        else _check_gap(rule, store, now)
    )
    data.mark_checked(int(rule["id"]), now)
    return result


def check_store(store: str, today: date) -> dict[str, Any]:
    """Every rule of a store. Never raises for one rule: its error is returned instead."""
    if not data.alarms_enabled(store):
        return {"store": store, "state": "alarms_off", "rules": {}}
    out: dict[str, Any] = {}
    for rule in data.alarm_rules(store):
        try:
            out[str(rule["id"])] = check_rule(rule, store, today)
        except Exception as e:  # noqa: BLE001 - one broken rule must not stop the others
            log.exception("CRO alarm rule %s failed", rule.get("id"))
            out[str(rule["id"])] = {
                "status": "error",
                "detail": (getattr(e, "message", None) or str(e))[:300],
            }
    return {"store": store, "state": "checked", "rules": out}
