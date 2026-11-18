"""The AI job callbacks on POST /api/hooks/workflow, and the job endpoints, through the real HTTP stack.

The webhook is the one route other computers may reach, so these tests are strict about what a caller can and cannot do: wrong or
missing secret, oversized or malformed bodies, unknown or finished jobs, duplicates, stale and out-of-order events, and every way a
callback might try to approve, publish or overwrite something."""
import asyncio
import json
import uuid

import pytest

from flowmerce.modules.seo import api as api_module
from flowmerce.modules.seo.app import create_app
from flowmerce.modules.seo.db import all_rows, get, run
from flowmerce.modules.seo.services import ai_jobs
from flowmerce.modules.seo.util import HttpError
from tests.fixtures.seo import DRAFT_RESULT, TOPIC_RESULT, local_client, make_topic, remote_client

SECRET = "hook-secret-for-tests"
H = {"X-Requested-With": "blog-ops"}
HOOK = {"X-Workflow-Secret": SECRET}


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def hook_env(ai_env, monkeypatch):
    """External-worker mode with a webhook secret. No worker exists: jobs are moved along by callbacks only."""
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    monkeypatch.setattr(ai_env, "ai_worker_url", "http://127.0.0.1:9")
    monkeypatch.setattr(ai_env, "ai_worker_token", "worker-token-for-tests")
    monkeypatch.setattr(ai_env, "workflow_webhook_secret", SECRET)
    return ai_env


@pytest.fixture
def job(hook_env):
    j, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    return j


class Hook:
    """Posts callbacks for one job as a worker on another computer would (no CSRF header, no sign-in), numbering sequences itself."""

    def __init__(self, app, job_id, run_number=1):
        self.c, self.job_id, self.seq, self.run_number = remote_client(app), job_id, 0, run_number

    def body(self, event_type, **extra):
        self.seq += 1
        return {"event_id": f"evt-{uuid.uuid4().hex[:16]}", "job_id": self.job_id, "event_type": event_type, "sequence": self.seq, **extra}

    def send(self, event_type, **extra):
        return self.post(self.body(event_type, **extra))

    def post(self, body, headers=HOOK):
        return self.c.post("/api/hooks/workflow", json=body, headers=headers)


def _job_row(job_id):
    return get("SELECT * FROM ai_jobs WHERE id = ?", job_id)


def _runs_for(job_id):
    return all_rows("SELECT * FROM workflow_runs WHERE details_json LIKE ?", f"%{job_id}%")


# ---------------- authentication ----------------

def test_missing_and_wrong_secret_return_401_and_change_nothing(app, job):
    h = Hook(app, job["id"])
    body = h.body("started")
    assert h.post(body, headers={}).status_code == 401
    assert h.post(body, headers={"X-Workflow-Secret": "wrong"}).status_code == 401
    assert h.post(body, headers={"X-Workflow-Secret": SECRET + "x"}).status_code == 401
    assert _job_row(job["id"])["status"] == "pending" and _job_row(job["id"])["last_sequence"] == 0


def test_secret_is_checked_before_the_body_is_read(app, job):
    big = remote_client(app).post("/api/hooks/workflow", content=b"x" * 500_000, headers={"X-Workflow-Secret": "wrong"})
    assert big.status_code == 401                                                              # not 413: the caller was never allowed that far


def test_webhook_is_disabled_when_no_secret_is_configured(app, job, monkeypatch):
    monkeypatch.setattr(api_module.config, "workflow_webhook_secret", "")
    r = Hook(app, job["id"]).send("started")
    assert r.status_code == 404 and "not enabled" in r.text


# ---------------- request size and shape ----------------

