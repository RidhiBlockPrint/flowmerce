-- =====================================================================================
-- Flowmerce central database · 020 · orders and work
-- orders · items · shipments · stock · events
-- Safe to run more than once.
-- =====================================================================================

-- ---------------------------------------------------------------- orders
-- Left half: Shopify's copy (written only by the Shopify sync).
-- Right half: our status, hold and alert summary (written only by our team and jobs).
create table if not exists ops.orders (
  id                  bigint primary key,                               -- Shopify order id
  store               text not null references ops.stores(id),
  name                text not null,                                    -- #RBP7752
  customer_id         bigint,
  customer_name       text,
  email               text,
  phone               text,
  ship_name           text,
  ship_address1       text,
  ship_address2       text,
  ship_city           text,
  ship_province       text,
  ship_zip            text,
  ship_country        text,
  placed_at           timestamptz not null,
  shop_updated_at     timestamptz not null,                             -- older incoming messages are ignored
  cancelled_at        timestamptz,
  cancel_reason       text,
  financial_status    text,
  fulfillment_status  text,
  currency            text not null default 'USD',
  subtotal            numeric(12,2),
  discounts           numeric(12,2),
  shipping_charged    numeric(12,2),
  tax                 numeric(12,2),
  total               numeric(12,2),
  refunded_amount     numeric(12,2) not null default 0,
  tags                text[] not null default '{}',
  note                text,
  risk_level          text,
  raw                 jsonb,
  synced_at           timestamptz not null default now(),
  -- ours
  stage               text not null default 'new' check (stage in (
                        'new','checked','routed','in_production','packed','shipped','transit',
                        'delivered','closed','on_hold','cancelled','return_open')),
  stage_at            timestamptz not null default now(),
  due_at              timestamptz,
  late                boolean not null default false,
  checked_by          text,
  checked_at          timestamptz,
  hold_reason         text,
  hold_by             text,
  hold_at             timestamptz,
  dispute             text,
  open_alerts         int not null default 0,
  worst_alert         text check (worst_alert in ('red','amber')),
  closed_at           timestamptz,
  updated_by          text,
  updated_at          timestamptz not null default now(),
  -- FLOWMERCE ADDITION: where this row came from, for traceability of the migration.
  origin              text not null default 'shopify_sync' check (origin in ('shopify_sync','tracker_import'))
);
-- Not unique on purpose: imported data must never fail a whole refresh over one odd order name.
create index if not exists orders_store_name on ops.orders (store, name);
create index if not exists orders_open on ops.orders (store, stage, due_at) where closed_at is null;
create index if not exists orders_placed on ops.orders (store, placed_at desc);
drop trigger if exists orders_updated_at on ops.orders;
create trigger orders_updated_at before update on ops.orders
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- items
create table if not exists ops.items (
  id             bigint primary key,                                   -- Shopify line item id
  order_id       bigint not null references ops.orders(id) on delete cascade,
  store          text not null references ops.stores(id),
  sku            text,
  title          text not null,
  variant_title  text,
  product_id     bigint,
  variant_id     bigint,
  image_url      text,
  qty            int not null,
  current_qty    int not null,
  refunded_qty   int not null default 0,
  fulfilled_qty  int not null default 0,
  open_qty       int not null default 0,                               -- the only number we ship against
  price          numeric(12,2),
  discount       numeric(12,2) not null default 0,
  route          text check (route in ('mcf','india','make','skip')),
  send_qty       int check (send_qty is null or send_qty >= 0),
  out_of_stock   boolean not null default false,
  shelf          text,
  shelf_qty      int,
  ppc_route      text,                                                 -- from the ERP
  erp_order_no   text,                                                 -- from the ERP
  updated_by     text,
  updated_at     timestamptz not null default now()
);
create index if not exists items_order on ops.items (order_id);
create index if not exists items_sku on ops.items (store, sku);
drop trigger if exists items_updated_at on ops.items;
create trigger items_updated_at before update on ops.items
  for each row execute function ops.set_updated_at();

