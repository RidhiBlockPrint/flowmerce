"""CRO experiment results: the team writes the plan, the result is worked out from Shopify.

    before = the same number of days just before the start date
    during = start date .. end date (or yesterday while it is still running)

Rates (conversion, add to cart, bounce) come from ShopifyQL `sessions` with bots left out, for the
whole store or one landing page (matched after normalising the path, as on the Landing pages tab).
Average order value comes from Shopify's sales report ((gross sales - discounts) / orders).
Confidence for a rate = a two-sided two-proportion z-test on the visit counts: how sure we are the
change is not day-to-day noise. A win or loss needs 95% and at least 200 visits on each side; order
value gets no confidence (Shopify does not give per-order values in that report).

A before-and-after comparison is not an A/B test: anything else that changed in the same days (ads,
a sale, the season) also moves the number, so the page shows the change log next to each result.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from . import shopify
from .conversion import HUMAN, run, sales_daily
from .landing import norm_path
from .traffic import num, since

METRICS: dict[str, dict[str, str]] = {
    "conversion_rate": {"label": "Conversion rate", "better": "up"},
    "added_to_cart_rate": {"label": "Add-to-cart rate", "better": "up"},
    "bounce_rate": {"label": "Bounce rate", "better": "down"},
    "aov": {"label": "Average order value", "better": "up"},
}
MIN_SESSIONS = 200  # visits per side before a rate result is called
WIN_CONFIDENCE = 95.0  # % confidence needed to call a win or a loss
RATE_FIELDS = ("conversion_rate", "added_to_cart_rate", "bounce_rate")


def confidence(p1: float, n1: int, p2: float, n2: int) -> float | None:
    """Two-sided two-proportion z-test: confidence in % that the rates p1 (n1) and p2 (n2) differ.
    Rates are fractions (0.02 = 2%)."""
    if n1 <= 0 or n2 <= 0:
        return None
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = abs(p2 - p1) / se
    p_value = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return round((1 - p_value) * 100, 1)


def windows(start: date, end: date | None, today: date) -> tuple[date, date, date, date, str]:
    """(before first, before last, during first, during last, state) for an experiment. State is
    'planned' (starts today or later), 'running' or 'finished'."""
    yesterday = today - timedelta(days=1)
    if start > yesterday:
        return start, start, start, start, "planned"
    last = min(end or yesterday, yesterday)
    n = (last - start).days + 1
    b_last = start - timedelta(days=1)
    state = "finished" if end and end <= yesterday else "running"
    return b_last - timedelta(days=n - 1), b_last, start, last, state


def rates(
    store: str, first: date, last: date, page: str | None, gql: shopify.Gql | None = None
) -> dict[str, Any]:
    """{sessions, conversion_rate, added_to_cart_rate, bounce_rate} for local days first..last,
    the whole store or one landing page. Rates are fractions, weighted by visits."""
    shown = "sessions, " + ", ".join(RATE_FIELDS)
    w = since((first, last))
    if page:
        rows = run(
            store,
            f"FROM sessions SHOW {shown} {HUMAN}GROUP BY landing_page_path {w} "
            "ORDER BY sessions DESC LIMIT 1000",
            gql,
        )
        want = norm_path(page)
        rows = [
            r
            for r in rows
            if r.get("landing_page_path") is not None and norm_path(r["landing_page_path"]) == want
        ]
    else:
        rows = run(store, f"FROM sessions SHOW {shown} {HUMAN}{w}", gql)
    visits = sum(int(num(r.get("sessions"))) for r in rows)
    out: dict[str, Any] = {"sessions": visits}
    for k in RATE_FIELDS:
        out[k] = (
            sum(num(r.get(k)) * num(r.get("sessions")) for r in rows) / visits if visits else None
        )
    return out


def order_value(
    store: str, first: date, last: date, gql: shopify.Gql | None = None
) -> tuple[float | None, int]:
    """(average order value, orders) from Shopify's sales report for local days first..last."""
    days = sales_daily(store, first, last, gql).values()
    orders = int(sum(d["orders"] for d in days))
    net = sum(d["gross"] - d["discounts"] for d in days)
    return (round(net / orders, 2) if orders else None), orders


def _label(a: date, b: date) -> str:
    return f"{a:%d %b}" if a == b else f"{a:%d %b} - {b:%d %b}"


