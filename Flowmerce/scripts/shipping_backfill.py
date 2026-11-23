r"""Load each store's Shopify orders placed 60 to 120 days ago into Supabase (ops.shopify_orders), once.

The normal refresh reads only the last 60 days and the changes since. Both store apps can read every order
(read_all_orders), so this fills in the 120 days the Shipping board tracks (agreed 23 Nov 2026). Orders already in ops.shopify_orders are left alone.

Default is a DRY RUN: it reads Shopify and prints counts, and writes nothing. With --write it stores the orders;
the next refresh (every 15 minutes, or "Refresh now") then merges them into the Shipping board, so the live page
changes within 15 minutes. Prints counts only, never keys or customer data.

Usage: .venv\Scripts\python.exe scripts\shipping_backfill.py [--write] [--store RBP|CPC]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowmerce.modules.shipping import shopify_source  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="store the orders (default: dry run, writes nothing)")
    ap.add_argument("--store", choices=sorted(shopify_source.STORE_BRAND), help="one store only (default: both)")
    a = ap.parse_args()
    ok = True
    for store in [a.store] if a.store else list(shopify_source.STORE_BRAND):
        t = time.time()
        if not shopify_source.store_configured(store):
            print(store, "not configured")
            continue
        try:
            res = shopify_source.backfill_store(store, write=a.write)
        except Exception as e:  # noqa: BLE001 - report and go on with the other store
            ok = False
            print(store, "failed:", (getattr(e, "message", None) or str(e))[:300])
            continue
        print(store, json.dumps(res), f"{time.time() - t:.0f} s", "" if a.write else "(dry run: nothing written)")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
