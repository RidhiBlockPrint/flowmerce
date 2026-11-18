r"""Run one Shipping refresh now, from the command line (same as the "Refresh now" button).

1. Reads each store's changes straight from Shopify with the keys in .env (first run per store: the last 60 days,
   as one Shopify bulk export; can take a few minutes). Keys stay in .env; nothing about them goes to Supabase.
2. Runs ops.refresh_from_shopify_orders() in Supabase to merge that with the hub's orders.
Prints counts only, never keys or customer data.

Usage: .venv\Scripts\python.exe scripts\shipping_refresh.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowmerce.modules.shipping import service  # noqa: E402
from flowmerce.modules.shipping.supabase import SupabaseError  # noqa: E402


def main() -> int:
    t = time.time()
    try:
        res = service.refresh("cli:shipping_refresh")
    except SupabaseError as e:
        print(f"refresh failed ({e.state}): {e.message}")
        return 1
    for s in res.get("shopify") or []:
        print("shopify", json.dumps(s))
    print("merge  ", json.dumps(res.get("result")))
    print(f"done in {time.time() - t:.0f} s")
    return 0 if all(s.get("state") in ("ok", "not_configured") for s in res.get("shopify") or []) else 2


if __name__ == "__main__":
    raise SystemExit(main())