def test_oversized_body_is_rejected_with_a_content_length(app, job):
    r = remote_client(app).post("/api/hooks/workflow", content=b'{"job_id": "' + b"a" * 70_000 + b'"}', headers={**HOOK, "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


def test_oversized_body_is_rejected_without_a_content_length(app, job):
    def chunks():
        for _ in range(100):                                                                   # 100 KB sent as a stream: no Content-Length header at all
            yield b"a" * 1024
    r = remote_client(app).post("/api/hooks/workflow", content=chunks(), headers={**HOOK, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_the_limit_applies_to_real_bytes_not_to_a_lying_header():
    class FakeRequest:
        headers = {"content-length": "10"}                                                     # claims 10 bytes

        async def stream(self):
            for _ in range(80):
                yield b"x" * 1024                                                              # sends 80 KB

    with pytest.raises(HttpError) as e:
        asyncio.run(api_module._read_limited(FakeRequest(), 64 * 1024))
    assert e.value.status == 413


def test_a_body_just_under_the_limit_is_read():
    class Small:
        headers = {}

        async def stream(self):
            yield b"x" * (64 * 1024)

    assert len(asyncio.run(api_module._read_limited(Small(), 64 * 1024))) == 64 * 1024


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", b'"text"', b"null", b'{"job_id": NaN}', b'{"a":', b"\xff\xfe"])
def test_malformed_bodies_are_rejected(app, job, raw):
    r = remote_client(app).post("/api/hooks/workflow", content=raw, headers={**HOOK, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_json"


@pytest.mark.parametrize("patch", [
    {"event_id": "short"}, {"event_id": "has spaces in it!"}, {"event_id": 12345678}, {"event_type": "finished"}, {"event_type": "SUCCEEDED"},
    {"sequence": 0}, {"sequence": -1}, {"sequence": "1"}, {"sequence": 1.5}, {"sequence": True}, {"progress": 101}, {"progress": -1}, {"progress": "50"},
    {"message": "x" * 1001}, {"agent": "x" * 121}, {"external_id": "x" * 201}, {"error": "x" * 2001}, {"unexpected_field": 1}, {"approve": True},
    {"callback_reference": "some-other-job"}, {"occurred_at": "yesterday"}, {"occurred_at": "2026-11-04T10:00:00"}, {"run_number": 0}, {"result": {"topics": []}},
])
def test_strict_validation_rejects_bad_fields(app, job, patch):
    h = Hook(app, job["id"])
    r = h.post({**h.body("progress", progress=10), **patch})
    assert r.status_code == 400, (patch, r.text)
    assert _job_row(job["id"])["status"] == "pending"


def test_status_must_agree_with_the_event_type(app, job):
    h = Hook(app, job["id"])
    for bad in ("succeeded", "bogus", "waiting", "skipped", "", "running "):
        r = h.post(h.body("started", status=bad))
        assert r.status_code == 400 and r.json()["code"] == "invalid_status", bad
    assert h.post(h.body("started", status="running")).status_code == 200
    assert _job_row(job["id"])["status"] == "running"                                           # never silently turned into succeeded


def test_progress_is_not_allowed_on_final_events_and_results_only_on_success(app, job):
    h = Hook(app, job["id"])
    assert h.send("failed", progress=10).status_code == 400
    assert h.send("progress", progress=10, result={"x": 1}).status_code == 400
    assert h.send("succeeded").status_code == 400                                               # success needs a result object
    assert h.send("succeeded", result="text").status_code == 400


# ---------------- job association ----------------

def test_unknown_job_is_rejected(app, hook_env):
    r = Hook(app, str(uuid.uuid4())).send("started")
    assert r.status_code == 404 and r.json()["code"] == "unknown_job"


def test_callbacks_must_match_the_jobs_brand_and_stage(app, job):
    h = Hook(app, job["id"])
    assert h.send("started", brand="cpc").status_code == 409
    assert h.send("started", stage="content_generation").status_code == 409
    assert h.send("started", brand="ridhi", stage="topic_research", callback_reference=job["id"]).status_code == 200


def test_external_id_must_not_change_mid_job(app, job):
    h = Hook(app, job["id"])
    assert h.send("started", external_id="exec-1").status_code == 200
    assert h.send("progress", progress=5, external_id="exec-2").status_code == 409
    assert h.send("progress", progress=5, external_id="exec-1").status_code == 200
    assert _job_row(job["id"])["external_id"] == "exec-1"


def test_callbacks_cannot_target_a_job_this_server_runs_itself(app, hook_env, monkeypatch):
    monkeypatch.setattr(hook_env, "ai_execution_mode", "anthropic_api")
    monkeypatch.setattr(hook_env, "anthropic_api_key", "placeholder-not-a-real-key")
    own, _ = ai_jobs.create_job(None, "ridhi", "topic_research")
    r = Hook(app, own["id"]).send("succeeded", result=TOPIC_RESULT)
    assert r.status_code == 409 and r.json()["code"] == "job_mismatch"
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


# ---------------- lifecycle ----------------

def test_progress_callbacks_update_one_job_and_one_workflow_run(app, job):
    h = Hook(app, job["id"])
    runs_before = len(all_rows("SELECT id FROM workflow_runs"))
    assert h.send("accepted", agent="claude-worker", external_id="exec-1").json()["status"] == "queued"
    assert _job_row(job["id"])["accepted_at"]
    assert h.send("started", progress=5).json()["status"] == "running"
    for p in (20, 45, 45, 80):                                                                  # equal progress is allowed, going back is not
        assert h.send("progress", progress=p, message=f"working {p}").status_code == 200
    j = _job_row(job["id"])
    assert (j["status"], j["progress"], j["message"], j["worker_id"], j["external_id"], j["last_sequence"]) == ("running", 80, "working 80", "claude-worker", "exec-1", 6)
    assert j["started_at"] and j["last_progress_at"] and j["finished_at"] is None
    assert len(all_rows("SELECT id FROM workflow_runs")) == runs_before                         # six callbacks, no new run rows
    runs = _runs_for(job["id"])
    assert len(runs) == 1 and runs[0]["status"] == "running" and json.loads(runs[0]["details_json"])["progress"] == 80
    assert len(all_rows("SELECT id FROM ai_job_events WHERE job_id = ? AND source = 'worker'", job["id"])) == 6


def test_success_stores_validated_topics_against_the_job(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    r = h.send("succeeded", result=TOPIC_RESULT, message="done", external_id="exec-1")
    assert r.status_code == 200 and r.json() == {"ok": True, "duplicate": False, "jobId": job["id"], "status": "succeeded", "progress": 100}
    j = _job_row(job["id"])
    assert (j["status"], j["progress"], j["lease_owner"]) == ("succeeded", 100, None) and j["finished_at"]
    stored = json.loads(j["result_json"])
    assert stored["kind"] == "topics" and stored["added"] == 2
    topics = all_rows("SELECT * FROM topics WHERE id IN (%s)" % ",".join(map(str, stored["topicIds"])))
    assert {t["status"] for t in topics} == {"proposed"} and {t["brand_id"] for t in topics} == {"ridhi"} and {t["created_by"] for t in topics} == {None}
    assert _runs_for(job["id"])[0]["status"] == "succeeded"


def test_failure_callback_records_the_reason(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    assert h.send("failed", error="Execution service unavailable.", message="Claude execution failed.").json()["status"] == "failed"
    j = _job_row(job["id"])
    assert (j["status"], j["error"], j["error_kind"]) == ("failed", "Execution service unavailable.", "worker_failed")
    run = _runs_for(job["id"])[0]
    assert run["status"] == "failed" and run["error"] == "Execution service unavailable."
    assert ai_jobs.public(j)["retryAvailable"] is True


def test_a_final_job_cannot_be_changed_by_later_callbacks(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    h.send("succeeded", result=TOPIC_RESULT)
    topics_after = all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'")
    for kind, extra in (("progress", {"progress": 99}), ("failed", {"error": "late"}), ("succeeded", {"result": {"topics": [{**TOPIC_RESULT["topics"][0], "primary_keyword": "ait another"}]}}), ("started", {})):
        r = h.send(kind, **extra)
        assert r.status_code == 409 and r.json()["code"] == "job_finished", kind
    j = _job_row(job["id"])
    assert (j["status"], j["progress"], j["error"]) == ("succeeded", 100, None)
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == topics_after


def test_invalid_transitions_are_rejected(app, job):
    h = Hook(app, job["id"])
    assert h.send("succeeded", result=TOPIC_RESULT).status_code == 409                          # pending cannot jump straight to succeeded
    assert h.send("started").status_code == 200
    r = h.send("accepted")                                                                      # running cannot go back to queued
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"
    assert _job_row(job["id"])["status"] == "running"


# ---------------- idempotency, ordering, staleness ----------------

def test_a_duplicate_event_is_ignored_safely(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    body = h.body("succeeded", result=TOPIC_RESULT)
    first, second, third = h.post(body), h.post(body), h.post(body)
    assert first.json()["duplicate"] is False and second.json()["duplicate"] is True and third.json()["duplicate"] is True
    assert second.status_code == 200 and second.json()["status"] == "succeeded"
    assert len(all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'")) == 2                 # stored once
    assert len(all_rows("SELECT id FROM ai_job_events WHERE job_id = ? AND event_id = ?", job["id"], body["event_id"])) == 1


def test_a_duplicate_progress_event_does_not_move_anything(app, job):
    h = Hook(app, job["id"])
    body = h.body("progress", progress=30)
    h.post(body)
    run("UPDATE ai_jobs SET message = 'edited elsewhere' WHERE id = ?", job["id"])
    assert h.post(body).json()["duplicate"] is True
    assert _job_row(job["id"])["message"] == "edited elsewhere" and _job_row(job["id"])["last_sequence"] == 1


def test_out_of_order_events_are_rejected(app, job):
    h = Hook(app, job["id"])
    late, early = h.body("progress", progress=60), h.body("progress", progress=30)              # sequences 1 and 2, delivered in reverse
    assert h.post(early).status_code == 200
    r = h.post(late)
    assert r.status_code == 409 and r.json()["code"] == "stale_event"
    j = _job_row(job["id"])
    assert (j["progress"], j["last_sequence"]) == (30, 2)                                       # the older event did not overwrite the newer one
    same = {**h.body("progress", progress=31), "sequence": 2}
    assert h.post(same).status_code == 409                                                      # the same sequence number again is stale too


def test_progress_cannot_move_backwards(app, job):
    h = Hook(app, job["id"])
    assert h.send("progress", progress=70).status_code == 200
    r = h.send("progress", progress=40)
    assert r.status_code == 409 and r.json()["code"] == "stale_progress"
    assert _job_row(job["id"])["progress"] == 70


def test_sequence_gaps_are_allowed_but_never_going_back(app, job):
    h = Hook(app, job["id"])
    h.seq = 9
    assert h.send("progress", progress=10).status_code == 200                                   # sequence 10
    assert _job_row(job["id"])["last_sequence"] == 10


def test_event_times_must_be_plausible(app, job):
    h = Hook(app, job["id"])
    assert h.send("progress", progress=1, occurred_at="2099-01-01T00:00:00Z").status_code == 400
    assert h.send("progress", progress=1, occurred_at="2001-01-01T00:00:00Z").status_code == 400   # before the job existed
    assert h.send("progress", progress=1, occurred_at=get("SELECT created_at FROM ai_jobs WHERE id = ?", job["id"])["created_at"]).status_code == 200


def test_events_from_an_earlier_attempt_are_stale_after_a_retry(app, job):
    old = Hook(app, job["id"])
    old.send("started")
    old.send("failed", error="boom")
    ai_jobs.retry_job(None, job["id"])
    assert _job_row(job["id"])["run_number"] == 2
    assert old.send("progress", progress=50).status_code == 409                                  # no run_number while the job is on attempt 2
    stale = old.post({**old.body("progress", progress=50), "run_number": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "stale_run"
    fresh = Hook(app, job["id"], run_number=2)
    assert fresh.send("started", run_number=2).status_code == 200                                # sequences restart with the new attempt
    assert fresh.send("succeeded", run_number=2, result=TOPIC_RESULT).status_code == 200
    assert len(_runs_for(job["id"])) == 1


# ---------------- results ----------------

@pytest.mark.parametrize("bad", [
    {"topics": []}, {"topics": [{"title": "AIT x"}]}, {"topics": TOPIC_RESULT["topics"], "publish": True},
    {"topics": [{**TOPIC_RESULT["topics"][0], "status": "approved"}]}, {"topics": [{**TOPIC_RESULT["topics"][0], "title": "AIT <script>x</script>"}]},
])
def test_a_rejected_result_fails_the_job_and_stores_nothing(app, job, bad):
    h = Hook(app, job["id"])
    h.send("started")
    r = h.send("succeeded", result=bad)
    assert r.status_code == 422 and r.json()["code"] == "invalid_result"
    j = _job_row(job["id"])
    assert (j["status"], j["error_kind"], j["result_json"]) == ("failed", "invalid_result", None)
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []
    assert _runs_for(job["id"])[0]["status"] == "failed"
    assert Hook(app, job["id"]).send("succeeded", result=TOPIC_RESULT).status_code == 409        # and it is final: no second chance by callback


def test_a_result_for_another_task_type_is_rejected(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    assert h.send("succeeded", result=DRAFT_RESULT).status_code == 422                           # a draft is not a topic list
    assert all_rows("SELECT id FROM articles WHERE title LIKE 'AIT %'") == []


def test_content_result_becomes_a_draft_for_the_approved_topic(app, hook_env):
    tid = make_topic("approved")
    j, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    h = Hook(app, j["id"])
    h.send("started")
    assert h.send("succeeded", result=DRAFT_RESULT).status_code == 200
    res = json.loads(_job_row(j["id"])["result_json"])
    a = get("SELECT * FROM articles WHERE id = ?", res["articleId"])
    assert (a["status"], a["topic_id"], a["origin"], a["brand_id"], a["shopify_published"]) == ("draft", tid, "claude", "ridhi", 0)
    assert a["approved_hash"] is None and a["shopify_article_id"] is None and a["live_url"] is None
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "in_production"
    assert len(all_rows("SELECT id FROM publish_requests WHERE article_id = ?", a["id"])) == 0


def test_a_draft_for_a_topic_that_changed_is_refused(app, hook_env):
    tid = make_topic("approved")
    j, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    run("UPDATE topics SET status = 'rejected' WHERE id = ?", tid)
    h = Hook(app, j["id"])
    h.send("started")
    r = h.send("succeeded", result=DRAFT_RESULT)
    assert r.status_code == 422 and "not approved" in r.json()["error"]
    assert all_rows("SELECT id FROM articles WHERE title LIKE 'AIT %'") == []
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "rejected"           # the unrelated record was left alone


# ---------------- what a callback can never do ----------------

def test_callbacks_cannot_approve_publish_or_change_other_records(app, hook_env):
    tid = make_topic("approved")
    other_topic = make_topic("proposed", title="AIT someone else's topic")
    ts = "2026-11-04T00:00:00.000Z"
    aid = run("""INSERT INTO articles (brand_id, title, handle, status, content_hash, approved_hash, created_at, updated_at)
                 VALUES ('ridhi', 'AIT existing article', 'ait-existing', 'publish_requested', 'h1', 'h1', ?, ?)""", ts, ts).last_id
    rid = run("""INSERT INTO publish_requests (article_id, brand_id, mode, content_hash, version, status, requested_by, requested_at)
                 VALUES (?, 'ridhi', 'publish_now', 'h1', 1, 'pending', 1, ?)""", aid, ts).last_id

    def snapshot():
        return (all_rows("SELECT id, status, approved_hash, shopify_published, content_hash, version FROM articles WHERE id = ?", aid),
                all_rows("SELECT * FROM publish_requests"), all_rows("SELECT id, status FROM topics WHERE id IN (?, ?)", other_topic, other_topic),
                all_rows("SELECT id, email, role, active FROM users"), all_rows("SELECT * FROM review_notes"))
    before = snapshot()
    j, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    h = Hook(app, j["id"])
    h.send("started")
    # Every attempt to smuggle an instruction in is refused before it can do anything.
    for evil in ({"approve": True}, {"publish": True}, {"article_id": aid}, {"sql": "DELETE FROM users"}, {"role": "admin"}):
        assert h.send("progress", progress=10, **evil).status_code == 400
    assert h.send("succeeded", result={**DRAFT_RESULT, "status": "approved", "article_id": aid}).status_code == 422
    assert snapshot() == before
    assert h.send("succeeded", result=DRAFT_RESULT).status_code == 409                           # the job was failed by the rejected result above
    h2 = Hook(app, ai_jobs.retry_job(None, j["id"])["id"], run_number=2)
    h2.send("started", run_number=2)
    assert h2.send("succeeded", run_number=2, result=DRAFT_RESULT).status_code == 200
    assert snapshot() == before                                                                  # the legitimate draft touched none of the existing records
    new = all_rows("SELECT status, shopify_published, approved_hash FROM articles WHERE title LIKE 'AIT %' AND id != ?", aid)
    assert new == [{"status": "draft", "shopify_published": 0, "approved_hash": None}]
    assert api_module.config.allow_live_publish is False
    run("DELETE FROM publish_requests WHERE id = ?", rid)
    run("DELETE FROM articles WHERE id = ?", aid)


# ---------------- legacy callbacks ----------------

def test_legacy_callback_still_logs_a_status_line(app, hook_env):
    n = len(all_rows("SELECT id FROM workflow_runs"))
    c = remote_client(app)
    ok = c.post("/api/hooks/workflow", json={"brand": "ridhi", "stage": "performance_tracking", "status": "succeeded", "message": "done", "agent": "routine"}, headers=HOOK)
    assert ok.status_code == 200 and len(all_rows("SELECT id FROM workflow_runs")) == n + 1
    row = get("SELECT * FROM workflow_runs WHERE id = ?", ok.json()["id"])
    assert (row["status"], row["trigger_kind"], row["message"]) == ("succeeded", "webhook", "done") and json.loads(row["details_json"])["legacy"] is True


@pytest.mark.parametrize("patch", [{"status": "bogus"}, {"status": ""}, {"status": None}, {"status": 5}, {"brand": "nope"}, {"stage": "nope"}, {"result": {"topics": []}}, {"brand": None}])
def test_legacy_callback_rejects_bad_input_and_never_turns_it_into_success(app, hook_env, patch):
    n = len(all_rows("SELECT id FROM workflow_runs"))
    body = {"brand": "ridhi", "stage": "performance_tracking", "status": "succeeded", **patch}
    r = remote_client(app).post("/api/hooks/workflow", json=body, headers=HOOK)
    assert r.status_code == 400
    assert len(all_rows("SELECT id FROM workflow_runs")) == n


def test_legacy_callback_without_a_status_is_rejected(app, hook_env):
    r = remote_client(app).post("/api/hooks/workflow", json={"brand": "ridhi", "stage": "performance_tracking"}, headers=HOOK)
    assert r.status_code == 400 and r.json()["code"] == "invalid_status"


def test_legacy_callback_cannot_create_records_or_carry_results(app, hook_env):
    topics, articles = len(all_rows("SELECT id FROM topics")), len(all_rows("SELECT id FROM articles"))
    r = remote_client(app).post("/api/hooks/workflow", json={"brand": "ridhi", "stage": "topic_research", "status": "succeeded", "result": TOPIC_RESULT}, headers=HOOK)
    assert r.status_code == 400 and r.json()["code"] == "result_requires_job"
    assert (len(all_rows("SELECT id FROM topics")), len(all_rows("SELECT id FROM articles"))) == (topics, articles)


def test_legacy_timestamps_are_validated(app, hook_env):
    r = remote_client(app).post("/api/hooks/workflow", json={"brand": "ridhi", "stage": "performance_tracking", "status": "running", "started_at": "'; DROP TABLE users; --"}, headers=HOOK)
    assert r.status_code == 200
    assert get("SELECT started_at FROM workflow_runs WHERE id = ?", r.json()["id"])["started_at"].endswith("Z")     # replaced by the server's clock


# ---------------- worker silence ----------------

def test_a_silent_worker_times_the_job_out(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    run("UPDATE ai_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", job["id"])
    assert ai_jobs.recover()["timed_out"] == 1
    j = _job_row(job["id"])
    assert (j["status"], j["error_kind"]) == ("failed", "timeout")
    assert h.send("progress", progress=90).status_code == 409                                      # a callback after the timeout is refused
    assert _runs_for(job["id"])[0]["status"] == "failed"


def test_each_callback_extends_the_workers_deadline(app, job):
    h = Hook(app, job["id"])
    h.send("started")
    run("UPDATE ai_jobs SET lease_expires_at = '2000-01-01T00:00:01.000Z' WHERE id = ?", job["id"])
    h.send("progress", progress=10)
    assert _job_row(job["id"])["lease_expires_at"] > "2026"
    assert ai_jobs.recover()["timed_out"] == 0


# ---------------- the job endpoints (local operator only) ----------------

def test_job_endpoints_are_local_only(app, job):
    c = remote_client(app)
    for method, path in (("GET", "/api/ai/jobs"), ("GET", f"/api/ai/jobs/{job['id']}"), ("POST", "/api/ai/jobs"), ("POST", f"/api/ai/jobs/{job['id']}/retry"), ("POST", f"/api/ai/jobs/{job['id']}/cancel")):
        r = c.request(method, path, json={}, headers={**HOOK, **H})
        assert r.status_code == 403 and r.json()["code"] == "local_only", path


def test_creating_a_job_needs_the_csrf_header_and_returns_a_job_id(app, hook_env):
    c = local_client(app)
    assert c.post("/api/ai/jobs", json={"brand": "ridhi", "task_type": "topic_research"}).status_code == 403
    r = c.post("/api/ai/jobs", json={"brand": "ridhi", "task_type": "topic_research", "input": {"count": 2}}, headers=H)
    assert r.status_code == 202 and r.json()["deduplicated"] is False
    job = r.json()["job"]
    assert job["status"] == "pending" and job["provider"] == "external_worker" and uuid.UUID(job["id"])
    again = c.post("/api/ai/jobs", json={"brand": "ridhi", "task_type": "topic_research", "input": {"count": 2}}, headers=H)
    assert again.status_code == 200 and again.json()["deduplicated"] is True and again.json()["job"]["id"] == job["id"]
    assert len(all_rows("SELECT id FROM ai_jobs")) == 1


@pytest.mark.parametrize(("body", "status"), [({"brand": "nope", "task_type": "topic_research"}, 400), ({"brand": "ridhi", "task_type": "publish"}, 400),
                                                ({"task_type": "topic_research"}, 400), ({"brand": "ridhi", "task_type": "topic_research", "input": {"x": 1}}, 400)])
def test_job_creation_validates_input(app, hook_env, body, status):
    assert local_client(app).post("/api/ai/jobs", json=body, headers=H).status_code == status
    assert all_rows("SELECT id FROM ai_jobs") == []


def test_creating_a_job_reports_pending_setup_not_a_fake_queue(app, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "anthropic_api_key", "")
    c = local_client(app)
    r = c.post("/api/ai/jobs", json={"brand": "ridhi", "task_type": "topic_research"}, headers=H)
    assert r.status_code == 412 and r.json()["code"] == "pending_setup"
    assert all_rows("SELECT id FROM ai_jobs") == []
    listing = c.get("/api/ai/jobs").json()
    assert listing["provider"]["state"] == "pending_setup" and listing["provider"]["missing"] == "anthropic_api_key" and listing["jobs"] == []


def test_list_detail_retry_and_cancel_endpoints(app, job):
    c = local_client(app)
    Hook(app, job["id"]).send("started")
    listing = c.get("/api/ai/jobs?brand=ridhi").json()
    assert [j["id"] for j in listing["jobs"]] == [job["id"]] and listing["jobs"][0]["cancellable"] is True and listing["jobs"][0]["retryAvailable"] is False
    detail = c.get(f"/api/ai/jobs/{job['id']}").json()
    assert detail["status"] == "running" and [e["event_type"] for e in detail["events"]] == ["created", "started"]
    assert c.get("/api/ai/jobs/not-a-job").status_code == 404
    assert c.post(f"/api/ai/jobs/{job['id']}/retry", headers=H).status_code == 409                # only failed jobs can be retried
    assert c.post(f"/api/ai/jobs/{job['id']}/cancel", headers=H).json()["job"]["status"] == "cancelled"
    assert c.post(f"/api/ai/jobs/{job['id']}/cancel", headers=H).status_code == 409                # already final
    assert Hook(app, job["id"]).send("progress", progress=50).status_code == 409                  # and the worker's later events are refused
    assert c.get("/api/ai/jobs?status=cancelled").json()["jobs"][0]["id"] == job["id"]


def test_failed_job_can_be_retried_over_http(app, job):
    c = local_client(app)
    h = Hook(app, job["id"])
    h.send("started")
    h.send("failed", error="boom")
    r = c.post(f"/api/ai/jobs/{job['id']}/retry", headers=H)
    assert r.status_code == 200 and r.json()["job"]["status"] == "pending" and r.json()["job"]["runNumber"] == 2
    # the generic run retry must not re-run an AI job's stage inline
    run_id = _job_row(job["id"])["workflow_run_id"]
    run("UPDATE workflow_runs SET status = 'failed' WHERE id = ?", run_id)
    blocked = c.post(f"/api/automation/runs/{run_id}/retry", headers=H)
    assert blocked.status_code == 409 and blocked.json()["code"] == "ai_job_run"


def test_responses_expose_no_secrets(app, job):
    c = local_client(app)
    Hook(app, job["id"]).send("started", external_id="exec-1")
    texts = [c.get(p).text for p in ("/api/ai/jobs", f"/api/ai/jobs/{job['id']}", "/api/integrations", "/api/automation")]
    for text in texts:
        for secret in (SECRET, "worker-token-for-tests", "placeholder-not-a-real-key"):
            assert secret not in text


def test_integrations_and_automation_describe_ai_execution(app, hook_env):
    c = local_client(app)
    items = {i["key"]: i for i in c.get("/api/integrations").json()["items"]}
    assert items["ai_execution"]["state"] == "connected" and "external_worker" in items["ai_execution"]["provides"]
    assert c.get("/api/automation").json()["configured"]["ai"]["state"] == "ready"


def test_a_job_cannot_be_flooded_with_events(app, job, monkeypatch):
    monkeypatch.setattr(ai_jobs, "MAX_EVENTS_PER_JOB", 5)                                        # 1 'created' event already exists
    h = Hook(app, job["id"])
    codes = [h.send("progress", progress=i).status_code for i in range(1, 7)]
    assert codes == [200, 200, 200, 200, 429, 429]
    assert len(all_rows("SELECT id FROM ai_job_events WHERE job_id = ?", job["id"])) == 5


# ---------------- existing workflow controls now use the background queue ----------------

def _boom(*_a, **_k):
    raise AssertionError("Claude must not be called inside a request: AI work runs as a background job")


@pytest.fixture
def claude_trap(monkeypatch):
    """Any direct Claude call made while handling a request fails the test."""
    from flowmerce.modules.seo.integrations import claude
    monkeypatch.setattr(claude, "research_topics", _boom)
    monkeypatch.setattr(claude, "generate_draft", _boom)
    monkeypatch.setattr(claude, "_get_client", _boom)


def test_the_topic_research_stage_queues_a_job_instead_of_calling_claude(app, ai_env, claude_trap):
    r = local_client(app).post("/api/automation/ridhi/stages/topic_research/run", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued" and "queued" in body["message"] and body["job"]["status"] == "pending" and body["job"]["taskType"] == "topic_research"
    job = _job_row(body["job"]["id"])
    assert (job["status"], job["provider"], job["workflow_run_id"]) == ("pending", "anthropic_api", body["id"])
    assert get("SELECT trigger_kind FROM workflow_runs WHERE id = ?", body["id"])["trigger_kind"] == "ai_job"
    again = local_client(app).post("/api/automation/ridhi/stages/topic_research/run", headers=H).json()
    assert again["job"]["id"] == body["job"]["id"] and again["message"].startswith("Already queued")      # a second click does not queue a second job
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


def test_the_queued_stage_job_runs_in_the_background_and_proposes_topics(app, ai_env, monkeypatch):
    from flowmerce.modules.seo.integrations import claude
    monkeypatch.setattr(claude, "research_topics", lambda *a, **k: (TOPIC_RESULT, "test-model"))
    job = local_client(app).post("/api/automation/ridhi/stages/topic_research/run", headers=H).json()["job"]
    ai_jobs.run_pending()
    assert _job_row(job["id"])["status"] == "succeeded"
    assert {t["status"] for t in all_rows("SELECT status FROM topics WHERE title LIKE 'AIT %'")} == {"proposed"}


def test_content_generation_stage_queues_one_job_per_approved_topic(app, ai_env, claude_trap):
    first, second = make_topic("approved", title="AIT stage topic one"), make_topic("approved", title="AIT stage topic two")
    body = local_client(app).post("/api/automation/ridhi/stages/content_generation/run", headers=H).json()
    assert body["status"] == "queued" and len(body["jobs"]) == 1                                  # the brand's drafts-per-run is 1
    assert json.loads(_job_row(body["job"]["id"])["input_json"])["topic_id"] in (first, second)
    assert get("SELECT status FROM topics WHERE id = ?", first)["status"] == "approved"            # nothing is written until the job runs


def test_content_generation_stage_with_nothing_approved_is_skipped(app, ai_env, claude_trap):
    body = local_client(app).post("/api/automation/cpc/stages/content_generation/run", headers=H).json()
    assert body["status"] == "skipped" and all_rows("SELECT id FROM ai_jobs") == []


def test_the_topic_draft_button_queues_a_job_and_returns_no_article_yet(app, ai_env, claude_trap):
    tid = make_topic("approved", title="AIT button topic")
    r = local_client(app).post(f"/api/topics/{tid}/article", json={"mode": "claude"}, headers=H)
    assert r.status_code == 202 and r.json()["articleId"] is None
    job = r.json()["job"]
    assert job["taskType"] == "content_generation" and job["status"] == "pending" and job["input"] == {"topic_id": tid}
    assert all_rows("SELECT id FROM articles WHERE topic_id = ?", tid) == []
    assert get("SELECT status FROM topics WHERE id = ?", tid)["status"] == "approved"


def test_the_topic_draft_button_keeps_its_approval_rules(app, ai_env, claude_trap):
    proposed = make_topic("proposed", title="AIT not approved yet")
    assert local_client(app).post(f"/api/topics/{proposed}/article", json={"mode": "claude"}, headers=H).status_code == 409
    assert all_rows("SELECT id FROM ai_jobs") == []


def test_ai_stage_runs_keep_permission_brand_and_pause_rules(app, ai_env, claude_trap, monkeypatch):
    from flowmerce.modules.seo import permissions
    c = local_client(app)
    assert c.post("/api/automation/nope/stages/topic_research/run", headers=H).status_code == 400
    assert c.post("/api/automation/ridhi/stages/topic_approval/run", headers=H).status_code == 400          # a person's stage is never run
    assert c.post("/api/automation/ridhi/stages/topic_research/run").status_code == 403                    # CSRF header still needed
    run("INSERT INTO automation_state (brand_id, paused, reason) VALUES ('ridhi', 1, 'test')")
    try:
        assert c.post("/api/automation/ridhi/stages/topic_research/run", headers=H).status_code == 423
    finally:
        run("DELETE FROM automation_state WHERE brand_id = 'ridhi'")
    monkeypatch.setitem(permissions.ROLE_PERMS, "admin", ["view"])
    assert c.post("/api/automation/ridhi/stages/topic_research/run", headers=H).status_code == 403          # workflow:run is still required
    assert all_rows("SELECT id FROM ai_jobs") == []


def test_ai_stages_report_a_setup_gap_for_whichever_method_is_missing_and_accept_a_worker(app, ai_env, monkeypatch):
    c = local_client(app)

    def gap(stage="topic_research"):
        stages = c.get("/api/automation?brand=ridhi").json()["brands"][0]["stages"]
        return next(s for s in stages if s["key"] == stage)
    monkeypatch.setattr(ai_env, "anthropic_api_key", "")
    assert gap()["state"] == "pending_setup" and "ANTHROPIC_API_KEY" in gap()["setupGap"]
    assert c.post("/api/automation/ridhi/stages/topic_research/run", headers=H).status_code == 412
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")                                  # worker mode, but not set up yet
    assert "AI_WORKER_URL" in gap()["setupGap"] and "WORKFLOW_WEBHOOK_SECRET" in gap("content_generation")["setupGap"]
    monkeypatch.setattr(ai_env, "ai_worker_url", "https://worker.example.com")
    monkeypatch.setattr(ai_env, "ai_worker_token", "worker-token-for-tests")
    monkeypatch.setattr(ai_env, "workflow_webhook_secret", SECRET)
    assert gap()["setupGap"] is None and gap("content_generation")["setupGap"] is None                   # a worker is a valid execution method
    body = c.post("/api/automation/ridhi/stages/topic_research/run", headers=H).json()
    assert body["status"] == "queued" and body["job"]["provider"] == "external_worker"


def test_a_failed_legacy_ai_run_is_retried_through_the_queue(app, ai_env, claude_trap):
    rid = run("""INSERT INTO workflow_runs (brand_id, stage, status, trigger_kind, error, started_at) VALUES ('ridhi', 'topic_research', 'failed', 'manual', 'old failure', '2026-01-01T00:00:00.000Z')""").last_id
    r = local_client(app).post(f"/api/automation/runs/{rid}/retry", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["job"]["taskType"] == "topic_research"


def test_non_ai_stages_still_run_immediately(app, ai_env, claude_trap):
    c = local_client(app)
    r = c.post("/api/automation/ridhi/stages/keyword_validation/run", headers=H)
    assert r.status_code == 200 and r.json()["status"] in ("succeeded", "waiting") and "job" not in r.json()
    assert get("SELECT trigger_kind FROM workflow_runs WHERE id = ?", r.json()["id"])["trigger_kind"] == "manual"          # logged as before, not as an AI job
    r2 = c.post("/api/automation/ridhi/stages/image_selection/run", headers=H)
    assert r2.status_code == 200 and "job" not in r2.json()
    assert all_rows("SELECT id FROM ai_jobs") == []
    run("DELETE FROM workflow_runs WHERE trigger_kind = 'manual' AND stage IN ('keyword_validation', 'image_selection')")


def test_the_inline_claude_runners_are_gone():
    from flowmerce.modules.seo.services import workflow
    assert not hasattr(workflow, "_topic_research") and not hasattr(workflow, "_content_generation")
    assert workflow.AI_STAGES == ("topic_research", "content_generation")


# ---------------- security regressions ----------------

def test_a_worker_cannot_complete_a_job_without_valid_callback_authentication(app, job):
    body = {"event_id": "evt-noauth-0001", "job_id": job["id"], "event_type": "succeeded", "sequence": 1, "result": TOPIC_RESULT}
    c = remote_client(app)
    for headers in ({}, {"X-Workflow-Secret": ""}, {"X-Workflow-Secret": "guess"}, {"Authorization": "Bearer worker-token-for-tests"}):
        assert c.post("/api/hooks/workflow", json=body, headers=headers).status_code == 401
    assert _job_row(job["id"])["status"] == "pending" and all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


@pytest.mark.parametrize("n", [1, 5, 20])
def test_a_worker_cannot_exceed_the_requested_topic_count(app, hook_env, n):
    from tests.fixtures.seo import make_topics
    j, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": n})
    h = Hook(app, j["id"])
    h.send("started")
    r = h.send("succeeded", result=make_topics(n + 1))
    assert r.status_code == 422 and r.json()["code"] == "invalid_result" and f"only {n}" in r.json()["error"]
    assert (_job_row(j["id"])["status"], all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'")) == ("failed", [])        # nothing was created
    h2 = Hook(app, ai_jobs.retry_job(None, j["id"])["id"], run_number=2)
    h2.send("started", run_number=2)
    assert h2.send("succeeded", run_number=2, result=make_topics(n)).status_code == 200
    topics = all_rows("SELECT status FROM topics WHERE title LIKE 'AIT %'")
    assert len(topics) == n and {t["status"] for t in topics} == {"proposed"}


def test_a_job_without_a_recorded_count_falls_back_to_the_brand_default(app, hook_env):
    from tests.fixtures.seo import make_topics
    j, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    run("UPDATE ai_jobs SET input_json = '{}' WHERE id = ?", j["id"])                                  # an older job row
    h = Hook(app, j["id"])
    h.send("started")
    assert h.send("succeeded", result=make_topics(6)).status_code == 422                               # the default is 5
    assert all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'") == []


def test_ai_results_never_publish_or_approve_and_live_publishing_stays_off(app, hook_env, monkeypatch):
    from flowmerce.modules.seo import api as api_mod
    tid = make_topic("approved", title="AIT publish guard")
    j, _ = ai_jobs.create_job(None, "ridhi", "content_generation", {"topic_id": tid})
    h = Hook(app, j["id"])
    h.send("started")
    assert h.send("succeeded", result=DRAFT_RESULT).status_code == 200
    a = get("SELECT * FROM articles WHERE topic_id = ?", tid)
    assert (a["status"], a["shopify_published"], a["approved_hash"], a["shopify_article_id"]) == ("draft", 0, None, None)
    assert all_rows("SELECT id FROM publish_requests WHERE article_id = ?", a["id"]) == [] and api_mod.config.allow_live_publish is False
    c = local_client(app)                                                                              # the human path is still required and still refuses a fresh draft
    assert c.post(f"/api/articles/{a['id']}/publish-request", json={"mode": "publish_now"}, headers=H).status_code in (400, 409, 412)
    assert c.post(f"/api/articles/{a['id']}/review", json={"decision": "approve", "version": a["version"]}, headers=H).status_code in (400, 409)
    after = get("SELECT status, approved_hash, shopify_published FROM articles WHERE id = ?", a["id"])
    assert (after["status"], after["approved_hash"], after["shopify_published"]) == ("draft", None, 0)


# ---------------- malformed fields over HTTP, and the pause controls ----------------

@pytest.mark.parametrize("patch", [
    {"event_type": []}, {"event_type": {}}, {"event_type": [1, 2]}, {"event_type": {"a": 1}}, {"event_type": 5}, {"event_type": None}, {"event_type": True},
    {"status": []}, {"status": {}}, {"status": [1]}, {"status": {"a": 1}}, {"status": 5}, {"status": True},
    {"event_id": []}, {"event_id": {}}, {"job_id": []}, {"job_id": {}}, {"sequence": []}, {"sequence": {}}, {"progress": []}, {"progress": {}},
    {"message": []}, {"agent": {}}, {"external_id": []}, {"error": {}}, {"brand": []}, {"stage": {}}, {"callback_reference": []}, {"occurred_at": []}, {"run_number": []},
])
def test_malformed_callback_fields_are_a_controlled_400_never_a_server_error(app, job, patch):
    h = Hook(app, job["id"])
    r = h.post({**h.body("progress", progress=5), **patch})
    assert r.status_code == 400, (patch, r.status_code, r.text)
    assert r.json()["code"] in ("invalid_event", "invalid_status")
    j = _job_row(job["id"])
    assert (j["status"], j["last_sequence"]) == ("pending", 0)


def test_a_non_string_job_id_is_a_400_not_a_lookup(app, hook_env):
    r = remote_client(app).post("/api/hooks/workflow", json={"job_id": [], "event_type": "started", "event_id": "evt-12345678", "sequence": 1}, headers=HOOK)
    assert r.status_code == 400


@pytest.fixture
def unpaused():
    yield
    run("DELETE FROM automation_state")


def test_pausing_through_the_dashboard_holds_ai_jobs_and_resuming_releases_them(app, job, unpaused, monkeypatch):
    # `job` is an external-worker job. Pause and resume through the real endpoints (the same ones the Automation page uses).
    c = local_client(app)
    assert c.post("/api/automation/ridhi/pause", json={"reason": "freeze"}, headers=H).status_code == 200
    assert ai_jobs.claim_next("runner-A") is None
    listing = c.get("/api/ai/jobs?brand=ridhi").json()["jobs"][0]
    assert listing["brandPaused"] is True and listing["waitingForResume"] is True
    assert c.post(f"/api/ai/jobs/{job['id']}/cancel", headers=H).json()["job"]["status"] == "cancelled"        # cancelling still works while paused
    assert c.post("/api/automation/ridhi/resume", headers=H).status_code == 200
    j2, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3})
    claimed = ai_jobs.claim_next("runner-A")
    assert claimed and claimed["id"] == j2["id"]                                                                 # eligible again after the resume


def test_retry_over_http_is_423_while_paused(app, job, unpaused):
    c = local_client(app)
    h = Hook(app, job["id"])
    h.send("started")
    h.send("failed", error="boom")
    c.post("/api/automation/ridhi/pause", json={"reason": "freeze"}, headers=H)
    r = c.post(f"/api/ai/jobs/{job['id']}/retry", headers=H)
    assert r.status_code == 423 and r.json()["code"] == "paused"
    c.post("/api/automation/ridhi/resume", headers=H)
    assert c.post(f"/api/ai/jobs/{job['id']}/retry", headers=H).status_code == 200


def test_pause_still_blocks_every_stage_including_non_ai_ones(app, ai_env, unpaused):
    c = local_client(app)
    c.post("/api/automation/ridhi/pause", json={"reason": "freeze"}, headers=H)
    for stage in ("keyword_validation", "image_selection", "topic_research", "content_generation"):
        assert c.post(f"/api/automation/ridhi/stages/{stage}/run", headers=H).status_code == 423, stage
    assert c.post("/api/automation/cpc/stages/keyword_validation/run", headers=H).status_code == 200            # the other brand is unaffected
    run("DELETE FROM workflow_runs WHERE trigger_kind = 'manual' AND stage = 'keyword_validation'")
