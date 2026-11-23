"""CRO routes, mounted under /api/cro. Every route checks the `view` permission like the rest of
Flowmerce; every change (rules, settings, change log, manual sync) is written to the shared audit
log.

Errors the page can explain come back with a `code`:
  400 bad_request (a value that cannot be used), 404 not_found,
  503 not_configured / schema_missing / permission_denied / connection_failed (Supabase),
  503 reports_access_missing / query_error / shopify_error (Shopify analytics).
`brand` is 'ridhi' or 'cpc' on every route.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Request

from ..seo.audit import audit
from ..seo.auth import require_perm
from ..seo.util import HttpError
from ..shipping.supabase import SupabaseError
from . import ai_advice, alarms, data, goals, scheduler, service, sync
from .benchmarks import BENCHMARKS
from .config import store_for
from .shopify import AnalyticsError

cro = APIRouter(prefix="/api/cro")

# One shared JSON-body marker for the write routes (FastAPI reads the request body into it).
_BODY: Any = Body(default={})
_SUPABASE_STATUS = {
    "not_configured": 503,
    "schema_missing": 503,
    "permission_denied": 503,
    "connection_failed": 503,
    "bad_request": 400,
    "not_found": 404,
    "conflict": 409,
}


def _call[T](fn: Callable[[], T]) -> T:
    """Run a service call and turn its known failures into explained HTTP errors."""
    try:
        return fn()
    except service.InputError as e:
        raise HttpError(400, str(e), "bad_request") from None
    except AnalyticsError as e:
        raise HttpError(503, e.message, e.state) from None
    except SupabaseError as e:
        message = e.message
        if e.state == "schema_missing":
            message = (
                "The CRO tables are missing, or the `cro` schema is not exposed in Supabase "
                "(Project Settings -> Data API -> Exposed schemas). Run db/central/112, 113 "
                "and 114 first."
            )
        raise HttpError(_SUPABASE_STATUS.get(e.state, 502), message, e.state) from None


def _int(v: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(v)))
    except TypeError, ValueError:
        return default


def _who(user: dict[str, Any]) -> str:
    return str(user.get("email") or user.get("name") or "team")


# ------------------------------------------------------------------------------------------ reports
def _rq(request: Request, last: int | None = None, today: bool = True) -> service.RangeQuery:
    """The range a report asks for: `from`/`to` (YYYY-MM-DD) and `compare`, or the older
    `period` / `days` parameters when no range is given."""
    q = request.query_params
    days = q.get("days") or ""
    return service.RangeQuery(
        frm=(q.get("from") or "")[:10] or None,
        to=(q.get("to") or "")[:10] or None,
        compare=(q.get("compare") or "")[:20],
        period=(q.get("period") or "yesterday")[:20],
        last=_int(days, last or 0, 1, 366) if (days or last) else None,
        last_includes_today=today,
    )


@cro.get("/overview")
def overview(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """KPI cards for a range (or period) against its comparison."""
    require_perm(request, "view")
    return _call(lambda: service.overview(brand, _rq(request)))


@cro.get("/sales-breakdown")
def sales_breakdown(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Gross to total sales."""
    require_perm(request, "view")
    return _call(lambda: service.sales_breakdown(brand, _rq(request)))


