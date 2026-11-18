"""The external-worker adapter and dispatch, tested against a throwaway HTTP server on 127.0.0.1 that plays the worker.
Nothing leaves this computer. The server records every request and answers from a script."""
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from flowmerce.modules.seo.integrations import ai_worker
from flowmerce.modules.seo.integrations.status import status_of
from flowmerce.modules.seo.services import ai_jobs
from flowmerce.modules.seo.db import all_rows, get, run
from flowmerce.modules.seo.util import HttpError

TOKEN = "worker-token-for-tests"
HOOK_SECRET = "hook-secret-for-tests"
ACCEPT = (202, {}, {"status": "accepted", "worker_id": "w-1", "external_id": "ext-9"})


class FakeWorker:
    """A loopback HTTP server. script: list of (status, headers, body | raw bytes | callable) answered in order, then the last one repeats."""

    def __init__(self, script):
        self.script, self.requests, self.delay, self.on_request = list(script), [], 0.0, None   # on_request(request) runs while the worker "works"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if outer.on_request:
                    outer.on_request(outer.requests[-1])
                if outer.delay:
                    time.sleep(outer.delay)
                status, headers, payload = outer.script.pop(0) if len(outer.script) > 1 else outer.script[0]
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def worker_env(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    monkeypatch.setattr(ai_env, "ai_worker_token", TOKEN)
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 5)
    monkeypatch.setattr(ai_env, "workflow_webhook_secret", HOOK_SECRET)
    monkeypatch.setattr(ai_env, "ai_callback_url", "https://flowmerce.example.test/api/hooks/workflow")
    servers = []

    def start(script):
        w = FakeWorker(script)
        servers.append(w)
        monkeypatch.setattr(ai_env, "ai_worker_url", w.url)
        return w
    yield start
    for w in servers:
        w.close()


def _job():
    job, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    return job


def _row(job):
    return get("SELECT * FROM ai_jobs WHERE id = ?", job["id"])


# ---------------- request format ----------------

