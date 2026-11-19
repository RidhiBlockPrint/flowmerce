"""AI jobs: migration, state machine, creation and de-duplication, claiming and leases, recovery, retry policy, the
Claude client's error handling, and result validation. No network and no real Claude call: Claude is always replaced."""
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from flowmerce.modules.seo import db
from flowmerce.modules.seo.integrations import claude
from flowmerce.modules.seo.services import ai_jobs, ai_results
from flowmerce.modules.seo.util import HttpError
from flowmerce.modules.seo.db import all_rows, get, run
from tests.fixtures.seo import DRAFT_RESULT, TOPIC_RESULT, make_topic


# ---------------- migration ----------------

def test_migration_is_additive_and_keeps_existing_data():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row

    def apply(sql):
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            c.execute(stmt)

    apply(db.MIGRATIONS[0])
    c.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES ('a@x', 'a', 'admin', 'h', 't')")
    c.execute("INSERT INTO workflow_runs (brand_id, stage, status, started_at) VALUES ('ridhi', 'topic_research', 'succeeded', 't')")
    before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "workflow_runs", "topics", "articles")}
    tables_before = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    apply(db.MIGRATIONS[1])
    tables_after = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables_after - tables_before == {"ai_jobs", "ai_job_events"}          # only two new tables
    assert tables_before <= tables_after                                          # nothing dropped
    assert {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before} == before   # rows untouched
    assert len(db.MIGRATIONS) >= 2 and db._db().execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_database_rejects_an_unknown_status():
    with pytest.raises(sqlite3.IntegrityError):
        run("""INSERT INTO ai_jobs (id, brand_id, stage, task_type, status, provider, created_at, updated_at) VALUES ('x','ridhi','s','t','bogus','p','t','t')""")


# ---------------- state machine ----------------

ALLOWED = {("pending", "queued"), ("pending", "running"), ("pending", "failed"), ("pending", "cancelled"), ("queued", "running"), ("queued", "succeeded"),
           ("queued", "failed"), ("queued", "cancelled"), ("running", "succeeded"), ("running", "failed"), ("running", "cancelled"), ("running", "pending"), ("failed", "pending")}
STATES = ("pending", "queued", "running", "succeeded", "failed", "cancelled")


@pytest.mark.parametrize(("a", "b"), [(a, b) for a in STATES for b in STATES if a != b])
def test_transition_table(a, b):
    assert ai_jobs.can_transition(a, b) == ((a, b) in ALLOWED)


def test_invalid_transitions_are_rejected_and_final_states_are_final(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    with pytest.raises(HttpError) as e:
        ai_jobs.transition(job["id"], "succeeded")                        # pending cannot jump to succeeded
    assert e.value.status == 409 and e.value.code == "invalid_transition"
    ai_jobs.transition(job["id"], "running")
    ai_jobs.transition(job["id"], "succeeded")
    for to in ("running", "pending", "failed", "cancelled", "queued"):
        with pytest.raises(HttpError):
            ai_jobs.transition(job["id"], to)
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "succeeded"


# ---------------- creating jobs ----------------

def test_create_persists_the_job_and_one_workflow_run(ai_env):
    job, existing = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3})
    assert existing is False and job["status"] == "pending" and job["provider"] == "anthropic_api"
    assert job["task_type"] == job["stage"] == "topic_research" and json.loads(job["input_json"]) == {"count": 3}
    assert job["max_retries"] == 3 and job["retry_count"] == 0 and job["run_number"] == 1 and job["lease_owner"] is None
    runs = all_rows("SELECT * FROM workflow_runs WHERE id = ?", job["workflow_run_id"])
    assert len(runs) == 1 and runs[0]["status"] == "running" and runs[0]["trigger_kind"] == "ai_job"
    assert [e["event_type"] for e in all_rows("SELECT event_type FROM ai_job_events WHERE job_id = ?", job["id"])] == ["created"]


def test_invalid_brand_task_stage_and_input_are_rejected(ai_env, monkeypatch):
    for args, status, code in [(("nope", "topic_research"), 400, "error"), (("ridhi", "write_poems"), 400, "unsupported_task"),
                               (("ridhi", "topic_research", {"count": 99}), 400, "error"), (("ridhi", "topic_research", {"extra": 1}), 400, "error"),
                               (("ridhi", "topic_research", "text"), 400, "error"), (("ridhi", "content_generation", {}), 400, "error")]:
        with pytest.raises(HttpError) as e:
            ai_jobs.create_job(None, *args)
        assert (e.value.status, e.value.code) == (status, code), args
    monkeypatch.setitem(ai_jobs.TASKS, "approve", "topic_approval")        # a stage that belongs to a person
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "ridhi", "approve")
    assert e.value.code == "unsupported_stage"
    assert all_rows("SELECT id FROM ai_jobs") == []


def test_no_job_is_created_when_no_executor_is_configured(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "anthropic_api_key", "")
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "ridhi", "topic_research")
    assert (e.value.status, e.value.code) == (412, "pending_setup")
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    monkeypatch.setattr(ai_env, "ai_worker_url", "")
    with pytest.raises(HttpError) as e2:
        ai_jobs.create_job(None, "ridhi", "topic_research")
    assert e2.value.code == "pending_setup"
    monkeypatch.setattr(ai_env, "ai_execution_mode", "disabled")
    with pytest.raises(HttpError) as e3:
        ai_jobs.create_job(None, "ridhi", "topic_research")
    assert e3.value.code == "pending_setup"
    assert all_rows("SELECT id FROM ai_jobs") == [] and all_rows("SELECT id FROM workflow_runs WHERE trigger_kind = 'ai_job'") == []