@cro.get("/sales-trend")
def sales_trend(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Daily orders and sales against the comparison period (default: last 14 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.sales_trend(brand, _rq(request, 14, today=False)))


@cro.get("/order-health")
def order_health(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Paid / refunded / cancelled / pending orders (default: last 30 days)."""
    require_perm(request, "view")
    return _call(lambda: service.order_health(brand, _rq(request, 30)))


@cro.get("/products")
def products(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Product performance (default: last 30 days)."""
    require_perm(request, "view")
    return _call(lambda: service.products(brand, _rq(request, 30)))


@cro.get("/product-insights")
def product_insights(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Products tab: sales, refunds, GA4 views, groups, price bands, bought together (default: last
    28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.product_insights(brand, _rq(request, 28, today=False)))


@cro.get("/discount-codes")
def discount_codes(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Orders with vs without a discount code, and per code (default: last 28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.discount_codes(brand, _rq(request, 28, today=False)))


@cro.get("/customers")
def customers(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """New vs returning customers and the path to a first purchase (default: last 28 complete
    days)."""
    require_perm(request, "view")
    return _call(lambda: service.customers(brand, _rq(request, 28, today=False)))


@cro.get("/conversion")
def conversion_trend(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Daily sessions, funnel and conversion rate (default: last 7 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.conversion_trend(brand, _rq(request, 7, today=False)))


@cro.get("/funnel")
def funnel(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Yesterday's funnel."""
    require_perm(request, "view")
    return _call(lambda: service.funnel(brand))


@cro.get("/segments")
def segments(request: Request, brand: str = "ridhi", dimension: str = "device") -> dict[str, Any]:
    """Device or channel split (default: last 7 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.segments(brand, dimension[:20], _rq(request, 7, today=False)))


@cro.get("/landing-pages")
def landing_pages(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Landing pages, page types and bounce (default: last 28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_pages(brand, _rq(request, 28, today=False)))


@cro.get("/landing-compare")
def landing_compare(request: Request, brand: str = "ridhi", mode: str = "week") -> dict[str, Any]:
    """Every landing page week on week (mode=week) or month on month (mode=month)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_compare(brand, mode[:10]))


@cro.get("/landing-funnel")
def landing_funnel(request: Request, brand: str = "ridhi", mode: str = "week") -> dict[str, Any]:
    """Every landing page's funnel week on week (mode=week) or month on month (mode=month)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_funnel(brand, mode[:10]))


@cro.get("/landing-daily")
def landing_daily(
    request: Request, brand: str = "ridhi", paths: str = "", days: str = "60"
) -> dict[str, Any]:
    """Landing pages side by side, day by day (paths comma-separated; empty = the busiest 8)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_daily(brand, paths[:6000], _int(days, 60, 7, 60)))


@cro.get("/landing-page")
def landing_page(request: Request, brand: str = "ridhi", path: str = "") -> dict[str, Any]:
    """One landing page's deep dive (the last 60 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_page(brand, path[:500]))


@cro.get("/landing-grids")
def landing_grids(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Top landing pages x traffic source and page types x device (default: last 28 days)."""
    require_perm(request, "view")
    return _call(lambda: service.landing_grids(brand, _rq(request, 28, today=False)))


@cro.get("/traffic-changes")
def traffic_changes(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Device and channel changes with the top movers (default: last 7 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.traffic_changes(brand, _rq(request, 7, today=False)))


@cro.get("/geo")
def geo(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Conversion by country and US state (default: last 28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.geo(brand, _rq(request, 28, today=False)))


@cro.get("/site-health")
def site_health(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Page speed and site search (default: last 28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.site_health(brand, _rq(request, 28, today=False)))


@cro.get("/overview-trends")
def overview_trends(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Average order value by day and sales by channel (default: last 28 complete days)."""
    require_perm(request, "view")
    return _call(lambda: service.overview_trends(brand, _rq(request, 28, today=False)))


@cro.get("/checkout-extras")
def checkout_extras(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Payment methods, order values and items per order (default: last 28 days)."""
    require_perm(request, "view")
    return _call(lambda: service.checkout_extras(brand, _rq(request, 28)))


@cro.get("/buy-heatmap")
def buy_heatmap(request: Request, brand: str = "ridhi", days: str = "28") -> dict[str, Any]:
    """Conversion by weekday x hour over the last `days` (7-56) complete days."""
    require_perm(request, "view")
    return _call(lambda: service.buy_heatmap(brand, _int(days, 28, 7, 56)))


@cro.get("/home")
def home(request: Request, brand: str = "") -> dict[str, Any]:
    """Sales summary for Home (both stores when no brand). Never fails for data reasons."""
    require_perm(request, "view")
    return _call(lambda: service.home(brand or None))


@cro.get("/recommendations")
def recommendations(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Rule-based recommendations."""
    require_perm(request, "view")
    return _call(lambda: service.recommendation_list(brand))


def _known(brand: str) -> None:
    try:
        store_for(brand)
    except ValueError as e:
        raise HttpError(400, str(e), "bad_request") from None


@cro.get("/goal")
def goal(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The store's monthly revenue goal (0 = none)."""
    require_perm(request, "view")
    _known(brand)
    return goals.goal(brand)


@cro.put("/goal")
def set_goal(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Set or clear (0) the store's monthly revenue goal."""
    user = require_perm(request, "view")
    _known(brand)
    return goals.set_goal(brand, body or {}, user)


@cro.get("/ai-advice")
def ai_advice_state(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Claude's latest action plan for the store, and whether a new one is being made."""
    require_perm(request, "view")
    _known(brand)
    return ai_advice.state(brand)


@cro.post("/ai-advice")
def ai_advice_start(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Ask Claude for a new action plan (within the shared daily Claude limit). `auto: true` asks
    only once a day."""
    user = require_perm(request, "view")
    _known(brand)
    auto = bool((body or {}).get("auto"))
    st = ai_advice.start(brand, _who(user), auto=auto)
    if not auto:
        audit(user, "cro.ai_advice", "cro_store", None, brand, "Asked Claude for a CRO action plan")
    return st


@cro.get("/store-notes")
def store_notes(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """The team's notes about the store that Claude reads with the figures."""
    require_perm(request, "view")
    _known(brand)
    return ai_advice.notes(brand)


@cro.put("/store-notes")
def set_store_notes(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:
    """Save or clear (empty text) the team's notes about the store."""
    user = require_perm(request, "view")
    _known(brand)
    result = ai_advice.set_notes(brand, (body or {}).get("text"), _who(user))
    audit(
        user,
        "cro.store_notes",
        "cro_store",
        None,
        brand,
        f"CRO: {'saved' if result['text'] else 'cleared'} the store notes for Claude",
    )
    return result


@cro.get("/benchmarks")
def benchmarks(request: Request) -> dict[str, Any]:
    """Industry reference figures."""
    require_perm(request, "view")
    return {"benchmarks": BENCHMARKS}


# ------------------------------------------------------------------------------------------ alarms
@cro.get("/alarms")
def alarm_rules(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Alarm rules with their open alert."""
    require_perm(request, "view")
    return _call(lambda: service.alarm_list(brand))


@cro.post("/alarms")
def create_alarm(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Add an alarm rule."""
    user = require_perm(request, "view")
    rule = _call(lambda: service.create_rule(brand, body, _who(user)))
    audit(
        user,
        "cro.alarm_create",
        "cro_alarm_rule",
        rule.get("id"),
        brand,
        summary=f"CRO: added alarm '{rule.get('title')}'",
        details={"kind": rule.get("kind")},
    )
    return rule


@cro.patch("/alarms/{rule_id}")
def update_alarm(
    request: Request, rule_id: int, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Change an alarm rule."""
    user = require_perm(request, "view")
    rule = _call(lambda: service.update_rule(brand, rule_id, body, _who(user)))
    if rule is None:
        raise HttpError(404, "No such alarm rule for this store.", "not_found")
    audit(
        user,
        "cro.alarm_update",
        "cro_alarm_rule",
        rule_id,
        brand,
        summary=f"CRO: changed alarm '{rule.get('title')}'",
        details={"fields": sorted(body)},
    )
    return rule


@cro.get("/alerts")
def alerts(request: Request, brand: str = "ridhi", limit: str = "50") -> dict[str, Any]:
    """Recent alerts."""
    require_perm(request, "view")
    return _call(lambda: service.alert_list(brand, _int(limit, 50, 1, 500)))


# ------------------------------------------------------------------------------------------
# settings and sync
@cro.get("/settings")
def get_settings(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Per-store settings and data source state."""
    require_perm(request, "view")
    return _call(lambda: service.settings(brand))


@cro.patch("/settings")
def set_settings(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Switch alarms on or off, and/or save the free-shipping amount."""
    user = require_perm(request, "view")
    result = _call(lambda: service.set_settings(brand, body, _who(user)))
    parts = []
    if "alarms_enabled" in body:
        parts.append(f"alarms {'on' if result['alarms_enabled'] else 'off'}")
    if "free_shipping_threshold" in body:
        parts.append(f"free shipping from {result['free_shipping_threshold'] or 'not set'}")
    audit(
        user,
        "cro.settings",
        "cro_store_settings",
        result["store"],
        brand,
        summary="CRO: " + ", ".join(parts),
    )
    return result


@cro.post("/sync")
def sync_now(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Copy new Shopify orders for this store now, then check its alarms."""
    user = require_perm(request, "view")
    try:
        store = store_for(brand)
    except ValueError as e:
        raise HttpError(400, str(e), "bad_request") from None
    result = _call(lambda: sync.sync_store(store))
    if result["state"] == "ok":
        _call(lambda: data.snapshot(store, force=True))
        result["alarms"] = _call(lambda: alarms.check_store(store, service.today_for(store)))
    audit(
        user,
        "cro.sync" if result["state"] == "ok" else "cro.sync_failed",
        "cro_sync",
        store,
        brand,
        summary=f"CRO: order sync {result['state']}",
        details={k: v for k, v in result.items() if k != "alarms"},
    )
    return result


@cro.get("/status")
def status(request: Request) -> dict[str, Any]:
    """The background job's last round."""
    require_perm(request, "view")
    return {"last_run": scheduler.last_run}


# ------------------------------------------------------------------------------------------ change
# log
@cro.get("/change-log")
def change_log(request: Request, brand: str = "ridhi", days: str = "90") -> dict[str, Any]:
    """Store changes recorded by the team."""
    require_perm(request, "view")
    return _call(lambda: service.change_log(brand, _int(days, 90, 1, 730)))


@cro.post("/change-log")
def add_change(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Record a store change."""
    user = require_perm(request, "view")
    entry = _call(lambda: service.add_change(brand, body, _who(user)))
    audit(
        user,
        "cro.change_log_add",
        "cro_change_log",
        entry.get("id"),
        brand,
        summary=f"CRO: logged a {entry.get('area')} change for {entry.get('entry_date')}",
    )
    return entry


@cro.delete("/change-log/{entry_id}")
def delete_change(request: Request, entry_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """Remove a change-log entry."""
    user = require_perm(request, "view")
    if not _call(lambda: service.delete_change(brand, entry_id)):
        raise HttpError(404, "No such change-log entry for this store.", "not_found")
    audit(
        user,
        "cro.change_log_delete",
        "cro_change_log",
        entry_id,
        brand,
        summary="CRO: removed a change-log entry",
    )
    return {"deleted": entry_id}


# ------------------------------------------------------------------------------------------
# recommendation status and experiments (db/central/114)
@cro.post("/recommendations/status")
def set_rec_status(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Save the team's status (open / in_progress / done / ignored) for one recommendation."""
    user = require_perm(request, "view")
    result = _call(lambda: service.set_rec_status(brand, body, _who(user)))
    audit(
        user,
        "cro.recommendation_status",
        "cro_recommendation",
        result["key"],
        brand,
        summary=f"CRO: marked '{result['key']}' {result['status'].replace('_', ' ')}",
    )
    return result


@cro.get("/experiments")
def experiment_list(request: Request, brand: str = "ridhi") -> dict[str, Any]:
    """Every experiment with its result from Shopify."""
    require_perm(request, "view")
    return _call(lambda: service.experiment_list(brand))


@cro.post("/experiments")
def add_experiment(
    request: Request, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Log a new experiment."""
    user = require_perm(request, "view")
    exp = _call(lambda: service.save_experiment(brand, body, _who(user)))
    audit(
        user,
        "cro.experiment_add",
        "cro_experiment",
        exp.get("id"),
        brand,
        summary=f"CRO: logged experiment '{exp.get('name')}'",
    )
    return exp


@cro.patch("/experiments/{exp_id}")
def update_experiment(
    request: Request, exp_id: int, brand: str = "ridhi", body: dict[str, Any] = _BODY
) -> dict[str, Any]:  # noqa: B008
    """Change an experiment."""
    user = require_perm(request, "view")
    exp = _call(lambda: service.save_experiment(brand, body, _who(user), exp_id))
    audit(
        user,
        "cro.experiment_update",
        "cro_experiment",
        exp_id,
        brand,
        summary=f"CRO: changed experiment '{exp.get('name')}'",
    )
    return exp


@cro.delete("/experiments/{exp_id}")
def delete_experiment(request: Request, exp_id: int, brand: str = "ridhi") -> dict[str, Any]:
    """Remove an experiment."""
    user = require_perm(request, "view")
    if not _call(lambda: service.delete_experiment(brand, exp_id)):
        raise HttpError(404, "No such experiment for this store.", "not_found")
    audit(
        user,
        "cro.experiment_delete",
        "cro_experiment",
        exp_id,
        brand,
        summary="CRO: removed an experiment",
    )
    return {"deleted": exp_id}
