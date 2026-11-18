-- Read-only: lists every table, view and column in this Supabase project whose name mentions Amazon / MCF / FBA.
-- Changes nothing. Run it in the SQL editor and share the result (names only, no data).

select 'table' as what, c.table_schema as schema, c.table_name as name, null as column_name,
       (select count(*) from information_schema.columns x
         where x.table_schema = c.table_schema and x.table_name = c.table_name) as columns
from information_schema.tables c
where c.table_schema not in ('pg_catalog', 'information_schema', 'pg_toast', 'auth', 'storage', 'realtime',
                             'supabase_functions', 'extensions', 'graphql', 'graphql_public', 'vault', 'pgsodium', 'net', 'cron')
  and (c.table_name ~* '(amazon|mcf|fba|sp_?api|seller)' or c.table_schema ~* '(amazon|mcf|fba)')

union all

select 'column', table_schema, table_name, column_name, null
from information_schema.columns
where table_schema not in ('pg_catalog', 'information_schema', 'pg_toast', 'auth', 'storage', 'realtime',
                           'supabase_functions', 'extensions', 'graphql', 'graphql_public', 'vault', 'pgsodium', 'net', 'cron')
  and column_name ~* '(amazon|mcf|fba|asin|seller_?order|fulfillment_?order)'
order by 1 desc, 2, 3, 4;
