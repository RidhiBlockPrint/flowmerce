-- =====================================================================================
-- Flowmerce central database · 113 · CRO order copy (money breakdown + line items)
-- Safe to run more than once. Needs 112 (schema cro). Never writes ops.*, seo.* or public.*.
--
-- Why CRO keeps its own copy (owner decision 2026-11-19): ops.orders has no subtotal / discounts / shipping / tax /
-- refunded amounts filled and ops.items is never filled, but the sales breakdown, top products and the
-- "no orders for a product" alarm need them. CRO's scheduler reads them from Shopify (read_orders, one app per
-- store) every 15 minutes. Keeping it separate means a CRO problem can never affect Shipping.
--
--   cro.orders       one row per Shopify order: dates, payment status, money fields. Test orders are not stored.
--   cro.order_lines  the order's line items: product id, title, type, tags, quantity, unit price
--   cro.sync_state   per store: the last Shopify "updated_at" read, and a lock so two syncs never overlap
--   cro.save_orders()  upserts orders and replaces their line items in one transaction
--   cro.begin_sync() / cro.end_sync()  take and release the per-store lock
--   cro.delete_change_log()  removes one change-log entry
--
-- No personal data: no customer name, email, phone or address is read or stored.
-- Replaces the view cro.daily_sales from 112 (built on ops.orders); CRO now reads cro.orders.
-- =====================================================================================

drop view if exists cro.daily_sales;

-- ---------------------------------------------------------------- orders
create table if not exists cro.orders (
  id                bigint primary key,                                -- Shopify order id (legacyResourceId)
  store             text not null references ops.stores(id),
  name              text not null,                                     -- #RBP7752
  placed_at         timestamptz not null,
  shop_updated_at   timestamptz not null,                              -- an older copy never overwrites a newer one
  cancelled_at      timestamptz,
  financial_status  text,                                              -- PAID, REFUNDED, PARTIALLY_REFUNDED, PENDING ...
  currency          text not null default 'USD',
  total             numeric(12,2) not null default 0,                  -- current total (after edits and refunds)
  subtotal          numeric(12,2) not null default 0,                  -- line items after discounts, before shipping/tax
  discounts         numeric(12,2) not null default 0,
  shipping          numeric(12,2) not null default 0,
  tax               numeric(12,2) not null default 0,
  refunded          numeric(12,2) not null default 0,
  synced_at         timestamptz not null default now()
);
comment on table cro.orders is 'CRO copy of Shopify orders (money fields only, no customer data). Filled by the CRO scheduler.';
create index if not exists cro_orders_store_placed on cro.orders (store, placed_at desc);

-- ---------------------------------------------------------------- order_lines
create table if not exists cro.order_lines (
  order_id      bigint not null references cro.orders(id) on delete cascade,
  line_no       int not null,                                          -- position in the order, from 1
  store         text not null references ops.stores(id),
  placed_at     timestamptz not null,                                  -- copied from the order, so reports need no join
  product_id    bigint,                                                -- null for a deleted product or a custom item
  title         text not null,
  product_type  text not null default '',
  tags          text not null default '',                              -- the product's tags, comma separated
  quantity      int not null check (quantity >= 0),
  unit_price    numeric(12,2) not null default 0,
  primary key (order_id, line_no)
);
comment on table cro.order_lines is 'Line items of cro.orders. Replaced as a whole whenever the order is saved again.';
create index if not exists cro_order_lines_store_placed on cro.order_lines (store, placed_at desc);

-- ---------------------------------------------------------------- sync_state
create table if not exists cro.sync_state (
  store          text primary key references ops.stores(id),
  cursor         timestamptz,                                          -- newest Shopify updated_at saved so far
  running_since  timestamptz,                                          -- set while a sync runs (the lock)
  last_run_at    timestamptz,
  last_status    text check (last_status in ('ok', 'failed')),
  last_error     text,
  last_orders    int
);
comment on table cro.sync_state is 'Per-store progress of the CRO order sync. running_since is the lock; a lock older than 30 minutes is treated as abandoned.';

-- ---------------------------------------------------------------- begin_sync / end_sync
-- begin_sync returns the cursor row when this caller got the lock, or no row when another sync is running.
create or replace function cro.begin_sync(p_store text)
returns table (got_lock boolean, since_cursor timestamptz)
language plpgsql security invoker set search_path = cro, pg_temp as $$
begin
  insert into cro.sync_state (store) values (p_store) on conflict (store) do nothing;
  return query
    with taken as (
      update cro.sync_state s set running_since = now()
       where s.store = p_store
         and (s.running_since is null or s.running_since < now() - interval '30 minutes')
      returning s.cursor as c
    )
    select true, taken.c from taken;
end $$;

create or replace function cro.end_sync(p_store text, p_ok boolean, p_cursor timestamptz, p_orders int, p_error text)
returns void
language plpgsql security invoker set search_path = cro, pg_temp as $$
begin
  update cro.sync_state set
    running_since = null,
    last_run_at   = now(),
    last_status   = case when p_ok then 'ok' else 'failed' end,
    last_error    = case when p_ok then null else left(p_error, 1000) end,
    last_orders   = p_orders,
    cursor        = case when p_ok and p_cursor is not null then greatest(coalesce(cursor, p_cursor), p_cursor) else cursor end
  where store = p_store;
