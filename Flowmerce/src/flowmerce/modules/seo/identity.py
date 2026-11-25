"""Sign-in through Supabase Auth, and each person's access as the database sees it.

Used on the hosted copy when FLOWMERCE_SUPABASE_URL and FLOWMERCE_SUPABASE_KEY are set
(docs/decisions/0012-supabase-sign-in.md). The people list is `flowmerce.member` in the ERP's Supabase project;
Flowmerce keeps no list of its own.

  * A password is checked by Supabase Auth. Flowmerce never stores or compares it.
  * Supabase answers with the person's tokens. They stay on this server, encrypted, in `identity_sessions`
    (one row per Flowmerce session); they are never sent to the browser.
  * What the person may open comes from the view `flowmerce.my_access`, read with their own token, so the
    database's rules answer for that person. No row there means no access (not a member, or switched off).
  * The access is read again at most once a minute, and the token is renewed before it runs out, so switching
    someone off in Supabase takes effect within a minute here.

Flowmerce has only the publishable key, which on its own can read nothing: every call below that returns data
carries a person's token.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import config
from .db import get, now, run

# Supabase role -> the Flowmerce role whose permissions apply (permissions.py). Supabase's own label is shown.
ROLE_MAP = {"owner": "admin", "admin": "admin", "manager": "seo_manager", "editor": "seo_manager", "viewer": "viewer"}
ROLE_LABELS = {"owner": "Owner", "admin": "Admin", "manager": "Manager", "editor": "Editor", "viewer": "Viewer"}
ROLE_NOTES = {
    "owner": "Everything in Flowmerce, including settings and approving publishing.",
    "admin": "Everything in Flowmerce, including settings and approving publishing.",
    "manager": "Writes and edits content, runs automation and requests publishing.",
    "editor": "Writes and edits content, runs automation and requests publishing.",
    "viewer": "Can look at everything they are given, and change nothing.",
}
# Stored in users.role, which only allows the three local roles. Permissions never come from that column here.
_LOCAL_ROLE = {"admin": "admin", "seo_manager": "seo_manager", "viewer": "reviewer"}
# users.password_hash for a record that mirrors a Supabase person: no password behind it, nothing can match it.
MIRROR_PASSWORD_HASH = "disabled$supabase"
# Store codes in Supabase -> the brand ids the SEO module uses.
STORE_BRANDS = {"RBP": "ridhi", "CPC": "cpc"}

RECHECK_SECONDS = 60          # how often a session's access is read again
RENEW_BEFORE_SECONDS = 120    # renew the token this long before it runs out
OUTAGE_GRACE_SECONDS = 15 * 60  # Supabase unreachable: keep the last known access this long, then sign out


class IdentityError(Exception):
    """code: invalid (wrong email or password) | throttled | expired (session gone) | weak_password |
    same_password | unavailable (Supabase did not answer as expected)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class Tokens:
    access: str
    refresh: str
    expires_at: float
    user_id: str
    email: str


def enabled() -> bool:
    return bool(config.hosted and config.identity_url and config.identity_key)


# ---------------- HTTP ----------------

