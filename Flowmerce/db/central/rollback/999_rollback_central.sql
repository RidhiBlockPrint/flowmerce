-- =====================================================================================
-- Flowmerce central database · ROLLBACK of files 000-100
-- Removes schemas ops and seo and the flowmerce_app role. NEVER touches public.*.
--
-- DESTRUCTIVE. Needs the owner's explicit approval every time.
-- Protected: it REFUSES to run if any ops/seo table has data rows other than the seed
-- data, unless you first run, in the same session:
--     set flowmerce.allow_rollback_with_data = 'yes';
-- Before using it on a database with real data: take a backup (pg_dump -n ops -n seo).
-- =====================================================================================
do $$
declare
  r record;
  n bigint;
  total bigint := 0;
  seed_tables text[] := array['stores','carriers','carrier_aliases','carrier_services','settings','status_map','schema_migrations'];
begin
  for r in
    select nspname, relname from pg_class c join pg_namespace s on s.oid = c.relnamespace
     where nspname in ('ops','seo') and relkind = 'r'
  loop
    if r.nspname = 'ops' and r.relname = any(seed_tables) then
      continue;
    end if;
    execute format('select count(*) from %I.%I', r.nspname, r.relname) into n;
    total := total + n;
  end loop;

  if total > 0 and coalesce(current_setting('flowmerce.allow_rollback_with_data', true), '') <> 'yes' then
    raise exception 'Refusing rollback: % data rows exist in ops/seo. Back up first, then set flowmerce.allow_rollback_with_data = ''yes''.', total;
  end if;
end $$;

drop schema if exists seo cascade;
drop schema if exists ops cascade;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'revoke all on all tables in schema public from flowmerce_app';
    execute 'revoke usage on schema public from flowmerce_app';
    execute 'drop role flowmerce_app';
  end if;
end $$;
