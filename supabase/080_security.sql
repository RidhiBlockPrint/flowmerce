-- =====================================================================================
-- Flowmerce central database · 080 · security
-- 1. Row-level security ON for every ops/seo table, with NO policy for anon/authenticated.
--    => the public browser key (anon) can read NOTHING in ops or seo. This closes the
--       audit's SH-3 finding (anon key + using(true) exposed shipments and order notes).
-- 2. Supabase `service_role` (used ONLY by the Flowmerce backend, never in a browser) gets the
--    rights it needs on ops/seo. anon and authenticated get none.
-- 3. A separate login role `flowmerce_app` for a direct Postgres connection later (no password set).
-- Safe to run more than once.
-- =====================================================================================

do $$
declare r record;
begin
  for r in
    select n.nspname, c.relname
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname in ('ops','seo') and c.relkind = 'r'
  loop
    execute format('alter table %I.%I enable row level security', r.nspname, r.relname);
  end loop;
end $$;

-- Functions are executable by PUBLIC by default in Postgres. Close that for ops functions.
revoke execute on all functions in schema ops from public;

-- ---------------------------------------------------------------- Supabase roles (skipped on plain Postgres)
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema ops, seo to service_role';
    execute 'grant select, insert, update, delete on all tables in schema ops, seo to service_role';
    execute 'grant usage, select on all sequences in schema ops, seo to service_role';
    execute 'grant execute on all functions in schema ops to service_role';
    execute 'alter default privileges in schema ops grant select, insert, update, delete on tables to service_role';
    execute 'alter default privileges in schema seo grant select, insert, update, delete on tables to service_role';
    execute 'alter default privileges in schema ops grant usage, select on sequences to service_role';
    execute 'alter default privileges in schema seo grant usage, select on sequences to service_role';
    execute 'alter default privileges in schema ops grant execute on functions to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema ops, seo from anon, authenticated';
    execute 'revoke all on schema ops, seo from anon, authenticated';
    execute 'revoke execute on all functions in schema ops from anon, authenticated';
  end if;
end $$;

-- ---------------------------------------------------------------- flowmerce_app (direct Postgres, later)
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    create role flowmerce_app nologin;
  end if;
end $$;

grant usage on schema ops, seo to flowmerce_app;
grant select, insert, update, delete on all tables in schema ops, seo to flowmerce_app;
grant usage, select on all sequences in schema ops, seo to flowmerce_app;
grant execute on all functions in schema ops to flowmerce_app;
alter default privileges in schema ops grant select, insert, update, delete on tables to flowmerce_app;
alter default privileges in schema seo grant select, insert, update, delete on tables to flowmerce_app;
alter default privileges in schema ops grant usage, select on sequences to flowmerce_app;
alter default privileges in schema seo grant usage, select on sequences to flowmerce_app;

-- Both backend roles may only READ the hub's public tables, never write them.
do $$
declare t text;
begin
  foreach t in array array['stores','orders','sync_runs'] loop
    if exists (select 1 from information_schema.tables where table_schema = 'public' and table_name = t) then
      execute 'grant usage on schema public to flowmerce_app';
      execute format('grant select on public.%I to flowmerce_app', t);
    end if;
  end loop;
end $$;

comment on column seo.users.password_hash is 'Obsolete. Never return to the browser.';
comment on column ops.shipping_accounts.credential_ref is 'Name of a secret, not the secret.';
