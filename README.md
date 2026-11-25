# Flowmerce

A unified e-commerce platform to track, manage and act on what happens in the business, for two Shopify brands: **Ridhi Block Print (RBP)** and **Cotton Print Club (CPC)**.

Flowmerce is one application with separate modules on one shared foundation (one Python backend, one Next.js frontend, one database):

| Module | State |
|---|---|
| **SEO & Blog** | Working (SQLite today). Articles, topics & keywords, approvals, publishing safeguards, Search Console / GA4, Claude AI jobs |
| **Shipping** | Built (2026-11-17). Reads the central Supabase database (schema `ops`), which refreshes itself from the *Delayed Orders Tracker* tables. Needs the one-time Supabase setup below |
| **Meta & Google Ads** | Backend started (2026-11-25), reading only. Schema `ads` and the Meta and Google clients are written and unit-tested; **nothing has run against a live ad account**, and `db/central/115_ads.sql` has not been run. Shows sample figures until credentials arrive. No page yet |
| **Creative Strategist** | Backend started (2026-11-25). Groups ad performance by creative format and hook, and Claude writes concepts with hooks, ad copy, carousels, Reel shot lists, UGC briefs, one-variable tests and variations of a winning concept. Checked against the live Claude API on 2026-11-25. `db/central/116_creative.sql` has not been run and the figures Claude reads are still samples, because no ad account is connected. No page yet |
| Landing Page Builder | Planned only. No menu entry or page |
| **CRO** | In progress. See `Flowmerce/docs/development/roadmap.md` |

---

## Current status (2026-11-17)

- **SEO & Blog** works as before (still on SQLite). The only change near it: `seo/app.py` now also mounts the Shipping routes, inside a guard so a Shipping failure can never stop SEO.
- **Shipping module built:** backend `src/flowmerce/modules/shipping/`, page `/shipping` (Overview, Shipments, Problems, Carriers, detail drawer with scan history and team check), CSV export, background refresh every 15 min. 27 unit tests pass; the frontend production build passes; the API smoke test passes.
- **Central database SQL** in [`db/central/`](db/central/README.md), one-file version `db/central/supabase_setup.sql`. Checked against the **live tracker tables** (columns and status words read on 2026-11-17), but **not yet run in Supabase**: that is the owner's step 1 below.
- **Accuracy bug found in the live data:** the tracker shows 9 `NOT_DELIVERED` and 2 `DELAYED` parcels as plain "fulfilled". Flowmerce maps Shopify's raw word instead and shows them as delivery problems. All 4,036 "delivered" parcels come from Shopify only and are labelled *not carrier-confirmed*.
- **Not built:** the other four modules, sign-in (planned for Phase 5), webhooks, the shared approval engine.

Earlier history: the SEO module was migrated from the standalone `blog-ops` app on 2026-10-29 ([ADR 0003](docs/decisions/0003-blog-ops-migration-plan.md)); the Next.js frontend replaced the old UI ([ADR 0006](docs/decisions/0006-nextjs-javascript-frontend.md)); local operator mode removed sign-in ([ADR 0005](docs/decisions/0005-local-operator-mode.md)); the AI job bridge was added ([ADR 0009](docs/decisions/0009-ai-job-bridge.md)).

---

## Unification: SEO + Shipping on one database

The goal is **one Flowmerce app** with Home · SEO & Blog · Shipping tabs, one Python backend, and **one Supabase PostgreSQL database**:

```
Supabase PostgreSQL
├─ ops      orders, items, shipments, tracking numbers + every scan, carriers, exceptions,
│           returns, costs, alerts timeline, data-feed logs, shared stores/settings/people
├─ seo      the 20 SEO tables, ported 1:1 from data/blog-ops.sqlite
└─ public   the Delayed Orders Tracker's live tables (never changed; read once for the import)
```

Why shipping data becomes trustworthy: every status keeps its **source** (Shopify / Amazon / tracking service / carrier), the original wording, and its **freshness**; the current status is worked out from the **newest scan by scan time**; "delivered" from Shopify alone is shown as **not carrier-confirmed**; unknown statuses become **unverified**, never "delivered"; a diagnostics view lists problem shipments.

| Phase | Work | State |
|---|---|---|
| 0 | Backups, safety branch, baseline | Backup ✓, branch ✓, commit and full SEO test run pending |
| 1 | Create the central database foundation | SQL ready (`supabase_setup.sql`); owner runs it in Supabase |
| 2 | Shipping truth: tracker refresh, status map, scan history, diagnostics, team marks | Built ✓ (refresh runs inside Supabase) |
| 3 | Shipping screens in Flowmerce | Built ✓ |
| 4 | Move SEO from SQLite to `seo` schema | SQL written; data copy not started |
| 5 | Team workflow: sign-in, alerts, escalation, returns | Not started |
| 6 | Costs, ERP stock, webhooks, writes to Shopify/Amazon (each needs approval) | Not started |

Full plan and owner decisions: [docs/FLOWMERCE_DATABASE_AND_BUILD_PLAN.md](docs/FLOWMERCE_DATABASE_AND_BUILD_PLAN.md). Database explained table by table: [docs/architecture/central-database.md](docs/architecture/central-database.md).

