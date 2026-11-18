-- =====================================================================================
-- Flowmerce central database · 090 · starting data
-- stores · carriers · carrier_services · settings (all write switches OFF) · status_map
-- Re-runnable: inserts only what is missing, never overwrites a value someone changed.
-- Example people / accounts from the design file are NOT seeded (they are fake examples).
-- =====================================================================================

insert into ops.stores (id, name, shopify_domain, currency, timezone, active, legacy_code) values
  ('RBP', 'Ridhi Block Print', 'guz0he-21.myshopify.com',          'USD', 'America/Los_Angeles', true, 'ridhi'),
  ('CPC', 'Cotton Print Club', 'liquidationfashion.myshopify.com', 'USD', 'America/Los_Angeles', true, 'cpc')
on conflict (id) do nothing;
-- Domains taken from the project's .env.example (RIDHI_SHOPIFY_SHOP / CPC_SHOPIFY_SHOP), which
-- matches the tracker audit. The v2 design file's example "ridhiblockprint.myshopify.com" is the
-- storefront name, not the myshopify address. Owner: confirm before go-live.

insert into ops.carriers (id, name, kind, shopify_name, tracking_slug, track_url, active) values
  ('dhl',                 'DHL Express',         'courier',     'DHL Express',         'dhl',       'https://www.dhl.com/global-en/home/tracking.html?tracking-id={tracking}', true),
  ('fedex',               'FedEx',               'courier',     'FedEx',               'fedex',     'https://www.fedex.com/fedextrack/?trknbr={tracking}', true),
  ('amazon_logistics_us', 'Amazon Logistics US', 'marketplace', 'Amazon Logistics US', 'amazon',    'https://track.amazon.com/tracking/{tracking}', true),
  ('usps',                'USPS',                'courier',     'USPS',                'usps',      'https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking}', true),
  ('shiprocket',          'Shiprocket',          'platform',    null,                  null,        'https://www.shiprocket.in/shipment-tracking/{tracking}', true),
  ('delhivery',           'Delhivery',           'courier',     null,                  'delhivery', 'https://www.delhivery.com/track/package/{tracking}', true),
  ('ups',                 'UPS',                 'courier',     'UPS',                 'ups',       'https://www.ups.com/track?tracknum={tracking}', true),
  ('dhl_ecommerce',       'DHL eCommerce',       'courier',     'DHL eCommerce',       'dhl-ecommerce', 'https://webtrack.dhlecs.com/?trackingnumber={tracking}', true),
  ('unknown',             'Unknown carrier',     'unknown',     null,                  null,        null, true)
on conflict (id) do nothing;

-- Every spelling found in the tracker's real data on 2026-11-17 (counts in brackets), plus each
-- carrier's own names. Blank and "Other" stay UNKNOWN on purpose: the carrier is not known.
insert into ops.carrier_aliases (alias, carrier_id, note) values
  ('dhl express',         'dhl',                 'tracker data (2553)'),
  ('dhl',                 'dhl',                 null),
  ('amazon logistics',    'amazon_logistics_us', 'tracker data (1429)'),
  ('amazon logistics us', 'amazon_logistics_us', 'tracker data (102)'),
  ('amazon fulfillment',  'amazon_logistics_us', 'tracker data (1)'),
  ('amazon',              'amazon_logistics_us', null),
  ('fedex',               'fedex',               'tracker data (742)'),
  ('usps',                'usps',                'tracker data (422)'),
  ('ups',                 'ups',                 'tracker data (35)'),
  ('dhl ecommerce',       'dhl_ecommerce',       'tracker data (1)'),
  ('shiprocket',          'shiprocket',          null),
  ('delhivery',           'delhivery',           null),
  ('',                    'unknown',             'tracker data: blank (106)'),
  ('other',               'unknown',             'tracker data (58)')
on conflict (alias) do nothing;

insert into ops.carrier_services (id, carrier_id, code, name, tier, days_min, days_max, active) values
  ('dhl-express',       'dhl',                 'EXPRESS WORLDWIDE',      'Express',  'express',  3, 5, true),
  ('fedex-priority',    'fedex',               'INTERNATIONAL_PRIORITY', 'Priority', 'express',  3, 5, true),
  ('amz-standard',      'amazon_logistics_us', 'Standard',               'Standard', 'standard', 2, 5, true),
  ('delhivery-surface', 'delhivery',           'Surface',                'Surface',  'economy',  3, 7, true)
on conflict (id) do nothing;

