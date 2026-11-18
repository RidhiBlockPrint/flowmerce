# db/central — the Flowmerce central database (Supabase)

**Easiest way:** open Supabase → SQL Editor, paste **`supabase_setup.sql`**, run it. Then add `ops` under
Project Settings → Data API → Exposed schemas. Full guide: `docs/operations/shipping-supabase-setup.md`.

`supabase_setup.sql` is files 000–105 below joined in order (generated; edit the numbered files, then rebuild it).
Every file is safe to run more than once, and none of them writes to the hub's `public.*` tables.

| File | What it does |
|---|---|
| `000_extensions_and_schemas.sql` | Schemas `ops` and `seo`, the `updated_at` helper, the migrations log |
| `010_ops_setup.sql` | stores, people, settings, carriers, **carrier_aliases**, carrier_services, shipping_accounts, **status_map** |
| `020_ops_orders_shipments.sql` | orders, items, shipments, stock, events |
| `030_ops_tracking.sql` | tracking_numbers (with team mark + freshness columns), tracking_scans, latest-status function, exceptions, claims, returns |
| `040_ops_costs_and_feeds.sql` | shipping_costs, rate_cards, webhook_inbox, sync_runs (duplicate-run lock) |
| `060_ops_views.sql` | design views + feed_freshness, shipment_diagnostics, diagnostics_list/summary, **shipment_list**, shipping_summary |
| `070_seo_tables.sql` | the 20 SEO tables, ported 1:1 from SQLite (SEO still runs on SQLite until Phase 4) |
| `080_security.sql` | RLS on everywhere; rights for Supabase `service_role` only; none for anon/authenticated |
| `090_seed.sql` | stores, carriers + every spelling seen in the live data, services, settings (write switches OFF), status map |
| `105_refresh_from_shopify_orders.sql` | `ops.refresh_from_shopify_orders()` (repeatable, reads `public.orders` / `public.sync_runs`, never writes `public`) and `ops.set_team_mark()`. Replaces the removed `100_tracker_refresh.sql` |
| `095_optional_supabase_auth.sql` | Phase 5 only (sign-in). Not in `supabase_setup.sql` |
| `110_validate.sql` | Read-only checks: A–C after setup, D–I after the first refresh |
| `rollback/999_rollback_central.sql` | Removes `ops` + `seo`; refuses while real data exists. **Destructive, owner approval** |

Checked on 2026-11-17 against the live database: it has no tracker tables (`order_checks`, `manual_status`);
shipping data lives in `public.orders.raw → fulfillments`. `105` was tested on a local PostgreSQL 17 with a copy of
that data (fresh install and upgrade over the earlier setup; second run changes nothing).