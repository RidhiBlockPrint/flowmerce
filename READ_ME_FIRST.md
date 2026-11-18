# Flowmerce delivery · 2026-11-17 (SEO + Shipping on Supabase)

| In this zip | What it is |
|---|---|
| `supabase/supabase_setup.sql` | **The Supabase SQL.** Paste into Supabase → SQL Editor → Run. Safe to re-run; never touches the tracker's `public.*` tables |
| `supabase/` (other files) | The same SQL split by topic, validation queries, rollback, README |
| `Flowmerce/` | The whole project: SEO module (unchanged) + new Shipping module, React (Next.js) frontend with a Shipping tab |
| `docs/shipping-supabase-setup.md` | **Start here:** 4 setup steps |
| `docs/central-database.md` | Every table explained, what changed and why |
| `docs/FLOWMERCE_DATABASE_AND_BUILD_PLAN.md` | The phased plan and decisions |
| `README.md` | Project README |

## Setup in 4 steps

1. Supabase → SQL Editor → run `supabase/supabase_setup.sql`. **Already ran it earlier today?** Run only `supabase/105_refresh_from_shopify_orders.sql` (the refresh now reads `public.orders`; the old one failed).
2. Supabase → Project Settings → Data API → Exposed schemas → add `ops`.
3. In `Flowmerce/.env` (copy from `.env.example`): set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or keep your existing `.env.shipping` next to it).
4. In `Flowmerce/`: `python scripts\run_flowmerce.py`, open **Shipping**, press **Refresh now**.

## Verified / not verified

- ✓ 27 Shipping unit tests pass · ✓ frontend production build passes · ✓ API smoke test: SEO routes work with Shipping mounted
- ✓ SQL written against the **real** tracker columns, status words and carrier names (read from your Supabase, read-only)
- ✗ The SQL has **not been run** in Supabase yet (step 1 is yours) · ✗ Shipping screens not yet seen with data
- ✗ Full SEO pytest suite not run (pytest not installed in `.venv`)

## Left out on purpose

`.env`, `.env.shipping` (real keys), `data/` (SQLite database, keyword workbook), `backups/`, `.git`, `node_modules`, `.venv`, `.next`.