def test_provider_status_names_what_is_missing(ai_env, monkeypatch):
    assert ai_jobs.provider_status()["state"] == "ready"
    monkeypatch.setattr(ai_env, "anthropic_api_key", "")
    p = ai_jobs.provider_status()
    assert (p["state"], p["missing"]) == ("pending_setup", "anthropic_api_key")
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    p = ai_jobs.provider_status()
    assert (p["state"], p["missing"]) == ("pending_setup", "worker_config")
    monkeypatch.setattr(ai_env, "ai_execution_mode", "disabled")
    assert ai_jobs.provider_status()["state"] == "disabled"
    monkeypatch.setattr(ai_env, "ai_execution_mode", "externl_worker")   # a typo is not "disabled"
    p = ai_jobs.provider_status()
    assert (p["state"], p["missing"]) == ("pending_setup", "execution_mode") and "externl_worker" in p["reason"]


def test_paused_brand_cannot_get_jobs(ai_env):
    run("INSERT INTO automation_state (brand_id, paused, reason) VALUES ('cpc', 1, 'test')")
    try:
        with pytest.raises(HttpError) as e:
            ai_jobs.create_job(None, "cpc", "topic_research")
        assert e.value.status == 423
    finally:
        run("DELETE FROM automation_state WHERE brand_id = 'cpc'")


def test_repeated_request_returns_the_same_job(ai_env):
    a, ea = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    b, eb = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})          # identical, still active
    c, ec = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3})          # different input: its own job
    assert (ea, eb, ec) == (False, True, False) and a["id"] == b["id"] != c["id"]
    assert len(all_rows("SELECT id FROM ai_jobs")) == 2
    ai_jobs.transition(a["id"], "running")
    ai_jobs.transition(a["id"], "succeeded")
    d, ed = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})          # the earlier one is finished: a new job is fine
    assert ed is False and d["id"] != a["id"]


def test_idempotency_key_is_honoured_even_after_the_job_finished(ai_env):
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", None, "daily-ridhi-2026-11-04")
    ai_jobs.transition(a["id"], "running")
    ai_jobs.transition(a["id"], "failed")
    b, existing = ai_jobs.create_job(None, "ridhi", "topic_research", None, "daily-ridhi-2026-11-04")
    assert existing is True and b["id"] == a["id"]
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "cpc", "topic_research", None, "daily-ridhi-2026-11-04")
    assert e.value.code == "idempotency_conflict"
    with pytest.raises(HttpError):
        ai_jobs.create_job(None, "ridhi", "topic_research", None, "bad key!")


def test_content_generation_needs_an_approved_topic_without_an_article(ai_env):
    proposed, approved = make_topic("proposed", title="AIT proposed one"), make_topic("approved", title="AIT approved one")
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": proposed})
    assert e.value.code == "topic_not_approved"
    with pytest.raises(HttpError):
        ai_jobs.create_job(None, "cpc", "content_generation", {"topic_id": approved})        # another brand's topic
    job, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": approved})
    assert json.loads(job["input_json"]) == {"topic_id": approved}


# ---------------- claiming, leases, recovery ----------------

def _fake_topics(monkeypatch, result=None):
    calls = []

    def fake(b, st, titles, products, queries, count, focus="", events=None):
        calls.append((b.id, count))
        return (result or TOPIC_RESULT), "test-model"
    monkeypatch.setattr(claude, "research_topics", fake)
    return calls


