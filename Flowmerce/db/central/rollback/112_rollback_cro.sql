-- =====================================================================================
-- Flowmerce central database · ROLLBACK of 112_cro.sql and 113_cro_orders.sql
-- Removes the schema `cro` only (113's order copy included). NEVER touches ops.*, seo.* or public.*.
-- The order copy (cro.orders / cro.order_lines) does not block the rollback: it is re-read from Shopify.
--
-- DESTRUCTIVE. Needs the owner's explicit approval every time.
-- Protected: it REFUSES to run if the team has recorded anything (alerts, change log entries, store settings,
-- alarm rules beyond the three defaults 112 inserts, or an edited default), unless you first run, in the same session:
--     set flowmerce.allow_cro_rollback_with_data = 'yes';
-- Before using it on a database with real data: take a backup (pg_dump -n cro).
-- =====================================================================================
do $$
declare
  n bigint := 0;
begin
  if not exists (select 1 from pg_namespace where nspname = 'cro') then
    raise notice 'Schema cro does not exist: nothing to roll back.';
    return;
  end if;

  select (select count(*) from cro.alerts)
       + (select count(*) from cro.change_log)
       + (select count(*) from cro.store_settings)
       + greatest((select count(*) from cro.alarm_rules) - 3, 0)
       + (select count(*) from cro.alarm_rules where updated_by is not null)   -- a default the team edited
    into n;

  if n > 0 and coalesce(current_setting('flowmerce.allow_cro_rollback_with_data', true), '') <> 'yes' then
    raise exception 'Refusing rollback: % CRO data rows exist. Back up first, then set flowmerce.allow_cro_rollback_with_data = ''yes''.', n;
  end if;
end $$;

drop schema if exists cro cascade;

delete from ops.schema_migrations where file in ('112_cro.sql', '113_cro_orders.sql');

notify pgrst, 'reload schema';
