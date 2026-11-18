-- =====================================================================================
-- Flowmerce central database · 000 · extensions, schemas, shared helpers
-- Target: Supabase PostgreSQL 15+ (also runs on plain PostgreSQL 15+ for rehearsal).
-- Safe to run more than once. Creates nothing in `public`, so the hub's tables
-- (public.orders, public.stores, public.sync_runs ...) are never touched.
-- STATUS: run in Supabase on 2026-11-17 (ops schema exists).
-- =====================================================================================

-- gen_random_uuid() is built in from PostgreSQL 13; pgcrypto kept for older rehearsal servers.
create extension if not exists pgcrypto;

-- ops = orders, shipments, tracking, carriers, alerts, data feeds (the v2 design)
create schema if not exists ops;
comment on schema ops is 'Flowmerce operations: orders, shipments, tracking, carriers, costs, alerts, feeds. Source design: Ridhi_Shopify_Database_v2_Flowmerce.html';

-- seo = the SEO & Blog module, ported 1:1 from data/blog-ops.sqlite (migrations 1 and 2)
create schema if not exists seo;
comment on schema seo is 'Flowmerce SEO & Blog module. Port of the SQLite tables in src/flowmerce/modules/seo/db.py';

-- One shared trigger function that keeps updated_at current on every UPDATE.
create or replace function ops.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- Bookkeeping: which numbered file has been applied, and when.
create table if not exists ops.schema_migrations (
  file        text primary key,
  applied_at  timestamptz not null default now(),
  applied_by  text not null default current_user,
  note        text
);
comment on table ops.schema_migrations is 'One row per db/central/*.sql file applied. Lets the runner skip files already applied.';

insert into ops.schema_migrations (file, note)
values ('000_extensions_and_schemas.sql', 'schemas ops and seo, helpers')
on conflict (file) do nothing;