def test_a_job_is_claimed_by_exactly_one_executor(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    first = ai_jobs.claim_next("runner-A")
    second = ai_jobs.claim_next("runner-B")
    assert first and first["id"] == job["id"] and first["status"] == "running" and first["lease_owner"].startswith("runner-A:") and first["attempts"] == 1
    assert second is None
    assert first["lease_expires_at"] > first["updated_at"]


def test_a_stale_executor_cannot_write_after_losing_the_lease(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    token_a = ai_jobs.claim_next("runner-A")["lease_owner"]
    ai_jobs.recover(startup=True)                                  # runner-A died: the job goes back to pending
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "pending"
    run("UPDATE ai_jobs SET next_attempt_at = NULL WHERE id = ?", job["id"])                      # skip the short backoff
    token_b = ai_jobs.claim_next("runner-B")["lease_owner"]
    assert token_b != token_a
    assert ai_jobs._update(job["id"], "succeeded", owner=token_a, progress=100) is None          # A is a zombie: ignored
    assert get("SELECT status, lease_owner FROM ai_jobs WHERE id = ?", job["id"]) == {"status": "running", "lease_owner": token_b}


def test_interrupted_jobs_are_requeued_then_failed_when_the_budget_is_used(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("runner-A")
    run("UPDATE ai_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])       # lease expired
    assert ai_jobs.recover()["requeued"] == 1
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["retry_count"], j["lease_owner"]) == ("pending", 1, None) and "Interrupted" in j["error"]
    assert get("SELECT status FROM workflow_runs WHERE id = ?", j["workflow_run_id"])["status"] == "running"      # the run follows the job
    run("UPDATE ai_jobs SET status = 'running', retry_count = max_retries, lease_owner = 'x', lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])
    ai_jobs.recover()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert j["status"] == "failed" and j["error_kind"] == "interrupted"
    assert get("SELECT status FROM workflow_runs WHERE id = ?", j["workflow_run_id"])["status"] == "failed"


def test_startup_recovery_requeues_running_jobs_but_the_old_sweep_leaves_their_runs_alone(ai_env):
    from flowmerce.modules.seo.services.runs import sweep_interrupted_runs
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("old-process")
    sweep_interrupted_runs()
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "running"       # not marked failed behind the job's back
    assert ai_jobs.recover_on_startup()["requeued"] == 1
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "pending"


def test_pending_jobs_from_another_execution_mode_fail_instead_of_hanging(ai_env, monkeypatch):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    assert ai_jobs.recover()["wrong_mode"] == 1
    assert get("SELECT error_kind FROM ai_jobs WHERE id = ?", job["id"])["error_kind"] == "provider_changed"


def test_graceful_shutdown_hands_running_jobs_back_without_using_a_retry(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("runner-A")
    assert ai_jobs.release_owned("runner-A") == 1
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["lease_owner"], j["retry_count"]) == ("pending", None, 0)


def test_concurrency_is_bounded(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_max_concurrency", 1)
    for n in range(3):
        ai_jobs.create_job(None, "ridhi", "topic_research", {"count": n + 1})
    gate, entered = threading.Event(), threading.Event()

    def slow(b, st, titles, products, queries, count, focus="", events=None):
        entered.set()
        gate.wait(5)
        return TOPIC_RESULT, "test-model"
    monkeypatch.setattr(claude, "research_topics", slow)
    runner = ai_jobs.Runner(owner="runner-T", poll_seconds=0.05)
    try:
        assert runner.tick() == 1                                  # one slot: one job claimed
        assert entered.wait(5)
        assert runner.tick() == 0                                  # still busy: nothing else is taken
        assert len(all_rows("SELECT id FROM ai_jobs WHERE status = 'running'")) == 1
        assert len(all_rows("SELECT id FROM ai_jobs WHERE status = 'pending'")) == 2
    finally:
        gate.set()
        runner.stop(timeout=5)


def test_runner_stop_returns_unfinished_work_to_the_queue(ai_env, monkeypatch):
    ai_jobs.create_job(None, "ridhi", "topic_research")
    gate, entered = threading.Event(), threading.Event()

    def stuck(*a, **k):
        entered.set()
        gate.wait(5)
        return TOPIC_RESULT, "test-model"
    monkeypatch.setattr(claude, "research_topics", stuck)
    runner = ai_jobs.Runner(owner="runner-S")
    assert runner.tick() == 1 and entered.wait(5)
    runner.stop(timeout=0.2)                                       # the call is still in flight when we stop
    j = all_rows("SELECT * FROM ai_jobs")[0]
    assert (j["status"], j["lease_owner"]) == ("pending", None)
    gate.set()
    time.sleep(0.3)                                                # the abandoned call finishes later: its result must be discarded
    assert get("SELECT status FROM ai_jobs WHERE id = ?", j["id"])["status"] == "pending"
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


# ---------------- direct execution ----------------

def test_topic_research_job_runs_and_proposes_topics(ai_env, monkeypatch):
    calls = _fake_topics(monkeypatch)
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    assert ai_jobs.run_pending() == [job["id"]]
    j = ai_jobs.get_job(job["id"])
    assert j["status"] == "succeeded" and j["progress"] == 100 and j["resultAvailable"] and j["result"]["added"] == 2
    assert calls == [("ridhi", 2)]
    topics = all_rows("SELECT status, source, created_by FROM topics WHERE title LIKE 'AIT %'")
    assert len(topics) == 2 and {t["status"] for t in topics} == {"proposed"} and {t["created_by"] for t in topics} == {None}
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "succeeded"
    assert len(all_rows("SELECT id FROM workflow_runs WHERE trigger_kind = 'ai_job'")) == 1
    assert [e["event_type"] for e in j["events"]] == ["created", "started", "succeeded"]


def test_content_job_saves_a_draft_for_the_approved_topic_only(ai_env, monkeypatch):
    tid = make_topic("approved")
    monkeypatch.setattr(claude, "generate_draft", lambda b, st, topic, links: (DRAFT_RESULT, "test-model"))
    job, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    ai_jobs.run_pending()
    j = ai_jobs.get_job(job["id"])
    assert j["status"] == "succeeded" and j["result"]["kind"] == "article"
    a = get("SELECT * FROM articles WHERE id = ?", j["result"]["articleId"])
    assert (a["status"], a["topic_id"], a["origin"], a["shopify_published"], a["approved_hash"]) == ("draft", tid, "claude", 0, None)
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "in_production"


def test_a_job_that_loses_its_topic_fails_without_writing(ai_env, monkeypatch):
    tid = make_topic("approved")
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (DRAFT_RESULT, "m"))
    job, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    run("UPDATE topics SET status = 'rejected' WHERE id = ?", tid)           # a person changed their mind meanwhile
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert j["status"] == "failed" and all_rows("SELECT id FROM articles WHERE title LIKE 'AIT %'") == []


def test_invalid_claude_output_fails_the_job_and_stores_nothing(ai_env, monkeypatch):
    _fake_topics(monkeypatch, {"topics": [{"title": "AIT x", "primary_keyword": "ait x", "secondary_keywords": [], "intent": "bogus", "rationale": ""}]})
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["error_kind"]) == ("failed", "invalid_result") and all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


@pytest.mark.parametrize(("error", "final", "kind"), [
    (claude.ClaudeError("auth", "auth"), "failed", "auth"),
    (claude.ClaudeError("bad request", "invalid_request"), "failed", "invalid_request"),
    (claude.ClaudeError("slow", "timeout", ambiguous=True), "failed", "timeout"),           # a timeout is never retried automatically
    (claude.ClaudeError("busy", "rate_limit", retryable=True, retry_after=7), "pending", "rate_limit"),
    (claude.ClaudeError("down", "server", retryable=True), "pending", "server"),
])
def test_failure_policy_for_claude_errors(ai_env, monkeypatch, error, final, kind):
    def boom(*a, **k):
        raise error
    monkeypatch.setattr(claude, "research_topics", boom)
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["error_kind"]) == (final, kind)
    if final == "pending":
        assert j["retry_count"] == 1 and j["next_attempt_at"] and j["lease_owner"] is None
    if kind == "timeout":
        assert "may have been processed" in j["error"] and j["retry_count"] == 0


def test_retry_after_is_respected_and_the_budget_ends_in_failure(ai_env, monkeypatch):
    def limited(*a, **k):
        raise claude.ClaudeError("busy", "rate_limit", retryable=True, retry_after=42)
    monkeypatch.setattr(claude, "research_topics", limited)
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    wait = (time.mktime(time.strptime(j["next_attempt_at"][:19], "%Y-%m-%dT%H:%M:%S")) - time.mktime(time.gmtime()))
    assert 38 <= wait <= 46                                                                  # about 42 seconds
    assert ai_jobs.run_pending() == []                                                       # not due yet: not claimed
    for _ in range(3):
        run("UPDATE ai_jobs SET next_attempt_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])
        ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["retry_count"], j["attempts"]) == ("failed", 3, 4)


def test_manual_retry_starts_a_new_run_and_reopens_the_same_workflow_run(ai_env, monkeypatch):
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (_ for _ in ()).throw(claude.ClaudeError("auth", "auth")))
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.run_pending()
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "failed"
    assert ai_jobs.public(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]))["retryAvailable"] is True
    again = ai_jobs.retry_job(None, job["id"])
    assert (again["status"], again["run_number"], again["retry_count"], again["error"], again["last_sequence"]) == ("pending", 2, 0, None, 0)
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "running"
    with pytest.raises(HttpError) as e:
        ai_jobs.retry_job(None, job["id"])                                                   # only a failed job can be retried
    assert e.value.status == 409
    _fake_topics(monkeypatch)
    ai_jobs.run_pending()
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "succeeded"
    assert len(all_rows("SELECT id FROM workflow_runs WHERE trigger_kind = 'ai_job'")) == 1


