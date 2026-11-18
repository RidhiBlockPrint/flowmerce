"""Shipping module: reads Shopify orders from the hub's `public` tables in Supabase and keeps
Flowmerce's own shipping tables (schema `ops`) up to date from them.

Independent of the SEO module: if Supabase is not configured or unreachable, only the Shipping pages show
that state; SEO keeps working."""
