-- =====================================================================================
-- Flowmerce central database · 114 · CRO tracking: recommendation status, experiments, free-shipping amount
-- Safe to run more than once. Needs 112 (schema cro). Never writes ops.*, seo.* or public.*.
--
--   cro.recommendation_status  the team's status for each recommendation (open / in_progress / done / ignored),
--                              by the recommendation's stable key, so it survives the list being rebuilt
--   cro.experiments            the experiment log: name, hypothesis, metric, dates, optional landing page, owner.
--                              Results are worked out from Shopify when the page asks; only the plan is stored.
--   cro.store_settings.free_shipping_threshold
--                              the store's free-shipping amount, marked on the order-value chart
--   cro.delete_experiment()    removes one experiment (the backend's REST client does not delete rows itself)
--
-- No personal data: owner is a free-text team or role name typed by the team.
-- =====================================================================================

-- ---------------------------------------------------------------- free-shipping amount
alter table cro.store_settings add column if not exists free_shipping_threshold numeric
  check (free_shipping_threshold is null or (free_shipping_threshold > 0 and free_shipping_threshold < 100000));
comment on column cro.store_settings.free_shipping_threshold is
  'Order value (subtotal after discounts) from which shipping is free; null = not set. Marks the order-value chart.';

-- ---------------------------------------------------------------- recommendation_status
create table if not exists cro.recommendation_status (
  store       text not null references ops.stores(id),
  rec_key     text not null check (length(rec_key) between 1 and 300),
  status      text not null default 'open' check (status in ('open', 'in_progress', 'done', 'ignored')),
  updated_by  text,
  updated_at  timestamptz not null default now(),
  primary key (store, rec_key)
);
comment on table cro.recommendation_status is
  'Team status per CRO recommendation, keyed by its stable key (e.g. landing_fix:/collections/quilts). No row = open.';

-- ---------------------------------------------------------------- experiments
create table if not exists cro.experiments (
  id          bigint generated always as identity primary key,
  store       text not null references ops.stores(id),
  name        text not null check (length(btrim(name)) between 1 and 200),
  hypothesis  text not null check (length(btrim(hypothesis)) between 1 and 2000),
  metric      text not null check (metric in ('conversion_rate', 'added_to_cart_rate', 'bounce_rate', 'aov')),
  page_path   text check (page_path is null or length(page_path) <= 500),   -- one landing page, or null = whole store
  start_date  date not null,
  end_date    date check (end_date is null or end_date >= start_date),     -- null = still running
  owner       text check (owner is null or length(owner) <= 200),
  rec_key     text check (rec_key is null or length(rec_key) <= 300),       -- the recommendation it came from
  created_by  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
comment on table cro.experiments is 'CRO experiment log. Before/during results and confidence are computed from Shopify on read.';
create index if not exists experiments_store_start on cro.experiments (store, start_date desc);

drop trigger if exists experiments_updated_at on cro.experiments;
create trigger experiments_updated_at before update on cro.experiments
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- delete_experiment
create or replace function cro.delete_experiment(p_store text, p_id bigint)
returns boolean
language plpgsql security invoker set search_path = cro, pg_temp as $$
begin
  delete from cro.experiments where id = p_id and store = p_store;
  return found;
end $$;

-- ---------------------------------------------------------------- security (same rules as 112 / 113)
alter table cro.recommendation_status enable row level security;
alter table cro.experiments           enable row level security;

revoke all on cro.recommendation_status, cro.experiments from public;
revoke execute on function cro.delete_experiment(text, bigint) from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on cro.recommendation_status, cro.experiments to service_role';
    execute 'grant usage, select on all sequences in schema cro to service_role';
    execute 'grant execute on function cro.delete_experiment(text, bigint) to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on cro.recommendation_status, cro.experiments from anon, authenticated';
    execute 'revoke execute on function cro.delete_experiment(text, bigint) from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on cro.recommendation_status, cro.experiments to flowmerce_app';
    execute 'grant usage, select on all sequences in schema cro to flowmerce_app';
    execute 'grant execute on function cro.delete_experiment(text, bigint) to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('114_cro_tracking.sql', 'cro.recommendation_status, cro.experiments, store_settings.free_shipping_threshold')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
