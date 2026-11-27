"""The Ads page's answers, built from schema `ads` (Meta and Google figures), cro.orders (store
sales) and the rules in metrics.py. Each public function answers one /api/ads route with the shape
the screens read (the preview copy's sample data, frontend/src/demo/modules/ads.js, returns the
same shapes).

Platforms: "All" adds Meta and Google spend (never their claimed sales: the total is the store's
own); MER, cost per order and the spend call always use the spend of every connected platform.
A brand whose Google Ads account is not set (or not read yet) is shown with Meta only, and asking
for Google alone answers GoogleNotConnectedError with the reason.
"""

from __future__ import annotations

import functools
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import data, metrics
from .config import BRAND_STORE, STORE_TIMEZONE, check_brand, google_account, meta_account
from .google_ads import CHANNEL_TYPE
from .metrics import Totals, block, div, pct, ratio
from .sync import account_today

MAX_RANGE_DAYS = 366
TREND_MIN_DAYS = 14
TREND_MAX_DAYS = 60
TYPE_LABEL = {
    "cbo": "CBO",
    "abo": "ABO",
    "catalog": "Catalog",
    "retargeting": "Retargeting",
    "pmax": "Performance Max",
    "search": "Search",
    "display": "Display",
    "shopping": "Shopping",
    "video": "Video",
    "demand_gen": "Demand Gen",
    "app": "App",
    "smart": "Smart",
    "local": "Local",
    "other": "Other",
}
GOOGLE_STATUS = {"ENABLED": "ACTIVE", "PAUSED": "PAUSED", "REMOVED": "REMOVED"}
READ_ONLY = (
    "Flowmerce does not change anything in Meta or Google. Make the change in the ad account, then "
    "mark "
    "it done here."
)
GOOGLE_RULES_NOTE = "No Google rules are agreed yet, so there are no automatic Google suggestions."
GLOSSARY = [
    (
        "MER",
        "Store sales divided by all ad spend (Meta and Google together). The store-level answer to "
        '"are the '
        'ads paying?".',
    ),
    (
        "ROAS",
        "Sales an ad platform claims, divided by what was spent on that platform. Two platforms "
        "can both claim "
        "the same order.",
    ),
    ("CPA", "Spend divided by purchases: the cost of one order."),
    ("AOV", "Store sales divided by orders (bulk orders left out)."),
    ("CTR", "Of the people who saw the ad, the share who clicked through to the website."),
    (
        "Hook rate",
        "Of the times a video was shown, the share watched for at least 3 seconds. Low means the "
        "first "
        "frame does not stop the scroll.",
    ),
    (
        "25% to 95%",
        "Of the viewers at one point of a video, the share who reach the next. A sharp fall shows "
        "where "
        "the video loses people.",
    ),
    (
        "Add-to-cart rate",
        "Of the people whose page loaded, the share who added to cart. Low with a good CTR points "
        "at the page or the offer, not the ad.",
    ),
    (
        "CBO / ABO",
        "CBO: one budget for the campaign, shared by its ads (used for scaling). ABO: a budget per "
        "ad set "
        "(used for testing).",
    ),
    (
        "Scaling gate",
        "Red, amber or green from the 3-day and 7-day MER without bulk orders. It says whether "
        "total "
        "spend may go up.",
    ),
    (
        "Bulk order",
        'One unusually large order. Left out of the "excl. bulk" figures so a single order does '
        "not "
        "hide a weak day.",
    ),
    (
        "Store sales",
        "Orders as placed (before later refunds), cancelled and test orders left out, by the "
        "store's "
        "own day.",
    ),
]


# Database reads that do not depend on each other go out at the same time: each round trip costs
# 0.3 to 0.9 s, so six of them one after another made the Overview take 4 s (measured 2026-11-24).
_READS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ads-read")


def _together(*reads: Callable[[], Any]) -> list[Any]:
    """Run independent reads at the same time; their answers in order (the first error is
    raised)."""
    futures = [_READS.submit(r) for r in reads]
    return [f.result() for f in futures]


def _kept[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Keep the function's answer for the same arguments (data.answer: ANSWER_SECONDS, cleared by
    every write and every Meta read)."""

    @functools.wraps(fn)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        return data.answer(key, lambda: fn(*args, **kwargs))

    return run


class InputError(ValueError):
    """A request the page can correct (bad dates, unknown brand or setting)."""


class NotReadyError(Exception):
    """Ads cannot answer yet: `code` is not_configured (no Meta keys) or not_synced (first read not
    finished)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GoogleNotConnectedError(Exception):
    """Google figures were asked for, but the brand's Google Ads account is not set or not read
    yet."""

    def __init__(self, message: str = "") -> None:
        self.message = message or "Google Ads is not connected for this brand. Choose Meta or All."
        super().__init__(self.message)


@dataclass(frozen=True)
class Ctx:
    """One request's brand, platform, days and rules."""

    brand: str
    platform: str
    key: str
    account: dict[str, Any]
    today: date
    frm: date
    to: date
    cmp: str  # one of COMPARES
    rules: dict[str, float]
    cfrom: date | None = None  # the first day of a custom comparison
    g_key: str | None = None  # the brand's Google Ads account, when it is set and has been read
    g_account: dict[str, Any] | None = None

    @property
    def meta_on(self) -> bool:
        """Whether Meta's figures are in the chosen platforms."""
        return self.platform in ("all", "meta")

    @property
    def google_on(self) -> bool:
        """Whether Google's figures are in the chosen platforms (and can be read)."""
        return self.g_key is not None and self.platform in ("all", "google")

    @property
    def days(self) -> int:
        """Days in the chosen range."""
        return (self.to - self.frm).days + 1

    @property
    def compare(self) -> bool:
        """Whether figures are compared with anything."""
        return self.cmp != "none"

    @property
    def prev_from(self) -> date:
        """First day of the comparison period (as long as the chosen days)."""
        if self.cmp == "previous_year":
            return _year_back(self.frm)
        if self.cmp == "previous_year_dow":
            return self.frm - timedelta(days=364)
        if self.cmp == "custom" and self.cfrom is not None:
            return self.cfrom
        return self.frm - timedelta(days=self.days)

    @property
    def prev_to(self) -> date:
        """Last day of the comparison period."""
        return self.prev_from + timedelta(days=self.days - 1)

    @property
    def compare_label(self) -> str:
        """The comparison in words, for the page."""
        if self.cmp == "previous_year":
            return "same dates last year"
        if self.cmp == "previous_year_dow":
            return "last year, same weekdays"
        if self.cmp == "custom":
            return f"{self.prev_from:%d %b %Y} – {self.prev_to:%d %b %Y}"
        return "the day before" if self.days == 1 else f"previous {self.days} days"


# The comparisons the page offers (Shopify's, as on the CRO page). Older CRO links may say last_week
# or 4week_avg:
# Ads reads them as the previous period.
COMPARES = ("previous", "previous_year", "previous_year_dow", "custom", "none")


def _year_back(d: date) -> date:
    """The same date a year earlier (29 February becomes the 28th)."""
    return (
        d.replace(year=d.year - 1, day=28)
        if (d.month, d.day) == (2, 29)
        else d.replace(year=d.year - 1)
    )


