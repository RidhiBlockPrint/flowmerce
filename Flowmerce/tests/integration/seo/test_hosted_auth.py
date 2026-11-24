"""Hosted mode (config.hosted): each person signs in with their own account, through the real HTTP stack.

The Next.js frontend is the only caller: it reaches the API from a loopback address, forwards the sign-in
form to POST /api/auth/login with the internal secret, and keeps the returned session token in the
`fm_session` cookie (`v2.<expiry>.<token>.<signature>`; the API only uses the token). These tests play the
frontend's part. Local operator mode is covered by test_http.py and must not change.
"""
import pytest

from flowmerce.modules.seo import auth
from flowmerce.modules.seo.app import create_app
from flowmerce.modules.seo.config import config
from flowmerce.modules.seo.db import all_rows, get, run
from tests.fixtures.seo import PASSWORD, local_client, remote_client

H = {"X-Requested-With": "blog-ops"}
INTERNAL = "internal-secret-for-tests-0123456789"
OWNER_PASSWORD = "owner-key-for-tests-0123456789"
FRONTEND = {**H, "X-Flowmerce-Internal": INTERNAL}


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def hosted(monkeypatch, users):
    monkeypatch.setattr(config, "hosted", True)
    monkeypatch.setattr(config, "internal_secret", INTERNAL)
    monkeypatch.setattr(config, "login_user", "admin")
    monkeypatch.setattr(config, "login_password", OWNER_PASSWORD)
    auth._failures.clear()
    before = {r["id"]: r for r in all_rows("SELECT * FROM users")}
    audit_from = get("SELECT COALESCE(MAX(id), 0) n FROM audit_log")["n"]
    yield users
    auth._failures.clear()
    run("DELETE FROM sessions")
    run("DELETE FROM audit_log WHERE id > ?", audit_from)
    for row in all_rows("SELECT id FROM users"):
        if row["id"] not in before:
            run("DELETE FROM users WHERE id = ?", row["id"])
    for uid, r in before.items():
        run("UPDATE users SET email = ?, name = ?, role = ?, password_hash = ?, active = ?, last_login_at = ? WHERE id = ?",
            r["email"], r["name"], r["role"], r["password_hash"], r["active"], r["last_login_at"], uid)


def login(app, username, password, **extra):
    """What the frontend gate does with a submitted sign-in form."""
    return local_client(app).post("/api/auth/login", headers=FRONTEND,
                                  json={"username": username, "password": password, "address": "203.0.113.7", **extra})


def signed_in(app, username, password=PASSWORD):
    """A browser session for this person, as the frontend would set it up."""
    r = login(app, username, password)
    assert r.status_code == 200, r.text
    c = local_client(app)
    c.cookies.set("fm_session", f"v2.4102444800.{r.json()['token']}.signature-checked-by-the-frontend")
    return c


# ---------------- signing in ----------------

def test_each_person_signs_in_as_themselves_with_their_own_role(app, hosted):
    for role, email in (("admin", "admin@test.local"), ("seo_manager", "manager@test.local"), ("reviewer", "reviewer@test.local")):
        me = signed_in(app, email).get("/api/auth/me").json()
        assert me["user"]["id"] == hosted[role]["id"] and me["user"]["role"] == role
        assert me["localOperator"] is False
        assert ("users:manage" in me["permissions"]) is (role == "admin")
    assert get("SELECT last_login_at FROM users WHERE id = ?", hosted["reviewer"]["id"])["last_login_at"]
    signins = all_rows("SELECT user_email FROM audit_log WHERE action = 'auth.login' ORDER BY id")
    assert [r["user_email"] for r in signins][-3:] == ["admin@test.local", "manager@test.local", "reviewer@test.local"]


def test_email_is_not_case_sensitive_and_the_response_carries_no_password_hash(app, hosted):
    r = login(app, "  Manager@Test.Local ", PASSWORD)
    assert r.status_code == 200 and r.json()["user"]["email"] == "manager@test.local"
    assert "password_hash" not in r.text and "scrypt" not in r.text


