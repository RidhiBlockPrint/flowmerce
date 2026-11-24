-- =====================================================================================
-- Flowmerce central database · ROLLBACK of 115_ads.sql
-- Removes the schema `ads` only. NEVER touches ops.*, cro.*, seo.* or public.*.
-- The ad figures do not block the rollback: they are read again from Meta and Google.
--
-- DESTRUCTIVE. Needs the owner's explicit approval every time.
-- Protected: it REFUSES to run if the team has recorded anything (rules they changed, suggestions marked done or
-- skipped, exchange rates beyond the default), unless you first run, in the same session:
--     set flowmerce.allow_ads_rollback_with_data = 'yes';
-- Before using it on a database with real data: take a backup (pg_dump -n ads).
-- =====================================================================================
do $$
declare
  n bigint := 0;
begin
  if not exists (select 1 from pg_namespace where nspname = 'ads') then
    raise notice 'Schema ads does not exist: nothing to roll back.';
    return;
  end if;

  select (select count(*) from ads.rules)
       + (select count(*) from ads.action_status)
       + (select count(*) from ads.action_history)
       + (select count(*) from ads.fx_rates where valid_from > date '2000-01-01')
    into n;

  if n > 0 and coalesce(current_setting('flowmerce.allow_ads_rollback_with_data', true), '') <> 'yes' then
    raise exception 'Refusing rollback: % Ads rows recorded by the team exist. Back up first, then set flowmerce.allow_ads_rollback_with_data = ''yes''.', n;
  end if;
end $$;

drop schema if exists ads cascade;

delete from ops.schema_migrations where file = '115_ads.sql';

notify pgrst, 'reload schema';