def test_request_matches_the_documented_contract_and_leaks_no_secret(worker_env, ai_env):
    w = worker_env([ACCEPT])
    job = _job()
    assert ai_jobs.run_pending() == [job["id"]]
    assert len(w.requests) == 1
    r = w.requests[0]
    assert r["path"] == "/v1/jobs"
    assert r["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert r["headers"]["idempotency-key"] == f"{job['id']}:1"
    assert r["headers"]["content-type"] == "application/json" and r["headers"]["x-flowmerce-contract"] == "1"
    body = json.loads(r["body"])
    assert set(body) == {"contract", "job_id", "run_number", "brand", "task_type", "stage", "input", "callback_url", "callback_reference"}
    assert (body["contract"], body["job_id"], body["run_number"], body["brand"], body["task_type"], body["stage"], body["callback_reference"]) == \
        (1, job["id"], 1, "ridhi", "topic_research", "topic_research", job["id"])
    assert body["callback_url"] == "https://flowmerce.example.test/api/hooks/workflow"
    assert body["input"]["count"] == 2 and {"brand", "existing_titles", "products", "queries", "focus"} <= set(body["input"])
    raw = r["body"].decode() + json.dumps(r["headers"])
    assert HOOK_SECRET not in r["body"].decode() and "X-Workflow-Secret".lower() not in r["headers"]
    assert "placeholder-not-a-real-key" not in raw                                           # the Anthropic key is not sent either


def test_callback_url_is_left_out_when_not_configured(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_callback_url", "")
    w = worker_env([ACCEPT])
    _job()
    ai_jobs.run_pending()
    assert "callback_url" not in json.loads(w.requests[0]["body"])


# ---------------- success ----------------

def test_accepted_job_becomes_queued_and_records_the_worker(worker_env):
    worker_env([ACCEPT])
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["worker_id"], j["external_id"], j["lease_owner"], j["attempts"]) == ("queued", "w-1", "ext-9", None, 1)
    assert j["accepted_at"] and j["lease_expires_at"]                                          # now watched by a worker deadline
    assert get("SELECT status FROM workflow_runs WHERE id = ?", j["workflow_run_id"])["status"] == "running"
    assert ai_jobs.provider_status()["state"] == "ready" and status_of("ai_worker", "")["status"] == "connected"


def test_a_queued_job_is_never_dispatched_twice(worker_env):
    w = worker_env([ACCEPT])
    _job()
    ai_jobs.run_pending()
    ai_jobs.run_pending()
    ai_jobs.run_pending()
    assert len(w.requests) == 1


def test_a_dispatch_lease_stops_two_runners_sending_the_same_job(worker_env):
    w = worker_env([ACCEPT])
    job = _job()
    first, second = ai_jobs.claim_next("runner-A"), ai_jobs.claim_next("runner-B")
    assert first and first["id"] == job["id"] and second is None and first["status"] == "pending"
    assert w.requests == []                                                                    # claiming alone sends nothing


def test_duplicate_submission_answered_409_counts_as_accepted(worker_env):
    worker_env([(409, {}, {"status": "queued", "worker_id": "w-1"})])
    job = _job()
    ai_jobs.run_pending()
    assert _row(job)["status"] == "queued"
    assert "already submitted" in " ".join(e["message"] for e in ai_jobs.get_job(job["id"])["events"])


def test_events_that_beat_the_dispatch_response_are_not_overwritten(worker_env):
    """The worker may call back before submit() returns. The late acknowledgement must not move a running job back to queued."""
    worker_env([ACCEPT])
    job = _job()
    claimed = ai_jobs.claim_next("runner-A")
    ai_jobs.apply_event(ai_jobs.parse_event({"event_id": "evt-early-1", "job_id": job["id"], "event_type": "started", "sequence": 1}))
    ai_jobs._dispatch(claimed, claimed["lease_owner"])
    j = _row(job)
    assert j["status"] == "running" and j["lease_owner"] is None and j["worker_id"] == "w-1"


# ---------------- failures ----------------

def test_timeout_is_retried_and_marks_the_worker_unavailable(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.0
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["retry_count"]) == ("pending", "timeout", 1) and j["next_attempt_at"]
    p = ai_jobs.provider_status()
    assert p["state"] == "unavailable" and "did not answer" in p["reason"]
    w.delay = 0.0                                                                               # the worker recovers
    from flowmerce.modules.seo.db import run
    run("UPDATE ai_jobs SET next_attempt_at = NULL WHERE id = ?", job["id"])
    ai_jobs.run_pending()
    assert _row(job)["status"] == "queued" and ai_jobs.provider_status()["state"] == "ready"


def test_network_failure_is_retried_and_never_looks_queued(worker_env, ai_env):
    w = worker_env([ACCEPT])
    w.close()                                                                                    # nobody is listening any more
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["retry_count"], j["accepted_at"]) == ("pending", "unavailable", 1, None)
    assert ai_jobs.provider_status()["state"] == "unavailable"


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_http_statuses_go_back_to_pending(worker_env, status):
    worker_env([(status, {}, {"error": "x"})])
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["retry_count"], j["error_kind"]) == ("pending", 1, "unavailable")


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (403, "auth"), (400, "rejected"), (404, "rejected"), (422, "rejected"), (501, "rejected"), (505, "rejected")])
def test_permanent_http_statuses_fail_at_once(worker_env, status, kind):
    w = worker_env([(status, {}, {"error": "x"})])
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["retry_count"]) == ("failed", kind, 0) and len(w.requests) == 1
    assert "AI_WORKER_TOKEN" in j["error"] if kind == "auth" else True


def test_retry_after_header_sets_the_next_attempt(worker_env):
    worker_env([(503, {"Retry-After": "120"}, {"error": "busy"})])
    job = _job()
    ai_jobs.run_pending()
    nxt = datetime.fromisoformat(_row(job)["next_attempt_at"].replace("Z", "+00:00"))
    assert 110 <= (nxt - datetime.now(timezone.utc)).total_seconds() <= 125


@pytest.mark.parametrize("answer", [(200, {}, b"<html>not json</html>"), (200, {}, {"status": "weird"}), (200, {}, {"status": "accepted", "worker_id": 5}), (200, {}, ["x"]), (200, {}, b"")])
def test_invalid_worker_responses_are_retryable_failures_not_acceptance(worker_env, answer):
    worker_env([answer])
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["accepted_at"]) == ("pending", "invalid_response", None)


