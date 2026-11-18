"""One-time copy of this computer's SEO database to the hosted copy (Supabase Storage).

    .venv\\Scripts\\python.exe scripts\\upload_seo_seed.py --bucket flowmerce-data

Makes a consistent snapshot of data/blog-ops.sqlite (SQLite's online backup, safe while Flowmerce runs) and
uploads it to <bucket>/seed/blog-ops.sqlite with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from your .env.
The hosted app loads it on its first start only (when it has no database of its own yet).
The bucket must be PRIVATE; this script refuses to upload into a public bucket. Keys are never printed.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB_FILE = ROOT / "data" / "blog-ops.sqlite"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", required=True, help="private Supabase Storage bucket (same as LITESTREAM_BUCKET)")
    parser.add_argument("--object", default="seed/blog-ops.sqlite", help="path inside the bucket")
    args = parser.parse_args()

    env = read_env()
    url, key = env.get("SUPABASE_URL", "").rstrip("/"), env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and key):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    if not DB_FILE.exists():
        sys.exit(f"no database at {DB_FILE}")
    headers = {"Authorization": f"Bearer {key}", "apikey": key}

    info = httpx.get(f"{url}/storage/v1/bucket/{args.bucket}", headers=headers, timeout=30)
    if info.status_code != 200:
        sys.exit(f"bucket '{args.bucket}' not found (HTTP {info.status_code}). Create it as a private bucket first.")
    if info.json().get("public"):
        sys.exit(f"bucket '{args.bucket}' is PUBLIC. Make it private before uploading business data.")

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "blog-ops.sqlite"
        src, dst = sqlite3.connect(DB_FILE), sqlite3.connect(snapshot)
        with dst:
            src.backup(dst)
        src.close()
        dst.execute("PRAGMA journal_mode = DELETE")
        dst.close()
        data = snapshot.read_bytes()

    resp = httpx.post(f"{url}/storage/v1/object/{args.bucket}/{args.object}", content=data, timeout=300,
                      headers={**headers, "Content-Type": "application/octet-stream", "x-upsert": "true"})
    if resp.status_code not in (200, 201):
        sys.exit(f"upload failed (HTTP {resp.status_code}): {resp.text[:300]}")
    print(f"Uploaded {len(data) // 1024} KB to {args.bucket}/{args.object}. The hosted app loads it on first start.")


if __name__ == "__main__":
    main()
