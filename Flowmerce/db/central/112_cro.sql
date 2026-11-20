-- =====================================================================================
-- Flowmerce central database · 112 · CRO (Conversion Rate Optimization) module
-- Safe to run more than once. Creates the schema `cro`; reads ops.orders / ops.stores; never writes ops.*,
-- seo.* or public.*.
--
-- What lives here (only what is CRO's own; orders and stores stay in ops):
--   cro.store_settings  one row per store: whether CRO alarms run for it
--   cro.alarm_rules     alarm thresholds the team can edit (conversion-rate drop, no orders for a product keyword)
--   cro.alerts          every alarm that fired, open until resolved
--   cro.change_log      what the team changed on the store (theme, app, price, promo, ad), typed in by hand
--   cro.daily_sales     view: orders and revenue per store per local day, from ops.orders
--
-- Conversion rate, sessions and the funnel are NOT stored: Flowmerce asks Shopify (ShopifyQL) when a page needs them.
-- No personal data: no customer names, emails or addresses are stored here.
--
-- After running: Project Settings -> Data API -> Exposed schemas -> add "cro" (next to "ops").
-- =====================================================================================

create schema if not exists cro;
comment on schema cro is 'Flowmerce CRO module: alarm rules, alerts, change log, per-store settings. Orders stay in ops.';

-- ---------------------------------------------------------------- store_settings
create table if not exists cro.store_settings (
  store           text primary key references ops.stores(id),
  alarms_enabled  boolean not null default true,
  updated_by      text,
  updated_at      timestamptz not null default now()
);
comment on table cro.store_settings is 'Per-store CRO switches. A store without a row is treated as alarms_enabled = true.';

drop trigger if exists store_settings_updated_at on cro.store_settings;
create trigger store_settings_updated_at before update on cro.store_settings
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- alarm_rules
-- kind 'cvr_drop':          fire when yesterday's conversion rate fell by threshold % or more vs the day before.
-- kind 'no_product_orders': fire when no order containing a product matching product_keyword arrived for threshold hours.
create table if not exists cro.alarm_rules (
  id               bigint generated always as identity primary key,
  store            text not null references ops.stores(id),
  kind             text not null check (kind in ('cvr_drop', 'no_product_orders')),
  title            text not null check (length(btrim(title)) between 1 and 200),
  threshold        numeric(10,2) not null check (threshold > 0),
  product_keyword  text check (product_keyword is null or length(btrim(product_keyword)) between 1 and 100),
  is_active        boolean not null default true,
  last_checked_at  timestamptz,
  created_at       timestamptz not null default now(),
  updated_by       text,
  updated_at       timestamptz not null default now(),
  constraint alarm_rules_keyword_matches_kind check (
    (kind = 'no_product_orders' and product_keyword is not null)
    or (kind = 'cvr_drop' and product_keyword is null)),
  constraint alarm_rules_cvr_threshold_is_percent check (kind <> 'cvr_drop' or threshold <= 100)
);
comment on table cro.alarm_rules is 'Editable CRO alarm rules. threshold: percent drop (cvr_drop) or hours without an order (no_product_orders).';
comment on column cro.alarm_rules.product_keyword is 'no_product_orders only: matched (case-insensitive) against product title, type and tags.';

-- One rule per store + kind + keyword.
create unique index if not exists alarm_rules_one_per_kind
  on cro.alarm_rules (store, kind, lower(coalesce(product_keyword, '')));

drop trigger if exists alarm_rules_updated_at on cro.alarm_rules;
create trigger alarm_rules_updated_at before update on cro.alarm_rules
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- alerts
create table if not exists cro.alerts (
  id            bigint generated always as identity primary key,
  rule_id       bigint not null references cro.alarm_rules(id) on delete restrict,   -- keep history: rules are switched off, not deleted
  store         text not null references ops.stores(id),
  period_date   date,                                     -- cvr_drop: the store-local day that dropped; null for other kinds
  message       text not null check (length(message) between 1 and 2000),
  details       jsonb not null default '{}'::jsonb,       -- the figures behind the alert (rates, hours, order number)
  triggered_at  timestamptz not null default now(),
  resolved_at   timestamptz,
  constraint alerts_resolved_after_triggered check (resolved_at is null or resolved_at >= triggered_at)
);
comment on table cro.alerts is 'Every CRO alarm that fired. Open while resolved_at is null.';

-- At most one open alert per rule, and one conversion-drop alert per rule per day: the database refuses duplicates.
create unique index if not exists alerts_one_open_per_rule on cro.alerts (rule_id) where resolved_at is null;
create unique index if not exists alerts_one_per_rule_day on cro.alerts (rule_id, period_date) where period_date is not null;
create index if not exists alerts_store_recent on cro.alerts (store, triggered_at desc);

-- ---------------------------------------------------------------- change_log
create table if not exists cro.change_log (
  id          bigint generated always as identity primary key,
  store       text not null references ops.stores(id),
  entry_date  date not null,
  change      text not null check (length(btrim(change)) between 1 and 1000),
  area        text not null default 'other' check (area in ('theme', 'app', 'price', 'promo', 'ad', 'other')),
  owner       text check (owner is null or length(owner) <= 200),   -- who made the change on the store
  created_by  text,                                                  -- who recorded it in Flowmerce
  created_at  timestamptz not null default now()
);
comment on table cro.change_log is 'Store changes typed in by the team, shown as markers on CRO trend charts.';
create index if not exists change_log_store_date on cro.change_log (store, entry_date desc);

-- ---------------------------------------------------------------- daily_sales (view)
-- One row per store per store-local day that has orders. Cancelled orders are left out.
-- Uses only ops.orders columns the Shipping refresh fills today (placed_at, total, currency, cancelled_at,
-- financial_status). Days without orders have no row; the backend fills those gaps with zero.
create or replace view cro.daily_sales with (security_invoker = true) as
select o.store,
       (o.placed_at at time zone s.timezone)::date                                    as day,
       count(*)                                                                         as orders,
       coalesce(sum(o.total), 0)::numeric(14,2)                                         as revenue,
       count(*) filter (where o.financial_status in ('refunded', 'partially_refunded')) as refunded_orders,
       min(o.currency)                                                                  as currency
from ops.orders o
join ops.stores s on s.id = o.store
where o.cancelled_at is null
group by o.store, (o.placed_at at time zone s.timezone)::date;
comment on view cro.daily_sales is 'Orders and revenue per store per local day (ops.stores.timezone), cancelled orders excluded.';

-- ---------------------------------------------------------------- default rules
-- The two alarms the CRO prototype ran on the Ridhi store (guz0he-21): conversion-rate drop 20%, and 12 hours
-- without a quilt order. CPC gets the conversion-rate rule only; a product rule for CPC is added from the app.
-- Inserted only when missing: edits made later in the app are never overwritten.
insert into cro.alarm_rules (store, kind, title, threshold, product_keyword)
select v.store, v.kind, v.title, v.threshold, v.product_keyword
from (values
  ('RBP', 'cvr_drop',          'Conversion rate drop 20%',      20::numeric, null::text),
  ('RBP', 'no_product_orders', 'No quilt orders for 12 hours',  12::numeric, 'quilt'),
  ('CPC', 'cvr_drop',          'Conversion rate drop 20%',      20::numeric, null::text)
) v(store, kind, title, threshold, product_keyword)
where exists (select 1 from ops.stores s where s.id = v.store)
on conflict (store, kind, lower(coalesce(product_keyword, ''))) do nothing;

-- ---------------------------------------------------------------- security (same rules as 080)
-- RLS on, no policies: the browser keys (anon, authenticated) can read nothing. Only the backend's service_role
-- (and flowmerce_app, for a direct connection later) may read and write.
alter table cro.store_settings enable row level security;
alter table cro.alarm_rules    enable row level security;
alter table cro.alerts         enable row level security;
alter table cro.change_log     enable row level security;

revoke all on all tables in schema cro from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant usage on schema cro to service_role';
    execute 'grant select, insert, update, delete on all tables in schema cro to service_role';
    execute 'grant usage, select on all sequences in schema cro to service_role';
    execute 'alter default privileges in schema cro grant select, insert, update, delete on tables to service_role';
    execute 'alter default privileges in schema cro grant usage, select on sequences to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema cro from anon, authenticated';
    execute 'revoke all on schema cro from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant usage on schema cro to flowmerce_app';
    execute 'grant select, insert, update, delete on all tables in schema cro to flowmerce_app';
    execute 'grant usage, select on all sequences in schema cro to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('112_cro.sql', 'schema cro: store_settings, alarm_rules, alerts, change_log, daily_sales view')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