def test_the_retry_budget_ends_in_failure(worker_env):
    from flowmerce.modules.seo.db import run
    w = worker_env([(503, {}, {})])
    job = _job()
    for _ in range(4):
        run("UPDATE ai_jobs SET next_attempt_at = NULL WHERE id = ?", job["id"])
        ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["retry_count"], j["attempts"]) == ("failed", 3, 4) and len(w.requests) == 4


def test_redirects_are_not_followed(worker_env):
    w = worker_env([(302, {"Location": "http://127.0.0.1:1/steal"}, {})])
    job = _job()
    ai_jobs.run_pending()
    assert _row(job)["status"] == "failed" and len(w.requests) == 1                          # the token never went to the other address


# ---------------- adapter helpers ----------------

@pytest.mark.parametrize(("url", "ok"), [
    ("https://worker.example.com", True), ("https://worker.example.com/", True), ("http://127.0.0.1:9000", True), ("http://localhost:9000", True), ("http://[::1]:9000", True),
    ("http://worker.example.com", False), ("http://192.168.1.5", False), ("ftp://worker.example.com", False), ("https://user:pw@worker.example.com", False),
    ("https://worker.example.com?x=1", False), ("", False), ("worker.example.com", False),
])
def test_worker_url_must_be_https_or_loopback(ai_env, monkeypatch, url, ok):
    monkeypatch.setattr(ai_env, "ai_worker_url", url)
    monkeypatch.setattr(ai_env, "ai_worker_token", TOKEN)
    assert ai_worker.configured() is ok


