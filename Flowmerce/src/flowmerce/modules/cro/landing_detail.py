"""Landing pages week on week and month on month, and one landing page's deep dive (owner request
2026-11-23, laid out like the CRO prototype's "Week / Month compare" and page deep dive).

Windows are store-local complete days ending yesterday: a week is the last 7 days against the 7
before, a month the last 30 against the 30 before. Figures come from ShopifyQL (bots left out),
rates in % (2.5 = 2.5%), changes of rates in points:

* compare_pages: every landing page Shopify lists (up to 200) with sessions, bounce, add to cart,
  conversion, orders, revenue and revenue per visit for both periods and the change.
* page_detail: one page's day-by-day figures for the last 60 days (the week and month totals are
  added up from them), its traffic sources and devices week on week and month on month, its own
  funnel by device, and "what changed": the biggest moves as plain sentences. (Countries were
  removed on 2026-11-24 at the owner's request.)
* funnel_pages: every landing page's funnel (sessions, viewed a product, added to cart, reached
  checkout, purchased) week on week or month on month, each step as a share of sessions and of
  the step before.
* pages_daily: several pages side by side day by day (the busiest 8 unless chosen), with the
  busiest 200 pages to choose from.

The page path goes into the query, so it is checked first (`clean_path`): only a plain path of
letters, digits and / - _ . ~ % + is accepted.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from . import shopify
from .conversion import FUNNEL_FIELDS, FUNNEL_STEPS, HUMAN
from .landing import SESSION_METRICS, min_sessions, norm_path, rate_rows
from .traffic import Window, num, rate, required, run_many, since

PATH_OK = re.compile(r"^/[a-z0-9/_\-.~%+]{0,480}$")
DETAIL_DAYS = 60
PAGES_LIMIT = 200
FIELDS = ("sessions", "bounce_rate", "added_to_cart_rate", "conversion_rate")
SEGMENTS = {"sources": "referrer_source", "devices": "session_device_type"}


class PathError(ValueError):
    """A landing page path that cannot be used in a query."""


def clean_path(raw: Any) -> str:
    """The page path as Shopify reports it (no domain, query or trailing slash, lower case);
    raises PathError for anything that is not a plain path."""
    path = norm_path(raw)
    if not PATH_OK.match(path):
        raise PathError("Give a landing page path like /collections/quilts.")
    return path


def windows(yesterday: date) -> dict[str, tuple[Window, Window]]:
    """{'week': (this week, the week before), 'month': (last 30 days, the 30 before)}."""

    def pair(n: int) -> tuple[Window, Window]:
        cur = (yesterday - timedelta(days=n - 1), yesterday)
        return cur, (cur[0] - timedelta(days=n), cur[0] - timedelta(days=1))

    return {"week": pair(7), "month": pair(30)}


def _span(w: Window) -> dict[str, str]:
    return {"from": w[0].isoformat(), "to": w[1].isoformat()}


def _block(rates: dict[str, Any] | None, sale: tuple[float, float] | None) -> dict[str, Any]:
    """One period's figures for a page: its rates and its orders and revenue."""
    r = rates or {
        "sessions": 0,
        "bounce_rate": None,
        "added_to_cart_rate": None,
        "conversion_rate": None,
    }
    revenue = round(sale[0], 2) if sale else 0.0
    orders = int(sale[1]) if sale else 0
    return {
        **r,
        "orders": orders,
        "revenue": revenue,
        "revenue_per_session": round(revenue / r["sessions"], 2) if r["sessions"] else None,
        "aov": round(revenue / orders, 2) if orders else None,
    }


def _pct(now: float | None, before: float | None) -> float | None:
    if now is None or not before:
        return None
    return round((now - before) / abs(before) * 100, 1)


def _pts(now: float | None, before: float | None) -> float | None:
    return None if now is None or before is None else round(now - before, 2)