def _day(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        raise InputError(f"Not a date: {v[:10]!r}. Use YYYY-MM-DD.") from None


def _account(brand: str) -> tuple[str, dict[str, Any]]:
    try:
        check_brand(brand)
    except ValueError as e:
        raise InputError(str(e)) from None
    acc = meta_account(brand)
    if acc is None:
        raise NotReadyError(
            "not_configured",
            f"The {brand} Meta ad account is not set in the server's .env "
            f"({brand.upper()}_META_AD_ACCOUNT_ID and {brand.upper()}_META_ACCESS_TOKEN).",
        )
    row = data.account(acc.key)
    if row is None or row.get("first_day") is None:
        why = (
            f" The last attempt said: {row['last_error']}" if row and row.get("last_error") else ""
        )
        raise NotReadyError(
            "not_synced",
            "The first read of the Meta ad account has not finished yet. It runs in the "
            f"background a minute after the server starts and takes a few minutes.{why}",
        )
    return acc.key, row


def _google(brand: str) -> tuple[str | None, dict[str, Any] | None, str]:
    """The brand's Google Ads account key and row when it can be shown, else (None, None, why)."""
    acc = google_account(brand)
    if acc is None:
        return (
            None,
            None,
            "No Google Ads account is set for this brand yet "
            f"({brand.upper()}_GOOGLE_ADS_CUSTOMER_ID in the server's .env), so there are no "
            "Google figures. Choose Meta or All.",
        )
    row = data.account(acc.key)
    if row is None or row.get("first_day") is None:
        why = (
            f" The last attempt said: {row['last_error']}" if row and row.get("last_error") else ""
        )
        return (
            None,
            None,
            "The first read of the Google Ads account has not finished yet; it runs with the "
            f"hourly Meta read.{why} Choose Meta or All for now.",
        )
    return acc.key, row, ""


def context(
    brand: str,
    platform: str = "all",
    frm: str | None = None,
    to: str | None = None,
    compare: str | None = None,
    cfrom: str | None = None,
) -> Ctx:
    """Resolve a request: the account's days up to today (today is still running), the last 7
    complete days by default, and the comparison (the previous period when none is given)."""
    platform = platform if platform in ("all", "meta", "google") else "all"
    try:
        check_brand(brand)  # before any read that uses it
    except ValueError as e:
        raise InputError(str(e)) from None
    (key, row), saved_rules, (g_key, g_row, g_why) = _together(
        lambda: _account(brand), lambda: data.rules(brand), lambda: _google(brand)
    )
    if platform == "google" and g_key is None:
        raise GoogleNotConnectedError(g_why)
    today = account_today(str(row.get("timezone") or "UTC"))
    end = min(_day(to) or today - timedelta(days=1), today)
    start = min(_day(frm) or end - timedelta(days=6), end)
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise InputError(f"Pick at most {MAX_RANGE_DAYS} days.")
    cmp = compare if compare in COMPARES else "previous"
    first = _day(cfrom) if cmp == "custom" else None
    if cmp == "custom" and first is None:
        cmp = "previous"  # a custom comparison without its first day: the previous period
    if first is not None and first >= start:
        raise InputError("The comparison must start before the chosen days.")
    return Ctx(
        brand,
        platform,
        key,
        row,
        today,
        start,
        end,
        cmp,
        metrics.rules_for(brand, saved_rules),
        first,
        g_key,
        g_row,
    )


def _info(c: Ctx) -> dict[str, Any]:
    cmp = None
    if c.compare:
        cmp = {
            "key": c.cmp,
            "from": c.prev_from.isoformat(),
            "to": c.prev_to.isoformat(),
            "label": c.compare_label,
        }
        first = c.account.get("first_day")
        if first and c.prev_from.isoformat() < str(first):
            cmp["note"] = (
                f"Meta figures are loaded from {date.fromisoformat(str(first)):%d %b %Y}, so the "
                "comparison has no ad figures before that day."
            )
    return {
        "brand": c.brand,
        "platform": c.platform,
        "from": c.frm.isoformat(),
        "to": c.to.isoformat(),
        "days": c.days,
        "compare": cmp,
    }


def _rate_now(c: Ctx) -> float:
    return data.fx_rate(str(c.account.get("currency") or "USD"), c.today)


# ------------------------------------------------------------------ settings
@_kept
def settings(brand: str) -> dict[str, Any]:
    """Which accounts the page reads, their currency, when each was last read, and the account's
    today."""
    key, row = _account(brand)
    today = account_today(str(row.get("timezone") or "UTC"))
    currency = str(row.get("currency") or "USD")
    expires = row.get("token_expires_at")
    days_left = None
    if expires:
        days_left = max(0, (datetime.fromisoformat(str(expires)) - datetime.now(UTC)).days)
    meta = {
        "platform": "meta",
        "name": row.get("name") or key,
        "currency": currency,
        "timezone": row.get("timezone"),
        "status": row.get("last_status") or "ok",
        "last_read_at": row.get("last_run_at"),
        "last_error": row.get("last_error"),
        "token_days_left": days_left,
        "converted_at": data.fx_rate(currency, today) if currency != "USD" else None,
    }
    accounts = [meta]
    g_key, g_row, g_why = _google(brand)
    if g_key and g_row:
        g_currency = str(g_row.get("currency") or "USD")
        accounts.append(
            {
                "platform": "google",
                "name": g_row.get("name") or g_key,
                "currency": g_currency,
                "timezone": g_row.get("timezone"),
                "status": g_row.get("last_status") or "ok",
                "last_read_at": g_row.get("last_run_at"),
                "last_error": g_row.get("last_error"),
                "token_days_left": None,
                "converted_at": data.fx_rate(g_currency, today) if g_currency != "USD" else None,
            }
        )
    return {
        "brand": brand,
        "reporting_currency": "USD",
        "today": today.isoformat(),
        "data_from": row.get("first_day"),
        "accounts": accounts,
        "product_lines": [{"key": k, "label": label} for k, label, _ in metrics.PRODUCT_LINES],
        "google": {"connected": g_key is not None, "note": g_why or None},
    }


# ------------------------------------------------------------------ shared reads
def _store(c: Ctx, since: date, until: date) -> dict[str, dict[str, Any]]:
    """Store days by ISO date."""
    rows = data.store_days(
        BRAND_STORE[c.brand], STORE_TIMEZONE[c.brand], since, until, c.rules["bulk_order_min"]
    )
    return {str(r["day"]): r for r in rows}


def _meta_days(c: Ctx, since: date, until: date) -> dict[str, dict[str, Any]]:
    return {str(r["day"]): r for r in data.account_days(c.key, since, until)}


def _google_days(c: Ctx, since: date, until: date) -> dict[str, dict[str, Any]]:
    """Google's per day totals (US dollars), or nothing when the brand has no Google account."""
    if c.g_key is None:
        return {}
    return {str(r["day"]): r for r in data.g_days(c.g_key, since, until)}


AD_FIELDS = ("spend", "value", "purchases", "impressions", "clicks")


def _merge(*parts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per day sums of several platforms' days (spend, claimed value, purchases, impressions,
    clicks). Claimed value is only ever summed per platform for a ROAS, never shown as a total."""
    out: dict[str, dict[str, Any]] = {}
    for part in parts:
        for day, r in part.items():
            t = out.setdefault(day, dict.fromkeys(AD_FIELDS, 0.0))
            for f in AD_FIELDS:
                t[f] += float(r.get(f) or 0)
    return out


def _chosen(c: Ctx, meta: dict[str, Any], google: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The days of the platforms the page asked for."""
    return _merge(*([meta] if c.meta_on else []), *([google] if c.google_on else []))


def _sum(rows: dict[str, dict[str, Any]], since: date, until: date, field: str) -> float:
    total = 0.0
    d = since
    while d <= until:
        total += float((rows.get(d.isoformat()) or {}).get(field) or 0)
        d += timedelta(days=1)
    return total


def _side(
    chosen: dict[str, dict[str, Any]],
    store: dict[str, dict[str, Any]],
    since: date,
    until: date,
    total: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Figures for since..until: spend, claimed value and purchases of the chosen platforms; MER,
    cost per order and total_spend from the spend of every connected platform (`total`, defaults to
    the chosen ones)."""
    spend = _sum(chosen, since, until, "spend")
    value = _sum(chosen, since, until, "value")
    purchases = _sum(chosen, since, until, "purchases")
    every = _sum(total if total is not None else chosen, since, until, "spend")
    sales = _sum(store, since, until, "sales")
    bulk = _sum(store, since, until, "bulk_amount")
    orders = _sum(store, since, until, "orders")
    bulk_orders = _sum(store, since, until, "bulk_orders")
    return {
        "spend": spend,
        "total_spend": every,
        "value": value,
        "purchases": purchases,
        "roas": div(value, spend),
        "cpa": div(spend, purchases),
        "sales": sales,
        "sales_ex_bulk": sales - bulk,
        "orders": orders,
        "mer": div(sales, every),
        "mer_ex_bulk": div(sales - bulk, every),
        "aov": div(sales - bulk, orders - bulk_orders),
        "cost_per_order": div(every, orders),
        "bulk_orders": bulk_orders,
        "bulk_amount": bulk,
    }


# ------------------------------------------------------------------ overview
@_kept
def overview(
    brand: str,
    platform: str,
    frm: str | None,
    to: str | None,
    compare: str | None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Store sales against ad spend for the range, the scaling gate, the goal, the day strip and the
    platforms."""
    c = context(brand, platform, frm, to, compare, cfrom)
    trend_from = max(
        min(c.frm, c.to - timedelta(days=TREND_MIN_DAYS - 1)),
        c.to - timedelta(days=TREND_MAX_DAYS - 1),
    )
    since = min(c.prev_from, trend_from, c.to - timedelta(days=6))
    meta, google, store, latest, g_latest, rate = _together(
        lambda: _meta_days(c, since, c.to),
        lambda: _google_days(c, since, c.to),
        lambda: _store(c, since, c.to),
        lambda: data.latest_day(c.key),
        lambda: data.g_latest_day(c.g_key) if c.g_key else None,
        lambda: _rate_now(c),
    )
    every = _merge(meta, google)
    chosen = _chosen(c, meta, google)
    cur = _side(chosen, store, c.frm, c.to, every)
    prev = _side(chosen, store, c.prev_from, c.prev_to, every) if c.compare else None
    keys = [
        "spend",
        "total_spend",
        "sales",
        "sales_ex_bulk",
        "mer",
        "mer_ex_bulk",
        "orders",
        "aov",
        "cost_per_order",
    ]
    if c.platform != "all":
        keys += ["roas", "value", "purchases", "cpa"]
    out_metrics = {k: block(cur[k], prev[k] if prev else None) for k in keys}

    def mer(n: int) -> float | None:
        s = _side(every, store, c.to - timedelta(days=n - 1), c.to)
        v = s["mer_ex_bulk"]
        return float(v) if v is not None else None

    # The spend call needs every platform's spend for the last days: a platform not read up to the
    # range's end would make MER look better than it is.
    saved = [latest] + ([g_latest] if c.g_key else [])
    complete = all(x is not None and x >= c.to for x in saved)
    week = _side(every, store, c.to - timedelta(days=6), c.to)
    g = metrics.gate(mer(3), mer(7), week["total_spend"] / 7, c.rules, complete)
    trend = []
    d = trend_from
    while d <= c.to:
        m = meta.get(d.isoformat()) or {}
        gd = google.get(d.isoformat()) or {}
        s = store.get(d.isoformat()) or {}
        m_spend = float(m.get("spend") or 0)
        g_spend = float(gd.get("spend") or 0)
        spend = m_spend + g_spend
        sales = float(s.get("sales") or 0)
        ex = sales - float(s.get("bulk_amount") or 0)
        day_mer = div(ex, spend)
        trend.append(
            {
                "date": d.isoformat(),
                "meta_spend": round(m_spend, 2),
                "google_spend": round(g_spend, 2) if c.g_key else None,
                "spend": round(spend, 2),
                "sales": round(sales, 2),
                "sales_ex_bulk": round(ex, 2),
                "mer": ratio(sales, spend),
                "mer_ex_bulk": None if day_mer is None else round(day_mer, 2),
                "meta_roas": ratio(float(m.get("value") or 0), m_spend),
                "google_roas": ratio(float(gd.get("value") or 0), g_spend) if c.g_key else None,
                "purchases": float(m.get("purchases") or 0) + float(gd.get("purchases") or 0),
                "orders": int(s.get("orders") or 0),
                "colour": metrics.day_colour(day_mer, c.rules),
                "in_range": d >= c.frm,
            }
        )
        d += timedelta(days=1)
    goal = c.rules["goal_daily_sales"]
    avg_sales = week["sales_ex_bulk"] / 7

    def platform_row(name: str, days: dict[str, Any], account: str | None) -> dict[str, Any]:
        now_ = _side(days, store, c.frm, c.to, every)
        before = _side(days, store, c.prev_from, c.prev_to, every) if c.compare else None
        return {
            "platform": name,
            "account": account,
            "spend": round(now_["spend"], 2),
            "purchases": now_["purchases"],
            "value": round(now_["value"], 2),
            "roas": ratio(now_["value"], now_["spend"]),
            "cpa": ratio(now_["spend"], now_["purchases"]),
            "prev_roas": ratio(before["value"], before["spend"]) if before else None,
            "prev_spend": round(before["spend"], 2) if before else None,
            "share_of_spend": round(now_["spend"] / now_["total_spend"] * 100, 1)
            if now_["total_spend"]
            else None,
        }

    platforms = [platform_row("meta", meta, c.account.get("name"))]
    if c.g_key:
        platforms.append(platform_row("google", google, (c.g_account or {}).get("name")))
    else:
        platforms.append(
            {
                "platform": "google",
                "account": "Not connected yet",
                **dict.fromkeys(
                    ("spend", "purchases", "value", "roas", "cpa", "prev_roas", "prev_spend"), None
                ),
                "share_of_spend": None,
            }
        )
    currency = str(c.account.get("currency") or "USD")
    notes = [
        "Platform sales are what Meta and Google each claim. They are never added together: the "
        "total is the store's own sales.",
        "MER, cost per order and the spend call use the spend of every connected platform "
        + (
            "(Meta and Google)."
            if c.g_key
            else "(Meta only: Google Ads is not connected for this brand yet)."
        ),
        "Store sales are orders as placed (before later refunds), by the store's own day; ad "
        "figures are by each ad account's day.",
    ]
    if latest is not None and latest < c.to:
        notes.insert(
            0,
            f"Meta figures are saved up to {latest:%d %b} so far; the days after it are read in "
            "the next round, so spend and MER for those days are not complete yet.",
        )
    if c.g_key and g_latest is not None and g_latest < c.to:
        notes.insert(
            0,
            f"Google figures are saved up to {g_latest:%d %b} so far; the days after it are read "
            "in the next round.",
        )
    if currency != "USD":
        notes.append(
            f"Meta is billed in {currency} and shown in dollars at the rate set on the Rules tab "
            f"(now {currency} {rate:g} = $1)."
        )
    return {
        **_info(c),
        "metrics": out_metrics,
        "gate": g,
        "platforms": platforms,
        "trend": trend,
        "meta_saved_to": latest.isoformat() if latest else None,
        "google_saved_to": g_latest.isoformat() if g_latest else None,
        "goal": {
            "daily_sales_goal": goal,
            "avg_sales_7d": round(avg_sales),
            "avg_spend_7d": round(week["total_spend"] / 7),
            "mer_7d": g["mer_7d"],
            "pct_of_goal": round(avg_sales / goal * 100) if goal else 0,
            "gap": max(0, round(goal - avg_sales)),
            "spend_needed": round(goal / g["mer_7d"]) if g["mer_7d"] else None,
        },
        "bulk": {
            "min_order": c.rules["bulk_order_min"],
            "orders": int(cur["bulk_orders"]),
            "amount": round(cur["bulk_amount"], 2),
        },
        "targets": {
            "roas": c.rules["target_roas"],
            "mer": c.rules["target_mer"],
            "mer_floor": c.rules["mer_floor"],
        },
        "gate_lines": {"green": c.rules["gate_green_3d"], "red": c.rules["gate_red"]},
        "notes": notes,
    }


# ------------------------------------------------------------------ per ad and per campaign
def _windows(c: Ctx) -> dict[str, dict[str, dict[str, Any]]]:
    """{ad id: {window: Totals, 'raw_<window>': the video sums}} for cur, prev, d3, d7 and d14."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in data.ad_windows(c.key, c.frm, c.to, c.prev_from, c.prev_to):
        out[str(r["ad_id"])][str(r["w"])] = r
    return out


def _totals(r: dict[str, Any] | None, video: bool) -> Totals:
    if not r:
        return Totals()
    imp = int(r.get("impressions") or 0)
    return Totals(
        spend=float(r.get("spend") or 0),
        purchases=float(r.get("purchases") or 0),
        value=float(r.get("value") or 0),
        impressions=imp,
        vimp=imp if video else 0,
        clicks=int(r.get("clicks") or 0),
        lpv=int(r.get("lpv") or 0),
        atc=int(r.get("atc") or 0),
        v3=int(r.get("v3") or 0),
    )


def _local_day(ts: Any, c: Ctx) -> date | None:
    if not ts:
        return None
    try:
        return account_today(
            str(c.account.get("timezone") or "UTC"), datetime.fromisoformat(str(ts))
        )
    except ValueError:
        return None


def _ads(c: Ctx) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """Every ad worth showing (active, or with spend in the windows) as the page's ad rows, plus the
    structure and the raw windows."""
    st, win, rate = _together(
        lambda: data.structure(c.key), lambda: _windows(c), lambda: _rate_now(c)
    )
    camps = {x["id"]: x for x in st["campaigns"]}
    sets = {x["id"]: x for x in st["ad_sets"]}
    rows = []
    for a in st["ads"]:
        w = win.get(a["id"], {})
        if a.get("status") != "ACTIVE" and not w:
            continue
        camp = camps.get(a["campaign_id"]) or {"id": a["campaign_id"], "name": "(unknown campaign)"}
        budget = (
            float(camp["daily_budget"]) / rate if camp.get("daily_budget") is not None else None
        )
        ctype = metrics.campaign_type(str(camp.get("name") or ""), camp.get("objective"), budget)
        video = a.get("format") == "video"
        cur, prev, d3, d7, d14 = (
            _totals(w.get(k), video) for k in ("cur", "prev", "d3", "d7", "d14")
        )
        if a.get("lt_spend") is not None:
            life = Totals(
                spend=float(a["lt_spend"]) / rate,
                purchases=float(a.get("lt_purchases") or 0),
                value=float(a.get("lt_value") or 0) / rate,
            )
        else:
            life = Totals(spend=d14.spend, purchases=d14.purchases, value=d14.value)
        if life.spend < d14.spend:  # lifetime is refreshed nightly: never below the last 14 days
            life = Totals(spend=d14.spend, purchases=d14.purchases, value=d14.value)
        verdict, reason = metrics.verdict(d3, d7, life, ctype == "abo", c.rules)
        launched = _local_day(a.get("created_time"), c)
        raw = w.get("cur") or {}
        p25, p50, p75, p95 = (int(raw.get(k) or 0) for k in ("p25", "p50", "p75", "p95"))
        plays = int(raw.get("plays") or 0)
        name = str(a.get("name") or "")
        parts = [p.strip() for p in name.split("|")]
        rows.append(
            {
                "id": a["id"],
                "code": metrics.ad_code(name),
                "name": name,
                "hook": parts[1] if len(parts) > 1 else "",
                "format": "video" if video else "image",
                "status": a.get("status"),
                "post_id": a.get("post_id"),
                "campaign_id": camp["id"],
                "campaign": camp.get("name"),
                "campaign_type": ctype,
                "product_line": metrics.product_line(str(camp.get("name") or "")),
                "ad_set": (sets.get(a["ad_set_id"]) or {}).get("name", ""),
                "launched": launched.isoformat() if launched else None,
                "days_live": (c.to - launched).days + 1 if launched else None,
                "is_new": bool(launched and (c.to - launched).days < 7),
                "verdict": verdict,
                "reason": reason,
                "weakest": metrics.weakest(
                    video, d14 if d14.impressions > cur.impressions else cur
                ),
                "spend": round(cur.spend, 2),
                "purchases": cur.purchases,
                "value": round(cur.value, 2),
                "roas": ratio(cur.value, cur.spend),
                "cpa": ratio(cur.spend, cur.purchases),
                "prev_roas": ratio(prev.value, prev.spend),
                "roas_3d": ratio(d3.value, d3.spend),
                "roas_7d": ratio(d7.value, d7.spend),
                "roas_14d": ratio(d14.value, d14.spend),
                "spend_7d": round(d7.spend, 2),
                "purchases_7d": d7.purchases,
                "lifetime": {
                    "spend": round(life.spend, 2),
                    "purchases": life.purchases,
                    "roas": ratio(life.value, life.spend),
                },
                "impressions": cur.impressions,
                "ctr": pct(cur.clicks, cur.impressions),
                "cpm": ratio(cur.spend * 1000, cur.impressions),
                "lpv": cur.lpv,
                "atc": cur.atc,
                "atc_rate": pct(cur.atc, cur.lpv),
                "purchase_rate": pct(cur.purchases, cur.atc),
                "video": {
                    "hook_rate": pct(cur.v3, cur.vimp),
                    "hook_25": pct(p25, cur.vimp),
                    "to_50": pct(p50, p25),
                    "to_75": pct(p75, p50),
                    "to_95": pct(p95, p75),
                    "avg_watch_s": round(float(raw.get("watch_s") or 0) / plays) if plays else None,
                    "length_s": float(a["video_length_s"])
                    if a.get("video_length_s") is not None
                    else None,
                }
                if video
                else None,
                "_ctype": ctype,
                "_life": life,
                "_d3": d3,
                "_d7": d7,
                "_prev_spend": prev.spend,
                "_prev_value": prev.value,
            }
        )
    return rows, st, win


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


@_kept
def creatives(
    brand: str,
    frm: str | None,
    to: str | None,
    compare: str | None = None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Every Meta ad with its verdict, figures and video drop-off; the winners bench; the account
    average."""
    c = context(brand, "meta", frm, to, compare, cfrom)
    (rows, _st, _w), acct = _together(
        lambda: _ads(c), lambda: data.account_days(c.key, c.frm, c.to)
    )
    rows.sort(key=lambda a: -a["spend"])
    counts: dict[str, int] = defaultdict(int)
    for a in rows:
        counts[a["verdict"]] += 1
    r = c.rules
    bench = [a for a in rows if metrics.proven(a["_life"], r)]
    bench.sort(key=lambda a: -(a["lifetime"]["roas"] or 0))

    def tot(f: str) -> float:
        return sum(float(x.get(f) or 0) for x in acct)

    return {
        **_info(c),
        "ads": [_public(a) for a in rows],
        "counts": dict(counts),
        "winners": [a["id"] for a in bench[:10]],
        "targets": {
            "roas": r["target_roas"],
            "test_spend": r["test_spend"],
            "proven_spend": r["proven_spend"],
        },
        "account": {
            "roas": ratio(tot("value"), tot("spend")),
            "ctr": pct(tot("clicks"), tot("impressions")),
            "atc_rate": pct(tot("atc"), tot("lpv")),
            "hook_rate": pct(tot("v3"), tot("vimp")),
            "cpa": ratio(tot("spend"), tot("purchases")),
        },
    }


def _campaign_rows(c: Ctx, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    st = data.structure(c.key)
    if rows is None:
        rows, st, _w = _ads(c)
    rate = _rate_now(c)
    by_camp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in rows:
        by_camp[a["campaign_id"]].append(a)
    out = []
    for camp in st["campaigns"]:
        mine = by_camp.get(camp["id"], [])
        if camp.get("status") != "ACTIVE" and not any(a["spend"] or a["spend_7d"] for a in mine):
            continue
        budget = (
            float(camp["daily_budget"]) / rate if camp.get("daily_budget") is not None else None
        )
        ctype = metrics.campaign_type(str(camp.get("name") or ""), camp.get("objective"), budget)

        def s(f: str, items: list[dict[str, Any]]) -> float:
            return sum(float(a.get(f) or 0) for a in items)

        def win(attr: str, items: list[dict[str, Any]]) -> tuple[float, float]:
            return (sum(a[attr].spend for a in items), sum(a[attr].value for a in items))

        sp7, v7 = win("_d7", mine)
        sp3, v3 = win("_d3", mine)
        spend, value = s("spend", mine), s("value", mine)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for a in mine:
            groups[a["ad_set"]].append(a)
        health = None
        if ctype == "cbo":
            delivering = [a for a in mine if a["_d3"].spend > 0]
            top = max(mine, key=lambda a: a["spend_7d"], default=None)
            changed = camp.get("budget_changed_at")
            changed_days = None
            if changed:
                changed_days = (
                    datetime.now(UTC) - datetime.fromisoformat(str(changed))
                ).total_seconds() / 86400
            health = {
                "delivering_ads": len(delivering),
                "min_ads": int(c.rules["cbo_min_ads"]),
                "max_ads": int(c.rules["cbo_max_ads"]),
                "top_ad": top["code"] if top else None,
                "top_ad_share": round(top["spend_7d"] / sp7 * 100) if top and sp7 else None,
                "call": metrics.budget_call(
                    budget or 0, div(v7, sp7) or 0, div(v3, sp3) or 0, changed_days, c.rules
                ),
            }
        prev_spend, prev_value = camp_prev(mine)
        out.append(
            {
                "id": camp["id"],
                "platform": "meta",
                "name": camp.get("name"),
                "type": ctype,
                "type_label": TYPE_LABEL[ctype],
                "product_line": metrics.product_line(str(camp.get("name") or "")),
                "status": camp.get("status"),
                "is_brand": False,
                "daily_budget": None if ctype == "abo" or budget is None else round(budget, 2),
                "spend": round(spend, 2),
                "purchases": s("purchases", mine),
                "value": round(value, 2),
                "roas": ratio(value, spend),
                "cpa": ratio(spend, s("purchases", mine)),
                "prev_spend": round(prev_spend, 2),
                "prev_roas": ratio(prev_value, prev_spend),
                "impressions": int(s("impressions", mine)),
                "clicks": None,
                "ctr": None,
                "cpm": ratio(spend * 1000, s("impressions", mine)),
                "roas_3d": ratio(v3, sp3),
                "roas_7d": ratio(v7, sp7),
                "atc": int(s("atc", mine)),
                "frequency": None,
                "groups": sorted(
                    (
                        {
                            "name": n,
                            "kind": "ad_set",
                            "ads": len(g),
                            "active_ads": sum(1 for a in g if a["status"] == "ACTIVE"),
                            "spend": round(s("spend", g), 2),
                            "purchases": s("purchases", g),
                            "roas": ratio(s("value", g), s("spend", g)),
                        }
                        for n, g in groups.items()
                    ),
                    key=lambda g: -float(g["spend"] or 0),
                ),
                "ads": len(mine),
                "active_ads": sum(1 for a in mine if a["status"] == "ACTIVE"),
                "health": health,
            }
        )
    out.sort(key=lambda x: -float(x["spend"] or 0))
    return out


def camp_prev(ads: list[dict[str, Any]]) -> tuple[float, float]:
    """A campaign's spend and value in the comparison period, from its ads' rows."""
    spend = sum(float(a.get("_prev_spend") or 0) for a in ads)
    value = sum(float(a.get("_prev_value") or 0) for a in ads)
    return spend, value


@_kept
def campaigns(
    brand: str,
    platform: str,
    frm: str | None,
    to: str | None,
    compare: str | None = None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Every campaign that is active or spent: Meta's with CBO health and their ad sets, Google's
    with their ad groups or asset groups."""
    c = context(brand, platform, frm, to, compare, cfrom)
    meta_rows, google_rows = _together(
        lambda: _campaign_rows(c) if c.meta_on else [],
        lambda: _google_campaign_rows(c) if c.google_on else [],
    )
    rows = sorted(meta_rows + google_rows, key=lambda x: -float(x["spend"] or 0))
    return {**_info(c), "targets": {"roas": c.rules["target_roas"]}, "campaigns": rows}


def _by_item(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["item"]): r for r in rows}


def _google_campaign_rows(c: Ctx) -> list[dict[str, Any]]:
    """Google campaigns with their figures for the range, the comparison, the last 3 and 7 days, and
    their ad groups or asset groups."""
    if c.g_key is None:
        return []
    key = c.g_key
    currency = str((c.g_account or {}).get("currency") or "USD")
    camps, cur, prev, d3, d7, groups, rate = _together(
        lambda: data.g_campaigns(key),
        lambda: _by_item(data.g_sum(key, "campaign", c.frm, c.to)),
        lambda: _by_item(data.g_sum(key, "campaign", c.prev_from, c.prev_to)) if c.compare else {},
        lambda: _by_item(data.g_sum(key, "campaign", c.to - timedelta(days=2), c.to)),
        lambda: _by_item(data.g_sum(key, "campaign", c.to - timedelta(days=6), c.to)),
        lambda: data.g_sum(key, "group", c.frm, c.to),
        lambda: data.fx_rate(currency, c.today),
    )
    by_camp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in groups:
        by_camp[str(g["campaign_id"])].append(g)

    def f(r: dict[str, Any] | None, field: str) -> float:
        return float((r or {}).get(field) or 0)

    out = []
    for camp in camps:
        cid = str(camp["id"])
        now_, before = cur.get(cid), prev.get(cid)
        status = GOOGLE_STATUS.get(str(camp.get("status") or ""), str(camp.get("status") or ""))
        if status != "ACTIVE" and not f(now_, "spend") and not f(d7.get(cid), "spend"):
            continue
        name = str(camp.get("name") or "")
        ctype = CHANNEL_TYPE.get(str(camp.get("channel") or ""), "other")
        spend, value, purchases = f(now_, "spend"), f(now_, "value"), f(now_, "purchases")
        budget = camp.get("daily_budget")
        out.append(
            {
                "id": cid,
                "platform": "google",
                "name": name,
                "type": ctype,
                "type_label": TYPE_LABEL.get(ctype, "Other"),
                "product_line": metrics.product_line(name),
                "status": status,
                "is_brand": "brand" in name.lower(),
                "daily_budget": round(float(budget) / rate, 2) if budget is not None else None,
                "spend": round(spend, 2),
                "purchases": purchases,
                "value": round(value, 2),
                "roas": ratio(value, spend),
                "cpa": ratio(spend, purchases),
                "prev_spend": round(f(before, "spend"), 2) if c.compare else None,
                "prev_roas": ratio(f(before, "value"), f(before, "spend")) if c.compare else None,
                "impressions": int(f(now_, "impressions")),
                "clicks": int(f(now_, "clicks")),
                "ctr": pct(f(now_, "clicks"), f(now_, "impressions")),
                "cpm": ratio(spend * 1000, f(now_, "impressions")),
                "roas_3d": ratio(f(d3.get(cid), "value"), f(d3.get(cid), "spend")),
                "roas_7d": ratio(f(d7.get(cid), "value"), f(d7.get(cid), "spend")),
                "atc": None,
                "frequency": None,
                "groups": sorted(
                    (
                        {
                            "name": str(g.get("label") or g["item"]),
                            "kind": str(g.get("extra") or "ad_group"),
                            "ads": None,
                            "active_ads": None,
                            "spend": round(f(g, "spend"), 2),
                            "purchases": f(g, "purchases"),
                            "roas": ratio(f(g, "value"), f(g, "spend")),
                        }
                        for g in by_camp.get(cid, [])
                        if f(g, "spend") or f(g, "purchases")
                    ),
                    key=lambda g: -float(g["spend"] or 0),
                ),
                "ads": None,
                "active_ads": None,
                "health": None,
            }
        )
    return out


# ------------------------------------------------------------------ funnel
FUNNEL_META = [
    ("impressions", "Impressions"),
    ("link_clicks", "Link clicks"),  # the Daily sheet's funnel; outbound clicks can be below LPV
    ("lpv", "Landing page views"),
    ("atc", "Add to cart"),
    ("ic", "Checkout started"),
    ("purchases", "Purchases"),
]


FUNNEL_GOOGLE = [("impressions", "Impressions"), ("clicks", "Clicks"), ("purchases", "Purchases")]


def _steps(
    cur: dict[str, float],
    prev: dict[str, float] | None,
    steps: list[tuple[str, str]] = FUNNEL_META,
) -> list[dict[str, Any]]:
    out = []
    for i, (key, label) in enumerate(steps):
        before = steps[i - 1][0] if i else None
        out.append(
            {
                "key": key,
                "label": label,
                "value": cur[key],
                "previous": prev[key] if prev else None,
                "change_pct": round((cur[key] / prev[key] - 1) * 100, 1)
                if prev and prev[key]
                else None,
                "rate": pct(cur[key], cur[before]) if before else None,
                "previous_rate": pct(prev[key], prev[before]) if before and prev else None,
            }
        )
    return out


@_kept
def funnel(
    brand: str,
    platform: str,
    frm: str | None,
    to: str | None,
    compare: str | None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Meta's funnel from impression to purchase, and the store's orders and AOV, against the
    comparison."""
    c = context(brand, platform, frm, to, compare, cfrom)
    meta, google, store = _together(
        lambda: _meta_days(c, c.prev_from, c.to),
        lambda: _google_days(c, c.prev_from, c.to),
        lambda: _store(c, c.prev_from, c.to),
    )

    def span(
        days: dict[str, Any], steps: list[tuple[str, str]], since: date, until: date
    ) -> dict[str, float]:
        return {k: _sum(days, since, until, k) for k, _ in steps}

    every = _merge(meta, google)
    s = _side(every, store, c.frm, c.to)
    b = _side(every, store, c.prev_from, c.prev_to) if c.compare else None
    meta_part = None
    if c.meta_on:
        meta_part = {
            "steps": _steps(
                span(meta, FUNNEL_META, c.frm, c.to),
                span(meta, FUNNEL_META, c.prev_from, c.prev_to) if c.compare else None,
            )
        }
    google_part = None
    if c.google_on:
        google_part = {
            "steps": _steps(
                span(google, FUNNEL_GOOGLE, c.frm, c.to),
                span(google, FUNNEL_GOOGLE, c.prev_from, c.prev_to) if c.compare else None,
                FUNNEL_GOOGLE,
            ),
            "note": "Google reports clicks and purchases only; it has no page-view or cart steps.",
        }
    return {
        **_info(c),
        "meta": meta_part,
        "google": google_part,
        "store": {
            "sessions": block(None, None),
            "orders": block(s["orders"], b["orders"] if b else None),
            "conversion_rate": block(None, None),
            "aov": block(s["aov"], b["aov"] if b else None),
        },
        "notes": [
            "Store sessions and conversion rate are on the Conversion (CRO) page; they are not "
            "repeated here yet.",
            *(
                []
                if c.g_key
                else ["Google Ads is not connected for this brand, so its funnel is not shown."]
            ),
        ],
    }


# ------------------------------------------------------------------ ABO to CBO gap
def _scaling(camps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The scaling campaign of each product line: its CBO that spent the most in the range."""
    out: dict[str, dict[str, Any]] = {}
    for x in camps:
        line = x["product_line"]
        if (
            x["type"] == "cbo"
            and line != "all"
            and (line not in out or x["spend"] > out[line]["spend"])
        ):
            out[line] = x
    return out


def _gap_verdict(
    proven: bool, already: bool, has_target: bool, verdict: str, life: Totals, r: dict[str, float]
) -> str:
    if not has_target:
        return "watch" if proven else "stop" if verdict == "stop" else "early"
    if already:
        return "already"
    if proven:
        return "add"
    if verdict == "stop":
        return "stop"
    return "watch" if life.roas >= r["scale_roas"] and life.purchases >= 1 else "early"


def _gap_pairs(
    c: Ctx, rows: list[dict[str, Any]], camps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {x["id"]: x for x in camps}
    cbo_posts: dict[str, set[str]] = defaultdict(set)
    for a in rows:
        if a["_ctype"] == "cbo" and a["post_id"]:
            cbo_posts[a["product_line"]].add(a["post_id"])
    scale = _scaling(camps)
    tests: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in rows:
        if a["_ctype"] == "abo" and a["product_line"] != "all" and a["lifetime"]["spend"] > 0:
            tests[a["campaign_id"]].append(a)
    order = {"add": 0, "watch": 1, "already": 2, "stop": 3, "early": 4}
    pairs = []
    for cid, ads in tests.items():
        line = ads[0]["product_line"]
        target = scale.get(line)
        out = []
        for a in ads:
            life = a["_life"]
            ok = metrics.proven(life, c.rules)
            already = bool(a["post_id"] and a["post_id"] in cbo_posts[line])
            v = _gap_verdict(ok, already, target is not None, a["verdict"], life, c.rules)
            if v == "already" and target:
                why = f"Already running in {target['name']}."
            elif ok:
                why = (
                    f"Lifetime ROAS {life.roas:.2f} with {int(life.purchases)} purchases on "
                    f"${round(life.spend):,}."
                )
            else:
                why = a["reason"]
            out.append(
                {
                    "id": a["id"],
                    "code": a["code"],
                    "name": a["name"],
                    "status": a["status"],
                    "verdict": v,
                    "why": why,
                    "spend": a["lifetime"]["spend"],
                    "purchases": a["lifetime"]["purchases"],
                    "roas": a["lifetime"]["roas"],
                    "cpa": ratio(life.spend, life.purchases),
                    "ctr": a["ctr"],
                    "roas_7d": a["roas_7d"],
                }
            )
        out.sort(key=lambda r: (order[r["verdict"]], -(r["roas"] or 0)))
        pairs.append(
            {
                "test_campaign": (by_id.get(cid) or {}).get("name") or ads[0]["campaign"],
                "scale_campaign": target["name"] if target else None,
                "product_line": line,
                "missing": sum(1 for r in out if r["verdict"] == "add"),
                "rows": out,
                "note": None
                if target
                else "This product has no scaling campaign: proven ads stay in testing.",
            }
        )
    pairs.sort(key=lambda p: -p["missing"])
    return pairs


def _recent(brand: str) -> Ctx:
    """The last 7 complete days (for the gap and the suggestions)."""
    return context(brand, "meta", None, None, None)


@_kept
def gap(brand: str) -> dict[str, Any]:
    """Proven ads in the testing (ABO) campaigns that are missing from the scaling (CBO) campaign of
    their product."""
    c = _recent(brand)
    rows, _st, _w = _ads(c)
    pairs = _gap_pairs(c, rows, _campaign_rows(c, rows))
    return {
        "brand": brand,
        "as_of": c.to.isoformat(),
        "pairs": pairs,
        "missing": sum(p["missing"] for p in pairs),
        "rule": {
            "roas": c.rules["scale_roas"],
            "purchases": c.rules["graduate_min_purchases"],
            "spend": c.rules["proven_spend"],
        },
        "note": "Ads are matched by their post, not by their code, because a code can be reused "
        "for a different "
        "product.",
    }


# ------------------------------------------------------------------ suggestions
def x2(v: float | None) -> str:
    """A ratio for a sentence: 1.87, or n/a."""
    return "n/a" if v is None else f"{v:.2f}"


def _actions(c: Ctx) -> list[dict[str, Any]]:
    (rows, _st, _w), marks = _together(lambda: _ads(c), lambda: data.action_status(c.brand))
    camps = _campaign_rows(c, rows)
    out: list[dict[str, Any]] = []

    def push(a: dict[str, Any]) -> None:
        out.append(
            {
                "platform": "meta",
                "confidence": "Medium",
                "daily_impact": 0,
                **a,
                "status": marks.get(a["id"], "open"),
            }
        )

    for x in camps:
        call = (x.get("health") or {}).get("call")
        if call and call["key"] != "hold" and x["daily_budget"]:
            push(
                {
                    "id": f"budget:{x['id']}",
                    "group": "budget",
                    "title": x["name"],
                    "where": "Campaign budget",
                    "current": f"${round(x['daily_budget']):,}/day",
                    "proposed": f"${call['new_budget']:,}/day",
                    "evidence": call["why"],
                    "confidence": "High",
                    "daily_impact": call["new_budget"] - round(x["daily_budget"]),
                }
            )
    stops = [
        a
        for a in rows
        if a["verdict"] == "stop" and a["status"] == "ACTIVE" and a["_ctype"] != "catalog"
    ]
    for a in sorted(stops, key=lambda a: -a["spend_7d"])[:6]:
        push(
            {
                "id": f"stop:{a['id']}",
                "group": "stop",
                "title": a["name"],
                "where": f"{a['campaign']} › {a['ad_set']}",
                "current": "Active",
                "proposed": "Paused",
                "evidence": a["reason"],
                "confidence": "High" if a["lifetime"]["purchases"] == 0 else "Medium",
                "daily_impact": -round(a["spend_7d"] / 7) if a["_ctype"] == "abo" else 0,
            }
        )
    for p in _gap_pairs(c, rows, camps):
        for r in [r for r in p["rows"] if r["verdict"] == "add"][:2]:
            push(
                {
                    "id": f"add:{r['id']}",
                    "group": "refresh",
                    "title": f"Add {r['code']} to {p['scale_campaign']}",
                    "where": f"{p['scale_campaign']} (use the existing post)",
                    "current": f"Only in {p['test_campaign']}",
                    "proposed": "Running in the scaling campaign",
                    "evidence": r["why"],
                }
            )
    iterate = [
        a
        for a in rows
        if a["verdict"] == "iterate"
        and a["status"] == "ACTIVE"
        and a["weakest"]["key"] not in ("none", "early")
    ]
    for a in sorted(iterate, key=lambda a: -a["spend_7d"])[:3]:
        push(
            {
                "id": f"iterate:{a['id']}",
                "group": "iterate",
                "title": a["name"],
                "where": f"{a['campaign']} › {a['ad_set']}",
                "current": f"7-day ROAS {x2(a['roas_7d'])}",
                "proposed": f"New version that fixes the {a['weakest']['label'].lower()}",
                "evidence": f"{a['reason']} Weakest step: {a['weakest']['label']}.",
            }
        )
    order = {"stop": 0, "refresh": 1, "budget": 2, "iterate": 3}
    out.sort(key=lambda a: order[a["group"]])
    return [{"n": i + 1, **a} for i, a in enumerate(out)]


@_kept
def actions(brand: str, platform: str) -> dict[str, Any]:
    """The rules' suggestions from the last 7 days, with what the team marked, and the history."""
    c = _recent(brand)
    acts, past = _together(
        lambda: [] if platform == "google" else _actions(c), lambda: data.action_history(brand)
    )
    history = [
        {
            "id": h["id"],
            "brand": brand,
            "action_id": h["action_id"],
            "title": h["title"],
            "group": h["grp"],
            "status": h["status"],
            "by": h.get("by_user") or "team",
            "at": h["at"],
        }
        for h in past
    ]
    open_ = [a for a in acts if a["status"] == "open"]
    return {
        "brand": brand,
        "platform": platform,
        "as_of": c.to.isoformat(),
        "actions": acts,
        "open": len(open_),
        "daily_impact": sum(a["daily_impact"] for a in open_),
        "history": history,
        "google_note": GOOGLE_RULES_NOTE,
        "read_only": READ_ONLY,
    }


def mark_action(brand: str, action_id: str, status: str, by: str) -> dict[str, Any]:
    """Mark a suggestion done, skipped or open again. LookupError when it no longer applies."""
    if status not in ("open", "done", "skipped"):
        raise InputError("status must be 'open', 'done' or 'skipped'.")
    action = next((a for a in _actions(_recent(brand)) if a["id"] == action_id), None)
    if action is None:
        raise LookupError("That suggestion no longer applies.")
    data.set_action_status(brand, action, status, by)
    return {**action, "status": status}


# ------------------------------------------------------------------ rules
@_kept
def rules(brand: str) -> dict[str, Any]:
    """Every threshold for the brand, the rupee rate when Meta bills in another currency, the
    defaults, the glossary."""
    c = _recent(brand)
    currency = str(c.account.get("currency") or "USD")
    values: dict[str, Any] = dict(c.rules)
    defaults: dict[str, Any] = metrics.rules_for(brand, {})
    if currency != "USD":
        values["fx_rate"], values["fx_from"] = _together(
            lambda: data.fx_rate(currency, c.today), lambda: data.fx_since(currency)
        )
        defaults["fx_rate"] = 88.0
    return {
        "brand": brand,
        "rules": values,
        "defaults": defaults,
        "meta_currency": currency,
        "glossary": [{"term": t, "meaning": m} for t, m in GLOSSARY],
    }


def save_rules(brand: str, changes: Any, by: str) -> dict[str, Any]:
    """Validate and store changed thresholds; a new rupee rate applies from today on (earlier days
    keep theirs)."""
    if not isinstance(changes, dict) or not changes:
        raise InputError("Send the settings to change as {name: number}.")
    c = _recent(brand)
    try:
        ok = metrics.check_rule_changes(changes, c.rules)
    except ValueError as e:
        raise InputError(str(e)) from None
    currency = str(c.account.get("currency") or "USD")
    fx = ok.pop("fx_rate", None)
    if fx is not None:
        if currency == "USD":
            raise InputError(
                "This brand's Meta account is billed in dollars: there is no rate to set."
            )
        data.set_fx_rate(currency, c.today, fx, by)
    if ok:
        data.save_rules(brand, {**data.rules(brand), **ok}, by)
    data.forget(c.key)
    return rules(brand)


TERMS_SHOWN = 300  # rows per list; the rest have the least spend


@_kept
def search_terms(
    brand: str,
    frm: str | None = None,
    to: str | None = None,
    compare: str | None = None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Google's keywords, search terms and products for the range, and how much of Google's claimed
    sales came from people searching for the brand by name."""
    c = context(brand, "google", frm, to, compare, cfrom)
    if c.g_key is None:
        raise GoogleNotConnectedError
    key = c.g_key
    camps, terms, keywords, products, totals = _together(
        lambda: data.g_campaigns(key),
        lambda: data.g_sum(key, "term", c.frm, c.to),
        lambda: data.g_sum(key, "keyword", c.frm, c.to),
        lambda: data.g_sum(key, "product", c.frm, c.to),
        lambda: data.g_sum(key, "campaign", c.frm, c.to),
    )
    brand_ids = {str(x["id"]) for x in camps if "brand" in str(x.get("name") or "").lower()}

    def merged(rows: list[dict[str, Any]], group: Any) -> list[dict[str, Any]]:
        out: dict[Any, dict[str, Any]] = {}
        for r in rows:
            k = group(r)
            t = out.setdefault(
                k,
                {
                    "id": "|".join(map(str, k)) if isinstance(k, tuple) else str(k),
                    "is_brand": False,
                    **dict.fromkeys(("spend", "value", "purchases", "impressions", "clicks"), 0.0),
                },
            )
            for f in ("spend", "value", "purchases", "impressions", "clicks"):
                t[f] += float(r.get(f) or 0)
            t["is_brand"] = t["is_brand"] or str(r.get("campaign_id")) in brand_ids
            t["_label"], t["_extra"] = str(r.get("label") or r["item"]), str(r.get("extra") or "")
        rows_out = []
        for t in out.values():
            if not t["spend"] and not t["purchases"]:
                continue
            rows_out.append(
                {
                    **{k: v for k, v in t.items() if not k.startswith("_")},
                    "spend": round(t["spend"], 2),
                    "value": round(t["value"], 2),
                    "impressions": int(t["impressions"]),
                    "clicks": int(t["clicks"]),
                    "roas": ratio(t["value"], t["spend"]),
                    "cpa": ratio(t["spend"], t["purchases"]),
                    "_label": t["_label"],
                    "_extra": t["_extra"],
                }
            )
        rows_out.sort(key=lambda r: -float(r["spend"]))
        return rows_out[:TERMS_SHOWN]

    def tidy(
        rows: list[dict[str, Any]], name: str, extra: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                **{k: v for k, v in r.items() if not k.startswith("_")},
                name: r["_label"],
                **({extra: r["_extra"]} if extra else {}),
            }
            for r in rows
        ]

    def tot(rows: list[dict[str, Any]], f: str, only: set[str] | None = None) -> float:
        return sum(float(r.get(f) or 0) for r in rows if only is None or str(r["item"]) in only)

    return {
        **_info(c),
        "keywords": tidy(
            merged(
                keywords, lambda r: (str(r.get("label") or "").lower(), str(r.get("extra") or ""))
            ),
            "text",
            "match_type",
        ),
        "terms": tidy(merged(terms, lambda r: str(r.get("label") or r["item"]).lower()), "term"),
        "products": tidy(merged(products, lambda r: str(r["item"])), "title"),
        "brand_share": {
            "spend": round(tot(totals, "spend", brand_ids), 2),
            "value": round(tot(totals, "value", brand_ids), 2),
            "total_value": round(tot(totals, "value"), 2),
            "total_spend": round(tot(totals, "spend"), 2),
        },
        "notes": [
            "Purchases are Google's main purchase action only (secondary purchase tags and click "
            "actions are left out). Search terms come from Search campaigns; Performance Max does "
            "not report them per term.",
        ],
    }


# ------------------------------------------------------------------ both brands (the company view)
BRAND_LABEL = {"ridhi": "Ridhi Block Print", "cpc": "Cotton Print Club"}


@_kept
def company(
    frm: str | None,
    to: str | None,
    compare: str | None,
    cfrom: str | None = None,
) -> dict[str, Any]:
    """Both brands together for directors: company ad spend (Meta + Google, both brands), the
    stores' sales, company MER and cost per order, each brand's own answer beside them (its spend
    call, MER, platforms and goal), and the days. Brands are added only where adding is honest:
    spend, store sales and orders. Platform-claimed sales and ROAS stay per brand."""
    from .config import BRANDS

    def one(brand: str) -> dict[str, Any]:
        try:
            return {
                "brand": brand,
                "ready": True,
                "o": overview(brand, "all", frm, to, compare, cfrom),
            }
        except NotReadyError as e:
            return {"brand": brand, "ready": False, "message": e.message}

    parts = _together(*(lambda b=b: one(b) for b in BRANDS))
    ready = [p for p in parts if p["ready"]]
    if not ready:
        raise NotReadyError(
            "not_configured",
            " ".join(p["message"] for p in parts) or "No brand's ad account is ready yet.",
        )
    first = ready[0]["o"]

    def total(key: str, side: str) -> float | None:
        vals = [p["o"]["metrics"][key][side] for p in ready]
        if all(v is None for v in vals):
            return None
        return sum(float(v or 0) for v in vals)

    def both(key: str) -> tuple[float | None, float | None]:
        return total(key, "value"), total(key, "baseline_value")

    spend, spend_b = both("total_spend")
    sales, sales_b = both("sales")
    ex, ex_b = both("sales_ex_bulk")
    orders, orders_b = both("orders")
    out_metrics = {
        "spend": block(spend, spend_b),
        "sales": block(sales, sales_b),
        "sales_ex_bulk": block(ex, ex_b),
        "orders": block(orders, orders_b),
        "mer_ex_bulk": block(
            div(ex or 0, spend or 0), div(ex_b or 0, spend_b or 0) if spend_b else None
        ),
        "cost_per_order": block(
            div(spend or 0, orders or 0), div(spend_b or 0, orders_b or 0) if orders_b else None
        ),
    }
    days: dict[str, dict[str, Any]] = {}
    for p in ready:
        b = p["brand"]
        for r in p["o"]["trend"]:
            t = days.setdefault(r["date"], {"date": r["date"], "spend": 0.0, "sales_ex_bulk": 0.0})
            t["spend"] += float(r["spend"] or 0)
            t["sales_ex_bulk"] += float(r["sales_ex_bulk"] or 0)
            t[f"{b}_spend"] = r["spend"]
            t[f"{b}_sales_ex_bulk"] = r["sales_ex_bulk"]
            t[f"{b}_mer_ex_bulk"] = r["mer_ex_bulk"]
    trend = []
    for d in sorted(days):
        t = days[d]
        m = div(t["sales_ex_bulk"], t["spend"])
        trend.append(
            {
                **t,
                "spend": round(t["spend"], 2),
                "sales_ex_bulk": round(t["sales_ex_bulk"], 2),
                "mer_ex_bulk": None if m is None else round(m, 2),
            }
        )
    brands = []
    for p in parts:
        if not p["ready"]:
            brands.append(
                {
                    "brand": p["brand"],
                    "label": BRAND_LABEL[p["brand"]],
                    "ready": False,
                    "message": p["message"],
                }
            )
            continue
        o = p["o"]
        m = o["metrics"]
        brands.append(
            {
                "brand": p["brand"],
                "label": BRAND_LABEL[p["brand"]],
                "ready": True,
                "gate": o["gate"],
                "targets": o["targets"],
                "gate_lines": o["gate_lines"],
                "metrics": {
                    k: m[k] for k in ("total_spend", "sales_ex_bulk", "mer_ex_bulk", "orders")
                },
                "share_of_spend": pct(float(m["total_spend"]["value"] or 0), spend or 0),
                "platforms": o["platforms"],
                "goal": o["goal"],
                "meta_saved_to": o["meta_saved_to"],
                "google_saved_to": o["google_saved_to"],
            }
        )
    return {
        "from": first["from"],
        "to": first["to"],
        "days": first["days"],
        "compare": first["compare"],
        "metrics": out_metrics,
        "brands": brands,
        "trend": trend,
        "notes": [
            "Both brands together: ad spend is Meta and Google for both brands; store sales are "
            "both stores' own orders (bulk orders left out of MER). Platform-claimed sales are "
            "never added together.",
            "Each brand keeps its own spend call, rules and goal: open a brand to act on it.",
        ],
    }
