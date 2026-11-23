"""The Claude spending limit. The owner sets a monthly budget; each day may spend at most budget / days-in-month, so the
budget lasts the whole month at an even pace. Unused money does not roll over to the next day.

Every Claude call made by this server is recorded with its token counts and an estimated cost (list prices below).
Before a call, the expected cost of that kind of call is checked against what is left today; a call that would go
over the limit is refused (HTTP 429, code daily_limit) and nothing is sent to Claude. Calls made by an external worker
are not seen here and are not counted."""
from __future__ import annotations

import calendar
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import get, now, run
from ..util import HttpError

# The owner's ceiling (2026-11-19): at most $90 a month. The budget can be set lower, never higher.
MAX_MONTHLY_USD = 90.0
DEFAULT_MONTHLY_USD = min(MAX_MONTHLY_USD, float(os.environ.get("CLAUDE_MONTHLY_BUDGET_USD", "90") or 90))
# Warn once this share of today's limit or of the month's budget is spent.
WARN_AT = 0.8
# The business day used for the limit: India by default (UTC+5:30). Set CLAUDE_BUDGET_UTC_OFFSET_MINUTES to change it.
UTC_OFFSET = timedelta(minutes=int(os.environ.get("CLAUDE_BUDGET_UTC_OFFSET_MINUTES", "330") or 330))

# US dollars per million tokens: input, output, cache read. A cache write costs 1.25 x input. Unknown models are priced
# as the default model, so the estimate never comes out lower than it should.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]
# What one call of each kind is expected to cost, used to refuse a call that would overshoot today's limit.
# cro_advice: Conversion (CRO) asks Claude for an action plan from a store's figures (modules/cro/ai_advice.py). The deep
# plan (2026-11-23) cost $0.37-0.59 a store in its first runs, so 0.60 keeps a call from overshooting today's limit.
ESTIMATE_USD = {"content_generation": 0.80, "content_revision": 0.80, "topic_research": 0.40, "assist": 0.15, "cro_advice": 0.60}


def _local_now() -> datetime:
    return datetime.now(timezone.utc) + UTC_OFFSET


def today() -> str:
    return _local_now().date().isoformat()


def settings() -> dict[str, Any]:
    row = get("SELECT value_json FROM app_settings WHERE key = 'claude_budget'")
    saved = json.loads(row["value_json"]) if row else {}
    return {"monthlyBudgetUsd": min(MAX_MONTHLY_USD, float(saved.get("monthlyBudgetUsd", DEFAULT_MONTHLY_USD)))}


def update_settings(patch: dict, user_id: int | None) -> dict[str, Any]:
    try:
        monthly = round(float(patch.get("monthlyBudgetUsd")), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HttpError(400, "monthlyBudgetUsd must be a number of US dollars.")
    if not 0 <= monthly <= MAX_MONTHLY_USD:
        raise HttpError(400, f"The monthly budget must be between $0 and ${MAX_MONTHLY_USD:.0f}.")
    run("""INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES ('claude_budget', ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        json.dumps({"monthlyBudgetUsd": monthly}), now(), user_id)
    return settings()


def cost_usd(usage: dict[str, Any]) -> float:
    """Estimated list-price cost of one call from its usage record (see integrations/claude.take_usage)."""
    p_in, p_out, p_read = PRICES.get(str(usage.get("model") or ""), DEFAULT_PRICE)
    tokens = lambda k: int(usage.get(k) or 0)  # noqa: E731
    return round((tokens("inputTokens") * p_in + tokens("cacheWriteTokens") * p_in * 1.25 + tokens("cacheReadTokens") * p_read
                  + tokens("outputTokens") * p_out) / 1_000_000, 6)


def record(usage: dict[str, Any] | None, brand_id: str, kind: str, job_id: str | None = None) -> float:
    """Store one Claude call. Returns its estimated cost. A missing usage record (no call was made) stores nothing."""
    if not usage or not usage.get("model"):
        return 0.0
    c = cost_usd(usage)
    run("""INSERT INTO claude_usage (ts, day, brand_id, kind, model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, job_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        now(), today(), brand_id or "", kind, str(usage.get("model")), int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0),
        int(usage.get("cacheWriteTokens") or 0), int(usage.get("cacheReadTokens") or 0), c, job_id)
    return c


def status() -> dict[str, Any]:
    """Today's and this month's spend against the limits, for the dashboard."""
    local = _local_now()
    days = calendar.monthrange(local.year, local.month)[1]
    monthly = settings()["monthlyBudgetUsd"]
    daily = round(monthly / days, 4)
    day = local.date().isoformat()
    t = get("SELECT COALESCE(SUM(cost_usd),0) usd, COUNT(*) n FROM claude_usage WHERE day = ?", day) or {"usd": 0, "n": 0}
    m = get("SELECT COALESCE(SUM(cost_usd),0) usd FROM claude_usage WHERE day >= ?", local.date().replace(day=1).isoformat()) or {"usd": 0}
    midnight = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - UTC_OFFSET
    today_usd, month_usd = float(t["usd"]), float(m["usd"])
    return {"warning": _warning(today_usd, daily, month_usd, monthly), "maxMonthlyUsd": MAX_MONTHLY_USD, "monthlyBudgetUsd": monthly, "dailyLimitUsd": daily, "daysInMonth": days, "today": day,
            "todayUsd": round(float(t["usd"]), 4), "callsToday": int(t["n"]), "monthUsd": round(float(m["usd"]), 4),
            "remainingTodayUsd": round(max(0.0, daily - float(t["usd"])), 4),
            "resetsAt": midnight.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "estimates": ESTIMATE_USD}


def _warning(today_usd: float, daily: float, month_usd: float, monthly: float) -> dict[str, Any] | None:
    """A warning when the money is nearly or fully used: today's limit first (it stops work soonest), then the month."""
    if daily > 0 and today_usd >= daily - ESTIMATE_USD["assist"]:
        return {"level": "crit", "scope": "day", "message": f"Today's Claude limit is used up (${today_usd:.2f} of ${daily:.2f}). New Claude work waits until midnight."}
    if daily > 0 and today_usd >= WARN_AT * daily:
        return {"level": "warn", "scope": "day", "message": f"Today's Claude limit is almost used: ${today_usd:.2f} of ${daily:.2f}, ${daily - today_usd:.2f} left."}
    if monthly > 0 and month_usd >= WARN_AT * monthly:
        return {"level": "warn", "scope": "month", "message": f"This month's Claude budget is almost used: ${month_usd:.2f} of ${monthly:.2f}, ${monthly - month_usd:.2f} left."}
    return None


def seconds_until_reset() -> float:
    st = status()
    return max(60.0, (datetime.fromisoformat(st["resetsAt"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds())


def check(kind: str) -> None:
    """Refuse (429 daily_limit) a call whose expected cost does not fit in what is left of today's limit."""
    st = status()
    need = ESTIMATE_USD.get(kind, ESTIMATE_USD["assist"])
    if st["todayUsd"] + need > st["dailyLimitUsd"]:
        raise HttpError(429, f"Today's Claude limit is used up (${st['todayUsd']:.2f} of ${st['dailyLimitUsd']:.2f}; this needs about ${need:.2f}). "
                             "It resets at midnight, or an admin can raise the monthly budget.", "daily_limit")
