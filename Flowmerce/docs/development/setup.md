# Setup

The project runs on **Python 3.14** only, the same version on this computer, in CI and in the hosted container ([ADR 0010](../decisions/0010-one-python-version.md)); `.python-version` names it and the launcher stops on any other version.

## Install (Windows PowerShell, from the repository root)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,seo]"
copy .env.example .env
```

On macOS/Linux use `source .venv/bin/activate` and `cp .env.example .env`.

## Dependencies

Runtime dependencies of the core package: none (standard library only). The `seo` extra (fastapi, uvicorn, httpx, openpyxl, anthropic, google-auth, requests; carried over from blog-ops) is needed for the SEO module. Dev tools: `pytest` (tests), `ruff` (lint and format), `mypy` (strict type checking). Add any new dependency to `pyproject.toml` and record the reason here.

- `tzdata` (in the `seo` extra, added 2026-11-19 with the owner's approval): the IANA timezone database for Python's `zoneinfo`. Windows ships none, so without it `ZoneInfo("America/Los_Angeles")` fails. The CRO module needs it to split orders into each store's local days (US Pacific, with daylight saving). Data only, no code; maintained by the Python core team.

### CRO module (optional settings)

| Variable | Default | What it does |
|---|---|---|
| `CRO_SYNC_MINUTES` | `15` | How often the background job copies new Shopify orders into schema `cro` and checks the alarms; `0` turns it off |
| `CRO_CACHE_SECONDS` | `600` | How long a ShopifyQL answer (sessions, conversion rate, funnel) is reused |
| `CRO_CACHE_MAX` | `4000` | How many ShopifyQL answers are kept in memory at most (hosted image: `500`) |
| `CRO_WARM_VIEWS` | `true` | After each round, read the CRO pages' default views so visits answer from the cache (hosted image: `false`) |
| `CRO_SNAPSHOT_SECONDS` | `120` | How long the in-memory order snapshot is reused between syncs |

CRO uses Shipping's `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` and each brand's existing Shopify keys (`RIDHI_SHOPIFY_*`, `CPC_SHOPIFY_*`). Supabase must expose the `cro` schema (Data API → Exposed schemas), and `db/central/112_cro.sql`, `113_cro_orders.sql` and `114_cro_tracking.sql` (recommendation status, experiments, free-shipping amount) must have been run. Conversion figures need each store's app to have the `read_reports` scope and Level 2 protected customer data access. The Products tab's views and product groups use GA4 through the SEO module's Google service account (`GOOGLE_SERVICE_ACCOUNT_FILE`, `RIDHI_GA4_PROPERTY_ID`, `CPC_GA4_PROPERTY_ID`); without them the tab still shows sales, refunds, price bands and products bought together.

### Ads module (Meta Ads; Google Ads in phase 3)

| Variable | Default | What it does |
|---|---|---|
| `RIDHI_META_AD_ACCOUNT_ID`, `CPC_META_AD_ACCOUNT_ID` | none | Each brand's Meta ad account (with or without `act_`). A brand without one is skipped |
| `RIDHI_META_ACCESS_TOKEN`, `CPC_META_ACCESS_TOKEN` | none | A token with the `ads_read` permission (read-only). The page shows how many days it has left |
| `ADS_SYNC_MINUTES` | `60` | How often the background job reads the Meta accounts into schema `ads`; `0` turns it off |
| `META_APP_ID`, `META_APP_SECRET`, `META_BUSINESS_ID` | none | Not used yet (kept in `.env` for a system-user token later) |
| `GOOGLE_ADS_*`, `RIDHI_/CPC_GOOGLE_ADS_CUSTOMER_ID` | none | Not used yet: Google Ads is phase 3 |

Ads uses Shipping's `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`. Before the page can show anything:
1. run `db/central/115_ads.sql` in Supabase (SQL Editor);
2. add `ads` under Project Settings -> Data API -> Exposed schemas (next to `ops` and `cro`);
3. restart Flowmerce. A minute later the job reads both Meta accounts; the first read loads 90 days and takes about
   5 to 10 minutes per account. Until it finishes, the page says so.
Store sales come from CRO's order copy (`cro.orders`, files 112-113), so CRO's sync must be running too.

## Configuration

| Variable | Default | Allowed values |
|---|---|---|
| `FLOWMERCE_ENV` | `development` | development, test, production |
| `FLOWMERCE_LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, CRITICAL |

Settings are read from the process environment. The code does not load `.env` itself; export the variables in your shell (or add a loader via an approved ADR).

## Run

```powershell
python -m flowmerce version
python -m flowmerce health
```

## Test and check

```powershell
pytest
ruff check .
ruff format --check .
mypy
```

The same checks run automatically on GitHub (see [CI/CD](../operations/ci-cd.md), which also lists the frontend commands and the local smoke test, `python scripts/ci_smoke.py`). CI runs `ruff check .` but not `ruff format --check .`, because the migrated SEO code is not formatted yet.