def test_wrong_password_unknown_email_and_inactive_account_all_answer_the_same(app, hosted):
    run("UPDATE users SET active = 0 WHERE id = ?", hosted["reviewer"]["id"])
    sessions_before = get("SELECT COUNT(*) n FROM sessions")["n"]
    answers = [login(app, "manager@test.local", "not the password"), login(app, "nobody@test.local", PASSWORD),
               login(app, "reviewer@test.local", PASSWORD), login(app, "", ""), login(app, "manager@test.local", None)]
    for r in answers:
        assert r.status_code == 401 and r.json()["code"] == "invalid"
        assert r.json()["error"] == answers[0].json()["error"]
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == sessions_before
    # A made-up name is never written to the audit log (it may be a password typed into the wrong box).
    assert not all_rows("SELECT 1 FROM audit_log WHERE summary LIKE '%nobody@test.local%'")
    assert all_rows("SELECT 1 FROM audit_log WHERE action = 'auth.login_failed' AND summary LIKE 'manager@test.local%'")


def test_repeated_failures_pause_that_person_but_not_their_colleagues(app, hosted):
    for _ in range(8):
        assert login(app, "manager@test.local", "wrong wrong wrong").status_code == 401
    paused = login(app, "manager@test.local", PASSWORD)          # even the right password waits now
    assert paused.status_code == 429 and paused.json()["code"] == "throttled"
    assert login(app, "reviewer@test.local", PASSWORD).status_code == 200   # same office address, different person


def test_a_person_is_paused_even_when_every_guess_comes_from_a_new_address(app, hosted):
    for n in range(20):
        assert login(app, "manager@test.local", "wrong wrong wrong", address=f"198.51.100.{n}").status_code == 401
    assert login(app, "manager@test.local", PASSWORD, address="198.51.100.200").status_code == 429


def test_keep_me_signed_in_lasts_thirty_days_otherwise_twelve_hours(app, hosted):
    assert login(app, "manager@test.local", PASSWORD).json()["seconds"] == 12 * 3600
    assert login(app, "manager@test.local", PASSWORD, remember=True).json()["seconds"] == 30 * 24 * 3600


def test_only_the_frontend_can_call_sign_in(app, hosted, monkeypatch):
    body = {"username": "admin@test.local", "password": PASSWORD}
    c = local_client(app)
    for headers in (H, {**H, "X-Flowmerce-Internal": "guess"}, {**H, "X-Flowmerce-Internal": ""}):
        r = c.post("/api/auth/login", json=body, headers=headers)
        assert r.status_code == 403 and r.json()["code"] == "forbidden"
    monkeypatch.setattr(config, "internal_secret", "")           # not configured: closed, never "anything matches"
    assert c.post("/api/auth/login", json=body, headers={**H, "X-Flowmerce-Internal": ""}).status_code == 403
    # Other computers are still refused outright, with or without the secret.
    r = remote_client(app).post("/api/auth/login", json=body, headers=FRONTEND)
    assert r.status_code == 403 and r.json()["code"] == "local_only"


# ---------------- the owner key ----------------

def test_the_owner_key_signs_in_as_the_first_administrator(app, hosted):
    c = signed_in(app, "admin", OWNER_PASSWORD)
    assert c.get("/api/auth/me").json()["user"]["id"] == hosted["admin"]["id"]
    assert get("SELECT summary FROM audit_log WHERE action = 'auth.login' ORDER BY id DESC LIMIT 1")["summary"] == "Signed in with the owner key"
    assert login(app, "admin", PASSWORD).status_code == 401             # a team password is not the owner key
    assert login(app, "admin@test.local", OWNER_PASSWORD).status_code == 401   # and the owner key is not a team password


def test_a_short_owner_key_is_never_accepted(app, hosted, monkeypatch):
    monkeypatch.setattr(config, "login_password", "short")
    assert login(app, "admin", "short").status_code == 401
    monkeypatch.setattr(config, "login_password", "")
    assert login(app, "admin", "").status_code == 401


def test_nobody_can_lock_the_owner_out_by_guessing(app, hosted):
    for n in range(45):
        login(app, "admin", "guess guess guess guess", address=f"198.51.100.{n}")
    assert login(app, "admin", OWNER_PASSWORD, address="192.0.2.9").status_code == 200


# ---------------- every call needs a live session ----------------

@pytest.mark.parametrize("path", ["/api/auth/me", "/api/home", "/api/articles", "/api/users", "/api/audit", "/api/shipping/overview", "/api/docs"])
def test_calls_without_a_session_are_refused(app, hosted, path):
    c = local_client(app)
    assert c.get(path).status_code == 401 and c.get(path).json()["code"] == "signed_out"
    for cookie in ("v2.4102444800.made-up-token.sig", "v1.4102444800.sig", "made-up", "v2.4102444800..sig"):
        c.cookies.set("fm_session", cookie)
        assert c.get(path).status_code == 401


