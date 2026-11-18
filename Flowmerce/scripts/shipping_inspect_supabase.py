"""Read-only look at the Supabase shipping tables.

Prints, for each table: whether it is reachable, its row count, and its column names with the
Python type of one sample value. It never prints a value, a URL or a key, and never writes.

Usage:  .venv\\Scripts\\python.exe scripts\\shipping_inspect_supabase.py
Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment, .env or .env.shipping.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from flowmerce.modules.shipping.config import shipping_config  # noqa: E402

TABLES = {
    "public": ["stores", "orders", "sync_runs", "shipments", "tracking_numbers"],
    "ops": ["stores", "carriers", "orders", "shipments", "tracking_numbers", "tracking_scans", "sync_runs"],
}


def main() -> int:
    cfg = shipping_config()
    if not cfg.configured:
        print("Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing).")
        return 1
    headers = {"apikey": cfg.key, "Authorization": f"Bearer {cfg.key}", "Prefer": "count=exact", "Range": "0-0"}
    with httpx.Client(base_url=cfg.url + "/rest/v1", headers=headers, timeout=20) as client:
        for schema, tables in TABLES.items():
            print(f"\n=== schema {schema} ===")
            for table in tables:
                h = {"Accept-Profile": schema}
                try:
                    r = client.get(f"/{table}", params={"select": "*", "limit": "1"}, headers=h)
                except httpx.HTTPError as e:
                    print(f"{table}: network error ({type(e).__name__})")
                    continue
                if r.status_code >= 400:
                    code = ""
                    try:
                        code = r.json().get("code", "")
                    except ValueError:
                        pass
                    print(f"{table}: not reachable (HTTP {r.status_code} {code})")
                    continue
                total = r.headers.get("content-range", "?/?").split("/")[-1]
                rows = r.json()
                cols = {k: type(v).__name__ for k, v in rows[0].items()} if rows else {}
                print(f"{table}: {total} rows")
                for name, kind in cols.items():
                    print(f"    {name}: {kind}")
        if "--values" in sys.argv:
            _values(client)
    return 0


# Low-cardinality columns only (status words, sources). IDs are shown as their SHAPE (digits -> 9).
VALUE_COLUMNS = [
    ("orders", "store"), ("orders", "stage"), ("orders", "fulfillment_status"), ("orders", "financial_status"),
    ("sync_runs", "kind"), ("sync_runs", "status"),
]
SHAPE_COLUMNS = [("orders", "shipped_at")]


def _values(client: httpx.Client) -> None:
    import re
    from collections import Counter
    for table, col in VALUE_COLUMNS + SHAPE_COLUMNS:
        seen: Counter[str] = Counter()
        offset = 0
        while True:
            r = client.get(f"/{table}", params={"select": col, "limit": "1000", "offset": str(offset)},
                           headers={"Accept-Profile": "public", "Range": f"{offset}-{offset + 999}"})
            if r.status_code >= 400:
                break
            rows = r.json()
            for row in rows:
                v = row.get(col)
                v = "(null)" if v is None else str(v)
                if (table, col) in SHAPE_COLUMNS:
                    v = re.sub(r"\d", "9", v)
                seen[v] += 1
            if len(rows) < 1000:
                break
            offset += 1000
        print(f"\n{table}.{col}:")
        for v, n in seen.most_common(25):
            print(f"    {n:6d}  {v!r}")


if __name__ == "__main__":
    raise SystemExit(main())
