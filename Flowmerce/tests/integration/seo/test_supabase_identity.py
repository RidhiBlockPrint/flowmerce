"""Hosted mode with people from Supabase (identity.py): sign-in, access, re-checks, sign-out and passwords,
through the real HTTP stack.

Supabase itself is played by `FakeSupabase` below (an httpx transport), which behaves like the real project
did when it was probed on 2026-11-25: Supabase Auth's token, user and logout endpoints, and the REST views
`my_access` and `member` in schema `flowmerce`. No test reaches the network.
"""
import json

import httpx
import pytest

from flowmerce.modules.seo import auth, identity
from flowmerce.modules.seo.app import create_app
from flowmerce.modules.seo.config import config
from flowmerce.modules.seo.db import all_rows, get, run
from tests.fixtures.seo import PASSWORD, local_client

H = {"X-Requested-With": "blog-ops"}
INTERNAL = "internal-secret-for-tests-0123456789"
FRONTEND = {**H, "X-Flowmerce-Internal": INTERNAL}
KEY = "sb_publishable_test_key"
WS = "d4073f80-0000-0000-0000-000000000001"
STORES = {"RBP": "Ridhi Block Print", "CPC": "Cotton Print Club"}


class FakeSupabase(httpx.BaseTransport):
    """Just enough of Supabase Auth and the `flowmerce` REST views for these tests."""

    def __init__(self):
        self.people = {}        # email -> {id, password, name, role, active, stores, sections, costs, member}
        self.access_tokens = {}   # token -> email
        self.refresh_tokens = {}  # token -> email
        self.calls = []
        self.down = False
        self.n = 0
        self.expires_in = 3600
        self.reject_password = None

    def person(self, email, role="editor", *, password=PASSWORD, active=True, stores=("RBP", "CPC"),
               sections=("home", "shipping", "seo", "cro", "ads"), costs=False, member=True, name=None):
        self.people[email] = {"id": f"00000000-0000-4000-8000-{len(self.people):012d}", "password": password,
                              "name": name or email.split("@")[0].title(), "role": role, "active": active,
                              "stores": list(stores), "sections": list(sections), "costs": costs, "member": member}
        return self.people[email]

    def _issue(self, email):
        self.n += 1
        access, refresh = f"access-{self.n}", f"refresh-{self.n}"
        self.access_tokens[access] = email
        self.refresh_tokens[refresh] = email
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "token_type": "bearer",
                                         "expires_in": self.expires_in,
                                         "user": {"id": self.people[email]["id"], "email": email}})

    def handle_request(self, request):
        path, params = request.url.path, dict(request.url.params)
        self.calls.append((request.method, path, params))
        if self.down:
            raise httpx.ConnectError("Supabase is down", request=request)
        if request.headers.get("apikey") != KEY:
            return httpx.Response(401, json={"message": "Invalid API key"})
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        who = self.access_tokens.get(bearer)
        body = json.loads(request.content) if request.content else {}

        if path == "/auth/v1/token" and params.get("grant_type") == "password":
            p = self.people.get(str(body.get("email", "")).lower())
            if not p or p["password"] != body.get("password"):
                return httpx.Response(400, json={"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"})
            return self._issue(str(body["email"]).lower())
        if path == "/auth/v1/token" and params.get("grant_type") == "refresh_token":
            email = self.refresh_tokens.pop(body.get("refresh_token"), None)     # single use, like Supabase
            if not email:
                return httpx.Response(400, json={"code": 400, "error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"})
            return self._issue(email)
        if path == "/auth/v1/logout":
            if who:
                del self.access_tokens[bearer]
                for t in [t for t, e in self.refresh_tokens.items() if e == who and t.split("-")[1] == bearer.split("-")[1]]:
                    del self.refresh_tokens[t]
            return httpx.Response(204)
        if path == "/auth/v1/user" and request.method == "PUT":
            if not who:
                return httpx.Response(401, json={"error_code": "bad_jwt"})
            if self.reject_password:
                return httpx.Response(422, json={"code": 422, "error_code": self.reject_password, "msg": "no"})
            self.people[who]["password"] = body["password"]
            return httpx.Response(200, json={"id": self.people[who]["id"]})

        if path.startswith("/rest/v1/"):
            if request.headers.get("accept-profile") != "flowmerce":
                return httpx.Response(406, json={"message": "wrong schema"})
            if not who:      # the publishable key alone opens nothing
                return httpx.Response(401, json={"code": "42501", "message": "permission denied for schema flowmerce"})
            p = self.people[who]
            visible = p["member"] and p["active"]
            if path == "/rest/v1/my_access":
                rows = [{"workspace_id": WS, "workspace_name": "Ridhi", "role": p["role"], "title": None,
                         "can_see_costs": p["costs"], "sections": p["sections"], "store_id": f"store-{code}",
                         "store": code, "store_name": STORES[code]} for code in p["stores"]] if visible else []
                return httpx.Response(200, json=rows)
            if path == "/rest/v1/member":
                rows = [{"user_id": x["id"], "display_name": x["name"], "role": x["role"], "is_active": x["active"],
                         "all_stores": len(x["stores"]) == 2, "sections": x["sections"], "can_see_costs": x["costs"]}
                        for x in self.people.values() if x["member"]] if visible else []
                if "user_id" in params:
                    rows = [r for r in rows if f"eq.{r['user_id']}" == params["user_id"]]
                return httpx.Response(200, json=rows)
        return httpx.Response(404, json={"message": "not found"})

    def count(self, path):
        return sum(1 for _m, p, _q in self.calls if p == path)


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def supabase(monkeypatch, users):
    fake = FakeSupabase()
    monkeypatch.setattr(config, "hosted", True)
    monkeypatch.setattr(config, "internal_secret", INTERNAL)
    monkeypatch.setattr(config, "login_user", "admin")
    monkeypatch.setattr(config, "login_password", "owner-key-for-tests-0123456789")
    monkeypatch.setattr(config, "identity_url", "https://project.supabase.test")
    monkeypatch.setattr(config, "identity_key", KEY)
    identity.set_transport(fake)
    identity.ensure_tables()
    auth._failures.clear()
    before = {r["id"]: r for r in all_rows("SELECT * FROM users")}
    audit_from = get("SELECT COALESCE(MAX(id), 0) n FROM audit_log")["n"]
    yield fake
    identity.set_transport(None)
    auth._failures.clear()
    run("DELETE FROM sessions")
    run("DELETE FROM audit_log WHERE id > ?", audit_from)
    for row in all_rows("SELECT id FROM users"):
        if row["id"] not in before:
            run("DELETE FROM users WHERE id = ?", row["id"])
    for uid, r in before.items():
        run("UPDATE users SET email = ?, name = ?, role = ?, password_hash = ?, active = ?, last_login_at = ? WHERE id = ?",
            r["email"], r["name"], r["role"], r["password_hash"], r["active"], r["last_login_at"], uid)