def test_the_old_local_cookie_name_is_not_a_way_in(app, hosted):
    token = login(app, "admin@test.local", PASSWORD).json()["token"]
    c = local_client(app)
    c.cookies.set("bo_session", token)
    assert c.get("/api/auth/me").status_code == 401


def test_an_expired_session_is_refused(app, hosted):
    c = signed_in(app, "manager@test.local")
    assert c.get("/api/auth/me").status_code == 200
    run("UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000Z'")
    assert c.get("/api/auth/me").status_code == 401


def test_signing_out_ends_only_that_session(app, hosted):
    phone, laptop = signed_in(app, "manager@test.local"), signed_in(app, "manager@test.local")
    assert phone.post("/api/auth/logout", headers=H).json() == {"ok": True}
    assert phone.get("/api/auth/me").status_code == 401
    assert laptop.get("/api/auth/me").status_code == 200


def test_csrf_header_is_still_required_when_signed_in(app, hosted):
    c = signed_in(app, "admin@test.local")
    r = c.post("/api/articles", json={"brand_id": "ridhi", "title": "x"})
    assert r.status_code == 403 and r.json()["code"] == "csrf"


# ---------------- roles are enforced per person ----------------

def test_roles_limit_what_each_person_can_do(app, hosted):
    admin, manager, reviewer = (signed_in(app, e) for e in ("admin@test.local", "manager@test.local", "reviewer@test.local"))
    new_user = {"email": "new@test.local", "name": "New", "role": "reviewer", "password": "a long enough password"}
    for c in (manager, reviewer):
        r = c.post("/api/users", json=new_user, headers=H)
        assert r.status_code == 403 and r.json()["code"] == "forbidden"
        assert c.patch(f"/api/users/{hosted['admin']['id']}", json={"active": False}, headers=H).status_code == 403
        assert "email" not in c.get("/api/users").json()["users"][0]          # colleagues' emails stay with admins
    assert reviewer.post("/api/topics", json={"brand_id": "ridhi", "title": "t", "primary_keyword": "k"}, headers=H).status_code == 403
    assert reviewer.get("/api/articles").status_code == 200                    # everyone can look
    assert admin.post("/api/users", json=new_user, headers=H).status_code == 200
    assert signed_in(app, "new@test.local", "a long enough password").get("/api/auth/me").json()["user"]["role"] == "reviewer"


def test_actions_are_recorded_under_the_person_who_did_them(app, hosted):
    admin = signed_in(app, "admin@test.local")
    made = admin.post("/api/users", headers=H, json={"email": "a@test.local", "name": "A", "role": "reviewer", "password": "a long enough password"})
    row = get("SELECT user_id, user_email FROM audit_log WHERE action = 'user.create' ORDER BY id DESC LIMIT 1")
    assert made.status_code == 200 and row == {"user_id": hosted["admin"]["id"], "user_email": "admin@test.local"}


# ---------------- managing the team ----------------

def test_deactivating_or_resetting_someone_signs_out_only_them(app, hosted):
    admin, manager, reviewer = (signed_in(app, e) for e in ("admin@test.local", "manager@test.local", "reviewer@test.local"))
    assert admin.patch(f"/api/users/{hosted['seo_manager']['id']}", json={"active": False}, headers=H).status_code == 200
    assert manager.get("/api/auth/me").status_code == 401
    assert login(app, "manager@test.local", PASSWORD).status_code == 401       # and cannot sign back in
    assert admin.patch(f"/api/users/{hosted['reviewer']['id']}", json={"password": "a freshly reset password"}, headers=H).status_code == 200
    assert reviewer.get("/api/auth/me").status_code == 401
    assert login(app, "reviewer@test.local", PASSWORD).status_code == 401
    assert login(app, "reviewer@test.local", "a freshly reset password").status_code == 200
    assert admin.get("/api/auth/me").status_code == 200                        # the admin was not signed out


