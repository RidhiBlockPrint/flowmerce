-- 106: give Flowmerce's server key enough time for the Shipping merge.
--
-- Supabase stops API calls after a few seconds by default. ops.refresh_from_shopify_orders() re-checks every
-- order Flowmerce knows about (about 5,000 orders and 45,000 carrier events today), which takes longer than that,
-- especially the first time. This raises the limit for the service_role (the server-only secret key) only.
-- The browser keys (anon, authenticated) keep Supabase's short limits.
-- Safe to run more than once.

alter role service_role set statement_timeout = '3min';
notify pgrst, 'reload config';
