"""Adapter for an independently deployed AI worker (AI_EXECUTION_MODE=external_worker).

Contract, version 1 (documented in docs/decisions/0009-ai-job-bridge.md):

    POST {AI_WORKER_URL}/v1/jobs
    Authorization: Bearer <AI_WORKER_TOKEN>
    Idempotency-Key: <job_id>:<run_number>   (stable across automatic retries of one run; a person's retry starts a new run_number)
    X-Flowmerce-Contract: 1
    {"contract": 1, "job_id", "run_number", "brand", "task_type", "stage", "input": {...}, "callback_url"?, "callback_reference"}

    2xx  {"status": "accepted" | "queued", "worker_id"?: str, "external_id"?: str}   the worker owns the job now
    409  {"status": "accepted" | "queued", ...}   the same job_id was already submitted: treated as accepted (idempotent)

The worker reports progress and the result to Flowmerce's webhook with its own credentials. The webhook
secret is never sent here. Anything that is not a valid acceptance is an error classified as retryable
(network failure, timeout, 408/425/429/500/502/503/504, an unreadable 2xx) or permanent (401/403/other 4xx,
501/505). Redirects are never followed. The base URL must be https, except for a loopback address."""
from __future__ import annotations

import ipaddress
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ..config import config

log = logging.getLogger(__name__)

Job = dict[str, Any]

CONTRACT_VERSION = 1
MAX_RESPONSE_BYTES = 64 * 1024
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
ACCEPTED_STATUS = frozenset({"accepted", "queued"})


class WorkerError(RuntimeError):
    """A failed submission. kind: auth, rejected, unavailable, timeout, invalid_response, not_configured."""

    def __init__(self, message: str, kind: str, retryable: bool, retry_after: float | None = None, http_status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after
        self.http_status = http_status


@dataclass(frozen=True)
class Ack:
    """What the worker said when it took the job."""
    status: str
    worker_id: str | None
    external_id: str | None
    duplicate: bool


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a: Any, **_k: Any) -> None:  # a redirect would send the token somewhere the owner did not configure
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_url(value: str) -> str:
    """value if it is an https URL (or http to a loopback address) with no credentials, query or fragment; otherwise ""."""
    u = urlparse(value.strip())
    if not u.hostname or u.username or u.password or u.query or u.fragment:
        return ""
    if u.scheme == "https" or (u.scheme == "http" and _is_loopback(u.hostname)):
        return value.strip()
    return ""


def base_url() -> str:
    """The validated worker base URL without a trailing slash, or "" when it is missing or unsafe."""
    return _safe_url(config.ai_worker_url.strip().rstrip("/"))


def callback_url() -> str:
    """AI_CALLBACK_URL if it is a safe URL, else "". It is sent to the worker as `callback_url`; it is optional only when the
    worker is separately configured with where to send callbacks."""
    return _safe_url(config.ai_callback_url) if config.ai_callback_url else ""


def configured() -> bool:
    return bool(base_url() and config.ai_worker_token)


def build_payload(job: Job, job_input: Job) -> Job:
    """The versioned request body. job_input is the task context built by Flowmerce; nothing secret goes in."""
    body = {"contract": CONTRACT_VERSION, "job_id": job["id"], "run_number": job["run_number"], "brand": job["brand_id"], "task_type": job["task_type"],
            "stage": job["stage"], "input": job_input, "callback_reference": job["id"]}
    if callback_url():
        body["callback_url"] = callback_url()
    return body


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Retry-After as seconds, from either a number or an HTTP date; None when absent or unreadable. Never negative."""
    if not value:
        return None
    v = value.strip()
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(v)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError):
        return None


def backoff_seconds(retry_number: int, retry_after: float | None = None) -> float:
    """Bounded exponential backoff: base * 2^(n-1), at most AI_RETRY_MAX_SECONDS. A server's Retry-After wins,
    also capped, so a hostile or broken worker cannot park a job for days."""
    cap = float(config.ai_retry_max_seconds)
    if retry_after is not None:
        return min(cap, float(retry_after))
    return min(cap, float(config.ai_retry_base_seconds) * float(2 ** max(0, retry_number - 1)))


def submit(job: Job, job_input: Job) -> Ack:
    """Send one job to the worker. Returns the acknowledgement or raises WorkerError."""
    if not configured():
        raise WorkerError("The AI worker is not configured (AI_WORKER_URL must be https, and AI_WORKER_TOKEN set).", "not_configured", retryable=False)
    data = json.dumps(build_payload(job, job_input), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base_url() + "/v1/jobs", data=data, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {config.ai_worker_token}",
        "Idempotency-Key": f"{job['id']}:{job['run_number']}", "X-Flowmerce-Contract": str(CONTRACT_VERSION), "User-Agent": "Flowmerce-AI-Dispatcher/1"})
    try:
        with _opener.open(req, timeout=float(config.ai_worker_timeout)) as resp:  # noqa: S310 - scheme and host validated in base_url()
            status, body = resp.status, resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read(MAX_RESPONSE_BYTES + 1)
        retry_after = parse_retry_after(e.headers.get("Retry-After") if e.headers else None)
        if status == 409:
            ack = _parse_ack(body, duplicate=True)
            if ack:
                return ack
        if status in (401, 403):
            raise WorkerError(f"The AI worker rejected the credentials (HTTP {status}). Check AI_WORKER_TOKEN.", "auth", False, http_status=status) from e
        retryable = status in RETRYABLE_STATUS
        raise WorkerError(f"The AI worker answered HTTP {status}.", "unavailable" if retryable else "rejected", retryable, retry_after, status) from e
    except TimeoutError as e:
        raise WorkerError("The AI worker did not answer in time.", "timeout", True) from e
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise WorkerError("The AI worker did not answer in time.", "timeout", True) from e
        raise WorkerError("The AI worker could not be reached.", "unavailable", True) from e
    if len(body) > MAX_RESPONSE_BYTES:
        raise WorkerError("The AI worker's response is too large.", "invalid_response", True, http_status=status)
    ack = _parse_ack(body, duplicate=False)
    if not ack:
        raise WorkerError("The AI worker's response was not a valid acceptance.", "invalid_response", True, http_status=status)
    return ack


def _parse_ack(body: bytes, duplicate: bool) -> Ack | None:
    try:
        d = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    status = d.get("status") if isinstance(d, dict) else None
    if not isinstance(status, str) or status not in ACCEPTED_STATUS:   # a list or object is unhashable: check the type first
        return None
    assert isinstance(d, dict)
    ids = {}
    for k in ("worker_id", "external_id"):
        v = d.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 200):
            return None
        ids[k] = v
    return Ack(d["status"], ids["worker_id"], ids["external_id"], duplicate)
