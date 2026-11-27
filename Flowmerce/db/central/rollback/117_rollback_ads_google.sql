-- =====================================================================================
-- Flowmerce central database · ROLLBACK of 117_ads_google.sql
-- Removes the Google Ads tables and functions from schema `ads` only. Leaves the rest of `ads` (Meta, rules,
-- action status, rupee rates) and every other schema untouched.
-- The Google figures are not the team's own records: they are read again from Google after 117 is run again.
-- The ads.accounts rows 'google:ridhi' / 'google:cpc' stay (harmless; the next sync updates them).
--
-- DESTRUCTIVE. Needs the owner's explicit approval every time.
-- =====================================================================================
drop function if exists ads.g_sum(text, text, date, date);
drop function if exists ads.g_days(text, date, date);
drop function if exists ads.g_replace(text, text, date, date, jsonb);
drop table if exists ads.g_daily;
drop table if exists ads.g_campaigns;

delete from ops.schema_migrations where file = '117_ads_google.sql';

notify pgrst, 'reload schema';