def test_changing_a_role_takes_effect_at_once(app, hosted):
    admin, reviewer = signed_in(app, "admin@test.local"), signed_in(app, "reviewer@test.local")
    assert admin.patch(f"/api/users/{hosted['reviewer']['id']}", json={"role": "admin"}, headers=H).status_code == 200
    assert reviewer.get("/api/auth/me").status_code == 401                     # the old session is gone
    assert "users:manage" in signed_in(app, "reviewer@test.local").get("/api/auth/me").json()["permissions"]


def test_at_least_one_active_admin_always_remains(app, hosted):
    admin = signed_in(app, "admin@test.local")
    for change in ({"active": False}, {"role": "reviewer"}):
        r = admin.patch(f"/api/users/{hosted['admin']['id']}", json=change, headers=H)
        assert r.status_code == 409
    assert admin.get("/api/auth/me").status_code == 200


def test_an_admin_can_correct_an_email_and_bad_values_change_nothing(app, hosted):
    admin = signed_in(app, "admin@test.local")
    uid = hosted["reviewer"]["id"]
    assert admin.patch(f"/api/users/{uid}", json={"email": "manager@test.local"}, headers=H).status_code == 409
    assert admin.patch(f"/api/users/{uid}", json={"email": "not an email"}, headers=H).status_code == 400
    assert admin.patch(f"/api/users/{uid}", json={"role": "admin", "password": "short"}, headers=H).status_code == 400
    assert get("SELECT email, role FROM users WHERE id = ?", uid) == {"email": "reviewer@test.local", "role": "reviewer"}
    assert admin.patch(f"/api/users/{uid}", json={"email": "Checker@Test.Local"}, headers=H).status_code == 200
    assert login(app, "checker@test.local", PASSWORD).status_code == 200
    assert login(app, "reviewer@test.local", PASSWORD).status_code == 401


def test_an_admin_editing_their_own_name_or_email_stays_signed_in(app, hosted):
    admin = signed_in(app, "admin@test.local")
    r = admin.patch(f"/api/users/{hosted['admin']['id']}", json={"name": "Owner", "email": "owner@test.local"}, headers=H)
    assert r.status_code == 200
    assert admin.get("/api/auth/me").json()["user"]["email"] == "owner@test.local"


# ---------------- changing your own password ----------------

def test_a_person_changes_their_own_password_and_other_devices_are_signed_out(app, hosted):
    phone, laptop = signed_in(app, "manager@test.local"), signed_in(app, "manager@test.local")
    wrong = phone.post("/api/auth/password", json={"current": "not it", "next": "a brand new password 1"}, headers=H)
    assert wrong.status_code == 400 and wrong.json()["code"] == "wrong_password"
    assert phone.post("/api/auth/password", json={"current": PASSWORD, "next": "short"}, headers=H).status_code == 400
    assert phone.post("/api/auth/password", json={"current": PASSWORD, "next": "a brand new password 1"}, headers=H).status_code == 200
    assert phone.get("/api/auth/me").status_code == 200
    assert laptop.get("/api/auth/me").status_code == 401
    assert login(app, "manager@test.local", PASSWORD).status_code == 401
    assert login(app, "manager@test.local", "a brand new password 1").status_code == 200


def test_the_first_administrator_can_set_a_first_password_after_the_owner_key(app, hosted):
    run("UPDATE users SET password_hash = ? WHERE id = ?", auth.LOCAL_OPERATOR_PASSWORD_HASH, hosted["admin"]["id"])
    assert login(app, "admin@test.local", PASSWORD).status_code == 401         # no password yet: only the owner key works
    owner = signed_in(app, "admin", OWNER_PASSWORD)
    assert owner.post("/api/auth/password", json={"next": "the owner's own password"}, headers=H).status_code == 200
    assert login(app, "admin@test.local", "the owner's own password").status_code == 200
    assert login(app, "admin", OWNER_PASSWORD).status_code == 200              # the owner key keeps working


# ---------------- local operator mode is unchanged ----------------

def test_without_hosted_mode_there_is_still_no_sign_in(app, users):
    assert config.hosted is False
    c = local_client(app)
    me = c.get("/api/auth/me").json()
    assert me["localOperator"] is True and me["user"]["id"] == users["admin"]["id"]
    r = c.post("/api/auth/login", json={"username": "admin@test.local", "password": PASSWORD},
               headers={**H, "X-Flowmerce-Internal": config.internal_secret})
    assert r.status_code == 410 and r.json()["code"] == "login_disabled"
    assert get("SELECT COUNT(*) n FROM sessions")["n"] == 0