def test_worker_needs_a_token(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_url", "https://worker.example.com")
    monkeypatch.setattr(ai_env, "ai_worker_token", "")
    assert ai_worker.configured() is False
    with pytest.raises(ai_worker.WorkerError) as e:
        ai_worker.submit({"id": "x", "run_number": 1, "brand_id": "ridhi", "task_type": "t", "stage": "s"}, {})
    assert e.value.kind == "not_configured" and not e.value.retryable


def test_retry_after_parsing():
    assert ai_worker.parse_retry_after("30") == 30.0 and ai_worker.parse_retry_after("0") == 0.0 and ai_worker.parse_retry_after("-5") == 0.0
    assert ai_worker.parse_retry_after(None) is None and ai_worker.parse_retry_after("soon") is None and ai_worker.parse_retry_after("") is None
    base = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    assert ai_worker.parse_retry_after("Wed, 04 Nov 2026 12:01:00 GMT", now=base) == 60.0
    assert ai_worker.parse_retry_after("Wed, 04 Nov 2026 11:00:00 GMT", now=base) == 0.0


def test_backoff_is_exponential_and_bounded(ai_env):
    assert [ai_worker.backoff_seconds(n) for n in (1, 2, 3, 4)] == [5.0, 10.0, 20.0, 40.0]
    assert ai_worker.backoff_seconds(30) == 300.0                                                # capped
    assert ai_worker.backoff_seconds(1, retry_after=12) == 12.0                                  # the server's wish wins
    assert ai_worker.backoff_seconds(1, retry_after=86400) == 300.0                              # but it cannot park a job for a day


# ---------------- external worker readiness: the callback secret is required ----------------

def _set(ai_env, monkeypatch, *, url="https://worker.example.com", token=TOKEN, secret=HOOK_SECRET, callback="https://flowmerce.example.test/api/hooks/workflow"):
    monkeypatch.setattr(ai_env, "ai_execution_mode", "external_worker")
    monkeypatch.setattr(ai_env, "ai_worker_url", url)
    monkeypatch.setattr(ai_env, "ai_worker_token", token)
    monkeypatch.setattr(ai_env, "workflow_webhook_secret", secret)
    monkeypatch.setattr(ai_env, "ai_callback_url", callback)


def test_fully_configured_external_worker_is_ready(ai_env, monkeypatch):
    _set(ai_env, monkeypatch)
    p = ai_jobs.provider_status()
    assert (p["state"], p["missing"], p["missingAll"], p["notes"]) == ("ready", None, [], [])
    assert p["callbackConfigured"] is True and p["webhookConfigured"] is True
    assert HOOK_SECRET not in json.dumps(p) and TOKEN not in json.dumps(p)                  # the status never carries a secret
    assert ai_jobs.create_job(None, "ridhi", "topic_research")[1] is False


@pytest.mark.parametrize(("kwargs", "main", "all_missing"), [
    ({"secret": ""}, "webhook_secret", ["webhook_secret"]),
    ({"url": ""}, "worker_config", ["worker_url"]),
    ({"url": "http://worker.example.com"}, "worker_config", ["worker_url"]),                   # not https
    ({"token": ""}, "worker_config", ["worker_token"]),
    ({"url": "", "token": "", "secret": ""}, "worker_config", ["worker_url", "worker_token", "webhook_secret"]),
    ({"callback": "http://flowmerce.example.test/hook"}, "callback_url", ["callback_url"]),    # a callback URL that is set must be safe
])
def test_incomplete_external_worker_configuration_is_pending_setup_and_creates_nothing(ai_env, monkeypatch, kwargs, main, all_missing):
    _set(ai_env, monkeypatch, **kwargs)
    p = ai_jobs.provider_status()
    assert (p["state"], p["missing"], p["missingAll"]) == ("pending_setup", main, all_missing)
    for item in all_missing:                                                                    # the reason names each missing piece
        assert {"worker_url": "AI_WORKER_URL", "worker_token": "AI_WORKER_TOKEN", "webhook_secret": "WORKFLOW_WEBHOOK_SECRET", "callback_url": "AI_CALLBACK_URL"}[item] in p["reason"]
    with pytest.raises(HttpError) as e:
        ai_jobs.create_job(None, "ridhi", "topic_research")
    assert (e.value.status, e.value.code) == (412, "pending_setup")
    assert all_rows("SELECT id FROM ai_jobs") == []


def test_a_missing_callback_url_is_allowed_but_flagged(ai_env, monkeypatch):
    _set(ai_env, monkeypatch, callback="")
    p = ai_jobs.provider_status()
    assert p["state"] == "ready" and p["callbackConfigured"] is False and "AI_CALLBACK_URL is not set" in p["notes"][0]


def test_nothing_is_dispatched_while_the_webhook_secret_is_missing(ai_env, monkeypatch):
    w = FakeWorker([ACCEPT])
    try:
        _set(ai_env, monkeypatch, url=w.url)
        job, _ = ai_jobs.create_job(None, "ridhi", "topic_research")                           # created while fully configured
        monkeypatch.setattr(ai_env, "workflow_webhook_secret", "")                              # then the secret is removed
        assert ai_jobs.claim_next("runner-A") is None and ai_jobs.run_pending() == []
        assert w.requests == []                                                                 # nothing reached the worker
        assert get("SELECT status, lease_owner, attempts FROM ai_jobs WHERE id = ?", job["id"]) == {"status": "pending", "lease_owner": None, "attempts": 0}
        monkeypatch.setattr(ai_env, "workflow_webhook_secret", HOOK_SECRET)                    # configuration completed: the waiting job now goes out
        assert ai_jobs.run_pending() == [job["id"]] and len(w.requests) == 1
    finally:
        w.close()


def test_the_callback_url_is_sent_to_the_worker_and_the_secret_never_is(ai_env, monkeypatch):
    w = FakeWorker([ACCEPT])
    try:
        _set(ai_env, monkeypatch, url=w.url, callback="https://flowmerce.example.test/api/hooks/workflow")
        ai_jobs.create_job(None, "ridhi", "topic_research")
        ai_jobs.run_pending()
        sent = w.requests[0]
        assert json.loads(sent["body"])["callback_url"] == "https://flowmerce.example.test/api/hooks/workflow"
        assert HOOK_SECRET not in sent["body"].decode() and HOOK_SECRET not in json.dumps(sent["headers"])
        assert "x-workflow-secret" not in sent["headers"]
    finally:
        w.close()


def test_the_anthropic_mode_does_not_need_the_webhook_secret(ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "workflow_webhook_secret", "")
    assert ai_jobs.provider_status()["state"] == "ready"


# ---------------- a worker callback versus a slow dispatch request ----------------

def test_a_worker_that_reports_started_before_its_dispatch_times_out_keeps_its_job(worker_env, ai_env, monkeypatch):
    """The worker takes the job and calls back 'started' while the dispatch HTTP request is still open; then that request times out.
    The job must stay running: no requeue, no retry used, no failure, no second dispatch, and a later success must still be stored."""
    from tests.fixtures.seo import TOPIC_RESULT
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5                                                                                  # longer than the 1 s timeout
    job = _job()

    def worker_starts(request):
        sent = json.loads(request["body"])
        ai_jobs.apply_event(ai_jobs.parse_event({"event_id": "evt-race-0001", "job_id": sent["job_id"], "event_type": "started", "sequence": 1,
                                                 "agent": "worker-race", "external_id": "exec-race"}))
    w.on_request = worker_starts
    assert ai_jobs.run_pending() == [job["id"]]                                                    # the dispatch request times out here
    j = _row(job)
    assert (j["status"], j["retry_count"], j["error"], j["error_kind"]) == ("running", 0, None, None)
    assert (j["lease_owner"], j["next_attempt_at"], j["attempts"]) == (None, None, 1)               # dispatch ownership released
    assert j["lease_expires_at"] > "2026" and j["worker_id"] == "worker-race"                      # the worker's inactivity deadline remains
    assert ai_jobs.provider_status()["state"] == "ready" and status_of("ai_worker", "") is None    # a worker that is working is not "unavailable"
    assert ai_jobs.run_pending() == [] and len(w.requests) == 1                                    # not claimed, not sent again
    assert get("SELECT status FROM workflow_runs WHERE id = ?", j["workflow_run_id"])["status"] == "running"

    ai_jobs.apply_event(ai_jobs.parse_event({"event_id": "evt-race-0002", "job_id": job["id"], "event_type": "succeeded", "sequence": 2,
                                             "external_id": "exec-race", "result": TOPIC_RESULT}))
    j = _row(job)
    assert j["status"] == "succeeded" and json.loads(j["result_json"])["added"] == 2
    assert len(all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'")) == 2


def test_a_dispatch_token_can_do_nothing_once_the_worker_has_the_job(worker_env):
    worker_env([ACCEPT])
    job = _job()
    token = ai_jobs.claim_next("runner-A")["lease_owner"]
    ai_jobs.apply_event(ai_jobs.parse_event({"event_id": "evt-token-0001", "job_id": job["id"], "event_type": "accepted", "sequence": 1}))
    assert _row(job)["lease_owner"] is None and _row(job)["status"] == "queued"
    assert ai_jobs._after_failure(job["id"], token, "dispatch timed out", "timeout", True) is None            # would have requeued it before
    assert ai_jobs._update(job["id"], "failed", owner=token, error="x") is None
    j = _row(job)
    assert (j["status"], j["retry_count"], j["error"]) == ("queued", 0, None)


def test_a_late_dispatch_acknowledgement_never_overwrites_newer_callback_state(worker_env):
    w = worker_env([(202, {}, {"status": "accepted", "worker_id": "w-late", "external_id": "ext-late"})])

    def worker_progresses(request):
        sent = json.loads(request["body"])
        for seq, kind, extra in ((1, "started", {}), (2, "progress", {"progress": 60, "message": "far along"})):
            ai_jobs.apply_event(ai_jobs.parse_event({"event_id": f"evt-late-000{seq}", "job_id": sent["job_id"], "event_type": kind, "sequence": seq, **extra}))
    w.on_request = worker_progresses
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["progress"], j["message"], j["last_sequence"], j["lease_owner"]) == ("running", 60, "far along", 2, None)    # not moved back to queued
    assert (j["worker_id"], j["external_id"]) == ("w-late", "ext-late")                                                                  # only the missing identifiers were filled
    assert j["accepted_at"] is None


# ---------------- malformed acknowledgements never cause an internal error ----------------

@pytest.mark.parametrize("body", [
    b'{"status": []}', b'{"status": {}}', b'{"status": 5}', b'{"status": null}', b'{"status": true}', b'{"status": ["accepted"]}',
    b'{"status": "accepted", "worker_id": []}', b'{"status": "accepted", "external_id": {}}', b"[]", b'"accepted"', b"null", b"7",
])
def test_malformed_worker_acknowledgements_are_a_controlled_invalid_response(worker_env, body):
    worker_env([(200, {}, body)])
    job = _row(_job())
    with pytest.raises(ai_worker.WorkerError) as e:
        ai_worker.submit(job, {})
    assert e.value.kind == "invalid_response" and e.value.retryable is True
    assert ai_worker._parse_ack(body, duplicate=False) is None


def test_a_malformed_409_body_is_a_controlled_rejection(worker_env):
    worker_env([(409, {}, b'{"status": []}')])
    with pytest.raises(ai_worker.WorkerError) as e:
        ai_worker.submit(_row(_job()), {})
    assert e.value.kind == "rejected" and e.value.http_status == 409


def test_a_job_with_a_malformed_acknowledgement_is_retried_not_crashed(worker_env):
    worker_env([(200, {}, b'{"status": {}}')])
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["retry_count"]) == ("pending", "invalid_response", 1)


