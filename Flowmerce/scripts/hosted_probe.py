"""Probe a running hosted Flowmerce (CI uses it against the container): the sign-in gate must hold, the app must
work after signing in through the /login form, and each person must act under their own account and role.

    python scripts/hosted_probe.py http://127.0.0.1:10000 <owner key password> [user] [--gate-only]

The team checks add a person ("Probe reviewer") and deactivate them again. Pass --gate-only to leave them out,
for example against a live workspace.
"""

from __future__ import annotations

import http.cookiejar
import json
import secrets
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


def call(op: urllib.request.OpenerDirector, method: str, url: str, body: dict[str, object] | None = None,
         headers: dict[str, str] | None = None) -> tuple[int, dict[str, object]]:
    """A JSON API call the way the app's own pages make it (with the X-Requested-With header)."""
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,  # noqa: S310
                                 headers={"X-Requested-With": "blog-ops", "Content-Type": "application/json", **(headers or {})})
    try:
        with op.open(req, timeout=30) as resp:
            status, text = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    return status, data if isinstance(data, dict) else {}


PROBE_EMAIL = "probe-reviewer@flowmerce.invalid"


def team_checks(base: str, owner: urllib.request.OpenerDirector) -> list[tuple[str, bool]]:
    """Each person signs in as themselves, their role is enforced by the API, and deactivating signs them out."""
    checks: list[tuple[str, bool]] = []
    status, me = call(owner, "GET", f"{base}/api/auth/me")
    who = me.get("user") if isinstance(me.get("user"), dict) else {}
    checks.append(("the owner key signs in as an administrator",
                   status == 200 and who.get("role") == "admin" and me.get("localOperator") is False))

    probe_password = secrets.token_urlsafe(18)
    status, made = call(owner, "POST", f"{base}/api/users",
                        {"email": PROBE_EMAIL, "name": "Probe reviewer", "role": "reviewer", "password": probe_password})
    uid = made.get("id")
    if status == 409:   # left from an earlier run: reuse the record
        _, listing = call(owner, "GET", f"{base}/api/users")
        rows = listing.get("users") if isinstance(listing.get("users"), list) else []
        uid = next((u["id"] for u in rows if u.get("email") == PROBE_EMAIL), None)
        status, _ = call(owner, "PATCH", f"{base}/api/users/{uid}", {"active": True, "role": "reviewer", "password": probe_password})
    checks.append((f"an administrator can add a person (HTTP {status})", status == 200 and uid is not None))

    reviewer = opener(http.cookiejar.CookieJar())
    fetch(reviewer, f"{base}/auth/login", {"username": PROBE_EMAIL, "password": probe_password, "next": "/"})
    status, me = call(reviewer, "GET", f"{base}/api/auth/me")
    who = me.get("user") if isinstance(me.get("user"), dict) else {}
    checks.append(("that person signs in as themselves, with their own role",
                   status == 200 and who.get("email") == PROBE_EMAIL and who.get("role") == "reviewer"))
    checks.append(("they can open the app", call(reviewer, "GET", f"{base}/api/home")[0] == 200))
    status, refused = call(reviewer, "POST", f"{base}/api/users",
                           {"email": "x@flowmerce.invalid", "name": "x", "role": "admin", "password": secrets.token_urlsafe(18)})
    checks.append(("their role is enforced: a reviewer cannot manage the team", status == 403 and refused.get("code") == "forbidden"))
    status, _ = call(reviewer, "POST", f"{base}/api/auth/login", {"username": PROBE_EMAIL, "password": probe_password})
    checks.append(("a browser cannot call the sign-in API directly", status == 403))
    status, _ = call(reviewer, "GET", f"{base}/api/home", headers={"X-Flowmerce-Internal": "guess"})
    checks.append(("a browser cannot pose as the server", status == 403))

    status, _ = call(owner, "PATCH", f"{base}/api/users/{uid}", {"active": False})
    checks.append(("an administrator can deactivate them", status == 200))
    checks.append(("a deactivated person is signed out at once", call(reviewer, "GET", f"{base}/api/auth/me")[0] == 401))
    status, location, _ = fetch(opener(follow=False), f"{base}/auth/login",
                                {"username": PROBE_EMAIL, "password": probe_password, "next": "/"})
    checks.append(("and cannot sign in again", status == 303 and "error=invalid" in location))
    checks.append(("the administrator is still signed in", call(owner, "GET", f"{base}/api/auth/me")[0] == 200))
    return checks


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gate_only = "--gate-only" in sys.argv
    base, password = args[0].rstrip("/"), args[1]
    user = args[2] if len(args) > 2 else "admin"
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

    forged = opener(follow=False)
    forged.addheaders = [("Cookie", "fm_session=v2.4102444800.made-up-session-token-0123456789.made-up-signature")]
    checks.append(("a made-up session cookie is refused", fetch(forged, f"{base}/api/home")[0] == 401))
    if not gate_only:
        checks.extend(team_checks(base, session))

    status, final, _ = fetch(session, f"{base}/auth/logout")
    checks.append(("sign out returns to the sign-in page", "/login" in final))
    checks.append(("API is refused after sign out", fetch(session, f"{base}/api/home")[0] == 401))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
