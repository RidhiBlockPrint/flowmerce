"""Shared fixtures for the SEO module tests (in-memory DB, three role users, network blocked). Loaded as a pytest plugin from tests/conftest.py.

In local operator mode the first active administrator ("admin@test.local") is the identity behind every local request;
the manager and reviewer records stay because services and tests still use them as record owners and assignees."""
import os

import pytest

os.environ["SCHEDULER"] = "false"
os.environ["ALLOW_LIVE_PUBLISH"] = "false"   # beats a developer's .env (config never overrides a real variable): tests expect it off

from flowmerce.modules.seo.auth import hash_password  # noqa: E402
from flowmerce.modules.seo.db import now, open_db, run  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture(scope="session", autouse=True)
def database():
    open_db(":memory:")
    users = {}
    for email, role in (("admin@test.local", "admin"), ("manager@test.local", "seo_manager"), ("reviewer@test.local", "reviewer")):
        uid = run("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                  email, email.split("@")[0], role, hash_password(PASSWORD), now()).last_id
        users[role] = {"id": uid, "email": email, "name": email.split("@")[0], "role": role}
    return users


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach a real outside service."""
    httpx = pytest.importorskip("httpx")

    def blocked(*_a, **_k):
        raise RuntimeError("network disabled in tests")
    monkeypatch.setattr(httpx, "get", blocked)
    monkeypatch.setattr(httpx, "post", blocked)


@pytest.fixture
def users(database):
    return database


# Local operator mode answers only loopback clients. Starlette's TestClient reports its peer as
# "testclient", which is deliberately NOT local, so every test names its peer address explicitly.
LOCAL_CLIENT = ("127.0.0.1", 50000)
REMOTE_CLIENT = ("192.168.1.50", 50000)


def make_client(app, peer=LOCAL_CLIENT):
    """A TestClient whose connection appears to come from `peer` (imported lazily: fastapi is an optional extra)."""
    from fastapi.testclient import TestClient

    return TestClient(app, client=peer)


def local_client(app):
    """A client on this computer: no sign-in needed, acts as the local administrator."""
    return make_client(app, LOCAL_CLIENT)


def remote_client(app):
    """A client on another computer of the network: refused everywhere except the secret-protected webhook."""
    return make_client(app, REMOTE_CLIENT)


# ---------------- AI job bridge ----------------

def clean_ai() -> None:
    """Remove everything the AI job tests create (jobs, events, their runs, the AIT-prefixed topics and articles)."""
    run("DELETE FROM ai_job_events")
    run("DELETE FROM ai_jobs")
    run("DELETE FROM workflow_runs WHERE trigger_kind IN ('ai_job', 'webhook')")
    run("DELETE FROM article_revisions WHERE article_id IN (SELECT id FROM articles WHERE title LIKE 'AIT %')")
    run("DELETE FROM articles WHERE title LIKE 'AIT %'")
    run("DELETE FROM topics WHERE title LIKE 'AIT %'")
    run("DELETE FROM integration_status WHERE key = 'ai_worker'")


@pytest.fixture
def ai_env(monkeypatch):
    """A clean database for the AI job tests and a Claude-API executor that is "configured" with a placeholder key.
    The key is never used: every test replaces the Claude calls."""
    from flowmerce.modules.seo.config import config

    monkeypatch.setattr(config, "ai_execution_mode", "anthropic_api")
    monkeypatch.setattr(config, "anthropic_api_key", "placeholder-not-a-real-key")
    monkeypatch.setattr(config, "ai_max_retries", 3)
    monkeypatch.setattr(config, "ai_lease_seconds", 900)
    monkeypatch.setattr(config, "ai_retry_base_seconds", 5)
    monkeypatch.setattr(config, "ai_retry_max_seconds", 300)
    clean_ai()
    yield config
    clean_ai()


def make_topic(status: str = "approved", brand: str = "ridhi", title: str = "AIT hand block print guide", keyword: str | None = None) -> int:
    """Insert a topic for the AI tests and return its id."""
    kw = keyword or f"ait {title.lower()}"
    t = now()
    return run("""INSERT INTO topics (brand_id, title, primary_keyword, keyword_norm, status, source, created_at, updated_at)
                  VALUES (?,?,?,?,?, 'manual', ?, ?)""", brand, title, kw, kw, status, t, t).last_id


TOPIC_RESULT = {"topics": [
    {"title": "AIT How to care for block print cotton", "primary_keyword": "ait block print cotton care", "secondary_keywords": ["wash block print", "fabric care"],
     "intent": "informational", "rationale": "Shoppers ask how to wash hand printed fabric."},
    {"title": "AIT Block print tablecloth sizes", "primary_keyword": "ait block print tablecloth size", "secondary_keywords": [], "intent": "commercial", "rationale": ""},
]}

DRAFT_RESULT = {
    "title": "AIT A guide to hand block printing", "handle": "ait-hand-block-printing-guide", "meta_title": "Hand block printing guide",
    "meta_description": "How artisans hand block print cotton and what to look for when you buy.",
    "summary_html": "<p>How hand block printing works.</p>",
    "body_html": "<h2>What is block printing?</h2><p>" + "Artisans carve wooden blocks and press them into dye on cotton by hand, repeating the motif across the cloth. " * 4 + "</p>",
    "tags": ["block print", "guide"], "image_alt": "Hand block printed cotton tablecloth",
}


def make_topics(n: int, prefix: str = "AIT count topic") -> dict:
    """A topic research result with n distinct topics."""
    return {"topics": [{"title": f"{prefix} {i}", "primary_keyword": f"ait count keyword {prefix.lower()} {i}", "secondary_keywords": [],
                        "intent": "informational", "rationale": "test"} for i in range(1, n + 1)]}