def test_retry_is_blocked_when_an_identical_job_is_active(ai_env):
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.transition(a["id"], "failed")
    ai_jobs.create_job(None, "ridhi", "topic_research")                                      # a new identical job is allowed once a is final
    with pytest.raises(HttpError) as e:
        ai_jobs.retry_job(None, a["id"])
    assert e.value.code == "duplicate_active_job"


def test_cancel_discards_a_result_that_arrives_later(ai_env, monkeypatch):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")

    def cancelled_midway(*a, **k):
        ai_jobs.cancel_job(None, job["id"])
        return TOPIC_RESULT, "test-model"
    monkeypatch.setattr(claude, "research_topics", cancelled_midway)
    ai_jobs.run_pending()
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "cancelled"
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "skipped"


def test_public_job_view_has_no_internal_fields(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("runner-A")
    view = ai_jobs.public(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]))
    assert "lease_owner" not in view and "leaseOwner" not in json.dumps(view) and "runner-A" not in json.dumps(view)


# ---------------- result validation ----------------

def test_valid_results_are_accepted():
    assert len(ai_results.validate("topic_research", TOPIC_RESULT)["topics"]) == 2
    assert ai_results.validate("content_generation", DRAFT_RESULT)["handle"] == "ait-hand-block-printing-guide"


@pytest.mark.parametrize("bad", [
    {}, {"topics": []}, {"topics": "x"}, {"topics": [{"title": "t"}]}, {"topics": TOPIC_RESULT["topics"], "approve": True},
    {"topics": [{**TOPIC_RESULT["topics"][0], "intent": "persuasive"}]}, {"topics": [{**TOPIC_RESULT["topics"][0], "status": "approved"}]},
    {"topics": [{**TOPIC_RESULT["topics"][0], "title": "x" * 300}]}, {"topics": [{**TOPIC_RESULT["topics"][0], "secondary_keywords": ["a"] * 11}]},
    {"topics": [{**TOPIC_RESULT["topics"][0], "title": "<script>alert(1)</script>"}]}, {"topics": [TOPIC_RESULT["topics"][0]] * 51},
    {"topics": [{**TOPIC_RESULT["topics"][0], "title": "bad\x00char"}]},
])
def test_invalid_topic_results_are_rejected(bad):
    with pytest.raises(ai_results.ResultError):
        ai_results.validate("topic_research", bad)


@pytest.mark.parametrize("patch", [
    {"body_html": "<p>too short</p>"}, {"handle": "Not A Slug"}, {"status": "approved"}, {"published": True}, {"title": ""},
    {"body_html": DRAFT_RESULT["body_html"] + "<script>steal()</script>"}, {"body_html": DRAFT_RESULT["body_html"] + '<p onclick="x()">hi</p>'},
    {"body_html": DRAFT_RESULT["body_html"] + '<a href="javascript:alert(1)">x</a>'}, {"summary_html": "<iframe src=//evil></iframe>"},
    {"tags": ["a"] * 31}, {"meta_description": "x" * 401}, {"body_html": "<p>" + "word " * 60000 + "</p>"}, {"tags": "not a list"},
])
def test_invalid_draft_results_are_rejected(patch):
    with pytest.raises(ai_results.ResultError):
        ai_results.validate("content_generation", {**DRAFT_RESULT, **patch})


