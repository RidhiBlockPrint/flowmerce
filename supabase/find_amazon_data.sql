-- Read-only. Finds where Amazon MCF data was loaded: every table in ANY schema whose name or columns mention
-- amazon / mcf / fba / fulfillment / tracking, with its approximate row count. Changes nothing.
select n.nspname                                   as schema,
       c.relname                                   as table_name,
       case c.relkind when 'r' then 'table' when 'v' then 'view' when 'm' then 'matview' when 'p' then 'table' end as kind,
       greatest(c.reltuples::bigint, 0)            as approx_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) as size,
       (select string_agg(a.attname, ', ' order by a.attnum)
          from pg_attribute a
         where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
           and a.attname ~* '(amazon|mcf|fba|fulfil|tracking|package|shipment|payload|seller)') as matching_columns
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where c.relkind in ('r', 'v', 'm', 'p')
   and n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast', 'auth', 'storage', 'realtime',
                         'supabase_functions', 'extensions', 'graphql', 'graphql_public', 'vault', 'pgsodium',
                         'net', 'cron', 'supabase_migrations')
   and (c.relname ~* '(amazon|mcf|fba|sp_?api|seller|fulfil)'
        or exists (select 1 from pg_attribute a
                    where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
                      and a.attname ~* '(amazon|mcf|fba|seller_fulfillment|package_number)'))
 order by approx_rows desc, schema, table_name;

-- Exact counts for the tables Flowmerce reads (should not be 0 once loaded):
select 'ops.amazon_mcf_orders' as t, count(*) from ops.amazon_mcf_orders
union all select 'ops.amazon_mcf_tracking', count(*) from ops.amazon_mcf_tracking;
