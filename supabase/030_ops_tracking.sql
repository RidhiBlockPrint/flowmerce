-- =====================================================================================
-- Flowmerce central database · 030 · tracking and problems (the accuracy fix)
-- tracking_numbers · tracking_scans · shipping_exceptions · shipping_claims · return_cases
-- Safe to run more than once.
-- =====================================================================================

-- ---------------------------------------------------------------- tracking_numbers
-- THE TRUTH FOR TRACKING. One row per (carrier, tracking number).
create table if not exists ops.tracking_numbers (
  id               uuid primary key default gen_random_uuid(),
  shipment_id      uuid not null references ops.shipments(id),
  store            text not null references ops.stores(id),
  carrier_id       text not null references ops.carriers(id),
  service_id       text references ops.carrier_services(id),
  tracking_number  text not null,
  source           text not null check (source in ('shopify','amazon','aggregator','carrier_api','manual','tracker_import')),
  aggregator_id    text unique,
  status           text not null default 'pending' check (status in (
                     'pending','info_received','in_transit','out_for_delivery','delivered','exception','returned','expired')),
  status_detail    text,
  registered_at    timestamptz not null default now(),
  picked_up_at     timestamptz,
  last_scan_at     timestamptz,
  eta              date,
  promised_by      date,
  delivered_at     timestamptz,
  signed_by        text,
  pod_url          text,
  scan_count       int not null default 0,
  origin_country   text,
  dest_country     text,
  active           boolean not null default true,
  stopped_at       timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- FLOWMERCE ADDITIONS: freshness and honesty, per tracking number
  last_checked_at     timestamptz,                                    -- last time we ASKED the source (success or not)
  last_check_ok_at    timestamptz,                                    -- last time the source answered correctly
  last_check_error    text,                                           -- last error from the source (no secrets)
  check_attempts      int not null default 0,                         -- failures in a row; reset on success
  delivery_confirmed  boolean not null default false,                 -- true ONLY when a source that can confirm delivery said delivered
  raw_status          text,                                           -- latest status exactly as the source wrote it
  -- team check, kept apart from carrier data so a person's mark never overwrites what the carrier said
  team_mark           text check (team_mark in ('delivered','lost','failed','in_transit','checked')),
  team_mark_by        text,
  team_mark_at        timestamptz,
  team_note           text,
  -- delivered must come with a time; a parcel is never "delivered" without one
  check (status <> 'delivered' or delivered_at is not null)
);
create unique index if not exists tracking_numbers_carrier_no on ops.tracking_numbers (carrier_id, tracking_number);
create index if not exists tracking_numbers_shipment on ops.tracking_numbers (shipment_id);
create index if not exists tracking_numbers_open on ops.tracking_numbers (status, last_scan_at) where active;
create index if not exists tracking_numbers_number on ops.tracking_numbers (tracking_number);
drop trigger if exists tracking_numbers_updated_at on ops.tracking_numbers;
create trigger tracking_numbers_updated_at before update on ops.tracking_numbers
  for each row execute function ops.set_updated_at();
comment on column ops.tracking_numbers.delivery_confirmed is 'Shopify-only "fulfilled" never sets this. Only amazon/aggregator/carrier_api delivered scans do.';

-- ---------------------------------------------------------------- tracking_scans
-- Every scan the source reports, in full. Never stored twice (external_id).
create table if not exists ops.tracking_scans (
  id           bigserial primary key,
  tracking_id  uuid not null references ops.tracking_numbers(id),
  shipment_id  uuid not null references ops.shipments(id),
  external_id  text not null unique,
  scanned_at   timestamptz not null,                                  -- carrier's clock (when it happened)
  received_at  timestamptz not null default now(),                    -- when we got it
  status       text not null check (status in (
                 'pending','info_received','in_transit','out_for_delivery','delivered','exception','returned','expired')),
  raw_status   text,
  message      text,
  city         text,
  province     text,
  country      text,
  source       text not null check (source in ('amazon','aggregator','carrier_api','shopify','tracker_import')),
  event_id     bigint references ops.events(id),
  raw          jsonb,
  -- FLOWMERCE ADDITION: which status_map rule produced `status` (null = not in the map -> pending)
  mapped_rule  text
);
create index if not exists tracking_scans_by_number on ops.tracking_scans (tracking_id, scanned_at desc);

-- ---------------------------------------------------------------- latest-status rule
-- The current status of a tracking number is the status of its NEWEST scan by scanned_at
-- (ties broken by received_at, then id), never "whatever arrived last". A late-arriving
-- older scan therefore cannot overwrite a newer one. This function recomputes one row.
create or replace function ops.recompute_tracking_status(p_tracking_id uuid) returns void
language plpgsql as $$
declare
  v_last ops.tracking_scans%rowtype;
  v_first_movement timestamptz;
  v_delivered timestamptz;
  v_confirm boolean;
