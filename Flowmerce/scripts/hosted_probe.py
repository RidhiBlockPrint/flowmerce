"""Probe a running hosted Flowmerce (CI uses it against the container): the gate must hold and the API must answer.

    python scripts/hosted_probe.py http://127.0.0.1:10000 <password> [user]
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request


def get(url: str, auth: tuple[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url)  # noqa: S310 - fixed http(s) URL given by the caller
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> None:
    base, password = sys.argv[1].rstrip("/"), sys.argv[2]
    user = sys.argv[3] if len(sys.argv) > 3 else "admin"
    good, bad = (user, password), (user, password + "x")
    checks = [
        ("health check is open", get(f"{base}/healthz")[0] == 200),
        ("home page needs sign-in", get(f"{base}/")[0] == 401),
        ("API needs sign-in", get(f"{base}/api/home")[0] == 401),
        ("wrong password is refused", get(f"{base}/", bad)[0] == 401),
        ("home page opens after sign-in", get(f"{base}/", good)[0] == 200),
        ("shipping page opens after sign-in", get(f"{base}/shipping", good)[0] == 200),
    ]
    status, body = get(f"{base}/api/home", good)
    try:
        api_ok = status == 200 and isinstance(json.loads(body), dict)
    except ValueError:
        api_ok = False
    checks.append((f"API answers after sign-in (HTTP {status})", api_ok))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
