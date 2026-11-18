"""Probe a running hosted Flowmerce (CI uses it against the container): the sign-in gate must hold and the app must
work after signing in through the /login form.

    python scripts/hosted_probe.py http://127.0.0.1:10000 <password> [user]
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def opener(jar: http.cookiejar.CookieJar | None = None, follow: bool = True) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPCookieProcessor(jar or http.cookiejar.CookieJar())]
    if not follow:
        handlers.append(NoRedirect())
    return urllib.request.build_opener(*handlers)


def fetch(op: urllib.request.OpenerDirector, url: str, form: dict[str, str] | None = None) -> tuple[int, str, str]:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    try:
        with op.open(urllib.request.Request(url, data=data), timeout=30) as resp:  # noqa: S310 - caller's URL
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location") or url, e.read().decode("utf-8", "replace")


def main() -> None:
    base, password = sys.argv[1].rstrip("/"), sys.argv[2]
    user = sys.argv[3] if len(sys.argv) > 3 else "admin"
    raw = opener(follow=False)
    checks: list[tuple[str, bool]] = []

    checks.append(("health check is open", fetch(raw, f"{base}/healthz")[0] == 200))
    status, location, _ = fetch(raw, f"{base}/shipping")
    checks.append(("a page without sign-in goes to /login", status in (302, 307) and "/login" in location))
    checks.append(("API without sign-in is refused", fetch(raw, f"{base}/api/home")[0] == 401))
    status, _, body = fetch(opener(), f"{base}/login")
    # The form itself renders in the browser; the server HTML carries the page shell and the art panel.
    checks.append(("sign-in page renders", status == 200 and "login-art" in body))

    status, location, _ = fetch(raw, f"{base}/auth/login", {"username": user, "password": password + "x", "next": "/"})
    checks.append(("wrong password is refused", status == 303 and "error=invalid" in location))

    req = urllib.request.Request(f"{base}/auth/login", data=urllib.parse.urlencode(
        {"username": user, "password": password, "next": "/"}).encode())
    try:
        raw.open(req, timeout=30)
        cookies: list[str] = []
    except urllib.error.HTTPError as e:
        cookies = e.headers.get_all("Set-Cookie") or []
    checks.append(("session cookie is HttpOnly",
                   any(c.startswith("fm_session=") and "httponly" in c.lower() for c in cookies)))

    jar = http.cookiejar.CookieJar()
    session = opener(jar)
    status, final, _ = fetch(session, f"{base}/auth/login",
                             {"username": user, "password": password, "next": "/shipping", "remember": "on"})
    checks.append((f"right password signs in and returns to the page (ended at {final})",
                   status == 200 and final.endswith("/shipping")))
    checks.append(("home page opens after sign-in", fetch(session, f"{base}/")[0] == 200))
    status, _, body = fetch(session, f"{base}/api/home")
    try:
        api_ok = status == 200 and isinstance(json.loads(body), dict)
    except ValueError:
        api_ok = False
    checks.append((f"API answers after sign-in (HTTP {status})", api_ok))

    status, final, _ = fetch(session, f"{base}/auth/logout")
    checks.append(("sign out returns to the sign-in page", "/login" in final))
    checks.append(("API is refused after sign out", fetch(session, f"{base}/api/home")[0] == 401))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