# ---------------- terminal callbacks that beat a dispatch timeout ----------------

def _race_worker(worker_env, ai_env, monkeypatch, events):
    """A worker that reports `events` (a list of callback dicts without ids) to Flowmerce while the dispatch request is still open,
    after which that request times out (1 s timeout, 2.5 s answer)."""
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5

    def worker_reports(request):
        job_id = json.loads(request["body"])["job_id"]
        for n, ev in enumerate(events, 1):
            ai_jobs.apply_event(ai_jobs.parse_event({"event_id": f"evt-term-{n:04d}", "job_id": job_id, "sequence": n, "external_id": "exec-term", **ev}))
    w.on_request = worker_reports
    return w


def test_a_success_callback_before_the_dispatch_times_out_leaves_the_job_succeeded_and_the_worker_healthy(worker_env, ai_env, monkeypatch):
    from tests.fixtures.seo import TOPIC_RESULT
    w = _race_worker(worker_env, ai_env, monkeypatch, [{"event_type": "started"}, {"event_type": "succeeded", "result": TOPIC_RESULT}])
    job = _job()
    assert ai_jobs.run_pending() == [job["id"]]                                                    # the dispatch request times out here
    j = _row(job)
    assert (j["status"], j["retry_count"], j["error"], j["error_kind"], j["lease_owner"]) == ("succeeded", 0, None, None, None)
    assert json.loads(j["result_json"])["added"] == 2 and j["progress"] == 100 and j["finished_at"]   # the stored result is untouched
    assert len(all_rows("SELECT id FROM topics WHERE title LIKE 'AIT %'")) == 2
    assert status_of("ai_worker", "") is None and ai_jobs.provider_status()["state"] == "ready"      # the worker is NOT marked unavailable
    assert get("SELECT status FROM workflow_runs WHERE id = ?", j["workflow_run_id"])["status"] == "succeeded"
    assert ai_jobs.run_pending() == [] and len(w.requests) == 1                                      # and nothing is re-sent