def login(app, email, password=PASSWORD, **extra):
    return local_client(app).post("/api/auth/login", headers=FRONTEND,
                                  json={"username": email, "password": password, "address": "203.0.113.7", **extra})


def signed_in(app, email, password=PASSWORD):
    r = login(app, email, password)
    assert r.status_code == 200, r.text
    c = local_client(app)
    c.cookies.set("fm_session", f"v2.4102444800.{r.json()['token']}.signature-checked-by-the-frontend")
    return c


def age_checks(seconds=identity.RECHECK_SECONDS + 1):
    """As if this much time had passed since each session's access was last read."""
    run("UPDATE identity_sessions SET checked_at = checked_at - ?", seconds)


# ---------------- signing in ----------------

def test_supabase_checks_the_password_and_gives_the_role(app, supabase):
    supabase.person("owner@ridhi.test", "owner", name="Asha")
    supabase.person("editor@ridhi.test", "editor")
    supabase.person("viewer@ridhi.test", "viewer")
    expected = {"owner@ridhi.test": ("admin", "Owner"), "editor@ridhi.test": ("seo_manager", "Editor"), "viewer@ridhi.test": ("viewer", "Viewer")}
    for email, (role, label) in expected.items():
        me = signed_in(app, email).get("/api/auth/me").json()
        assert (me["user"]["email"], me["user"]["role"], me["user"]["roleLabel"]) == (email, role, label)
        assert me["identity"] == "supabase" and me["localOperator"] is False
        assert me["access"]["role"] == label.lower() and me["access"]["stores"] == ["CPC", "RBP"]
    owner = signed_in(app, "owner@ridhi.test").get("/api/auth/me").json()
    assert owner["user"]["name"] == "Asha" and "users:manage" in owner["permissions"]
    assert signed_in(app, "viewer@ridhi.test").get("/api/auth/me").json()["permissions"] == ["view"]


