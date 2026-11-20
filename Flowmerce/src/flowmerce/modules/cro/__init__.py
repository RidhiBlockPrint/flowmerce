"""CRO (Conversion Rate Optimization) module.

Shows how each store converts visitors into orders and raises alarms when that gets worse:
  * order figures (sales, AOV, breakdown, products, order health) from CRO's own copy of Shopify
    orders in Supabase (schema `cro`, filled every 15 minutes by `scheduler.py`);
  * sessions, conversion rate, the cart/checkout funnel and device/channel splits asked live from
    Shopify (ShopifyQL, needs the `read_reports` scope), cached for 10 minutes;
  * alarm rules, alerts, the change log and per-store settings in schema `cro`.

Independent of SEO and Shipping: if Supabase or Shopify cannot be reached, only the CRO pages say
so.
"""