def change(now: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    """The change of each figure: % for counts and money, points for rates (pure)."""
    return {
        "sessions": (now["sessions"] or 0) - (before["sessions"] or 0),
        "sessions_pct": _pct(now["sessions"], before["sessions"]),
        "bounce_pts": _pts(now["bounce_rate"], before["bounce_rate"]),
        "added_to_cart_pts": _pts(now["added_to_cart_rate"], before["added_to_cart_rate"]),
        "conversion_pts": _pts(now["conversion_rate"], before["conversion_rate"]),
        "orders": (now["orders"] or 0) - (before["orders"] or 0),
        "orders_pct": _pct(now["orders"], before["orders"]),
        "revenue": round((now["revenue"] or 0) - (before["revenue"] or 0), 2),
        "revenue_pct": _pct(now["revenue"], before["revenue"]),
        "revenue_per_session_pct": _pct(now["revenue_per_session"], before["revenue_per_session"]),
        "aov_pct": _pct(now.get("aov"), before.get("aov")),
    }


def _sales(rows: list[dict[str, Any]] | None) -> dict[str, tuple[float, float]]:
    out: dict[str, list[float]] = {}
    for r in rows or []:
        if r.get("order_landing_page_path") is None:
            continue
        acc = out.setdefault(norm_path(r["order_landing_page_path"]), [0.0, 0.0])
        acc[0] += num(r.get("total_sales"))
        acc[1] += num(r.get("orders"))
    return {k: (v[0], v[1]) for k, v in out.items()}


def compare_rows(
    cur_rows: list[dict[str, Any]],
    base_rows: list[dict[str, Any]] | None,
    cur_sales: list[dict[str, Any]] | None,
    base_sales: list[dict[str, Any]] | None,
    least: int,
) -> list[dict[str, Any]]:
    """Every page of the current period with both periods' figures and the change (pure). A page
    under `least` visits in either period is marked low_data: its changes are mostly noise."""
    page_type: dict[str, str] = {}
    for r in cur_rows:
        if r.get("landing_page_path") is not None:
            page_type.setdefault(
                norm_path(r["landing_page_path"]),
                str(r.get("landing_page_type") or "").strip() or "Other",
            )
    now_rates = rate_rows(cur_rows, "landing_page_path")
    before_rates = rate_rows(base_rows, "landing_page_path")
    now_sales, before_sales = _sales(cur_sales), _sales(base_sales)
    out = []
    for path, r in sorted(now_rates.items(), key=lambda kv: -kv[1]["sessions"]):
        now = _block(r, now_sales.get(path))
        before = _block(before_rates.get(path), before_sales.get(path))
        out.append(
            {
                "path": path,
                "page_type": page_type.get(path, "Other"),
                "now": now,
                "before": before,
                "change": change(now, before),
                "low_data": now["sessions"] < least or before["sessions"] < least,
            }
        )
    return out


def compare_pages(
    store: str, yesterday: date, mode: str, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Every landing page this week against last week (`mode` 'week') or the last 30 days against
    the 30 before ('month')."""
    if mode not in ("week", "month"):
        raise PathError("mode must be week or month.")
    cur, base = windows(yesterday)[mode]
    page_q = f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}GROUP BY landing_page_path, "
    sales_q = "FROM sales SHOW total_sales, orders GROUP BY order_landing_page_path "
    rows, errors = run_many(
        store,
        {
            "pages": f"{page_q}landing_page_type {since(cur)} ORDER BY sessions DESC "
            f"LIMIT {PAGES_LIMIT}",
            "pages_prev": f"{page_q}landing_page_type {since(base)} ORDER BY sessions DESC "
            "LIMIT 1000",
            "sales": f"{sales_q}{since(cur)} ORDER BY total_sales DESC LIMIT 1000",
            "sales_prev": f"{sales_q}{since(base)} ORDER BY total_sales DESC LIMIT 1000",
        },
        gql,
    )
    least = min_sessions((cur[1] - cur[0]).days + 1)
    pages = compare_rows(
        required(rows, errors, "pages"),
        rows.get("pages_prev"),
        rows.get("sales"),
        rows.get("sales_prev"),
        least,
    )
    return {
        "mode": mode,
        "current": _span(cur),
        "previous": _span(base),
        "min_sessions": least,
        "revenue_available": rows.get("sales") is not None,
        "pages": pages,
        "errors": errors,
    }


# ------------------------------------------------------------------------------------- one page
def daily_rows(
    sessions: list[dict[str, Any]] | None, sales: list[dict[str, Any]] | None, days: list[date]
) -> list[dict[str, Any]]:
    """One row per day (oldest first), every day present even without visits (pure)."""
    by_day: dict[str, dict[str, Any]] = {}
    for r in sessions or []:
        day = str(r.get("day") or "")[:10]
        if day:
            s = num(r.get("sessions"))
            by_day[day] = {
                "sessions": int(s),
                **{k: round(num(r.get(k)) * 100, 2) if s else None for k in FIELDS[1:]},
            }
    money: dict[str, tuple[float, float]] = {}
    for r in sales or []:
        day = str(r.get("day") or "")[:10]
        if day:
            money[day] = (num(r.get("total_sales")), num(r.get("orders")))
    out = []
    for d in days:
        key = d.isoformat()
        base = by_day.get(key) or {"sessions": 0, **dict.fromkeys(FIELDS[1:])}
        out.append({"date": key, **_block(base, money.get(key))})
    return out


def total(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Days added up: visits and money summed, rates weighted by visits (pure)."""
    s = sum(r["sessions"] for r in rows)

    def weighted(key: str) -> float | None:
        return round(sum((r[key] or 0) * r["sessions"] for r in rows) / s, 2) if s else None

    revenue = round(sum(r["revenue"] for r in rows), 2)
    orders = sum(r["orders"] for r in rows)
    return {
        "sessions": s,
        **{k: weighted(k) for k in FIELDS[1:]},
        "orders": orders,
        "revenue": revenue,
        "revenue_per_session": round(revenue / s, 2) if s else None,
        "aov": round(revenue / orders, 2) if orders else None,
    }


def segment_rows(
    now: list[dict[str, Any]] | None, before: list[dict[str, Any]] | None, key: str, least: int
) -> list[dict[str, Any]]:
    """A page's traffic sources or devices in one period against the other (pure)."""
    cur, prev = rate_rows(now, key), rate_rows(before, key)
    whole = sum(v["sessions"] for v in cur.values())
    out = []
    for label, v in sorted(cur.items(), key=lambda kv: -kv[1]["sessions"]):
        p = prev.get(label) or {"sessions": 0, **dict.fromkeys(FIELDS[1:])}
        low = v["sessions"] < least or p["sessions"] < least
        out.append(
            {
                "label": label,
                **v,
                "share": rate(v["sessions"], whole, 1),
                "previous_sessions": p["sessions"],
                "sessions_change": v["sessions"] - p["sessions"],
                "sessions_change_pct": _pct(v["sessions"], p["sessions"]),
                "bounce_change_pts": None if low else _pts(v["bounce_rate"], p["bounce_rate"]),
                "added_to_cart_change_pts": None
                if low
                else _pts(v["added_to_cart_rate"], p["added_to_cart_rate"]),
                "conversion_change_pts": None
                if low
                else _pts(v["conversion_rate"], p["conversion_rate"]),
                "low_data": low,
            }
        )
    return out


def _f(v: float | None, unit: str = "%") -> str:
    if v is None:
        return "-"
    return f"{v:,.2f}%" if unit == "%" else f"{v:,.0f}"


def what_changed(
    week: dict[str, Any],
    month: dict[str, Any],
    sources: list[dict[str, Any]],
    devices: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """The biggest moves of a page as short sentences with a tone (good / bad / info) (pure)."""
    out: list[dict[str, str]] = []
    n, b = week["now"], week["before"]
    c = week["change"]

    def add(text: str, tone: str) -> None:
        out.append({"text": text, "tone": tone})

    if c["bounce_pts"] is not None and abs(c["bounce_pts"]) >= 3:
        add(
            f"Bounce rate {'up' if c['bounce_pts'] > 0 else 'down'} {abs(c['bounce_pts']):.1f} pts "
            f"week on week ({_f(b['bounce_rate'])} -> {_f(n['bounce_rate'])}).",
            "bad" if c["bounce_pts"] > 0 else "good",
        )
    if c["added_to_cart_pts"] is not None and abs(c["added_to_cart_pts"]) >= 0.5:
        add(
            f"Add-to-cart {'up' if c['added_to_cart_pts'] > 0 else 'down'} "
            f"{abs(c['added_to_cart_pts']):.2f} pts week on week "
            f"({_f(b['added_to_cart_rate'])} -> {_f(n['added_to_cart_rate'])}).",
            "good" if c["added_to_cart_pts"] > 0 else "bad",
        )
    if c["conversion_pts"] is not None and abs(c["conversion_pts"]) >= 0.3:
        add(
            f"Conversion {'up' if c['conversion_pts'] > 0 else 'down'} "
            f"{abs(c['conversion_pts']):.2f} pts week on week "
            f"({_f(b['conversion_rate'])} -> {_f(n['conversion_rate'])}).",
            "good" if c["conversion_pts"] > 0 else "bad",
        )
    for label, block in (("WoW", week), ("MoM", month)):
        ch = block["change"]
        if ch["sessions_pct"] is not None and abs(ch["sessions_pct"]) >= 15:
            add(
                f"Sessions {ch['sessions_pct']:+.0f}% {label} "
                f"({_f(block['before']['sessions'], '#')} -> {_f(block['now']['sessions'], '#')}).",
                "good" if ch["sessions_pct"] > 0 else "bad",
            )
    mc = month["change"]
    if mc["revenue_pct"] is not None and abs(mc["revenue_pct"]) >= 15:
        add(
            f"Revenue {mc['revenue_pct']:+.0f}% MoM ({_f(month['before']['revenue'], '#')} -> "
            f"{_f(month['now']['revenue'], '#')}).",
            "good" if mc["revenue_pct"] > 0 else "bad",
        )
    for kind, rows in (("source", sources), ("device", devices)):
        judged = [r for r in rows if r["conversion_change_pts"] is not None]
        if judged:
            worst = min(judged, key=lambda r: r["conversion_change_pts"])
            if worst["conversion_change_pts"] <= -0.5:
                was = worst["conversion_rate"] - worst["conversion_change_pts"]
                add(
                    f"{kind.title()} '{worst['label']}': conversion {_f(was)} -> "
                    f"{_f(worst['conversion_rate'])} week on week.",
                    "bad",
                )
        moved = [r for r in rows if r["previous_sessions"] or r["sessions"]]
        if moved:
            big = max(moved, key=lambda r: abs(r["sessions_change"]))
            if abs(big["sessions_change"]) >= 100:
                add(
                    f"Biggest traffic shift: {kind} '{big['label']}' "
                    f"{big['previous_sessions']:,} -> {big['sessions']:,} sessions week on week.",
                    "info",
                )
    return out


def page_detail(
    store: str, path: str, yesterday: date, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """One landing page's deep dive (see the module docstring). `path` must be clean_path()'d."""
    if not PATH_OK.match(path):
        raise PathError("Give a landing page path like /collections/quilts.")
    win = windows(yesterday)
    first = yesterday - timedelta(days=DETAIL_DAYS - 1)
    only = f"{HUMAN}AND landing_page_path = '{path}' "
    queries = {
        "daily": f"FROM sessions SHOW {SESSION_METRICS} {only}TIMESERIES day "
        f"{since((first, yesterday))}",
        "daily_sales": f"FROM sales SHOW total_sales, orders WHERE order_landing_page_path = "
        f"'{path}' TIMESERIES day {since((first, yesterday))}",
    }
    for mode, (cur, base) in win.items():
        for name, field in SEGMENTS.items():
            queries[f"{name}_{mode}"] = (
                f"FROM sessions SHOW {SESSION_METRICS} {only}GROUP BY {field} {since(cur)}"
            )
            queries[f"{name}_{mode}_prev"] = (
                f"FROM sessions SHOW {SESSION_METRICS} {only}GROUP BY {field} {since(base)}"
            )
        for name, w in ((f"funnel_{mode}", cur), (f"funnel_{mode}_prev", base)):
            queries[name] = (
                f"FROM sessions SHOW {FUNNEL_FIELDS} {only}GROUP BY session_device_type, "
                f"session_viewed_product {since(w)}"
            )
    rows, errors = run_many(store, queries, gql)
    days = [first + timedelta(days=i) for i in range(DETAIL_DAYS)]
    daily = daily_rows(required(rows, errors, "daily"), rows.get("daily_sales"), days)

    def period(w: Window) -> dict[str, Any]:
        return total([d for d in daily if w[0].isoformat() <= d["date"] <= w[1].isoformat()])

    blocks = {}
    for mode, (cur, base) in win.items():
        now, before = period(cur), period(base)
        blocks[mode] = {
            "current": _span(cur),
            "previous": _span(base),
            "now": now,
            "before": before,
            "change": change(now, before),
        }
    least = {"week": min_sessions(7) // 2, "month": min_sessions(30)}
    segments = {
        f"{name}_{mode}": segment_rows(
            rows.get(f"{name}_{mode}"), rows.get(f"{name}_{mode}_prev"), field, least[mode]
        )
        for mode in win
        for name, field in SEGMENTS.items()
    }
    return {
        "path": path,
        "days": DETAIL_DAYS,
        "week": blocks["week"],
        "month": blocks["month"],
        "daily": daily,
        **segments,
        "funnel": {
            mode: {
                "now": page_funnel(rows.get(f"funnel_{mode}")),
                "before": page_funnel(rows.get(f"funnel_{mode}_prev")),
            }
            for mode in win
        },
        "what_changed": what_changed(
            blocks["week"], blocks["month"], segments["sources_week"], segments["devices_week"]
        ),
        "revenue_available": rows.get("daily_sales") is not None,
        "errors": errors,
    }


# ------------------------------------------------------------------------------- funnel by page
STEP_KEYS = ("viewed_product", *(k for k, _ in FUNNEL_STEPS[1:]))


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def funnel_counts(
    rows: list[dict[str, Any]] | None, key: str = "landing_page_path"
) -> dict[str, dict[str, Any]]:
    """{page (or device): {page_type, sessions, viewed_product, added_to_cart, reached_checkout,
    completed_checkout}} from rows grouped by `key` and whether the visit viewed a product (pure).
    Rows of one page that collapse to one path (a trailing slash, a query) are added up."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        if r.get(key) is None:
            continue  # a totals row
        label = (
            norm_path(r[key])
            if key == "landing_page_path"
            else (str(r[key]).strip().title() or "Unknown")
        )
        acc = out.setdefault(
            label,
            {
                "page_type": str(r.get("landing_page_type") or "").strip() or "Other",
                "sessions": 0,
                **dict.fromkeys(STEP_KEYS, 0),
            },
        )
        s = int(num(r.get("sessions")))
        acc["sessions"] += s
        if _truthy(r.get("session_viewed_product")):
            acc["viewed_product"] += s
        for step, field in FUNNEL_STEPS[1:]:
            acc[step] += int(num(r.get(field)))
    return out


def funnel_steps(c: dict[str, Any] | None) -> dict[str, Any]:
    """One page's funnel: each step's count, share of sessions and share of the step before."""
    c = c or {"sessions": 0, **dict.fromkeys(STEP_KEYS, 0)}
    s = c["sessions"]
    steps, before = [], s
    for key in STEP_KEYS:
        n = c[key]
        steps.append(
            {
                "key": key,
                "count": n,
                "pct_of_sessions": rate(n, s),
                "step_pct": rate(n, before, 1),
            }
        )
        before = n
    reached, done = c["reached_checkout"], c["completed_checkout"]
    return {
        "sessions": s,
        "steps": steps,
        "purchase_rate": rate(done, s),
        "checkout_abandonment": rate(reached - done, reached, 1),
    }


def page_funnel(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """One page's funnel for all devices together and for each device (busiest first), from rows
    grouped by device and whether the visit viewed a product (pure). None when Shopify did not
    answer."""
    if rows is None:
        return None
    by_device = funnel_counts(rows, "session_device_type")
    together = {"sessions": 0, **dict.fromkeys(STEP_KEYS, 0)}
    for c in by_device.values():
        for k in together:
            together[k] += c[k]
    return {
        "all": funnel_steps(together),
        "devices": [
            {"label": label, **funnel_steps(c)}
            for label, c in sorted(by_device.items(), key=lambda kv: -kv[1]["sessions"])
        ],
    }


def funnel_rows(
    cur_rows: list[dict[str, Any]], base_rows: list[dict[str, Any]] | None, least: int
) -> list[dict[str, Any]]:
    """Every page of the current period with its funnel now and before, busiest first (pure)."""
    now_c, before_c = funnel_counts(cur_rows), funnel_counts(base_rows)
    out = []
    for path, c in sorted(now_c.items(), key=lambda kv: -kv[1]["sessions"])[:PAGES_LIMIT]:
        now, before = funnel_steps(c), funnel_steps(before_c.get(path))
        changes = {
            s["key"]: _pts(s["pct_of_sessions"], b["pct_of_sessions"])
            for s, b in zip(now["steps"], before["steps"], strict=True)
        }
        out.append(
            {
                "path": path,
                "page_type": c["page_type"],
                "now": now,
                "before": before,
                "sessions_change": now["sessions"] - before["sessions"],
                "sessions_change_pct": _pct(now["sessions"], before["sessions"]),
                "step_change_pts": changes,
                "low_data": now["sessions"] < least or before["sessions"] < least,
            }
        )
    return out


def funnel_pages(
    store: str, yesterday: date, mode: str, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """Every landing page's funnel this week against last week ('week') or the last 30 days
    against the 30 before ('month')."""
    if mode not in ("week", "month"):
        raise PathError("mode must be week or month.")
    cur, base = windows(yesterday)[mode]
    q = (
        f"FROM sessions SHOW {FUNNEL_FIELDS} {HUMAN}GROUP BY landing_page_path, landing_page_type, "
        "session_viewed_product "
    )
    rows, errors = run_many(
        store,
        {
            "funnel": f"{q}{since(cur)} ORDER BY sessions DESC LIMIT 1000",
            "funnel_prev": f"{q}{since(base)} ORDER BY sessions DESC LIMIT 1000",
        },
        gql,
    )
    least = min_sessions((cur[1] - cur[0]).days + 1)
    return {
        "mode": mode,
        "current": _span(cur),
        "previous": _span(base),
        "min_sessions": least,
        "pages": funnel_rows(required(rows, errors, "funnel"), rows.get("funnel_prev"), least),
        "errors": errors,
    }


# ----------------------------------------------------------------------------- pages day by day
DAILY_DEFAULT = 8
DAILY_MAX = 12


def pages_daily(
    store: str,
    yesterday: date,
    paths: list[str] | None = None,
    days: int = DETAIL_DAYS,
    gql: shopify.Gql | None = None,
) -> dict[str, Any]:
    """Several landing pages side by side, day by day for the last `days` complete days: the
    busiest 8 of the last 30 days unless `paths` (clean_path()'d, at most 12) are given. Also the
    busiest 200 pages of the last 30 days to choose from."""
    first = yesterday - timedelta(days=days - 1)
    month = windows(yesterday)["month"][0]
    top, top_errors = run_many(
        store,
        {
            "top": f"FROM sessions SHOW sessions {HUMAN}GROUP BY landing_page_path, "
            f"landing_page_type {since(month)} ORDER BY sessions DESC LIMIT {PAGES_LIMIT}"
        },
        gql,
    )
    choices: dict[str, dict[str, Any]] = {}
    for r in required(top, top_errors, "top"):
        if r.get("landing_page_path") is None:
            continue
        path = norm_path(r["landing_page_path"])
        got = choices.setdefault(
            path,
            {
                "path": path,
                "page_type": str(r.get("landing_page_type") or "").strip() or "Other",
                "sessions": 0,
            },
        )
        got["sessions"] += int(num(r.get("sessions")))
    ranked = sorted(choices.values(), key=lambda c: -c["sessions"])
    chosen = [p for p in (paths or []) if PATH_OK.match(p)][:DAILY_MAX] or [
        c["path"] for c in ranked[:DAILY_DEFAULT]
    ]
    listed = "(" + ", ".join(f"'{p}'" for p in chosen) + ")"
    w = since((first, yesterday))
    rows, errors = run_many(
        store,
        {
            "daily": f"FROM sessions SHOW {SESSION_METRICS} {HUMAN}AND landing_page_path IN "
            f"{listed} GROUP BY landing_page_path TIMESERIES day {w}",
            "sales": "FROM sales SHOW total_sales, orders WHERE order_landing_page_path IN "
            f"{listed} GROUP BY order_landing_page_path TIMESERIES day {w}",
        },
        gql,
    )
    by_page: dict[str, list[dict[str, Any]]] = {p: [] for p in chosen}
    for r in required(rows, errors, "daily"):
        p = norm_path(r.get("landing_page_path"))
        if p in by_page and r.get("day"):
            by_page[p].append(r)
    sales_by: dict[str, list[dict[str, Any]]] = {p: [] for p in chosen}
    for r in rows.get("sales") or []:
        p = norm_path(r.get("order_landing_page_path"))
        if p in sales_by and r.get("day"):
            sales_by[p].append(r)
    day_list = [first + timedelta(days=i) for i in range(days)]
    kinds = {c["path"]: c["page_type"] for c in ranked}
    return {
        "from": first.isoformat(),
        "to": yesterday.isoformat(),
        "pages": [
            {
                "path": p,
                "page_type": kinds.get(p, "Other"),
                "rows": daily_rows(by_page[p], sales_by[p], day_list),
            }
            for p in chosen
        ],
        "choices": ranked,
        "revenue_available": rows.get("sales") is not None,
        "errors": errors,
    }