def test_manager_and_admin_map_like_editor_and_owner(app, supabase):
    supabase.person("m@ridhi.test", "manager")
    supabase.person("a@ridhi.test", "admin")
    assert signed_in(app, "m@ridhi.test").get("/api/auth/me").json()["user"]["role"] == "seo_manager"
    assert signed_in(app, "a@ridhi.test").get("/api/auth/me").json()["user"]["role"] == "admin"


def test_no_password_is_ever_stored_here_and_tokens_never_leave(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    r = login(app, "Editor@Ridhi.Test")
    assert r.status_code == 200
    for secret in ("access-", "refresh-", PASSWORD):
        assert secret not in r.text
    row = get("SELECT password_hash FROM users WHERE email = 'editor@ridhi.test'")
    assert row["password_hash"] == identity.MIRROR_PASSWORD_HASH and not auth.verify_password(PASSWORD, row["password_hash"])
    stored = get("SELECT sealed_tokens, access_json FROM identity_sessions")
    assert "access-" not in stored["sealed_tokens"] and "refresh-" not in stored["sealed_tokens"]   # encrypted at rest
    c = signed_in(app, "editor@ridhi.test")
    for path in ("/api/auth/me", "/api/users", "/api/home"):
        body = c.get(path).text
        assert "access-" not in body and "refresh-" not in body and "sealed" not in body, path


def test_wrong_password_unknown_person_and_blank_all_answer_the_same(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    for r in (login(app, "editor@ridhi.test", "not the password"), login(app, "nobody@ridhi.test"), login(app, "", "")):
        assert r.status_code == 401 and r.json()["code"] == "invalid"
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == 0


def test_a_supabase_account_that_is_not_a_member_gets_no_access(app, supabase):
    supabase.person("stranger@elsewhere.test", "viewer", member=False)
    supabase.person("left@ridhi.test", "editor", active=False)
    for email in ("stranger@elsewhere.test", "left@ridhi.test"):
        r = login(app, email)
        assert r.status_code == 403 and r.json()["code"] == "no_access"
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == 0
    assert not get("SELECT 1 FROM users WHERE email = 'stranger@elsewhere.test'")      # no record is made for them
    assert supabase.access_tokens == {}                                                  # their Supabase session was ended


def test_a_role_this_version_does_not_know_gets_no_access(app, supabase):
    supabase.person("x@ridhi.test", "superuser")
    assert login(app, "x@ridhi.test").status_code == 403


def test_the_owner_key_and_old_local_passwords_sign_nobody_in(app, supabase):
    assert login(app, "admin", "owner-key-for-tests-0123456789").status_code == 401
    assert login(app, "admin@test.local").status_code == 401          # a local record with a real password hash
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == 0


def test_a_local_session_from_before_is_not_accepted(app, supabase, users):
    token = auth.issue_session(users["admin"]["id"], 3600)            # as the earlier local sign-in would have made
    c = local_client(app)
    c.cookies.set("fm_session", f"v2.4102444800.{token}.sig")
    assert c.get("/api/auth/me").status_code == 401


def test_supabase_not_answering_is_reported_as_unavailable_not_as_a_wrong_password(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    supabase.down = True
    r = login(app, "editor@ridhi.test")
    assert r.status_code == 503 and r.json()["code"] == "unavailable"
    assert auth._failures == {}                                        # an outage is not counted against the person


def test_repeated_wrong_passwords_pause_that_person(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    for _ in range(8):
        assert login(app, "editor@ridhi.test", "wrong wrong wrong").status_code == 401
    assert login(app, "editor@ridhi.test").status_code == 429
    assert supabase.count("/auth/v1/token") == 8                        # the paused attempt never reached Supabase


# ---------------- access follows Supabase ----------------

def test_switching_someone_off_in_supabase_signs_them_out_within_a_minute(app, supabase):
    p = supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    assert c.get("/api/auth/me").status_code == 200
    p["active"] = False
    assert c.get("/api/auth/me").status_code == 200                    # within the minute: last known access
    age_checks()
    r = c.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "signed_out"
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == 0
    assert login(app, "editor@ridhi.test").status_code == 403


def test_a_role_change_in_supabase_reaches_the_person_without_signing_in_again(app, supabase):
    p = supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    assert "users:manage" not in c.get("/api/auth/me").json()["permissions"]
    p["role"] = "admin"
    age_checks()
    me = c.get("/api/auth/me").json()
    assert me["user"]["roleLabel"] == "Admin" and "users:manage" in me["permissions"]


def test_access_is_read_again_at_most_once_a_minute(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    before = supabase.count("/rest/v1/my_access")
    for _ in range(5):
        assert c.get("/api/auth/me").status_code == 200
    assert supabase.count("/rest/v1/my_access") == before
    age_checks()
    for _ in range(5):
        assert c.get("/api/auth/me").status_code == 200
    assert supabase.count("/rest/v1/my_access") == before + 1


def test_the_token_is_renewed_before_it_runs_out_and_stays_encrypted(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    supabase.expires_in = 30                                            # about to run out
    c = signed_in(app, "editor@ridhi.test")
    first = get("SELECT sealed_tokens FROM identity_sessions")["sealed_tokens"]
    supabase.expires_in = 3600
    age_checks()
    assert c.get("/api/auth/me").status_code == 200
    second = get("SELECT sealed_tokens FROM identity_sessions")["sealed_tokens"]
    assert second != first and "refresh-" not in second
    assert supabase.count("/auth/v1/token") == 2                        # the sign-in and one renewal
    age_checks()
    assert c.get("/api/auth/me").status_code == 200
    assert supabase.count("/auth/v1/token") == 2                        # the new token is good for an hour


def test_a_session_supabase_no_longer_knows_is_ended(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    supabase.expires_in = 30
    c = signed_in(app, "editor@ridhi.test")
    supabase.refresh_tokens.clear()                                     # e.g. signed out everywhere in Supabase
    age_checks()
    assert c.get("/api/auth/me").status_code == 401


def test_a_short_supabase_outage_does_not_sign_people_out_but_a_long_one_does(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    supabase.down = True
    age_checks()
    assert c.get("/api/auth/me").status_code == 200
    age_checks(identity.OUTAGE_GRACE_SECONDS)
    assert c.get("/api/auth/me").status_code == 401


def test_changing_the_owner_key_makes_stored_tokens_unreadable_and_ends_the_session(app, supabase, monkeypatch):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    monkeypatch.setattr(config, "login_password", "a-different-owner-key-0123456789")
    age_checks()
    assert c.get("/api/auth/me").status_code == 401


# ---------------- what a role and its sections allow ----------------

def test_a_viewer_can_look_but_cannot_change_anything(app, supabase):
    supabase.person("viewer@ridhi.test", "viewer")
    c = signed_in(app, "viewer@ridhi.test")
    assert c.get("/api/articles").status_code == 200 and c.get("/api/home").status_code == 200
    for method, path in (("POST", "/api/articles"), ("POST", "/api/shipping/refresh"), ("PUT", "/api/cro/goal"),
                         ("POST", "/api/topics"), ("PATCH", "/api/brands/ridhi")):
        r = c.request(method, path, json={}, headers=H)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", (method, path)
    assert c.post("/api/auth/logout", headers=H).status_code == 200    # signing out is always allowed


def test_an_editor_can_write_content_but_not_manage_settings(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    made = c.post("/api/topics", json={"brand_id": "ridhi", "title": "ID topic", "primary_keyword": "identity test keyword"}, headers=H)
    assert made.status_code == 200
    run("DELETE FROM topics WHERE id = ?", made.json()["id"])
    assert c.patch("/api/brands/ridhi", json={}, headers=H).status_code == 403


def test_shipping_and_cro_are_closed_without_that_section(app, supabase):
    supabase.person("seo@ridhi.test", "editor", sections=("home", "seo"))
    c = signed_in(app, "seo@ridhi.test")
    for path in ("/api/shipping/overview", "/api/cro/overview", "/api/shipping", "/api/cro"):
        r = c.get(path)
        assert r.status_code == 403 and "section" in r.json()["error"], path
    assert c.get("/api/articles").status_code == 200
    assert c.get("/api/auth/me").json()["access"]["sections"] == ["home", "seo"]


def test_only_the_stores_a_person_was_given_are_offered(app, supabase):
    supabase.person("cpc@ridhi.test", "editor", stores=("CPC",))
    me = signed_in(app, "cpc@ridhi.test").get("/api/auth/me").json()
    assert [b["id"] for b in me["brands"]] == ["cpc"] and me["access"]["stores"] == ["CPC"]


def test_actions_are_recorded_under_the_person(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    signed_in(app, "editor@ridhi.test")
    row = get("SELECT user_email, summary FROM audit_log WHERE action = 'auth.login' ORDER BY id DESC LIMIT 1")
    assert row == {"user_email": "editor@ridhi.test", "summary": "Signed in (editor)"}


# ---------------- people are managed in Supabase ----------------

def test_admins_see_the_people_list_from_supabase_and_cannot_change_it_here(app, supabase):
    supabase.person("owner@ridhi.test", "owner", name="Asha")
    supabase.person("viewer@ridhi.test", "viewer", active=False)
    c = signed_in(app, "owner@ridhi.test")
    body = c.get("/api/users").json()
    assert body["managedBy"] == "supabase"
    assert [(m["name"], m["role"], m["active"], m["you"]) for m in body["members"]] == [("Asha", "owner", True, True), ("Viewer", "viewer", False, False)]
    assert [u["email"] for u in body["users"]] == ["owner@ridhi.test"]   # local records: only people who have signed in
    new = {"email": "new@ridhi.test", "name": "New", "role": "reviewer", "password": "a long enough password"}
    for r in (c.post("/api/users", json=new, headers=H), c.patch(f"/api/users/{body['users'][0]['id']}", json={"name": "x"}, headers=H)):
        assert r.status_code == 409 and r.json()["code"] == "managed_elsewhere"


def test_people_who_are_not_admins_do_not_get_the_supabase_list(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    body = signed_in(app, "editor@ridhi.test").get("/api/users").json()
    assert body["members"] == [] and "email" not in body["users"][0]


# ---------------- signing out and passwords ----------------

def test_signing_out_ends_the_supabase_session_too(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    assert len(supabase.access_tokens) == 1
    assert c.post("/api/auth/logout", headers=H).json() == {"ok": True}
    assert supabase.access_tokens == {} and supabase.refresh_tokens == {}
    assert c.get("/api/auth/me").status_code == 401
    assert get("SELECT COUNT(*) n FROM identity_sessions")["n"] == 0


def test_a_person_changes_their_password_in_supabase(app, supabase):
    p = supabase.person("editor@ridhi.test", "editor")
    phone, laptop = signed_in(app, "editor@ridhi.test"), signed_in(app, "editor@ridhi.test")
    wrong = phone.post("/api/auth/password", json={"current": "not it", "next": "a brand new password 1"}, headers=H)
    assert wrong.status_code == 400 and wrong.json()["code"] == "wrong_password"
    assert phone.post("/api/auth/password", json={"current": PASSWORD, "next": "short"}, headers=H).status_code == 400
    assert p["password"] == PASSWORD
    ok = phone.post("/api/auth/password", json={"current": PASSWORD, "next": "a brand new password 1"}, headers=H)
    assert ok.status_code == 200 and p["password"] == "a brand new password 1"
    assert get("SELECT password_hash FROM users WHERE email = 'editor@ridhi.test'")["password_hash"] == identity.MIRROR_PASSWORD_HASH
    assert phone.get("/api/auth/me").status_code == 200 and laptop.get("/api/auth/me").status_code == 401
    assert len(supabase.access_tokens) == 2      # the two sign-ins; the extra one used for the check was ended


def test_a_password_supabase_refuses_is_explained(app, supabase):
    supabase.person("editor@ridhi.test", "editor")
    c = signed_in(app, "editor@ridhi.test")
    supabase.reject_password = "weak_password"
    r = c.post("/api/auth/password", json={"current": PASSWORD, "next": "a brand new password 1"}, headers=H)
    assert r.status_code == 400 and r.json()["code"] == "weak_password"


# ---------------- off unless configured ----------------

def test_without_the_supabase_settings_nothing_here_applies(app, users, monkeypatch):
    assert identity.enabled() is False
    monkeypatch.setattr(config, "hosted", True)
    monkeypatch.setattr(config, "identity_url", "https://project.supabase.test")
    assert identity.enabled() is False                                   # the key is missing: both are needed
    monkeypatch.setattr(config, "identity_key", KEY)
    assert identity.enabled() is True
    monkeypatch.setattr(config, "hosted", False)
    assert identity.enabled() is False                                   # never on your own computer