---

## Technology and approved languages

Python 3.14 is the primary language (one version everywhere: [ADR 0010](docs/decisions/0010-one-python-version.md)). Approved exceptions ([ADR 0002](docs/decisions/0002-approved-language-exceptions.md), [ADR 0006](docs/decisions/0006-nextjs-javascript-frontend.md)): the web UI is **Next.js + React in JavaScript/JSX only (no TypeScript)**, and plain `.sql` files for database schema. Any other language needs explicit approval first.

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, uvicorn, httpx, openpyxl, anthropic, google-auth (the `seo` extra) |
| Database | SQLite `data/blog-ops.sqlite` today → Supabase PostgreSQL (`db/central/`) |
| Frontend | Next.js 15, React 19, JavaScript/JSX, hand-written CSS |
| Tests | pytest (backend) |
| Shipping data access | Supabase REST API via `httpx` (already installed). No new package was added. `psycopg` (approved) is only needed later for a direct Postgres connection |

---

## Project layout

```
Flowmerce/
├─ src/flowmerce/
│  ├─ main.py, core/, config/        CLI (flowmerce version | health), settings, logging
│  ├─ modules/shipping/              Shipping backend: config, supabase (REST client), rules, service, api, scheduler
│  └─ modules/seo/                   SEO & Blog backend (FastAPI)
│     ├─ app.py, api.py, auth.py, permissions.py, db.py, maintenance.py
│     ├─ services/                   articles, publishing, workflow, ai_jobs, sync, analytics, resync, scheduler ...
│     └─ integrations/               shopify, shopify_public, google, claude, ai_worker, status
├─ frontend/                         Next.js app (src/app routes, src/views pages, src/components)
├─ db/
│  ├─ central/                       ★ the central PostgreSQL database (ops + seo), run order in its README
│  └─ schema.sql                     earlier planning draft (superseded by db/central, kept for reference)
├─ docs/                             architecture, decisions (ADRs), development, operations
├─ tests/                            unit and integration tests (pytest)
├─ scripts/                          run_flowmerce.py launcher, ci_smoke.py
├─ data/  backups/  logs/            runtime files, git-ignored (never commit)
└─ pyproject.toml, .env.example, CHANGELOG.md, PROJECT_RULES.md
```

---

## Prerequisites and setup

Python 3.14 (exactly: the launcher checks), and Node.js with npm. Full steps: [docs/development/setup.md](docs/development/setup.md). Short version (Windows PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,seo]"      # dev = pytest, ruff, mypy · seo = the backend libraries
copy .env.example .env           # then fill in the values you have
python -m flowmerce health
python scripts\run_flowmerce.py  # starts the API and the web interface, opens http://127.0.0.1:3000
```

### Configuration (`.env`)

Copy `.env.example` to `.env`. **Never commit `.env` or any `.env.*` file** (they are git-ignored). Main groups (names only; values are yours):

| Group | Variables |
|---|---|
| App | `FLOWMERCE_ENV`, `FLOWMERCE_LOG_LEVEL`, `HOST`, `PORT`, `APP_ENV`, `SCHEDULER`, `DEMO_MODE` |
| Publishing safety | `ALLOW_LIVE_PUBLISH` (default `false`) |
| Shopify (per brand) | `RIDHI_SHOPIFY_SHOP`, `RIDHI_SHOPIFY_CLIENT_ID`, `RIDHI_SHOPIFY_CLIENT_SECRET` or `RIDHI_SHOPIFY_ADMIN_TOKEN`, `RIDHI_SHOPIFY_BLOG_HANDLE`, `RIDHI_STOREFRONT_DOMAIN`, the same with `CPC_`, and `SHOPIFY_API_VERSION`, `PUBLIC_FEED_SYNC` |
| Google | `GOOGLE_SERVICE_ACCOUNT_FILE`, `RIDHI_GSC_PROPERTY`, `CPC_GSC_PROPERTY`, `RIDHI_GA4_PROPERTY_ID`, `CPC_GA4_PROPERTY_ID` |
| Claude / AI jobs | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `AI_EXECUTION_MODE`, `AI_WORKER_URL`, `AI_WORKER_TOKEN`, `AI_*` limits, `WORKFLOW_WEBHOOK_SECRET` |
| Shipping (Supabase) | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (server only), `SHIPPING_REFRESH_MINUTES`, `SHIPPING_SCHEMA`, `SHIPPING_TIMEOUT_SECONDS`. Also read from `.env.shipping` |

---

## Start Flowmerce (one command)

```powershell
python scripts\run_flowmerce.py
```

| Service | Address | What it is |
|---|---|---|
| API | `http://127.0.0.1:8787` | Python / FastAPI backend (database, integrations, publishing rules) |
| Web interface | `http://127.0.0.1:3000` | Next.js / React frontend; forwards `/api/*` to the API |

The launcher creates `.venv`, installs packages when needed, builds the web interface when it is missing or out of date, opens the browser, and stops both services on Ctrl+C. `--dev` runs the frontend in development mode; `--no-browser` skips opening the browser. Both services listen on `127.0.0.1` only. (`scripts\run_seo.py` and `scripts\run_seo.bat` still work and forward to it.)

