# ADR 0009: AI job bridge between Flowmerce and Claude

- Status: approved (owner approved the plan and the safeguards on 2026-11-04; implementation not yet exercised with live credentials)
- Date: 2026-11-04

## Decision

Flowmerce hands AI work to Claude as **jobs**. A job is saved in the database first, then executed in the background either by this server calling the Anthropic API (`AI_EXECUTION_MODE=anthropic_api`) or by an independently deployed **worker** (`AI_EXECUTION_MODE=external_worker`) that reports progress and the result back to Flowmerce's existing webhook, `POST /api/hooks/workflow`. With `AI_EXECUTION_MODE=disabled`, or with the chosen method not configured, no job can be created (HTTP 412, `pending_setup`) and the rest of Flowmerce works as before.

```
Dashboard ──create job──▶ Flowmerce backend ──saves job + one workflow run──▶ database
                                  │ runner claims it (atomic, leased)
                  ┌───────────────┴────────────────┐
        anthropic_api                        external_worker
   Claude called from this server     POST {AI_WORKER_URL}/v1/jobs  (bearer token)
                  │                                 │
                  │                      worker runs Claude with ITS credentials
                  │                                 │ POST /api/hooks/workflow (X-Workflow-Secret)
                  ▼                                 ▼
          validate result  ◀──────  authenticate, validate, apply event to the SAME job
                  ▼
   proposed topics / draft article  ──▶  a person reviews and approves  ──▶  existing publishing approval
```

A finished job never approves or publishes anything.

**Every Claude call goes through a job.** The Automation controls (`Queue AI job` on Topic research and Content generation, `POST /api/automation/{brand}/stages/{stage}/run`, the topic page's "Draft with Claude" button, `POST /api/topics/{id}/article` with `mode: claude`, and the retry of an old failed run) no longer call Claude inside the request: `workflow.run_stage()` keeps its permission, brand, pause and setup checks, then calls `ai_jobs.create_job()` and returns at once (`status: queued`, with the job; content generation makes one job per approved topic, up to the brand's drafts-per-run; the topic button answers 202 with `articleId: null` and the job). The old inline runners were removed, so no code path can reach Claude without a job. Non-AI stages (keyword validation, image selection, Shopify drafts, performance tracking) run exactly as before. An AI stage is "ready" when either execution method is configured (`provider_status()`), including an external worker. Topics arrive as `proposed`, articles as `draft`; the existing human review, publish approval and `ALLOW_LIVE_PUBLISH=false` safeguard are untouched.

Not done: Flowmerce does not drive Claude.ai in a browser, use session cookies or unofficial endpoints, or assume a Claude.ai subscription includes API access. A standalone worker service is **not** built here; only the adapter, the contract below and tests against a mock worker.

## Status vocabulary (database = API = dashboard)

| Value | Where | Meaning |
|---|---|---|
| `pending` | job status | saved, not yet taken by an executor; also waiting for a retry, or for a worker that is unavailable |
| `queued` | job status | an external worker accepted it. **Never** used for an unavailable provider |
| `running` | job status | an executor is working on it |
| `succeeded`, `failed`, `cancelled` | job status | final; only a person can retry a `failed` job |
| `pending_setup` | provider state and HTTP 412 code | no execution method configured; **no job is created** |
| `ready`, `unavailable`, `disabled` | provider state | worker/API usable; last worker call failed; switched off |
| `accepted` | webhook **event type** | the worker took the job (moves it to `queued`); not a status |

Allowed transitions: `pending → queued | running | failed | cancelled`; `queued → running | succeeded | failed | cancelled`; `running → succeeded | failed | cancelled`; `running → pending` (internal only: interrupted, transient failure, shutdown); `failed → pending` (a person retried). `succeeded`, `cancelled` and `failed` cannot be updated in place. The workflow run of a job follows it: `running` while the job is active, then `succeeded`, `failed`, or `skipped` (cancelled).

## Database (migration 2, additive)

Two new tables; no existing table or row is touched; `PRAGMA user_version` runs the migration once, in a transaction.