insert into ops.settings (key, value, note, updated_by) values
  ('shopify_writes',  'false', 'Mark shipped in Shopify. Off until the owner turns it on.', 'seed'),
  ('amazon_writes',   'false', 'Send real MCF orders to Amazon. Off until turned on.', 'seed'),
  ('auto_mcf',        'false', 'Send MCF by itself when every item has FBA stock.', 'seed'),
  ('working_hours',   '{"tz":"Asia/Kolkata","days":"Mon-Sat","start":"10:00","end":"19:00"}', 'Alert clocks count only these hours.', 'seed'),
  ('escalation',      '{"after_hours":4,"level2":"head of the step''s team","level3":"owner"}', 'No answer in 4 working hours: head, then owner.', 'seed'),
  ('morning_summary', '{"time":"09:30","numbers":["late","shipped","orders"]}', 'One summary each morning.', 'seed'),
  ('step_limits',     '{"production_total_h":24,"qc_h":4,"packing_h":8,"mcf_to_shipped_h":24,"label_to_pickup_h":24,"no_scan_h":72,"order_check_h":4}', 'How long each step may take (working hours). Production total still to confirm.', 'seed'),
  ('step_teams',      '{"new":"orders","checked":"shipment","print":"production","cut":"production","stitch":"production","jobwork":"production","qc":"production","ready":"shipment","packed":"shipment","label":"shipment","shipped":"shipment","transit":"shipment","out":"orders"}', 'Which team answers for each step.', 'seed'),
  ('alert_reasons',   '{"production":["Waiting for fabric","No karigar free","Printer busy","Dye or colour issue","QC rework","Other"],"shipment":["Not on the shelf","Waiting for pickup","Amazon not shipped","Customs hold","Carrier exception"],"orders":["Payment pending","Address problem","Customer asked to wait"]}', 'Choices when answering an alert.', 'seed'),
  ('gst_invoice',     '{"next":null,"format":"to be decided"}', 'Next GST invoice number, taken in one locked step.', 'seed'),
  ('history_months',  '4', 'How far back the first load reads Shopify.', 'seed'),
  ('carriers',        '["DHL Express","FedEx","Amazon Logistics US"]', 'Carrier names exactly as Shopify knows them.', 'seed'),
  ('webhook_retention_months', '13', 'Owner decision D8.', 'seed'),
  ('age_bands',       '{"yellow":4,"orange":6,"red":9}', 'Days since dispatch for the yellow / orange / red bands (same as the tracker).', 'seed')
on conflict (key) do nothing;

-- ---------------------------------------------------------------- status_map
-- Shopify fulfillment displayStatus words. IMPORTANT: Shopify-only words never confirm
-- delivery (confirms_delivery = false) and "label / fulfilled" is pending, NOT in transit.
insert into ops.status_map (source, carrier_id, raw_status, status, is_terminal, confirms_delivery, note) values
  ('shopify','*','DELIVERED',          'delivered',        true,  false, 'Shopify says delivered; not carrier-confirmed'),
  ('shopify','*','IN_TRANSIT',         'in_transit',       false, false, null),
  ('shopify','*','OUT_FOR_DELIVERY',   'out_for_delivery', false, false, null),
  ('shopify','*','ATTEMPTED_DELIVERY', 'exception',        false, false, 'Delivery attempt failed'),
  ('shopify','*','FAILURE',            'exception',        false, false, null),
  ('shopify','*','RETURNED',           'returned',         true,  false, null),
  ('shopify','*','RETURN_TO_SENDER',   'returned',         true,  false, null),
  ('shopify','*','READY_FOR_PICKUP',   'out_for_delivery', false, false, 'Waiting at pickup point'),
  ('shopify','*','PICKED_UP',          'in_transit',       false, false, null),
  ('shopify','*','CONFIRMED',          'info_received',    false, false, null),
  ('shopify','*','LABEL_PRINTED',      'pending',          false, false, 'Label only; carrier has not scanned'),
  ('shopify','*','LABEL_PURCHASED',    'pending',          false, false, 'Label only; carrier has not scanned'),
  ('shopify','*','FULFILLED',          'pending',          false, false, 'Marked shipped in Shopify; no carrier evidence'),
  ('shopify','*','NOT_DELIVERED',      'exception',        false, false, null),
  ('shopify','*','DELAYED',            'exception',        false, false, null),
  -- The tracker's already-normalized words (for the one-time import, source tracker_import)
  ('tracker_import','*','DELIVERED',        'delivered',        true,  false, 'From tracker; originally Shopify displayStatus'),
  ('tracker_import','*','IN_TRANSIT',       'in_transit',       false, false, null),
  ('tracker_import','*','OUT_FOR_DELIVERY', 'out_for_delivery', false, false, null),
  ('tracker_import','*','FAILED_DELIVERY',  'exception',        false, false, null),
  ('tracker_import','*','RETURNED',         'returned',         true,  false, null),
  ('tracker_import','*','FULFILLED',        'pending',          false, false, 'Label/fulfilled only'),
  -- Tracking-service checkpoint tags (AfterShip-style). Confirm against the chosen service (D2).
  ('aggregator','*','PENDING',           'pending',          false, false, null),
  ('aggregator','*','INFORECEIVED',      'info_received',    false, false, null),
  ('aggregator','*','INTRANSIT',         'in_transit',       false, false, null),
  ('aggregator','*','OUTFORDELIVERY',    'out_for_delivery', false, false, null),
  ('aggregator','*','AVAILABLEFORPICKUP','out_for_delivery', false, false, null),
  ('aggregator','*','ATTEMPTFAIL',       'exception',        false, false, null),
  ('aggregator','*','EXCEPTION',         'exception',        false, false, null),
  ('aggregator','*','DELIVERED',         'delivered',        true,  true,  'Carrier-confirmed via tracking service'),
  ('aggregator','*','EXPIRED',           'expired',          true,  false, null)
on conflict (source, carrier_id, raw_status) do nothing;