def test_a_failure_callback_before_the_dispatch_times_out_keeps_the_workers_error_and_the_worker_healthy(worker_env, ai_env, monkeypatch):
    w = _race_worker(worker_env, ai_env, monkeypatch, [{"event_type": "started"}, {"event_type": "failed", "error": "the worker's own failure"}])
    job = _job()
    assert ai_jobs.run_pending() == [job["id"]]
    j = _row(job)
    assert (j["status"], j["error"], j["error_kind"], j["retry_count"], j["attempts"]) == ("failed", "the worker's own failure", "worker_failed", 0, 1)   # no retry consumed
    assert j["next_attempt_at"] is None and j["lease_owner"] is None
    assert status_of("ai_worker", "") is None and ai_jobs.provider_status()["state"] == "ready"     # a timed-out acknowledgement alone is not "unavailable"
    assert get("SELECT status, error FROM workflow_runs WHERE id = ?", j["workflow_run_id"]) == {"status": "failed", "error": "the worker's own failure"}
    assert ai_jobs.run_pending() == [] and len(w.requests) == 1


def test_a_genuine_dispatch_failure_is_retried_and_marks_the_worker_unavailable(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5                                                                                  # no callback of any kind arrives
    job = _job()
    ai_jobs.run_pending()
    j = _row(job)
    assert (j["status"], j["error_kind"], j["retry_count"], j["lease_owner"]) == ("pending", "timeout", 1, None) and j["next_attempt_at"]
    p = ai_jobs.provider_status()
    assert p["state"] == "unavailable" and status_of("ai_worker", "")["status"] == "error"


def test_a_cancelled_job_whose_dispatch_then_fails_is_left_cancelled_and_the_worker_healthy(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5
    job = _job()
    w.on_request = lambda request: ai_jobs.cancel_job(None, job["id"])                            # a person cancels while the request is open
    ai_jobs.run_pending()
    assert _row(job)["status"] == "cancelled" and _row(job)["retry_count"] == 0
    assert status_of("ai_worker", "") is None


# ---------------- worker health is ordered and atomic under concurrency ----------------

def _two_claimed_jobs():
    a, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    b, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3})
    ca, cb = ai_jobs.claim_next("runner-A"), ai_jobs.claim_next("runner-B")
    assert (ca["id"], cb["id"]) == (a["id"], b["id"])
    return a, b, ca, cb