- `ai_jobs`: `id` (uuid), `brand_id`, `stage`, `task_type`, `input_json`, `status` (CHECK constraint on the six values), `provider`, `worker_id`, `external_id`, `retry_count`, `max_retries`, `attempts`, `run_number`, `progress`, `message`, `error`, `error_kind`, `result_json` (a small summary: ids and counts, never the raw answer), `workflow_run_id`, `idempotency_key` (UNIQUE), `dedupe_key` (unique while the job is active), `last_sequence`, `lease_owner`, `lease_expires_at`, `next_attempt_at`, `accepted_at`, `created_by`, `created_at`, `started_at`, `last_progress_at`, `finished_at`, `updated_at`.
- `ai_job_events`: one row per callback and per lifecycle step; `UNIQUE (job_id, event_id)` is what makes callbacks idempotent.

The existing `workflow_runs` table is reused, one row per job (`trigger_kind = 'ai_job'`), never one per callback.

## Supported tasks

| `task_type` | Workflow stage | Input | What a result may create |
|---|---|---|---|
| `topic_research` | `topic_research` | `{"count"?: 1-20, "focus"?: text}`; the job records `count` (the request, or the brand's configured topics-per-run) | new topics with status `proposed` (duplicates of an existing keyword are skipped). **A result with more topics than `count` is rejected whole** (nothing is created) |
| `content_generation` | `content_generation` | `{"topic_id": n}` (must be an **approved** topic of that brand with no article yet) | one article with status `draft`, linked to that topic; the topic moves to `in_production` |

Other task types are rejected (`unsupported_task`). Adding one needs a new validator in `ai_results.py` and a decision on what it may create.

## API (local operator only; CSRF header on POST; permission `workflow:run` to change, `view` to read)

| Method and path | Purpose |
|---|---|
| `GET /api/ai/jobs?brand=&status=` | `{provider, jobs[]}`; `provider.state` is `ready`, `pending_setup` (with `missing`: `anthropic_api_key` or `worker_config`), `unavailable` or `disabled` |
| `GET /api/ai/jobs/{id}` | one job with its event history |
| `POST /api/ai/jobs` | body `{"brand","task_type","input"?,"idempotency_key"?}`. **202** `{job, deduplicated:false}`; **200** `deduplicated:true` for a repeated request; 412 `pending_setup`; 400/404/409/423 for invalid input, an unapproved topic, a paused brand |
| `POST /api/ai/jobs/{id}/retry` | failed job becomes `pending` again with a new `run_number` |
| `POST /api/ai/jobs/{id}/cancel` | pending, queued or running job becomes `cancelled` (a Claude call already in flight cannot be interrupted, but its result is discarded; Flowmerce does not call a worker to cancel, and the worker's later events are refused) |

Repeating a create request returns the same job: by `idempotency_key` when given (even after the job finished), otherwise while an identical (brand, task, input) job is still active. A key is bound to the complete request: Flowmerce stores a SHA-256 fingerprint of brand, task type and the normalised input (key order does not matter; a topic research job always records its topic count, so an omitted count and an explicit default are the same request). Reusing a key with a different brand, task type or input is **409 `idempotency_conflict`**. A replay is answered before any state check, so a client retry still gets its job after the topic was used up. Concurrent duplicates are safe: creation runs in one transaction under the database lock and the unique indexes arbitrate the rest.

## Outbound worker contract, version 1

```
POST {AI_WORKER_URL}/v1/jobs          (https, or http only to a loopback address; redirects are never followed)
Authorization: Bearer <AI_WORKER_TOKEN>
Idempotency-Key: <job_id>:<run_number>
X-Flowmerce-Contract: 1
{"contract": 1, "job_id": "…", "run_number": 1, "brand": "ridhi", "task_type": "topic_research", "stage": "topic_research",
 "input": {"brand": {"id","name","domain","voice","audience","avoid"}, "count": 5, "focus": "", "existing_titles": [], "products": [], "queries": []},
 "callback_url": "https://…/api/hooks/workflow",      // only if AI_CALLBACK_URL is set
 "callback_reference": "<job_id>"}
```
For `content_generation`, `input` holds `brand`, `topic` (`title`, `primary_keyword`, `secondary_keywords`, `intent`, `notes`) and `links` (real internal-link targets).

Worker answer: **2xx** `{"status": "accepted" | "queued", "worker_id"?: str, "external_id"?: str}`, or **409** with the same body when that `Idempotency-Key` was already accepted (treated as accepted). The webhook secret, the Anthropic key and any other credential are **never** in the payload or headers; the worker holds its own `WORKFLOW_WEBHOOK_SECRET` and Anthropic credentials in its own environment.

Failure handling (`ai_worker.py`, `ai_jobs._after_failure`): connection errors and timeouts (`AI_WORKER_TIMEOUT_SECONDS`, default 15), 408, 425, 429, 500, 502, 503, 504 and an unreadable 2xx are **retryable**: the job stays `pending` with exponential backoff (`AI_RETRY_BASE_SECONDS` × 2^(n-1), at most `AI_RETRY_MAX_SECONDS`, or the worker's `Retry-After`, also capped) up to `AI_JOB_MAX_RETRIES`, then fails. 401/403 (credentials), other 4xx and 501/505 are **permanent**: the job fails at once with the reason. An unavailable worker is recorded (`integration_status` key `ai_worker`) and shown as "Worker unavailable"; the job is never shown as queued. The same job sent twice carries the same `Idempotency-Key`, so a worker that de-duplicates by it never runs it twice.

## Inbound callbacks: `POST /api/hooks/workflow` with a `job_id`

Field types are checked explicitly before any membership test (`event_type` and `status` must be strings; a list or object is a 400 `invalid_event`/`invalid_status`, never an internal error), and a worker acknowledgement whose `status` or ids are not strings is a retryable `invalid_response` `WorkerError`.

Authentication: header `X-Workflow-Secret` compared in constant time (SHA-256 digests, `hmac.compare_digest`) **before** the body is read; no secret configured → 404 (disabled); wrong or missing → 401. The body is read in chunks and refused with **413 once it passes 64 KB of actual bytes**, whatever `Content-Length` says (or whether it is chunked and has none). It must be a JSON object (no NaN/Infinity). The route and header are unchanged from before.

Event body (unknown fields are rejected, not ignored):

```json
{"event_id": "unique-8-to-128-chars", "job_id": "…", "event_type": "progress", "sequence": 3,
 "status": "running", "progress": 45, "message": "Researching…", "agent": "claude-worker", "external_id": "exec-1",
 "run_number": 1, "brand": "ridhi", "stage": "topic_research", "occurred_at": "2026-11-04T10:00:00Z", "callback_reference": "<job_id>"}
```

| `event_type` | resulting status | extra |
|---|---|---|
| `accepted` | `queued` | |
| `started` | `running` | |
| `progress` | `running` | `progress` 0-100, never lower than the last |
| `succeeded` | `succeeded` | `result` object required (validated, below) |
| `failed` | `failed` | `error` text |

`status` is optional; if sent it must equal the status of its `event_type` (anything else is 400 `invalid_status`; nothing is ever turned into `succeeded`). `sequence` (whole number ≥ 1, required) must be higher than the job's last accepted sequence; gaps are allowed. `run_number` is required once a job has been retried (the worker is told it in the payload). Order a worker should follow: `accepted`, `started`, `progress`*, then `succeeded` or `failed`.

Processing, all in **one transaction** with the workflow run and any stored result: unknown job → 404; `brand`/`stage`/`callback_reference` that do not match the job → 409/400; job not executed by an external worker → 409; **a repeated `event_id` → 200 `duplicate: true`, nothing changes**; job already final → 409 `job_finished`; wrong `run_number` → 409 `stale_run`; `sequence` not newer → 409 `stale_event`; implausible `occurred_at` (future, or before the job existed, ±5 min) → 400; different `external_id` → 409; invalid transition → 409; progress going backwards → 409 `stale_progress`. A rejection changes nothing. Accepted events extend the worker's deadline (`AI_JOB_TIMEOUT_SECONDS`, default 30 min of silence fails the job with a timeout; a person can retry). Every accepted event is audited.

Result handling (`ai_results.py`): the result must match the job's task exactly (known fields only; lengths, counts and total size ≤ 256 KB; no control characters; no `<script>`, frames, forms, event handlers, `javascript:` URLs), then body HTML also passes the existing allow-list sanitizer. A bad result → **422**, the job becomes `failed` (`invalid_result`) and nothing is stored. For `content_generation` the draft is stored only if the job's topic is still approved and still has no article; its primary keyword comes from the topic, not from the worker. A callback can write only to: the job, its events, its workflow run, new `proposed` topics, and one new `draft` article with its first revision. It cannot approve, publish, schedule, call Shopify or Google, change users or permissions, or run SQL; sending such fields is a 400.

### Legacy callbacks (no `job_id`) and their retirement

The old body `{"brand","stage","status","message","error","agent","external_id","started_at","finished_at"}` still works and still appends one `workflow_runs` row per call, so existing routines keep reporting. Changes: `status` must be one of `running, succeeded, failed, waiting, skipped` (missing or invalid is now **400**, no longer silently `succeeded`); a `result` field is refused (400 `result_requires_job`); timestamps are validated or replaced by the server clock; the body obeys the same 64 KB limit. The legacy path cannot carry results or create records. **Deprecation:** use job callbacks for anything new; the legacy path will be removed after the owner confirms no integration still posts to it (tracked in the roadmap).

## Execution, leases and recovery (single instance)

The runner (`ai_jobs.Runner`, started at app startup, stopped on shutdown) polls every 2 s, claims due `pending` jobs atomically (one `UPDATE` inside the database lock), and runs them on a pool of at most `AI_MAX_CONCURRENCY` (default 2) threads. **Lease tokens.** Every claim of a job generates its own unique token (`<runner>:<random>`), stored in `lease_owner` and handed to that one execution. Every write an execution makes (result, failure, dispatch acknowledgement) is conditional on its token being the job's current token **and** the lease not having expired (`_holds`); otherwise nothing is written. So when a lease expires, the job is recovered and the same runner reclaims it, the first execution's late result is discarded and the second keeps the job (a regression test reproduces exactly this with a real `Runner`). Shutdown releases only the claims of that runner (by token prefix), never another's. **A worker callback takes the job over from the dispatch request:** the first valid `accepted`, `started` or `progress` callback clears the dispatch lease token and keeps only the worker's inactivity deadline (`lease_expires_at`, extended by every callback). If the dispatch HTTP request then times out or fails, its token holds nothing, so it cannot requeue or fail a job the worker is running (no retry is used, and the worker is not marked unavailable: a dispatch failure is applied only by `_after_failure()` with the original dispatch lease token, and the worker is marked unavailable only when that call actually applied a failure to this dispatch attempt; a job the worker already finished, failed or that was cancelled keeps its state and result). The failure and the health update are one transaction, and health writes are ordered by when the outcome was **observed** (`mark_success` / `mark_error` take an optional `at`; an older result never overwrites a newer one, a tie goes to success), so concurrent jobs cannot leave a stale "unavailable" behind; the existing `integration_status` table is used unchanged; a late acknowledgement can only fill identifiers (`worker_id`, `external_id`) that the callbacks did not carry, never status, progress, lease or deadline. In `anthropic_api` mode a claim sets `running` plus a **lease** (`AI_LEASE_SECONDS`, default 900, automatically raised to cover the worst case of one Claude call: `CLAUDE_TIMEOUT_SECONDS` × (`CLAUDE_MAX_RETRIES` + 1) + 2 minutes); every write by the executor requires it still holds that lease, so a stale or cancelled executor's result is discarded. In `external_worker` mode a claim only sets a dispatch lease (longer than the worker request timeout), so one job is sent once. A job receives at most 2000 events (429 after that), so a leaked secret cannot grow it or extend its deadline without limit. With `AI_EXECUTION_MODE=disabled` the runner does not start, but interrupted jobs are still settled at startup; pending jobs can be cancelled from the dashboard. Recovery runs at startup and every tick: interrupted `anthropic_api` jobs go back to `pending` within the retry budget, otherwise fail; silent worker jobs time out; leftover dispatch leases are cleared; pending jobs created for a different mode fail. Graceful shutdown stops claiming, waits up to 20 s for work in flight, then hands unfinished jobs back to `pending` without using a retry. Jobs are never lost on restart: they are rows. **Pausing a brand** (Automation → Pause) stops new AI work for it: `claim_next` skips a paused brand's pending jobs, `create_job` and a manual retry answer 423 `paused`, and non-AI stages are blocked as before. Work already running is not interrupted, a worker's callbacks still apply, and cancelling still works; resuming the brand makes waiting jobs eligible again at once. **Assumption:** one Flowmerce process per SQLite file (the local-operator setup). The claim is atomic within that process's database lock, **not** across several servers; do not run two instances on one database, and do not treat this as multi-instance safe.

Anthropic calls (`integrations/claude.py`): explicit timeout (`CLAUDE_TIMEOUT_SECONDS`, default 600); rate limits (honouring `Retry-After`), 5xx and connection errors are retried up to `CLAUDE_MAX_RETRIES` (default 2) with exponential backoff capped at 30 s; authentication, permission and invalid-request errors are never retried; **a timeout is never retried automatically** (the request may already have run, so the error is marked ambiguous and a person decides). Errors are classified (`ClaudeError.kind`). Model, token usage, request id, attempts and duration are recorded on the job (no prompt, no key, no answer text). Jobs add their own retry budget on top for rate limits and 5xx.

## Configuration (placeholders only; see `.env.example`)

`AI_EXECUTION_MODE` (`anthropic_api` default, `external_worker`, `disabled`), `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `AI_WORKER_URL`, `AI_WORKER_TOKEN`, `AI_CALLBACK_URL`, `WORKFLOW_WEBHOOK_SECRET`.

**External worker mode is ready only when** `AI_WORKER_URL` (https, or loopback http), `AI_WORKER_TOKEN` **and** `WORKFLOW_WEBHOOK_SECRET` are all set (and `AI_CALLBACK_URL`, if set, is a safe URL). Without the secret Flowmerce could not authenticate the worker's callbacks, so job creation answers 412 `pending_setup`, the dashboard says "Callback authentication not configured", and jobs already waiting are **not dispatched** until it is set. The administrator must provision the same secret in the worker's own environment, separately and securely: Flowmerce never sends it (not in the payload, not in headers), the worker sends it back as `X-Workflow-Secret`. `AI_CALLBACK_URL` is the public HTTPS URL of `POST /api/hooks/workflow` and is sent to the worker as `callback_url`; it may be left empty **only if** the worker is already configured with that destination by other means (the dashboard then shows a note). Tuning values: and the tuning values `AI_WORKER_TIMEOUT_SECONDS`, `AI_MAX_CONCURRENCY`, `AI_JOB_MAX_RETRIES`, `AI_LEASE_SECONDS`, `AI_JOB_TIMEOUT_SECONDS`, `AI_RETRY_BASE_SECONDS`, `AI_RETRY_MAX_SECONDS`, `CLAUDE_TIMEOUT_SECONDS`, `CLAUDE_MAX_RETRIES`.

## Making the webhook reachable from outside (not done by this change)

Flowmerce stays in local operator mode: every route except the one webhook answers only this computer, and that has not changed (no CORS, host-binding or firewall change was made). For a worker on another machine to call back, the owner must provide, outside this repository: a **publicly reachable HTTPS endpoint that forwards only `POST /api/hooks/workflow`** to the local server (a reverse proxy or gateway; never expose the development server or the whole app), valid TLS with certificate verification, secret management for `WORKFLOW_WEBHOOK_SECRET` and the worker's own credentials, **request rate limiting** at the gateway (the app does not rate-limit), and monitoring and alerting on 401/413/422 spikes and on `ai_job.*` audit entries. A tunnel or proxy on this computer makes remote requests look local to the other routes (a known limit of local operator mode, ADR 0005), so the gateway must allow-list the single path.

## Local testing

`python -m pytest tests -q` runs everything against an in-memory database with the Claude calls replaced and a loopback fake worker; no network, no credentials. A manual walk-through without a real worker is in `docs/development/setup.md` ("AI jobs: manual test").

## Alternatives considered

Reusing only `workflow_runs` (no separate job entity: no state machine, idempotency or lease, and one row per callback); running Claude inside the dashboard request (minutes-long requests, lost on restart); a message queue or Celery/Redis (new technology that needs the owner's approval first); automating Claude.ai (not an authorised method).

## Advantages

Work survives restarts; one record per job; duplicates, replays and out-of-order callbacks are harmless; the worker is replaceable behind a small contract; staff see status and failures; nothing can publish.

## Disadvantages

SQLite and an in-process runner mean single-instance only; no rate limiting inside the app; no worker-side cancellation; the legacy webhook path remains until retired.

## Consequences and dependencies

New tables and an additive migration; `WORKFLOW_WEBHOOK_SECRET` now protects result-bearing callbacks, so it must be a long random value; a worker implementing contract v1 is still to be built and deployed; live Anthropic and worker calls have **not** been tested with real credentials.