_http: httpx.Client | None = None
_http_lock = threading.Lock()


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: answer the Supabase calls from a stand-in. None goes back to the real network."""
    global _http
    with _http_lock:
        if _http is not None:
            _http.close()
        _http = httpx.Client(timeout=15, transport=transport) if transport is not None else None


def _client() -> httpx.Client:
    global _http
    with _http_lock:
        if _http is None:
            _http = httpx.Client(timeout=15)
        return _http


def _send(method: str, path: str, *, token: str | None = None, schema: bool = False, **kw: Any) -> httpx.Response:
    headers = {"apikey": config.identity_key, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if schema:
        headers["Accept-Profile"] = config.identity_schema
        headers["Content-Profile"] = config.identity_schema
    try:
        return _client().request(method, config.identity_url + path, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise IdentityError("unavailable", f"Supabase did not answer ({type(e).__name__}).") from e


def _error_code(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return ""
    return str(body.get("error_code") or body.get("error") or body.get("code") or "") if isinstance(body, dict) else ""


def _tokens(r: httpx.Response) -> Tokens:
    try:
        body = r.json()
        user = body["user"]
        return Tokens(access=body["access_token"], refresh=body["refresh_token"],
                      expires_at=time.time() + float(body.get("expires_in") or 3600),
                      user_id=str(user["id"]), email=str(user.get("email") or "").lower())
    except (ValueError, KeyError, TypeError) as e:
        raise IdentityError("unavailable", "Supabase sent an answer Flowmerce could not read.") from e


# ---------------- Supabase Auth ----------------

def sign_in(email: str, password: str) -> Tokens:
    r = _send("POST", "/auth/v1/token", params={"grant_type": "password"}, json={"email": email, "password": password})
    if r.status_code == 200:
        return _tokens(r)
    if r.status_code == 429:
        raise IdentityError("throttled")
    if r.status_code in (400, 401, 422):
        # invalid_credentials, email_not_confirmed, user_banned, validation_failed: all "cannot sign in" to the person
        raise IdentityError("invalid", _error_code(r))
    raise IdentityError("unavailable", f"Supabase sign-in answered {r.status_code}.")


def renew(refresh_token: str) -> Tokens:
    r = _send("POST", "/auth/v1/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token})
    if r.status_code == 200:
        return _tokens(r)
    if r.status_code in (400, 401, 403):
        raise IdentityError("expired", _error_code(r))
    raise IdentityError("unavailable", f"Supabase token renewal answered {r.status_code}.")


def sign_out(access_token: str) -> None:
    """End this one Supabase session. Best effort: the Flowmerce session is removed either way."""
    try:
        _send("POST", "/auth/v1/logout", token=access_token, params={"scope": "local"})
    except IdentityError:
        pass


def set_password(access_token: str, new_password: str) -> None:
    r = _send("PUT", "/auth/v1/user", token=access_token, json={"password": new_password})
    if r.status_code == 200:
        return
    code = _error_code(r)
    if code in ("weak_password", "same_password"):
        raise IdentityError(code)
    if r.status_code in (401, 403):
        raise IdentityError("expired", code)
    raise IdentityError("unavailable", f"Supabase password change answered {r.status_code} {code}".strip())


# ---------------- access (what the database says this person may open) ----------------

def read_access(access_token: str) -> dict[str, Any] | None:
    """The person's access from flowmerce.my_access, or None when they have none (not a member, or switched off).

    The view has one row per store the person may see. With more than one workspace the first is used."""
    r = _send("GET", "/rest/v1/my_access", token=access_token, schema=True, params={"select": "*"})
    if r.status_code == 401:
        raise IdentityError("expired", _error_code(r))
    if r.status_code != 200:
        raise IdentityError("unavailable", f"Supabase my_access answered {r.status_code}.")
    try:
        rows = [x for x in r.json() if isinstance(x, dict)]
    except ValueError as e:
        raise IdentityError("unavailable", "Supabase sent an answer Flowmerce could not read.") from e
    if not rows:
        return None
    first = rows[0]
    rows = [x for x in rows if x.get("workspace_id") == first.get("workspace_id")]
    role = str(first.get("role") or "")
    if role not in ROLE_MAP:
        return None            # a role this version does not know: no access rather than a guess
    return {
        "supabase_role": role,
        "role": ROLE_MAP[role],
        "workspace_id": str(first.get("workspace_id") or ""),
        "workspace": str(first.get("workspace_name") or ""),
        "sections": sorted({str(s) for s in (first.get("sections") or [])}),
        "stores": sorted({str(x.get("store")) for x in rows if x.get("store")}),
        "can_see_costs": bool(first.get("can_see_costs")) or role in ("owner", "admin"),
    }


def read_display_name(access_token: str, user_id: str, email: str) -> str:
    """The person's name from flowmerce.member; the part of their email before @ when that cannot be read."""
    fallback = email.split("@")[0] or "Member"
    try:
        r = _send("GET", "/rest/v1/member", token=access_token, schema=True,
                  params={"select": "display_name", "user_id": f"eq.{user_id}", "limit": "1"})
        rows = r.json() if r.status_code == 200 else []
        name = str(rows[0].get("display_name") or "").strip() if rows and isinstance(rows[0], dict) else ""
        return name[:120] or fallback
    except (IdentityError, ValueError):
        return fallback


def list_members(access_token: str) -> list[dict[str, Any]]:
    """Everyone in the workspace, as this person is allowed to see them (read-only: people are managed in Supabase)."""
    r = _send("GET", "/rest/v1/member", token=access_token, schema=True, params={
        "select": "user_id,display_name,role,is_active,all_stores,sections,can_see_costs,created_at",
        "order": "is_active.desc,display_name.asc"})
    if r.status_code != 200:
        raise IdentityError("unavailable", f"Supabase member list answered {r.status_code}.")
    return [x for x in r.json() if isinstance(x, dict)]


# ---------------- tokens at rest ----------------