def test_results_are_size_limited_and_task_bound():
    with pytest.raises(ai_results.ResultError):
        ai_results.validate("topic_research", {"topics": [{**TOPIC_RESULT["topics"][0], "rationale": "y" * 1999}] * 50 + [{"junk": "z" * 300_000}]})
    with pytest.raises(ai_results.ResultError):
        ai_results.validate("publish_article", {"ok": True})
    with pytest.raises(ai_results.ResultError):
        ai_results.validate("topic_research", ["not", "an", "object"])


def test_storing_the_same_topics_twice_does_not_duplicate_them(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    clean = ai_results.validate("topic_research", TOPIC_RESULT)
    first = ai_results.store(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]), clean)
    second = ai_results.store(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]), clean)
    assert (first["added"], second["added"], second["duplicatesSkipped"]) == (2, 0, 2)


def test_html_in_a_draft_is_sanitised_on_the_way_in(ai_env, monkeypatch):
    tid = make_topic("approved")
    job, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    clean = ai_results.validate("content_generation", {**DRAFT_RESULT, "body_html": DRAFT_RESULT["body_html"] + '<p style="x:y">ok <font color=red>f</font></p>'})
    summary = ai_results.store(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]), clean)
    body = get("SELECT body_html FROM articles WHERE id = ?", summary["articleId"])["body_html"]
    assert "style=" not in body and "<font" not in body and "ok" in body


# ---------------- the Claude client ----------------

def _http_error(cls, status, headers=None):
    req = httpx.Request("POST", "https://api.invalid/v1/messages")
    return cls("boom", response=httpx.Response(status, headers=headers or {}, request=req), body=None)


class FakeClient:
    """Stands in for the Anthropic client: each call pops the next scripted outcome (an exception to raise or a message)."""

    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **params):
        self.calls += 1
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Stream(outcome)


class _Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


def _message(text='{"ok": true}', stop="end_turn"):
    return SimpleNamespace(model="test-model", stop_reason=stop, content=[SimpleNamespace(type="text", text=text)], usage=SimpleNamespace(input_tokens=11, output_tokens=22), _request_id="req_test")


@pytest.fixture
def fake_claude(monkeypatch, ai_env):
    waits = []
    monkeypatch.setattr(claude.time, "sleep", waits.append)
    monkeypatch.setattr(ai_env, "claude_fallbacks", False)
    monkeypatch.setattr(ai_env, "claude_max_retries", 2)

    def install(script):
        client = FakeClient(script)
        monkeypatch.setattr(claude, "_get_client", lambda: client)
        return client
    install.waits = waits
    return install


def test_rate_limit_is_retried_using_retry_after(fake_claude):
    client = fake_claude([_http_error(anthropic.RateLimitError, 429, {"retry-after": "7"}), _message()])
    data, model = claude._structured("sys", "prompt", {}, "low")
    assert data == {"ok": True} and model == "test-model" and client.calls == 2 and fake_claude.waits == [7.0]


def test_transient_server_and_connection_errors_are_retried_a_bounded_number_of_times(fake_claude):
    req = httpx.Request("POST", "https://api.invalid")
    client = fake_claude([_http_error(anthropic.InternalServerError, 500), anthropic.APIConnectionError(request=req), _message()])
    assert claude._structured("s", "p", {}, "low")[0] == {"ok": True} and client.calls == 3 and fake_claude.waits == [2.0, 4.0]
    client = fake_claude([_http_error(anthropic.InternalServerError, 503)] * 3)
    with pytest.raises(claude.ClaudeError) as e:
        claude._structured("s", "p", {}, "low")
    assert e.value.kind == "server" and e.value.retryable and client.calls == 3                  # 1 try + 2 retries, then it gives up


@pytest.mark.parametrize(("error", "kind"), [
    (_http_error(anthropic.AuthenticationError, 401), "auth"), (_http_error(anthropic.PermissionDeniedError, 403), "auth"),
    (_http_error(anthropic.BadRequestError, 400), "invalid_request"),
])
def test_auth_and_invalid_requests_are_never_retried(fake_claude, error, kind):
    client = fake_claude([error, _message()])
    with pytest.raises(claude.ClaudeError) as e:
        claude._structured("s", "p", {}, "low")
    assert e.value.kind == kind and not e.value.retryable and client.calls == 1 and fake_claude.waits == []
    assert isinstance(e.value, RuntimeError)                                                      # older callers that catch RuntimeError keep working


