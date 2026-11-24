"""Who is calling, and whether the call may be answered at all.

Local operator mode (your own computer): there is no sign-in. A request from a loopback address acts as
the local administrator record (`local_operator`), and a request from anywhere else is refused before any
page or API is served (the loopback check lives in app.py's guard). The one exception is the secret-protected
workflow webhook, which carries its own authorization.

Hosted mode (config.hosted, the cloud copy): each person signs in with their own account. The Next.js
frontend is the only public entry; it forwards the sign-in form to POST /api/auth/login (marked with the
internal secret) and keeps the session token in the `fm_session` cookie. Every other /api call must carry a
live session: app.py's guard loads the person with `load_user` and answers 401 without one.
See docs/decisions/0011-hosted-team-sign-in.md.

Mutating requests must still carry the X-Requested-With header, which a cross-site form cannot set — that
is the CSRF guard (also in app.py)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

from .config import config
from .db import get, now, run
from .permissions import can
from .util import HttpError, sha256

COOKIE = "bo_session"
# Hosted mode: set by the frontend gate as `v2.<expiry>.<session token>.<signature>`. The frontend checks the
# signature; here only the token matters, because it is looked up in the sessions table.
HOSTED_COOKIE = "fm_session"
LONG_SESSION_SECONDS = 30 * 24 * 3600


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=16384, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
    return f"scrypt$16384${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    parts = str(stored).split("$")
    if len(parts) != 4 or parts[0] != "scrypt":
        return False
    salt, expected = base64.b64decode(parts[2]), base64.b64decode(parts[3])
    actual = hashlib.scrypt(pw.encode(), salt=salt, n=int(parts[1]), r=8, p=1, dklen=len(expected), maxmem=64 * 1024 * 1024)
    return hmac.compare_digest(expected, actual)


def validate_password(pw: object) -> str | None:
    if not isinstance(pw, str) or len(pw) < 12:
        return "Password must be at least 12 characters."
    if len(pw) > 200:
        return "Password must be 200 characters or fewer."
    return None


def issue_session(user_id: int, seconds: int) -> str:
    """Create a session record and return its token. Only the token's SHA-256 is stored."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    run("INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        sha256(token), user_id, now(), expires.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    run("DELETE FROM sessions WHERE expires_at < ?", now())
    return token


def create_session(response: Response, user_id: int) -> None:
    token = issue_session(user_id, config.session_hours * 3600)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=config.cookie_secure,
                        path="/", max_age=config.session_hours * 3600)


def session_token(request: Request) -> str | None:
    """The session token this request carries, or None. Hosted mode reads it out of the frontend's cookie."""
    if not config.hosted:
        return request.cookies.get(COOKIE) or None
    parts = (request.cookies.get(HOSTED_COOKIE) or "").split(".")
    return parts[2] if len(parts) == 4 and parts[0] == "v2" and parts[2] else None


def end_session(request: Request) -> bool:
    """Delete this request's session record. True when one was deleted."""
    token = session_token(request)
    return bool(token) and run("DELETE FROM sessions WHERE id = ?", sha256(token)).changes > 0


def destroy_session(request: Request, response: Response) -> None:
    end_session(request)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=config.cookie_secure)


def load_user(request: Request) -> dict | None:
    token = session_token(request)
    if not token:
        return None
    row = get(
        """SELECT u.id, u.email, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.id = ? AND s.expires_at > ? AND u.active = 1""",
        sha256(token), now(),
    )
    return row


def is_internal_call(request: Request) -> bool:
    """True only for a call the hosted frontend itself made: it carries the secret generated at start-up.

    Fails closed when no secret is configured."""
    secret = config.internal_secret
    given = request.headers.get("X-Flowmerce-Internal") or ""
    return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())


def is_owner_key(username: str, password: str) -> bool:
    """The owner key: FLOWMERCE_LOGIN_USER + FLOWMERCE_LOGIN_PASSWORD sign in as the first administrator."""
    if len(config.login_password) < 16:      # run_hosted.py refuses to start with less; never accept a weak key
        return False
    same_user = hmac.compare_digest(username.strip().lower().encode(), config.login_user.lower().encode())
    same_password = hmac.compare_digest(password.encode(), config.login_password.encode())
    return same_user & same_password


_dummy_hash = ""


def check_credentials(email: str, password: str) -> dict | None:
    """The active user with this email and password, or None.

    An unknown email costs the same hashing work as a wrong password, so the two cannot be told apart by timing."""
    global _dummy_hash
    row = get("SELECT id, email, name, role, password_hash FROM users WHERE email = ? AND active = 1", email.strip().lower())
    if not row and not _dummy_hash:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    if not verify_password(password, row["password_hash"] if row else _dummy_hash) or not row:
        return None
    return {k: row[k] for k in ("id", "email", "name", "role")}


# Stored in users.password_hash for a record created by local operator mode. It has no password behind it:
# verify_password() only accepts four "$"-separated scrypt parts, so this value can never match anything.
LOCAL_OPERATOR_PASSWORD_HASH = "disabled$local-operator"


def is_loopback_client(request: Request) -> bool:
    """True only when the connecting address is a loopback address (127.0.0.0/8 or ::1).

    Fails closed: a missing or unparsable address is not local. Forwarded-IP headers (X-Forwarded-For and
    friends) are never read here; only the address of the connection the server accepted is used. (uvicorn
    itself applies X-Forwarded-For only when the connection comes from 127.0.0.1, so a remote client cannot
    use it to look local.)
    """
    client = request.client
    if client is None or not client.host:
        return False
    try:
        ip = ipaddress.ip_address(client.host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def local_operator() -> dict | None:
    """The administrator record every local request acts as (for permissions and audit attribution).

    The first active administrator by id; None if the database has none (the server creates one at startup).
    """
    return get("SELECT id, email, name, role FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1")


def require_user(request: Request) -> dict:
    u = getattr(request.state, "user", None)
    if not u:
        raise HttpError(503, "No administrator record exists yet. Restart the server so it can create one.", "no_operator")
    return u


def require_perm(request: Request, perm: str) -> dict:
    u = require_user(request)
    if not can(u["role"], perm):
        raise HttpError(403, "Your role does not allow this action.", "forbidden", {"perm": perm})
    return u


# Sign-in throttling, kept in this process only: too many failures for one key pause that key for 15 minutes.
# Keys used by /api/auth/login: "<email>|<address>" (8), "<email>" (20) and "<address>" (40).
THROTTLE_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}


def login_throttle(key: str, limit: int = 8) -> None:
    cutoff = time.time() - THROTTLE_SECONDS
    lst = [t for t in _failures.get(key, []) if t > cutoff]
    if lst:
        _failures[key] = lst
    else:
        _failures.pop(key, None)
    if len(lst) >= limit:
        raise HttpError(429, "Too many failed sign-in attempts. Try again in 15 minutes.", "throttled")


def login_failed(key: str) -> None:
    if len(_failures) > 5000:        # bounded: under a flood, forget rather than grow
        _failures.clear()
    _failures.setdefault(key, []).append(time.time())


def login_succeeded(key: str) -> None:
    _failures.pop(key, None)