---

## Shipping: one-time Supabase setup

Full guide: [docs/operations/shipping-supabase-setup.md](docs/operations/shipping-supabase-setup.md).

1. Supabase → SQL Editor → paste and run **`db/central/supabase_setup.sql`** (safe to re-run; never touches `public.*`).
2. Supabase → Project Settings → Data API → **Exposed schemas** → add **`ops`**.
3. Put `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env` or `.env.shipping` (server only).
4. Start Flowmerce, open **Shipping**, press **Refresh now**.

How the data flows:

```
Shopify ──(hourly, GitHub Actions)──► Delayed Orders Tracker ──► Supabase public.shipments / order_checks / manual_status
                                                                         │  ops.refresh_from_tracker()  (every 15 min, inside Supabase)
                                                                         ▼
                                     Supabase ops.orders · shipments · tracking_numbers · tracking_scans · events · exceptions
                                                                         │  REST (service-role key, server only)
                                                                         ▼
                                              Flowmerce backend /api/shipping/*  ──►  Shipping page
```

Checks: `scripts\shipping_inspect_supabase.py` (read-only table look), `scripts\shipping_smoke.py` (API answers), `python -m unittest discover -s tests\unit\shipping`.

## Central database (`db/central/`)

The numbered files are the same SQL as `supabase_setup.sql`, split by topic. To rehearse on a separate database first: Each file `000`–`090` is safe to run more than once; none of them touches `public.*`.

```powershell
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -f db/central/000_extensions_and_schemas.sql
# ... 010, 020, 030, 040, 060, 070, 080, 090 in order (full list in db/central/README.md)
psql $env:DATABASE_URL -f db/central/110_validate.sql
```

- `105_refresh_from_shopify_orders.sql` creates `ops.refresh_from_shopify_orders()` (repeatable copy of `public.orders` and its Shopify fulfillments into `ops`, read-only towards `public`) and `ops.set_team_mark()`.
- `rollback/999_rollback_central.sql` removes `ops` and `seo` only, and refuses if real data exists. Back up first.
- Write switches (`shopify_writes`, `amazon_writes`, `auto_mcf`) are seeded **off**.
- Browser keys can read nothing in `ops` / `seo` (row-level security, no public policies).

---

## Local operator mode: no sign-in, this computer only

Opening Flowmerce on your own computer goes straight to the dashboard: no login, and everything is recorded as the local administrator.

- **It answers only requests from this computer.** Requests from any other machine get HTTP 403. Forwarded-address headers are ignored.
- **Both services bind to `127.0.0.1`.** **Never expose Flowmerce to a network or the internet**, and never put a reverse proxy or tunnel in front of it: there is no password to fall back on.
- **The one exception is the workflow webhook** `POST /api/hooks/workflow`, protected by `X-Workflow-Secret` (`WORKFLOW_WEBHOOK_SECRET`).
- Roles and passwords no longer restrict access; user records stay for audit history and assignments.
- Live publishing stays off unless `ALLOW_LIVE_PUBLISH` is set, and still needs the typed `PUBLISH` confirmation.
- An old `data/initial-admin.txt` (git-ignored) is no longer used.

---

## Run tests and checks

```powershell
pytest
ruff check .
mypy
cd frontend; npm run build; cd ..
python scripts\ci_smoke.py --web
```

Shipping tests run without pytest: `.venv\Scripts\python.exe -m unittest discover -s tests\unit\shipping -v`.

`pytest`, `ruff` and `mypy` come from the `dev` extra (`pip install -e ".[dev,seo]"`). If `pytest` is "not found", that extra is not installed in `.venv`.

---

## Safety rules for everyone working on this repo

- Do not delete files, tables or endpoints because they look unused. Confirm first.
- Back up `data/blog-ops.sqlite` (with its `-wal` and `-shm` files, servers stopped) before any database work.
- No new packages without the owner's approval. No TypeScript.
- Nothing is pushed to GitHub without the owner's say-so.
- Never put keys in code, docs, SQL or the browser. Only names of secrets.

---

## Documentation

- **Unification:** [Build plan & decisions](docs/FLOWMERCE_DATABASE_AND_BUILD_PLAN.md) · [Central database explained](docs/architecture/central-database.md) · [Database SQL](db/central/README.md)
- [System overview](docs/architecture/system-overview.md) · [Folder structure](docs/architecture/folder-structure.md) · [File registry](docs/FILE_REGISTRY.md)
- [Setup](docs/development/setup.md) · [Coding standards](docs/development/coding-standards.md)
- [Troubleshooting](docs/operations/troubleshooting.md) · [CI/CD](docs/operations/ci-cd.md)
- [Project rules](PROJECT_RULES.md) · [Roadmap](docs/development/roadmap.md) · [Architecture decisions](docs/decisions/) · [Changelog](CHANGELOG.md)
- Target design (planning v0.1): [architecture](docs/01-architecture.md), [connectors](docs/02-connectors-and-apis.md), [data model](docs/03-data-model.md)