begin
  select * into v_last
    from ops.tracking_scans
   where tracking_id = p_tracking_id
   order by scanned_at desc, received_at desc, id desc
   limit 1;
  if not found then
    return;                                    -- no scans: leave status as it is (pending by default)
  end if;

  select min(scanned_at) into v_first_movement
    from ops.tracking_scans
   where tracking_id = p_tracking_id and status in ('in_transit','out_for_delivery','delivered');

  select min(scanned_at) into v_delivered
    from ops.tracking_scans
   where tracking_id = p_tracking_id and status = 'delivered';

  v_confirm := v_last.status = 'delivered' and v_last.source in ('amazon','aggregator','carrier_api');

  update ops.tracking_numbers t set
    status             = v_last.status,
    status_detail      = v_last.message,
    raw_status         = v_last.raw_status,
    last_scan_at       = v_last.scanned_at,
    picked_up_at       = coalesce(t.picked_up_at, v_first_movement),
    delivered_at       = case when v_last.status = 'delivered' then coalesce(v_delivered, v_last.scanned_at) else null end,
    delivery_confirmed = v_confirm,
    scan_count         = (select count(*) from ops.tracking_scans s where s.tracking_id = p_tracking_id)
  where t.id = p_tracking_id;
end $$;
comment on function ops.recompute_tracking_status(uuid) is 'Derives tracking_numbers status from scans ordered by scanned_at. Call after inserting scans.';

-- ---------------------------------------------------------------- shipping_exceptions
create table if not exists ops.shipping_exceptions (
  id              uuid primary key default gen_random_uuid(),
  order_id        bigint not null references ops.orders(id),
  shipment_id     uuid not null references ops.shipments(id),
  tracking_id     uuid references ops.tracking_numbers(id),
  store           text not null references ops.stores(id),
  kind            text not null check (kind in ('delay','no_scan','damaged','lost','failed_delivery','address_issue','customs_hold','returned_to_sender','other')),
  severity        text not null default 'amber' check (severity in ('red','amber')),
  source          text not null check (source in ('carrier','job','person')),
  detected_at     timestamptz not null default now(),
  description     text,
  status          text not null default 'open' check (status in ('open','investigating','claim_filed','resolved','closed')),
  resolution      text,
  owner           text,
  alert_event_id  bigint references ops.events(id),
  resolved_at     timestamptz,
  closed_at       timestamptz
);
create index if not exists shipping_exceptions_shipment on ops.shipping_exceptions (shipment_id);
create index if not exists shipping_exceptions_open on ops.shipping_exceptions (status) where closed_at is null;
-- one OPEN exception of each kind per tracking number (stops the job raising duplicates)
create unique index if not exists shipping_exceptions_one_open
  on ops.shipping_exceptions (shipment_id, coalesce(tracking_id, '00000000-0000-0000-0000-000000000000'::uuid), kind)
  where closed_at is null;

-- ---------------------------------------------------------------- shipping_claims
create table if not exists ops.shipping_claims (
  id              uuid primary key default gen_random_uuid(),
  exception_id    uuid references ops.shipping_exceptions(id),
  shipment_id     uuid not null references ops.shipments(id),
  carrier_id      text not null references ops.carriers(id),
  store           text not null references ops.stores(id),
  claim_type      text not null check (claim_type in ('lost','damaged','late_delivery','overcharge')),
  claim_ref       text,
  amount_claimed  numeric(12,2),
  amount_paid     numeric(12,2),
  currency        text not null default 'USD',
  status          text not null default 'draft' check (status in ('draft','filed','accepted','rejected','paid')),
  filed_at        timestamptz,
  resolved_at     timestamptz,
  filed_by        text,
  note            text
);

-- ---------------------------------------------------------------- return_cases
create table if not exists ops.return_cases (
  id                    uuid primary key default gen_random_uuid(),
  order_id              bigint not null references ops.orders(id),
  store                 text not null references ops.stores(id),
  item_id               bigint references ops.items(id),
  qty                   int not null default 1 check (qty > 0),
  original_shipment_id  uuid references ops.shipments(id),
  return_shipment_id    uuid references ops.shipments(id),
  return_tracking_id    uuid references ops.tracking_numbers(id),
  case_type             text not null check (case_type in ('customer_return','rto','refused','undeliverable')),
  reason_code           text,
  reason                text,
  status                text not null default 'requested' check (status in ('requested','label_sent','on_way_back','received','inspected','closed')),
  condition             text check (condition in ('resellable','needs_repair','damaged')),
  outcome               text check (outcome in ('refund','replace','both','none')),
  restock_to            text,
  refund_amount         numeric(12,2),
  opened_by             text,
  opened_at             timestamptz not null default now(),
  received_at           timestamptz,
  closed_at             timestamptz
);
create index if not exists return_cases_order on ops.return_cases (order_id);