def test_a_delayed_failure_cannot_overwrite_a_newer_successful_contact(worker_env, ai_env, monkeypatch):
    """Job A really times out and its failure is applied, but its health update is held back; meanwhile job B reaches the same worker
    successfully. When A's handling completes, the newer 'connected' state must stand."""
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.on_request = lambda request: time.sleep(2.5) if len(w.requests) == 1 else None             # only the first request (job A) hangs
    a, b, claimed_a, claimed_b = _two_claimed_jobs()
    original, seen = ai_jobs._after_failure, []

    def delayed(*args, **kwargs):
        ai_jobs._dispatch(claimed_b, claimed_b["lease_owner"])                                    # in the gap, job B succeeds against the worker
        seen.append(status_of("ai_worker", "")["status"])
        return original(*args, **kwargs)
    monkeypatch.setattr(ai_jobs, "_after_failure", delayed)
    ai_jobs._dispatch(claimed_a, claimed_a["lease_owner"])
    assert seen == ["connected"]                                                                  # B's success was recorded first
    ja, jb = _row(a), _row(b)
    assert (ja["status"], ja["error_kind"], ja["retry_count"]) == ("pending", "timeout", 1)       # A's failure WAS applied (normal retry policy)
    assert jb["status"] == "queued"
    st = status_of("ai_worker", "")
    assert st["status"] == "connected" and st["last_error"] is None                                # ...but did not overwrite the newer success
    assert ai_jobs.provider_status()["state"] == "ready"


def test_two_concurrent_successful_dispatches_leave_the_worker_connected(worker_env):
    worker_env([ACCEPT])
    a, b, claimed_a, claimed_b = _two_claimed_jobs()
    threads = [threading.Thread(target=ai_jobs._dispatch, args=(c, c["lease_owner"])) for c in (claimed_a, claimed_b)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert (_row(a)["status"], _row(b)["status"]) == ("queued", "queued")
    assert status_of("ai_worker", "")["status"] == "connected" and ai_jobs.provider_status()["state"] == "ready"


def test_two_concurrent_worker_failures_leave_the_worker_unavailable_and_both_jobs_retrying(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5
    a, b, claimed_a, claimed_b = _two_claimed_jobs()
    threads = [threading.Thread(target=ai_jobs._dispatch, args=(c, c["lease_owner"])) for c in (claimed_a, claimed_b)]
    [t.start() for t in threads]
    [t.join(15) for t in threads]
    for j in (_row(a), _row(b)):
        assert (j["status"], j["error_kind"], j["retry_count"]) == ("pending", "timeout", 1)
    st = status_of("ai_worker", "")
    assert st["status"] == "error" and ai_jobs.provider_status()["state"] == "unavailable"
    assert len(all_rows("SELECT key FROM integration_status WHERE key = 'ai_worker'")) == 1


def test_a_dispatch_that_a_callback_already_took_over_does_not_disturb_a_healthy_worker(worker_env, ai_env, monkeypatch):
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    first, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 3})
    ai_jobs.run_pending()                                                                          # a normal, successful dispatch: connected
    assert status_of("ai_worker", "")["status"] == "connected"
    taken, _ = ai_jobs.create_job(None, "ridhi", "topic_research", {"count": 2})
    w.delay = 2.5
    w.on_request = lambda request: ai_jobs.apply_event(ai_jobs.parse_event(
        {"event_id": "evt-health-0001", "job_id": json.loads(request["body"])["job_id"], "event_type": "started", "sequence": 1}))
    ai_jobs.run_pending()                                                                          # the worker starts the job, then the request times out
    assert _row(taken)["status"] == "running" and _row(taken)["retry_count"] == 0
    st = status_of("ai_worker", "")
    assert st["status"] == "connected" and st["last_error"] is None


