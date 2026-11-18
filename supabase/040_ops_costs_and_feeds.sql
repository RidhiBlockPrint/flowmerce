-- =====================================================================================
-- Flowmerce central database · 040 · costs, rates, and data feeds
-- shipping_costs · rate_cards · webhook_inbox · sync_runs
-- Safe to run more than once.
-- NOTE: ops.sync_runs is a NEW table. The tracker's public.sync_runs is left untouched.
-- =====================================================================================

-- ---------------------------------------------------------------- shipping_costs
create table if not exists ops.shipping_costs (
  id           uuid primary key default gen_random_uuid(),
  shipment_id  uuid not null references ops.shipments(id),
  tracking_id  uuid references ops.tracking_numbers(id),
  store        text not null references ops.stores(id),
  kind         text not null check (kind in ('freight','fuel_surcharge','mcf_fee','remote_area','customs_duty','insurance','return_label','other')),
  amount       numeric(12,2) not null,
  currency     text not null default 'USD',
  amount_usd   numeric(12,2) not null,
  is_estimate  boolean not null default false,
  source       text not null check (source in ('carrier_invoice','amazon_report','rate_card','manual')),
  invoice_ref  text,
  billed_at    date,
  note         text,
  created_at   timestamptz not null default now()
);
create index if not exists shipping_costs_shipment on ops.shipping_costs (shipment_id);

-- ---------------------------------------------------------------- rate_cards
create table if not exists ops.rate_cards (
  id                  uuid primary key default gen_random_uuid(),
  carrier_id          text not null references ops.carriers(id),
  service_id          text not null references ops.carrier_services(id),
  origin_country      text not null,
  dest_country        text not null,
  zone                text,
  weight_from_kg      numeric(6,2) not null,
  weight_to_kg        numeric(6,2) not null,
  rate                numeric(12,2) not null,
  currency            text not null default 'USD',
  fuel_surcharge_pct  numeric(5,2) not null default 0,
  valid_from          date not null,
  valid_to            date,
  source              text not null default 'contract' check (source in ('contract','published','estimate')),
  active              boolean not null default true,
  check (weight_from_kg < weight_to_kg),
  check (valid_to is null or valid_from <= valid_to)
);
create index if not exists rate_cards_lookup on ops.rate_cards (carrier_id, service_id, dest_country, weight_from_kg) where active;

-- ---------------------------------------------------------------- webhook_inbox
-- Every incoming message, stored untouched BEFORE acting on it. Replayable.
-- Stays empty until a public HTTPS endpoint exists (plan C4 / decision D4).
create table if not exists ops.webhook_inbox (
  id            bigserial primary key,
  source        text not null check (source in ('shopify','amazon','aftership','17track','shiprocket','delhivery','dhl','fedex')),
  store         text references ops.stores(id),
  topic         text not null,
  external_id   text,
  received_at   timestamptz not null default now(),
  signature_ok  boolean not null,
  payload       jsonb not null,
  status        text not null default 'received' check (status in ('received','processed','failed','ignored')),
  attempts      int not null default 0,
  processed_at  timestamptz,
  error         text,
  event_id      bigint references ops.events(id)
);
create unique index if not exists webhook_inbox_once on ops.webhook_inbox (source, external_id);
create index if not exists webhook_inbox_todo on ops.webhook_inbox (status, received_at) where status in ('received','failed');

-- ---------------------------------------------------------------- sync_runs
-- Every load / check / poll. Powers "data freshness" on screen.
create table if not exists ops.sync_runs (
  id            bigserial primary key,
  source        text not null check (source in ('shopify','amazon','aftership','17track','shiprocket','delhivery','dhl','fedex','tracker_import','erp')),
  kind          text not null check (kind in ('backfill','nightly_check','poll','webhook_replay','import')),
  store         text references ops.stores(id),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  status        text not null default 'running' check (status in ('running','ok','partial','failed')),
  rows_read     int not null default 0,
  rows_written  int not null default 0,
  rows_failed   int not null default 0,
  cursor        text,
  error         text,
  triggered_by  text not null,
  -- FLOWMERCE ADDITION: a lock so the same feed never runs twice at once
  lock_key      text generated always as (case when status = 'running' then source || ':' || kind || ':' || coalesce(store,'*') end) stored
);
create index if not exists sync_runs_by_source on ops.sync_runs (source, started_at desc);
create unique index if not exists sync_runs_one_running on ops.sync_runs (lock_key) where lock_key is not null;
comment on column ops.sync_runs.lock_key is 'Only one running row per source/kind/store. A second start fails with a unique violation = duplicate run refused.';