def test_a_timeout_is_not_retried_because_the_request_may_have_run(fake_claude):
    client = fake_claude([anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.invalid")), _message()])
    with pytest.raises(claude.ClaudeError) as e:
        claude._structured("s", "p", {}, "low")
    assert e.value.kind == "timeout" and e.value.ambiguous and not e.value.retryable and client.calls == 1


def test_bad_outputs_are_classified(fake_claude):
    for message, kind in [(_message(stop="refusal"), "refusal"), (_message(stop="max_tokens"), "truncated"), (_message(text="not json"), "invalid_output"), (_message(text="[1]"), "invalid_output")]:
        fake_claude([message])
        with pytest.raises(claude.ClaudeError) as e:
            claude._structured("s", "p", {}, "low")
        assert e.value.kind == kind


def test_usage_is_recorded_without_the_prompt_or_the_key(fake_claude, ai_env):
    fake_claude([_message()])
    claude._structured("SECRET-SYSTEM-TEXT", "SECRET-PROMPT-TEXT", {}, "low")
    u = claude.take_usage()
    assert (u["model"], u["inputTokens"], u["outputTokens"], u["requestId"], u["attempts"]) == ("test-model", 11, 22, "req_test", 1)
    text = json.dumps(u)
    assert "SECRET" not in text and ai_env.anthropic_api_key not in text
    assert claude.take_usage() == {}                                                              # taking it clears it


# ---------------- leases cover the slowest legitimate call ----------------

def test_the_lease_is_never_shorter_than_a_slow_claude_call_with_retries(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_lease_seconds", 60)
    monkeypatch.setattr(ai_env, "claude_timeout", 600)
    monkeypatch.setattr(ai_env, "claude_max_retries", 2)
    assert ai_jobs.lease_seconds() == 600 * 3 + 120
    monkeypatch.setattr(ai_env, "ai_lease_seconds", 10_000)
    assert ai_jobs.lease_seconds() == 10_000
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 100)
    assert ai_jobs.dispatch_lease_seconds() == 230 and ai_jobs.dispatch_lease_seconds() > ai_env.ai_worker_timeout
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 5)
    assert ai_jobs.dispatch_lease_seconds() == 120


def test_a_job_claimed_now_is_not_recovered_while_its_call_is_still_within_the_lease(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("runner-A")
    assert ai_jobs.recover()["requeued"] == 0
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "running"


def test_interrupted_jobs_are_settled_at_startup_even_when_ai_execution_is_off(ai_env, monkeypatch):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.claim_next("crashed-process")
    monkeypatch.setattr(ai_env, "ai_execution_mode", "disabled")
    assert ai_jobs.start_runner() is None                                                     # nothing runs...
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["lease_owner"]) == ("pending", None)                               # ...but the crashed job is no longer "running"
    assert ai_jobs.cancel_job(None, job["id"])["status"] == "cancelled"                       # and a person can still cancel it
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "skipped"


# ---------------- per-claim lease tokens ----------------

def test_a_reclaimed_job_ignores_the_first_executions_late_result_in_a_real_runner(ai_env, monkeypatch):
    """The real Runner scenario: claim -> lease expires -> recovered and reclaimed by the SAME runner -> the first execution
    finishes late. Its result must be rejected and the second execution must keep the job."""
    from tests.fixtures.seo import make_topics
    monkeypatch.setattr(ai_env, "ai_max_concurrency", 2)
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 5})
    gates, entered, seen = [threading.Event(), threading.Event()], [threading.Event(), threading.Event()], []
    lock = threading.Lock()

    def fake(b, st, titles, products, queries, count, focus="", events=None):
        with lock:
            n = len(seen)
            seen.append(n)
        entered[n].set()
        assert gates[n].wait(10)
        return (make_topics(1, "AIT stale") if n == 0 else TOPIC_RESULT), "test-model"
    monkeypatch.setattr(claude, "research_topics", fake)
    runner = ai_jobs.Runner(owner="runner-R", poll_seconds=0.05)         # ticked by hand: no background thread
    try:
        assert runner.tick() == 1 and entered[0].wait(5)
        first = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        token1 = first["lease_owner"]
        future1 = next(iter(runner._futures))
        run("UPDATE ai_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])      # the lease expires
        assert runner.tick() == 0                                          # recovery requeues it (still in backoff)
        assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "pending"
        run("UPDATE ai_jobs SET next_attempt_at = NULL WHERE id = ?", job["id"])
        assert runner.tick() == 1 and entered[1].wait(5)                   # the same runner reclaims it
        second = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        token2 = second["lease_owner"]
        assert token2 != token1 and token1.startswith("runner-R:") and token2.startswith("runner-R:")   # one runner, two distinct claims
        assert second["status"] == "running" and second["attempts"] == 2

        gates[0].set()                                                     # the first execution now tries to save its result
        future1.result(timeout=5)
        j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        assert (j["status"], j["lease_owner"], j["result_json"]) == ("running", token2, None)           # the old result changed nothing
        assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []
        assert "succeeded" not in [e["event_type"] for e in all_rows("SELECT event_type FROM ai_job_events WHERE job_id = ?", job["id"])]

        gates[1].set()                                                     # the second execution finishes normally
        for f in list(runner._futures):
            f.result(timeout=5)
        j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
        assert j["status"] == "succeeded" and json.loads(j["result_json"])["added"] == 2
        assert {t["title"] for t in all_rows("SELECT title FROM topics WHERE title LIKE 'AIT %'")} == {t["title"] for t in TOPIC_RESULT["topics"]}
    finally:
        gates[0].set()
        gates[1].set()
        runner.stop(timeout=5)


def test_a_token_stops_working_the_moment_its_lease_expires(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    token = ai_jobs.claim_next("runner-A")["lease_owner"]
    assert ai_jobs._update(job["id"], "running", owner=token, message="still mine") is not None       # valid while the lease is live
    run("UPDATE ai_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])
    assert ai_jobs._update(job["id"], "succeeded", owner=token, progress=100) is None                   # expired: refused even though nobody reclaimed it
    assert ai_jobs._after_failure(job["id"], token, "late failure", "x", False) is None
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["error"]) == ("running", None)


def test_every_claim_gets_a_unique_token(ai_env):
    tokens = set()
    for n in range(5):
        ai_jobs.create_job(None, "ridhi", "topic_research", {"count": n + 1})
        tokens.add(ai_jobs.claim_next("runner-A")["lease_owner"])
    assert len(tokens) == 5 and all(t.startswith("runner-A:") for t in tokens)


def test_releasing_one_runner_never_releases_anothers_claims(ai_env):
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 1})
    b, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    ai_jobs.claim_next("runner-A")
    token_b = ai_jobs.claim_next("runner-B")["lease_owner"]
    assert ai_jobs.release_owned("runner-A") == 1
    assert get("SELECT status FROM ai_jobs WHERE id = ?", a["id"])["status"] == "pending"
    assert get("SELECT status, lease_owner FROM ai_jobs WHERE id = ?", b["id"]) == {"status": "running", "lease_owner": token_b}
    assert ai_jobs.release_owned("runner") == 0                                                    # a prefix of a name is not a match


