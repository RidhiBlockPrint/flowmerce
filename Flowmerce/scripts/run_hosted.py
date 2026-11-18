"""Hosted launcher (container entry point): run Flowmerce on a cloud host behind the sign-in gate.

Used only by the Dockerfile; on your own computer keep using scripts/run_flowmerce.py.

    1. Refuses to start without FLOWMERCE_LOGIN_PASSWORD (16+ characters): the app has no other sign-in.
    2. Google key: GOOGLE_SERVICE_ACCOUNT_JSON (the key file's contents) is written to secrets/google-key.json;
       otherwise a Render secret file /etc/secrets/google-key.json is used when present.
    3. SEO database (data/blog-ops.sqlite): when LITESTREAM_BUCKET is set, it is restored from Supabase Storage
       (S3) before start and then replicated continuously, so restarts and redeploys keep the data.
       Without it the database lives only on the container's temporary disk (a warning is printed).
    4. Starts the API on 127.0.0.1:18787 (inside the container only, proxy headers ignored so every call is
       "local" to it) and the Next.js frontend on 0.0.0.0:$PORT, which is the only public entry and holds the gate.
    If any process stops, the others are stopped too and the container exits, so the host restarts it.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess  # noqa: S404 - starts our own services with fixed argument lists
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("FLOWMERCE_ROOT") or Path(__file__).resolve().parent.parent)
FRONTEND = ROOT / "frontend"
DB_FILE = ROOT / "data" / "blog-ops.sqlite"
LITESTREAM_CONFIG = ROOT / "deploy" / "litestream.yml"
API_PORT = 18787


def log(message: str) -> None:
    print(f"[flowmerce-hosted] {message}", flush=True)


def fail(message: str) -> None:
    log(f"cannot start: {message}")
    sys.exit(1)


def check_password() -> None:
    password = os.environ.get("FLOWMERCE_LOGIN_PASSWORD", "")
    if len(password) < 16:
        fail("set FLOWMERCE_LOGIN_PASSWORD to at least 16 characters (Render generates one for you).")
    os.environ["FLOWMERCE_HOSTED"] = "1"


def setup_google_key() -> None:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    target = ROOT / "secrets" / "google-key.json"
    if raw:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(raw, encoding="utf-8")
        target.chmod(0o600)
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = str(target)
        log("Google key: from GOOGLE_SERVICE_ACCOUNT_JSON")
        return
    configured = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if configured and (ROOT / configured).exists():
        return
    render_file = Path("/etc/secrets/google-key.json")
    if render_file.exists():
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = str(render_file)
        log("Google key: from the secret file /etc/secrets/google-key.json")
    elif configured:
        log("Google key: not found; Search Console and GA4 stay unconfigured.")


def litestream_enabled() -> bool:
    if not os.environ.get("LITESTREAM_BUCKET"):
        log("WARNING: LITESTREAM_BUCKET is not set. SEO data lives on temporary disk and is lost on restart.")
        return False
    missing = [k for k in ("LITESTREAM_ENDPOINT", "LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY")
               if not os.environ.get(k)]
    if missing:
        fail(f"LITESTREAM_BUCKET is set but {', '.join(missing)} is missing.")
    os.environ.setdefault("LITESTREAM_REGION", "us-east-1")
    os.environ.setdefault("LITESTREAM_PATH", "flowmerce/blog-ops")
    if not shutil.which("litestream"):
        fail("the litestream program is not installed in this image.")
    return True


def restore_database() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    log("restoring the SEO database from storage (if a copy exists) ...")
    subprocess.run(  # noqa: S603
        ["litestream", "restore", "-config", str(LITESTREAM_CONFIG),
         "-if-db-not-exists", "-if-replica-exists", str(DB_FILE)],
        check=True,
    )
    if DB_FILE.exists():
        log("database ready")
        return
    seed_database()


def seed_database() -> None:
    """First boot only: load the one-time copy uploaded by scripts/upload_seo_seed.py, if there is one.

    It is read from the private Supabase Storage bucket with the service-role key the app already has.
    Afterwards Litestream keeps the live copy, and this seed is never read again (the database then exists).
    """
    seed = os.environ.get("FLOWMERCE_SEED_OBJECT", "seed/blog-ops.sqlite")
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = os.environ.get("LITESTREAM_BUCKET", "")
    if not (url and key and bucket):
        # Never start empty just because keys are missing: an empty database would be backed up and then
        # restored on every later start, hiding the uploaded copy for good. Stop; the host retries once keys exist.
        fail("no stored database yet, and SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set, so the uploaded "
             "copy (scripts/upload_seo_seed.py) cannot be checked. Add your .env values in Render, then deploy again.")
    import httpx

    try:
        resp = httpx.get(f"{url}/storage/v1/object/{bucket}/{seed}",
                         headers={"Authorization": f"Bearer {key}", "apikey": key}, timeout=120)
    except httpx.HTTPError as e:
        fail(f"could not reach Supabase Storage to load the uploaded copy ({type(e).__name__}); will retry.")
    if resp.status_code in (400, 404):
        log(f"no uploaded copy at {bucket}/{seed}; the app will create a fresh database")
        return
    if resp.status_code != 200:
        fail(f"loading the uploaded copy from {bucket}/{seed} failed (HTTP {resp.status_code}); will retry.")
    tmp = DB_FILE.with_suffix(".seed")
    tmp.write_bytes(resp.content)
    tmp.replace(DB_FILE)
    log(f"loaded the seed copy of the SEO database ({len(resp.content) // 1024} KB) from {bucket}/{seed}")


def wait_for_port(port: int, proc: subprocess.Popen[bytes], seconds: int = 90) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            fail(f"the API exited during start-up (code {proc.returncode}).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    fail(f"the API did not start listening on port {port} within {seconds} s.")


def main() -> None:
    check_password()
    setup_google_key()
    use_litestream = litestream_enabled()
    if use_litestream:
        restore_database()

    procs: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop_all(*_: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        log("stopping ...")
        # Frontend first, then the API, then Litestream last so it can copy the final writes.
        for proc in reversed(procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()

    signal.signal(signal.SIGTERM, stop_all)
    signal.signal(signal.SIGINT, stop_all)

    api = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "flowmerce.modules.seo.main:app",
         "--host", "127.0.0.1", "--port", str(API_PORT), "--no-proxy-headers"],
        cwd=ROOT,
    )
    procs.append(api)
    wait_for_port(API_PORT, api)
    log(f"API is up on 127.0.0.1:{API_PORT}")

    if use_litestream:
        # Started once the API has created the database; listed first so it is stopped last (final copy).
        procs.insert(0, subprocess.Popen(  # noqa: S603
            ["litestream", "replicate", "-config", str(LITESTREAM_CONFIG)]))
        log("continuous backup of the SEO database is running")

    web_port = os.environ.get("PORT", "10000")
    procs.append(subprocess.Popen(  # noqa: S603
        ["node", "node_modules/next/dist/bin/next", "start", "-H", "0.0.0.0", "-p", web_port],  # noqa: S104
        cwd=FRONTEND,
    ))
    log(f"frontend is up on port {web_port} (sign-in required)")

    while not stopping:
        for proc in procs:
            if proc.poll() is not None:
                log(f"a service exited (code {proc.returncode}); shutting down so the host restarts the app")
                stop_all()
                break
        time.sleep(1)
    sys.exit(1 if any(p.returncode not in (0, -signal.SIGTERM, None) for p in procs) else 0)


if __name__ == "__main__":
    main()