-- ---------------------------------------------------------------- shipments
-- Anything that moves: MCF parcel, India parcel, production job, return, replacement.
create table if not exists ops.shipments (
  id                      uuid primary key default gen_random_uuid(),
  order_id                bigint not null references ops.orders(id),
  store                   text not null references ops.stores(id),
  seq                     int not null,                                -- P1, P2 ...
  kind                    text not null check (kind in ('mcf','india','make','return','replacement','unknown')),
  items                   jsonb not null default '[]',                 -- [{ "item_id": ..., "qty": ... }]
  step                    text not null check (step in (
                            'requested','print','cut','stitch','jobwork','received','qc','ready',
                            'packed','label','shipped','transit','out','delivered',
                            'on_way_back','blocked','exception','cancelled')),
  step_at                 timestamptz not null default now(),
  step_times              jsonb not null default '{}',
  responsible             text,
  responsible_since       timestamptz,
  due_at                  timestamptz,
  late                    boolean not null default false,
  block_reason            text,
  ship_to                 jsonb,
  carrier                 text,                                        -- text exactly as Shopify knows it
  service                 text,
  carrier_id              text references ops.carriers(id),
  service_id              text references ops.carrier_services(id),
  account_id              text references ops.shipping_accounts(id),
  tracking                text[] not null default '{}',                -- handy copy; truth is tracking_numbers
  mcf_id                  text unique,
  mcf_account             text,
  shopify_fulfillment_id  bigint unique,
  dispatch_file           text,
  gst_invoice_no          text unique,
  weight_kg               numeric(6,2),
  dims_cm                 text,
  cost                    numeric(12,2),
  eta                     date,
  delivered_at            timestamptz,
  last_scan_at            timestamptz,
  last_scan_place         text,
  last_scan_text          text,
  cities                  text[] not null default '{}',
  return_reason           text,
  return_outcome          text check (return_outcome in ('refund','replace','both')),
  linked_id               uuid references ops.shipments(id),
  created_by              text,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  -- FLOWMERCE ADDITIONS for traceable migration from the Delayed Orders Tracker
  origin                  text not null default 'flowmerce' check (origin in ('flowmerce','shopify_sync','tracker_import')),
  kind_inferred           boolean not null default false               -- true when kind was guessed from the carrier name on import
);
create unique index if not exists shipments_seq on ops.shipments (order_id, seq);
create index if not exists shipments_carrier on ops.shipments (carrier_id);
create index if not exists shipments_open on ops.shipments (store, step, due_at) where step not in ('delivered','cancelled');
drop trigger if exists shipments_updated_at on ops.shipments;
create trigger shipments_updated_at before update on ops.shipments
  for each row execute function ops.set_updated_at();
comment on column ops.shipments.kind_inferred is 'Imported tracker rows do not say whether a parcel was MCF or India. true = kind was inferred from the carrier name and must be confirmed.';

-- ---------------------------------------------------------------- stock
create table if not exists ops.stock (
  store      text not null references ops.stores(id),
  sku        text not null,
  fba        int,
  india      int,
  shelf      text,
  make_open  int,
  as_of      timestamptz not null,
  primary key (store, sku)
);
comment on table ops.stock is 'Copied from the ERP every 15 minutes. Empty until ERP access exists (plan C7).';

-- ---------------------------------------------------------------- events
-- Everything that happened, once. The order timeline is just these rows.
create table if not exists ops.events (
  id            bigserial primary key,
  at            timestamptz not null default now(),
  store         text references ops.stores(id),
  order_id      bigint references ops.orders(id),
  shipment_id   uuid references ops.shipments(id),
  item_id       bigint references ops.items(id),
  type          text not null check (type in ('shopify','step','scan','note','action','alert','alert_update','system')),
  by            text not null,
  title         text not null,
  data          jsonb,
  external_id   text unique,                                          -- a repeat is refused
  parent_id     bigint references ops.events(id),
  alert_kind    text check (alert_kind in ('late','stuck','carrier','hold','changed_after_send','stock_short','blocked','system')),
  severity      text check (severity in ('red','amber')),
  level         int check (level in (1,2,3)),
  owner_team    text check (owner_team in ('production','shipment','orders','care')),
  assigned_to   text,
  reason        text,
  action        text,
  due_at        timestamptz,
  seen_at       timestamptz,
  escalated_at  timestamptz,
  closed_at     timestamptz,
  closed_by     text
);
create index if not exists events_order on ops.events (order_id, at);
create index if not exists events_shipment on ops.events (shipment_id, at);
create index if not exists events_open_alerts on ops.events (assigned_to, due_at) where type = 'alert' and closed_at is null;