def result(exp: dict[str, Any], today: date, gql: shopify.Gql | None = None) -> dict[str, Any]:
    """The before / during figures, change, confidence and verdict of one experiment row."""
    start = date.fromisoformat(str(exp["start_date"])[:10])
    end = date.fromisoformat(str(exp["end_date"])[:10]) if exp.get("end_date") else None
    b_first, b_last, d_first, d_last, state = windows(start, end, today)
    if state == "planned":
        return {"state": "planned", "verdict": "planned", "summary": f"Starts {start:%d %b}"}
    metric = str(exp["metric"])
    out: dict[str, Any] = {
        "state": state,
        "days_measured": (d_last - d_first).days + 1,
        "before_label": _label(b_first, b_last),
        "during_label": _label(d_first, d_last),
    }
    if metric == "aov":
        before, b_n = order_value(str(exp["store"]), b_first, b_last, gql)
        during, d_n = order_value(str(exp["store"]), d_first, d_last, gql)
        out |= {"before": before, "during": during, "before_n": b_n, "during_n": d_n}
        out |= {"n_unit": "orders", "confidence": None}
        if before and during:
            ch = (during - before) / before * 100
            out |= {"change": round(ch, 1), "change_unit": "%"}
            out["verdict"] = (
                "early"
                if state == "running"
                else "better"
                if ch > 0
                else "worse"
                if ch < 0
                else "flat"
            )
        else:
            out["verdict"] = "no_data"
        return out
    page = exp.get("page_path") or None
    b = rates(str(exp["store"]), b_first, b_last, page, gql)
    d = rates(str(exp["store"]), d_first, d_last, page, gql)
    pb, pd = b[metric], d[metric]
    out |= {
        "before": round(pb * 100, 2) if pb is not None else None,
        "during": round(pd * 100, 2) if pd is not None else None,
        "before_n": b["sessions"],
        "during_n": d["sessions"],
        "n_unit": "visits",
    }
    if pb is None or pd is None:
        return {**out, "verdict": "no_data", "confidence": None}
    conf = confidence(pb, b["sessions"], pd, d["sessions"])
    good = pd > pb if METRICS[metric]["better"] == "up" else pd < pb
    out |= {"change": round((pd - pb) * 100, 2), "change_unit": "pts", "confidence": conf}
    if min(b["sessions"], d["sessions"]) < MIN_SESSIONS:
        out["verdict"] = "too_few"
    elif conf is not None and conf >= WIN_CONFIDENCE:
        out["verdict"] = ("win" if good else "loss") + ("_so_far" if state == "running" else "")
    else:
        out["verdict"] = "running" if state == "running" else "no_clear_result"
    return out


def clean(body: dict[str, Any]) -> dict[str, Any]:
    """The stored fields of an experiment from a request body. Raises ValueError with a plain
    reason when something cannot be used."""
    name = str(body.get("name") or "").strip()
    hypothesis = str(body.get("hypothesis") or "").strip()
    metric = str(body.get("metric") or "")
    if not name or len(name) > 200:
        raise ValueError("Give the experiment a name of 1 to 200 characters.")
    if not hypothesis or len(hypothesis) > 2000:
        raise ValueError("Describe what you expect to happen (1 to 2,000 characters).")
    if metric not in METRICS:
        raise ValueError(f"The metric must be one of: {', '.join(METRICS)}.")
    try:
        start = date.fromisoformat(str(body.get("start_date") or "")[:10])
    except ValueError:
        raise ValueError("Give a start date (YYYY-MM-DD).") from None
    end = None
    if body.get("end_date"):
        try:
            end = date.fromisoformat(str(body["end_date"])[:10])
        except ValueError:
            raise ValueError("The end date must be YYYY-MM-DD.") from None
        if end < start:
            raise ValueError("The end date is before the start date.")
    page = str(body.get("page_path") or "").strip() or None
    if metric == "aov":
        page = None  # order value is for the whole store
    if page and (len(page) > 500 or not page.startswith("/")):
        raise ValueError("A landing page is a path that starts with /, like /collections/quilts.")
    owner = str(body.get("owner") or "").strip() or None
    rec_key = str(body.get("rec_key") or "").strip()[:300] or None
    return {
        "name": name,
        "hypothesis": hypothesis,
        "metric": metric,
        "page_path": page,
        "start_date": start.isoformat(),
        "end_date": end.isoformat() if end else None,
        "owner": owner[:200] if owner else None,
        "rec_key": rec_key,
    }


def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the tiles: total, planned, running, finished, won, and the win rate of the
    finished ones (wins and better order values count as wins)."""
    states = [i.get("result", {}).get("state") for i in items]
    verdicts = [i.get("result", {}).get("verdict") for i in items]
    finished = [v for s, v in zip(states, verdicts, strict=True) if s == "finished"]
    won = sum(1 for v in finished if v in ("win", "better"))
    return {
        "total": len(items),
        "planned": states.count("planned"),
        "running": states.count("running"),
        "finished": len(finished),
        "won": won,
        "win_rate": round(won / len(finished) * 100) if finished else None,
    }