def _fernet() -> Fernet:
    # The owner key (16+ characters, only in the host's settings) is the secret. Changing it makes every stored
    # token unreadable, which signs everyone out: the same effect it has on the session cookies.
    digest = hashlib.sha256(b"flowmerce-identity-tokens-v1\x00" + config.login_password.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _seal(t: Tokens) -> str:
    return _fernet().encrypt(json.dumps({"a": t.access, "r": t.refresh, "e": t.expires_at}).encode()).decode()


def _unseal(sealed: str, user_id: str, email: str) -> Tokens | None:
    try:
        d = json.loads(_fernet().decrypt(sealed.encode()))
        return Tokens(access=d["a"], refresh=d["r"], expires_at=float(d["e"]), user_id=user_id, email=email)
    except (InvalidToken, ValueError, KeyError, TypeError):
        return None


# ---------------- sessions ----------------

def ensure_tables() -> None:
    """One row per Flowmerce session that came from a Supabase sign-in. Created here, outside the numbered
    migrations, so it cannot collide with migration numbers on other branches; safe to run at every start."""
    run("""CREATE TABLE IF NOT EXISTS identity_sessions (
             session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
             supabase_user_id TEXT NOT NULL,
             access_json TEXT NOT NULL,
             sealed_tokens TEXT NOT NULL,
             checked_at REAL NOT NULL)""")


def mirror_user(email: str, name: str, access: dict[str, Any]) -> dict[str, Any]:
    """The local record articles, tasks and the audit log point at for this person. It mirrors Supabase: it is
    written at sign-in, holds no password, and its role column is never used for permissions."""
    local_role = _LOCAL_ROLE[access["role"]]
    row = get("SELECT id FROM users WHERE email = ?", email)
    if row:
        run("UPDATE users SET name = ?, role = ?, active = 1, password_hash = ?, last_login_at = ? WHERE id = ?",
            name, local_role, MIRROR_PASSWORD_HASH, now(), row["id"])
        uid = row["id"]
    else:
        uid = run("INSERT INTO users (email, name, role, password_hash, created_at, last_login_at) VALUES (?,?,?,?,?,?)",
                  email, name, local_role, MIRROR_PASSWORD_HASH, now(), now()).last_id
    return {"id": uid, "email": email, "name": name}


def save_session(session_id: str, tokens: Tokens, access: dict[str, Any]) -> None:
    run("INSERT INTO identity_sessions (session_id, supabase_user_id, access_json, sealed_tokens, checked_at) VALUES (?,?,?,?,?)",
        session_id, tokens.user_id, json.dumps(access), _seal(tokens), time.time())


def _person(row: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": access["role"],
            "role_label": ROLE_LABELS.get(access["supabase_role"], access["supabase_role"]), "access": access}


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: str) -> threading.Lock:
    with _locks_guard:
        if len(_locks) > 2000:
            _locks.clear()
        return _locks.setdefault(session_id, threading.Lock())


_ROW = """SELECT u.id, u.email, u.name, i.supabase_user_id, i.access_json, i.sealed_tokens, i.checked_at
          FROM sessions s JOIN users u ON u.id = s.user_id JOIN identity_sessions i ON i.session_id = s.id
          WHERE s.id = ? AND s.expires_at > ? AND u.active = 1"""


def load_person(session_id: str) -> dict[str, Any] | None:
    """Who this session acts as, with their current access; None when the session is over.

    At most once a minute the access is read again from Supabase (renewing the token first when it is about to
    run out). No access any more, or a token Supabase no longer accepts, ends the session."""
    row = get(_ROW, session_id, now())
    if not row:
        return None
    if time.time() - row["checked_at"] < RECHECK_SECONDS:
        return _person(row, json.loads(row["access_json"]))
    with _lock_for(session_id):                      # one check at a time: a renewed token can only be used once
        row = get(_ROW, session_id, now())
        if not row:
            return None
        if time.time() - row["checked_at"] < RECHECK_SECONDS:
            return _person(row, json.loads(row["access_json"]))
        tokens = _unseal(row["sealed_tokens"], row["supabase_user_id"], row["email"])
        if tokens is None:                            # the owner key changed: stored tokens cannot be read
            end(session_id)
            return None
        try:
            if tokens.expires_at - time.time() < RENEW_BEFORE_SECONDS:
                tokens = renew(tokens.refresh)
                run("UPDATE identity_sessions SET sealed_tokens = ? WHERE session_id = ?", _seal(tokens), session_id)
            access = read_access(tokens.access)
        except IdentityError as e:
            if e.code == "unavailable" and time.time() - row["checked_at"] < OUTAGE_GRACE_SECONDS:
                return _person(row, json.loads(row["access_json"]))   # Supabase is not answering: last known access
            end(session_id)
            return None
        if access is None:                            # switched off in Supabase, or removed
            end(session_id)
            run("UPDATE users SET active = 0 WHERE id = ?", row["id"])
            return None
        run("UPDATE identity_sessions SET access_json = ?, checked_at = ? WHERE session_id = ?",
            json.dumps(access), time.time(), session_id)
        return _person(row, access)


def tokens_for(session_id: str) -> Tokens | None:
    """This session's Supabase tokens, for calls made as the person. Never put them in a response."""
    row = get(_ROW, session_id, now())
    return _unseal(row["sealed_tokens"], row["supabase_user_id"], row["email"]) if row else None


def end(session_id: str) -> None:
    run("DELETE FROM sessions WHERE id = ?", session_id)      # identity_sessions goes with it (ON DELETE CASCADE)
    with _locks_guard:
        _locks.pop(session_id, None)