def test_the_job_failure_and_the_health_update_are_one_transaction(worker_env, ai_env, monkeypatch):
    """If the health write fails, the job failure is rolled back with it: no half-applied state."""
    monkeypatch.setattr(ai_env, "ai_worker_timeout", 1)
    w = worker_env([ACCEPT])
    w.delay = 2.5
    job = _job()
    claimed = ai_jobs.claim_next("runner-A")

    def broken(*args, **kwargs):
        raise RuntimeError("health write failed")
    monkeypatch.setattr(ai_jobs, "mark_error", broken)
    with pytest.raises(RuntimeError, match="health write failed"):
        ai_jobs._dispatch(claimed, claimed["lease_owner"])
    j = _row(job)
    assert (j["status"], j["retry_count"], j["error"], j["lease_owner"]) == ("pending", 0, None, claimed["lease_owner"])   # untouched
    assert all_rows("SELECT id FROM ai_job_events WHERE job_id = ? AND event_type = 'retry_scheduled'", job["id"]) == []
    assert status_of("ai_worker", "") is None


def test_health_writes_are_ordered_by_when_the_outcome_was_observed(ai_env):
    from flowmerce.modules.seo.integrations.status import mark_error, mark_success
    t = lambda n: f"2026-01-01T00:00:0{n}.000Z"   # noqa: E731
    assert mark_error("ai_worker", "", "external_worker", "first failure", at=t(2)) is True
    assert mark_success("ai_worker", "", "external_worker", None, at=t(1)) is False             # older than the failure: ignored
    assert status_of("ai_worker", "")["status"] == "error"
    assert mark_success("ai_worker", "", "external_worker", None, at=t(3)) is True              # newer: applied
    assert mark_error("ai_worker", "", "external_worker", "late failure", at=t(2)) is False     # older failure: ignored
    assert status_of("ai_worker", "")["status"] == "connected" and status_of("ai_worker", "")["last_error"] is None
    assert mark_error("ai_worker", "", "external_worker", "same instant", at=t(3)) is False     # a tie goes to success
    assert mark_success("ai_worker", "", "external_worker", None, at=t(3)) is True
    assert status_of("ai_worker", "")["status"] == "connected"
    assert mark_error("ai_worker", "", "external_worker", "plain call") is True                 # callers that pass no time keep the old behaviour
    assert status_of("ai_worker", "")["status"] == "error"


def test_a_skipped_stale_failure_is_not_audited(ai_env):
    from flowmerce.modules.seo.integrations.status import mark_error, mark_success
    run("DELETE FROM audit_log WHERE action = 'integration.failure' AND entity_id = 'ai_worker'")
    mark_success("ai_worker", "", "external_worker", None, at="2026-01-01T00:00:05.000Z")
    mark_error("ai_worker", "", "external_worker", "stale", at="2026-01-01T00:00:04.000Z")
    assert all_rows("SELECT id FROM audit_log WHERE action = 'integration.failure' AND entity_id = 'ai_worker'") == []
    mark_error("ai_worker", "", "external_worker", "fresh", at="2026-01-01T00:00:06.000Z")
    assert len(all_rows("SELECT id FROM audit_log WHERE action = 'integration.failure' AND entity_id = 'ai_worker'")) == 1
    run("DELETE FROM audit_log WHERE action = 'integration.failure' AND entity_id = 'ai_worker'")