## Running Flowmerce locally

```powershell
python scripts\run_flowmerce.py             # API on 127.0.0.1:8787 + web interface on 127.0.0.1:3000, opens the browser
python scripts\run_flowmerce.py --dev       # frontend in Next.js development mode
python scripts\run_flowmerce.py --no-browser
```

`scripts\run_seo.py` and `scripts\run_seo.bat` still work and forward to the same launcher. The launcher creates `.venv` if needed, installs `".[seo]"`, runs `npm install` in `frontend\` when `node_modules` is missing, builds the web interface when it is missing or older than its sources, starts both services, opens `http://127.0.0.1:3000` and stops both on Ctrl+C. It needs **Python 3.14** and **Node.js with npm** (Next.js 15 needs Node 18.18+; the project was last built with v26.13.0); it prints a clear message if Node.js/npm is missing, a package install or build fails, or port 8787 or 3000 is already in use.

Credentials and options are in `.env` (see the SEO section of `.env.example`). The module reads `.env` from the repository root and keeps its SQLite database in `data/` (`data/blog-ops.sqlite`).

**Two services.** The **API** is the Python FastAPI app (`flowmerce.modules.seo.main:app`); it returns JSON only and serves no pages. The **web interface** is the Next.js app in `frontend\` (React, JavaScript/JSX only, App Router). `frontend\next.config.mjs` forwards `/api/*` to `http://127.0.0.1:8787` (override at build time with `FLOWMERCE_API_ORIGIN`). The frontend holds no credentials.

**Local operator mode (no sign-in).** The dashboard opens without credentials. The web interface listens on `127.0.0.1` only, and the API answers only connections from this computer (loopback addresses); any other address gets HTTP 403 for every API path, even if the API's `HOST` is changed. Run it on `127.0.0.1` (the default) and do not expose it to a network or put a proxy or tunnel in front of it. The single exception is `POST /api/hooks/workflow`, the external workflow webhook, which has its own `X-Workflow-Secret` check and is reachable from other computers if the API is reachable. Local requests act as the first active administrator record, which the server creates at startup if none exists (no password is generated, shown or saved; `ADMIN_PASSWORD` is ignored). The old `/api/auth/login` and `/api/auth/password` endpoints answer 410. An existing `data/initial-admin.txt` is not deleted and is no longer used. Scripts that call the API from this computer still need the `X-Requested-With: blog-ops` header for mutating requests. See [ADR 0005](../decisions/0005-local-operator-mode.md).

**AI pictures for blog featured images (optional).** Set `GEMINI_API_KEY` (a key from Google AI Studio with billing on; Nano Banana Pro, about $0.13 a picture) or `OPENAI_API_KEY` (from the OpenAI API platform; the organization may need verifying). A ChatGPT Plus or Gemini app subscription does not include an API key. With both set, `IMAGE_PROVIDER=gemini` or `openai` picks one; `IMAGE_MODEL` overrides the model. Flowmerce then makes, checks and attaches each new draft's picture by itself (SEO & Blog, Automatic pictures: switches and daily/monthly limits). Pictures are stored in the store's Shopify Files, which needs the Shopify scope `write_files`.

**AI jobs (Flowmerce <-> Claude).** Choose how jobs are executed with `AI_EXECUTION_MODE` in `.env` (see `.env.example`). `anthropic_api`: set `ANTHROPIC_API_KEY` (an API key from the Anthropic Console; a Claude.ai subscription does not include one) and Claude is called from this server. `external_worker`: **all three** of `AI_WORKER_URL` (https), `AI_WORKER_TOKEN` and `WORKFLOW_WEBHOOK_SECRET` are required (without the secret Flowmerce cannot authenticate the worker's callbacks, so no job can be created and waiting jobs are not sent). The worker must implement the contract in [ADR 0009](../decisions/0009-ai-job-bridge.md) and you must put the **same** webhook secret into the worker's own environment yourself, through a secure channel: Flowmerce never sends it. `AI_CALLBACK_URL` (the public HTTPS URL of the webhook) is sent to the worker as `callback_url`; leave it empty only if the worker already knows where to call back. Topic research and content generation on the Automation page, and the topic page's "Draft with Claude" button, now queue background AI jobs in either mode ("Queue AI job"); the request returns at once and the job's progress is shown under **AI jobs**. Until the chosen method is configured, **Automation → AI jobs** says "API not configured" or "Worker not configured" and no job can be created. Run one Flowmerce process per database file. For a worker on another machine the webhook must be reached through a secured HTTPS gateway that forwards only `POST /api/hooks/workflow`, with rate limiting and monitoring; do not expose the dev server or the whole app. Nothing in this feature publishes: results become proposed topics or draft articles.

**Claude daily limit and brand knowledge.** `CLAUDE_MONTHLY_BUDGET_USD` (default 90, and never more than the $90 ceiling) is the starting monthly budget; a warning shows on the SEO & Blog pages once 80% of the day or the month is used; admins change it on **SEO & Blog → Content calendar**, and the saved value wins. Each day may spend at most budget / days in the month (estimated from list prices; calls made by an external worker are not counted). The day follows `CLAUDE_BUDGET_UTC_OFFSET_MINUTES` (default 330, India). What Claude knows about each brand is the files in `src/flowmerce/modules/seo/knowledge/<brand>/`; edit them and restart Flowmerce.

**AI jobs: manual test** (no real Claude or worker needed). 1) In `.env` set `AI_EXECUTION_MODE=external_worker`, `AI_WORKER_URL=http://127.0.0.1:9100`, `AI_WORKER_TOKEN=test-token`, `WORKFLOW_WEBHOOK_SECRET=test-secret`, then start Flowmerce. 2) Start a stand-in worker that answers `{"status":"accepted"}` on `POST /v1/jobs` at that address (for example a few lines of Python with `http.server`). 3) In Automation → AI jobs click **New AI job** (topic research): the job appears as Pending, then Queued after the stand-in accepts it. 4) Act as the worker with curl, using the job id shown in the list (the same pattern works for each step):

```bash
curl -X POST http://127.0.0.1:8787/api/hooks/workflow -H "X-Workflow-Secret: test-secret" -H "Content-Type: application/json" -d '{"event_id":"manual-0001","job_id":"<JOB ID>","event_type":"started","sequence":1}'
curl -X POST http://127.0.0.1:8787/api/hooks/workflow -H "X-Workflow-Secret: test-secret" -H "Content-Type: application/json" -d '{"event_id":"manual-0002","job_id":"<JOB ID>","event_type":"progress","sequence":2,"progress":45,"message":"Researching"}'
curl -X POST http://127.0.0.1:8787/api/hooks/workflow -H "X-Workflow-Secret: test-secret" -H "Content-Type: application/json" -d '{"event_id":"manual-0003","job_id":"<JOB ID>","event_type":"succeeded","sequence":3,"result":{"topics":[{"title":"Test topic","primary_keyword":"test keyword","secondary_keywords":[],"intent":"informational","rationale":"manual test"}]}}'
```

The job moves Running (45%) then Succeeded, and the topic appears under Topics as proposed. For a failure send `{"event_id":"manual-0004","job_id":"<JOB ID>","event_type":"failed","sequence":3,"error":"test failure"}` instead of the success, then use **Retry**. Re-sending an `event_id` is ignored; sending a lower `sequence` is refused with 409. Remove the test topic afterwards.

**Checking and repairing stored data** (run from the repository root with the project's Python, `.venv\Scripts\python.exe`):

```powershell
python -m flowmerce.modules.seo.maintenance db-report          # read-only summary: integration status, articles, stored GSC/GA4 coverage
python -m flowmerce.modules.seo.maintenance backup             # verified copy of data/blog-ops.sqlite into backups/
python -m flowmerce.modules.seo.maintenance resync-preview --source gsc --brand ridhi --from 2025-08-01 --to 2026-11-10
python -m flowmerce.modules.seo.maintenance resync-apply   --source gsc --brand ridhi --from 2025-08-01 --to 2026-11-10 --confirm
```

`db-report` opens the database read-only and changes nothing. `resync-preview` reads from Google and shows how many stored days would be added or changed; it writes nothing. `resync-apply` first makes a verified backup, then replaces only the live-API rows of the range (demo and imported rows are never touched) and writes an audit line. Run `resync-apply` only after the preview has been reviewed and approved. Routine syncs re-read only the last 10 days (Search Console) or 7 days (GA4); when the computer was off longer, the Integrations page and `db-report` show the gap and these commands fill it.

**Moving from the original blog-ops folder** (done 2026-10-29; the folder no longer exists): `.env`, `data/` and `backups/` now live in the repository root. Both are git-ignored; keep your own copy of `.env` and back up `data/` and `backups/`.

**Building the UI** (needs Node.js; `frontend\.next` and `frontend\node_modules` are git-ignored, so a fresh clone must install and build): from `frontend\` run `npm ci` (installs exactly what `package-lock.json` specifies) and `npm run build` (the Next.js build). There is no TypeScript type check: the frontend is JavaScript/JSX only. There is no frontend lint or test suite yet; `python scripts\ci_smoke.py --web` starts the built frontend and checks its routes.

**Changing the UI**: start the API (`python scripts\run_flowmerce.py --dev` does both), edit files in `frontend\src\`, and the page reloads. Routes are folders under `frontend\src\app\`; page implementations are in `frontend\src\views\`. The original `README` is archived at `docs/architecture/legacy-blog-ops-README.md`.