# ---------------- idempotency compares the whole request ----------------

def test_same_key_and_same_request_returns_the_job_whatever_the_key_order(ai_env):
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3, "focus": "table linen"}, "key-same-request")
    b, existing = ai_jobs.create_job(None, "ridhi", "topic_research", {"focus": "table linen", "count": 3}, "key-same-request")
    assert existing is True and b["id"] == a["id"]


@pytest.mark.parametrize(("brand", "task", "inp"), [
    ("cpc", "topic_research", {"count": 3}),                       # different brand
    ("ridhi", "topic_research", {"count": 4}),                     # different input
    ("ridhi", "topic_research", {"count": 3, "focus": "other"}),   # extra input
    ("ridhi", "content_generation", "topic"),                      # different task type (input filled in below)
])
def test_same_key_with_a_different_request_is_a_conflict(ai_env, brand, task, inp):
    ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3}, "key-conflict-1")
    if task == "content_generation":
        inp = {"topic_id": make_topic("approved")}
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, brand, task, inp, "key-conflict-1")
    assert (e.value.status, e.value.code) == (409, "idempotency_conflict")
    assert len(all_rows("SELECT id FROM ai_jobs")) == 1


def test_default_count_and_explicit_default_count_are_the_same_request(ai_env):
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", None, "key-default-count")
    assert json.loads(a["input_json"]) == {"count": 5}
    b, existing = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 5}, "key-default-count")
    assert existing is True and b["id"] == a["id"]


def test_a_replay_still_works_after_the_topic_was_used_up(ai_env, monkeypatch):
    tid = make_topic("approved")
    monkeypatch.setattr(claude, "generate_draft", lambda *a: (DRAFT_RESULT, "m"))
    a, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid}, "key-replay-draft")
    ai_jobs.run_pending()
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "in_production"
    b, existing = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid}, "key-replay-draft")     # a client retry of the same call
    assert existing is True and b["id"] == a["id"]
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid}, "a-new-key-1")                      # but a NEW request is refused
    assert e.value.code == "topic_not_approved"


def test_concurrent_identical_requests_make_one_job(ai_env):
    results, errors = [], []

    def go():
        try:
            results.append(ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2}, "key-concurrent-same"))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert errors == [] and len({j["id"] for j, _ in results}) == 1 and sum(1 for _, existing in results if not existing) == 1
    assert len(all_rows("SELECT id FROM ai_jobs")) == 1 and len(all_rows("SELECT id FROM workflow_runs WHERE trigger_kind = 'ai_job'")) == 1