end $$;

-- ---------------------------------------------------------------- save_orders
-- p_orders: a JSON array of orders, each with the cro.orders columns and "lines": [ {line_no, product_id, title,
-- product_type, tags, quantity, unit_price}, ... ]. Returns how many orders were written (newer than the stored copy).
create or replace function cro.save_orders(p_orders jsonb)
returns int
language plpgsql security invoker set search_path = cro, pg_temp as $$
declare
  v_ids bigint[];
begin
  -- 1. orders: only rows newer than (or as new as) the stored copy are written; their ids are kept.
  --    The caller sends each order id once (a duplicate id in one call is an error).
  with incoming as (
    select x.*
    from jsonb_to_recordset(p_orders) as x(
      id bigint, store text, name text, placed_at timestamptz, shop_updated_at timestamptz, cancelled_at timestamptz,
      financial_status text, currency text, total numeric, subtotal numeric, discounts numeric, shipping numeric,
      tax numeric, refunded numeric)
  ),
  written as (
    insert into cro.orders as o (id, store, name, placed_at, shop_updated_at, cancelled_at, financial_status, currency,
                                 total, subtotal, discounts, shipping, tax, refunded, synced_at)
    select id, store, name, placed_at, shop_updated_at, cancelled_at, financial_status, coalesce(currency, 'USD'),
           coalesce(total, 0), coalesce(subtotal, 0), coalesce(discounts, 0), coalesce(shipping, 0),
           coalesce(tax, 0), coalesce(refunded, 0), now()
    from incoming
    on conflict (id) do update set
      name = excluded.name, placed_at = excluded.placed_at, shop_updated_at = excluded.shop_updated_at,
      cancelled_at = excluded.cancelled_at, financial_status = excluded.financial_status, currency = excluded.currency,
      total = excluded.total, subtotal = excluded.subtotal, discounts = excluded.discounts,
      shipping = excluded.shipping, tax = excluded.tax, refunded = excluded.refunded, synced_at = now()
    where excluded.shop_updated_at >= o.shop_updated_at
    returning o.id
  )
  select coalesce(array_agg(id), '{}') into v_ids from written;

  -- 2. line items of the written orders are replaced as a whole (a line can be removed by an order edit).
  delete from cro.order_lines where order_id = any(v_ids);
  insert into cro.order_lines (order_id, line_no, store, placed_at, product_id, title, product_type, tags,
                               quantity, unit_price)
  select x.id, l.line_no, x.store, x.placed_at, l.product_id, coalesce(l.title, ''), coalesce(l.product_type, ''),
         coalesce(l.tags, ''), coalesce(l.quantity, 0), coalesce(l.unit_price, 0)
  from jsonb_to_recordset(p_orders) as x(id bigint, store text, placed_at timestamptz, lines jsonb)
  cross join lateral jsonb_to_recordset(coalesce(x.lines, '[]'::jsonb)) as l(
    line_no int, product_id bigint, title text, product_type text, tags text, quantity int, unit_price numeric)
  where x.id = any(v_ids);

  return cardinality(v_ids);
end $$;

-- ---------------------------------------------------------------- delete_change_log
-- The backend's REST client only inserts, updates and calls functions, so removing a change-log entry goes
-- through this function. Returns true when a row of that store was deleted.
create or replace function cro.delete_change_log(p_store text, p_id bigint)
returns boolean
language plpgsql security invoker set search_path = cro, pg_temp as $$
begin
  delete from cro.change_log where id = p_id and store = p_store;
  return found;
end $$;

-- ---------------------------------------------------------------- security (same rules as 080 / 112)
alter table cro.orders      enable row level security;
alter table cro.order_lines enable row level security;
alter table cro.sync_state  enable row level security;

revoke all on cro.orders, cro.order_lines, cro.sync_state from public;
revoke execute on function cro.begin_sync(text), cro.end_sync(text, boolean, timestamptz, int, text),
                           cro.save_orders(jsonb), cro.delete_change_log(text, bigint) from public;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select, insert, update, delete on cro.orders, cro.order_lines, cro.sync_state to service_role';
    execute 'grant execute on function cro.begin_sync(text), cro.end_sync(text, boolean, timestamptz, int, text), '
            'cro.save_orders(jsonb), cro.delete_change_log(text, bigint) to service_role';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on cro.orders, cro.order_lines, cro.sync_state from anon, authenticated';
    execute 'revoke execute on function cro.begin_sync(text), cro.end_sync(text, boolean, timestamptz, int, text), '
            'cro.save_orders(jsonb), cro.delete_change_log(text, bigint) from anon, authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'flowmerce_app') then
    execute 'grant select, insert, update, delete on cro.orders, cro.order_lines, cro.sync_state to flowmerce_app';
    execute 'grant execute on function cro.begin_sync(text), cro.end_sync(text, boolean, timestamptz, int, text), '
            'cro.save_orders(jsonb), cro.delete_change_log(text, bigint) to flowmerce_app';
  end if;
end $$;

-- ---------------------------------------------------------------- bookkeeping
insert into ops.schema_migrations (file, note)
values ('113_cro_orders.sql', 'cro.orders, cro.order_lines, cro.sync_state, save_orders/begin_sync/end_sync; drops cro.daily_sales')
on conflict (file) do update set applied_at = now();

notify pgrst, 'reload schema';
