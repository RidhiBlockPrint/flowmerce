"""A store's monthly revenue goal, shown on the CRO Overview as a progress bar with today's pace.
Owner request 2026-11-20 (design sample "store pulse").

One number per store: the revenue the team aims for in a calendar month, in the store's currency.
It is kept in the app's settings table (the local database), like Claude's CRO plan; 0 means
"no goal set". The progress itself is worked out on the page from the month-to-date revenue the
Overview already reads.
"""

from __future__ import annotations

import json
from typing import Any

from ..seo.audit import audit
from ..seo.db import get, now, run
from ..seo.util import HttpError

MAX_GOAL = 100_000_000.0


def _key(brand: str) -> str:
    return f"cro_goal:{brand}"


def goal(brand: str) -> dict[str, Any]:
    """The store's monthly revenue goal (0 when none is set) and when it was last changed."""
    row = get("SELECT value_json, updated_at FROM app_settings WHERE key = ?", _key(brand))
    try:
        saved = json.loads(row["value_json"]) if row else {}
    except ValueError:
        saved = {}
    value = float(saved.get("monthly_revenue") or 0) if isinstance(saved, dict) else 0.0
    return {
        "brand": brand,
        "monthly_revenue": value,
        "updated_at": row["updated_at"] if row else None,
    }


def set_goal(brand: str, body: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Set (or clear with 0) the monthly revenue goal."""
    try:
        value = round(float(body.get("monthly_revenue")), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HttpError(400, "monthly_revenue must be a number.", "bad_request") from None
    if not 0 <= value <= MAX_GOAL:
        raise HttpError(400, "The goal must be between 0 and 100,000,000.", "bad_request")
    run(
        """INSERT INTO app_settings (key, value_json, updated_at, updated_by) VALUES (?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
           updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        _key(brand),
        json.dumps({"monthly_revenue": value}),
        now(),
        user.get("id"),
    )
    audit(user, "cro.goal", "cro_store", None, brand, f"Monthly revenue goal {value:,.2f}")
    return goal(brand)