def test_concurrent_requests_with_one_key_but_different_input_make_one_job_and_conflicts(ai_env):
    outcomes = []

    def go(count):
        try:
            outcomes.append(("ok", ai_jobs.create_job(None, "ridhi", "topic_research", {"count": count}, "key-concurrent-mixed")[0]["id"]))
        except HttpError as e:
            outcomes.append(("err", e.code))
    threads = [threading.Thread(target=go, args=(3 + i % 2,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert len(all_rows("SELECT id FROM ai_jobs")) == 1
    assert len({v for k, v in outcomes if k == "ok"}) == 1
    assert {v for k, v in outcomes if k == "err"} == {"idempotency_conflict"}


# ---------------- requested topic count ----------------

@pytest.mark.parametrize("n", [1, 5, 20])
def test_a_result_may_hold_at_most_the_requested_number_of_topics(ai_env, n):
    from tests.fixtures.seo import make_topics
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": n})
    row = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert ai_results.requested_count(row) == n
    assert len(ai_results.validate("topic_research", make_topics(n), n)["topics"]) == n
    assert len(ai_results.validate("topic_research", make_topics(1), n)["topics"]) == 1                 # fewer is fine
    with pytest.raises(ai_results.ResultError) as e:
        ai_results.validate("topic_research", make_topics(n + 1), n)
    assert f"only {n}" in str(e.value)


def test_the_configured_default_count_applies_when_none_was_asked(ai_env):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    assert json.loads(job["input_json"]) == {"count": 5}                                                  # the brand's topicsPerRun
    assert ai_results.requested_count(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])) == 5
    run("INSERT INTO brand_settings (brand_id, settings_json, updated_at) VALUES ('cpc', ?, 't')", json.dumps({"topicsPerRun": 3}))
    try:
        c, _ = ai_jobs.create_job(None, "cpc", "topic_research")
        assert json.loads(c["input_json"]) == {"count": 3}
    finally:
        run("DELETE FROM brand_settings WHERE brand_id = 'cpc'")


@pytest.mark.parametrize("bad", [0, 21, -1, "5", 2.5, True])
def test_the_requested_count_itself_is_validated(ai_env, bad):
    with pytest.raises(HttpError):
        ai_jobs.create_job(None, "ridhi", "topic_research", {"count": bad})


@pytest.mark.parametrize("n", [1, 5, 20])
def test_claude_returning_more_topics_than_requested_fails_the_job_and_creates_none(ai_env, monkeypatch, n):
    from tests.fixtures.seo import make_topics
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (make_topics(n + 1), "m"))
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": n})
    ai_jobs.run_pending()
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert (j["status"], j["error_kind"]) == ("failed", "invalid_result") and "requested" in j["error"]
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (make_topics(n), "m"))
    again = ai_jobs.retry_job(None, job["id"])
    ai_jobs.run_pending()
    assert get("SELECT status FROM ai_jobs WHERE id = ?", again["id"])["status"] == "succeeded"
    assert len(all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %' AND status = 'proposed'")) == n                      # proposed only: a person approves


# ---------------- pausing a brand ----------------

def _pause(brand):
    run("INSERT INTO automation_state (brand_id, paused, reason) VALUES (?, 1, 'test') ON CONFLICT(brand_id) DO UPDATE SET paused = 1", brand)


def _resume(brand):
    run("DELETE FROM automation_state WHERE brand_id = ?", brand)


@pytest.fixture
def unpause():
    yield
    run("DELETE FROM automation_state")


def test_a_paused_brands_pending_jobs_are_not_claimed_until_it_is_resumed(ai_env, monkeypatch, unpause):
    calls = []
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: calls.append(1) or (TOPIC_RESULT, "m"))
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 5})                  # created while automation is active
    _pause("ridhi")                                                                              # paused before the runner gets to it
    assert ai_jobs.claim_next("runner-A") is None and ai_jobs.run_pending() == []
    runner = ai_jobs.Runner(owner="runner-P")
    try:
        assert runner.tick() == 0                                                                # the real runner does not start it either
    finally:
        runner.stop(timeout=2)
    assert calls == [] and get("SELECT status, attempts, lease_owner FROM ai_jobs WHERE id = ?", job["id"]) == {"status": "pending", "attempts": 0, "lease_owner": None}
    view = ai_jobs.public(get("SELECT * FROM ai_jobs WHERE id = ?", job["id"]))
    assert view["brandPaused"] is True and view["waitingForResume"] is True and view["cancellable"] is True
    _resume("ridhi")                                                                             # resuming makes it eligible again
    assert ai_jobs.run_pending() == [job["id"]] and calls == [1]
    assert get("SELECT status FROM ai_jobs WHERE id = ?", job["id"])["status"] == "succeeded"


def test_pausing_one_brand_does_not_hold_back_another(ai_env, monkeypatch, unpause):
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (TOPIC_RESULT, "m"))
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 5})
    b, _ = ai_jobs.create_job(None, "cpc", "topic_research", {"count": 5})
    _pause("ridhi")
    assert ai_jobs.run_pending() == [b["id"]]
    assert get("SELECT status FROM ai_jobs WHERE id = ?", a["id"])["status"] == "pending"
    run("DELETE FROM topics WHERE brand_id = 'cpc' AND title LIKE 'AIT %'")


def test_manual_retry_of_a_paused_brands_job_is_refused_with_423(ai_env, unpause):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    ai_jobs.transition(job["id"], "failed", error="boom")
    _pause("ridhi")
    with pytest.raises(HttpError) as e:
        ai_jobs.retry_job(None, job["id"])
    assert (e.value.status, e.value.code) == (423, "paused")
    assert get("SELECT status, run_number FROM ai_jobs WHERE id = ?", job["id"]) == {"status": "failed", "run_number": 1}
    _resume("ridhi")
    assert ai_jobs.retry_job(None, job["id"])["status"] == "pending"


def test_cancelling_is_allowed_while_paused(ai_env, unpause):
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    _pause("ridhi")
    assert ai_jobs.cancel_job(None, job["id"])["status"] == "cancelled"
    assert get("SELECT status FROM workflow_runs WHERE id = ?", job["workflow_run_id"])["status"] == "skipped"


def test_pausing_does_not_stop_a_job_that_is_already_running(ai_env, monkeypatch, unpause):
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (TOPIC_RESULT, "m"))
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 5})
    claimed = ai_jobs.claim_next("runner-A")                                                     # running
    _pause("ridhi")
    assert ai_jobs.recover()["requeued"] == 0                                                    # recovery does not touch it either
    assert get("SELECT status, lease_owner FROM ai_jobs WHERE id = ?", job["id"]) == {"status": "running", "lease_owner": claimed["lease_owner"]}
    ai_jobs.execute(claimed)                                                                      # it carries on and finishes
    j = get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])
    assert j["status"] == "succeeded" and len(all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %' AND status = 'proposed'")) == 2


# ---------------- malformed event fields ----------------

@pytest.mark.parametrize("value", [[], {}, [1], {"a": 1}, 5, 1.5, True, None, "", "nope", ["started"]])
def test_parse_event_rejects_any_non_string_or_unknown_event_type_cleanly(value):
    with pytest.raises(HttpError) as e:
        ai_jobs.parse_event({"event_id": "evt-12345678", "job_id": "j", "event_type": value, "sequence": 1})
    assert e.value.status == 400


@pytest.mark.parametrize("value", [[], {}, [1], {"a": 1}, 5, True, ["running"], "succeeded", "bogus"])
def test_parse_event_rejects_any_bad_status_cleanly(value):
    with pytest.raises(HttpError) as e:
        ai_jobs.parse_event({"event_id": "evt-12345678", "job_id": "j", "event_type": "started", "sequence": 1, "status": value})
    assert e.value.status == 400
