# Plan: Flowmerce reads Amazon MCF directly

Status: **replaced (2026-11-17).** There is no Seller Central API access, so Flowmerce does not call Amazon. The team
loads Amazon's API data into Supabase instead, and Flowmerce reads it: see
[docs/operations/amazon-mcf-data-loading.md](../operations/amazon-mcf-data-loading.md) and `db/central/109_amazon_mcf_intake.sql`.
The goals and rules below still apply.

## Why

Amazon Multi-Channel Fulfillment (MCF) does not report back to Shopify. When Amazon ships or delivers an MCF order,
Shopify is not told. So:

- Orders sent through Amazon can stay **unfulfilled** in Shopify, and Flowmerce counts them as "not dispatched".
- MCF parcels that *are* fulfilled in Shopify (with Amazon's tracking number) never get a delivery update:
  **1,283 of 2,071** Amazon / MCF parcels in Shopify have had no update at all (2026-11-17).
- Supabase has Amazon data only through the hub's own check (`public.hub_orders`, packages with route `mcf`).
  It starts around 12 Oct 2026, covers 22 of the 917 unfulfilled orders, and its furthest status is
  "Shipped by Amazon". It has **no delivery status**.

### About "DONE" in order notes

DONE (or "MCF DONE") in a Shopify order note is a note **to employees**: it says the shipping team has handled the
order, and asks staff to check that the order really is fulfilled. It is not proof that Amazon shipped it. Flowmerce
treats it that way: "Marked DONE by the team, but Shopify shows not fulfilled" is a to-check list, not a delivery
signal. When Amazon's own data says an order was shipped or delivered, that wins.

## Goal

1. Every MCF order, its shipments, packages and tracking numbers, read from Amazon, for both stores that use MCF.
2. **An order Amazon delivered is shown as delivered in Flowmerce**, matched to the Shopify order through its
   tracking number (the tracking number Amazon gave is the one the shipping team puts in the Shopify fulfilment).
3. Orders Amazon shipped but Shopify still shows unfulfilled: listed with Amazon's tracking number, so the team can
   mark them fulfilled in Shopify (Flowmerce stays read-only toward Shopify until write access is approved).
4. Reships: a cancelled or duplicate MCF order for the same Shopify order, or a second MCF order with the same items,
   moves the older parcel to the **Reshipped** section (see "Reshipped" below).

Same rules as the Shopify read: keys only in `.env`, never stored in Supabase, never sent to the browser; read-only
toward Amazon; no customer names, addresses, e-mails or phone numbers stored.

## Amazon's API (Selling Partner API, Fulfillment Outbound v2020-07-01)

| Call | Used for |
|---|---|
| `listAllFulfillmentOrders?queryStartDate=` | every MCF order changed since the last read (paged with `nextToken`) |
| `getFulfillmentOrder/{sellerFulfillmentOrderId}` | the order's status, its shipments, packages, tracking numbers, carrier, estimated arrival, and `displayableOrderId` (the Shopify order number the order was created with) |
| `getPackageTrackingDetails?packageNumber=` | the package's current status (`DELIVERED`, `IN_TRANSIT`, `RETURNED`, `UNDELIVERABLE`, ...), delivery time, tracking events with city/state |

Endpoint for the US marketplace: `https://sellingpartnerapi-na.amazon.com`, marketplace `ATVPDKIKX0DER`.
Sign-in: Login with Amazon (LWA) refresh-token grant → short-lived access token (no AWS request signing needed).
Rate limits are low (about 2 requests/second for order and package calls), so the first read of 60 days takes a
few minutes and later reads only fetch what changed.

## What you need to do in Seller Central (one time)

1. Seller Central → **Apps and Services → Develop Apps** → register as a developer (private developer, for your own
   account only) if not done yet.
2. Create an app client with the role **Amazon Fulfillment** (read MCF orders). No other role is needed.
3. **Authorize** the app for your seller account (self-authorization). This gives a **refresh token**.
4. Put these in `Flowmerce/.env` (names below), never in chat:

```
AMAZON_SP_CLIENT_ID=
AMAZON_SP_CLIENT_SECRET=
AMAZON_SP_REFRESH_TOKEN=
AMAZON_SP_REGION=na
AMAZON_MARKETPLACE_ID=ATVPDKIKX0DER
```

Ridhi and CPC sell under **one** Amazon seller account (confirmed by the owner, 2026-11-18), so one refresh token
covers both. Flowmerce splits MCF orders by brand through the Shopify order number on each MCF order.

Use a **separate** app for Flowmerce, not the key the PPC, listing or MCF tools use: its own request quota, read
only, and revoking it never affects them. Amazon makes the client secret expire on a schedule (rotation); update
`AMAZON_SP_CLIENT_SECRET` when Seller Central asks.

## What Flowmerce will build

1. `shipping/amazon_source.py` (like `shopify_source.py`): token from `.env`, read changed MCF orders since the last
   cursor (first run: 60 days), then shipments and packages, then package tracking for packages not yet delivered.
   Records each run in `ops.sync_runs` (source `amazon`, kind `poll`, per store).
2. Supabase (new SQL file, run once): `ops.amazon_mcf_orders` and `ops.amazon_mcf_packages`: Amazon order id,
   displayable (Shopify) order number, status, items (seller SKU + quantity), tracking number, carrier, ship date,
   estimated arrival, current package status, delivered time, last event (city/state only). No names or addresses.
3. The merge (`ops.refresh_from_shopify_orders`) gains an Amazon step:
   - match by tracking number to `ops.tracking_numbers`; where Amazon says delivered, set the parcel **delivered**
     with Amazon's time, source `amazon`; Amazon's tracking events become scans;
   - where Shopify has no fulfilment, add the Amazon package as the order's parcel (as the hub data does today);
   - Amazon cancelled / duplicate MCF orders feed the Reshipped section.
4. Shipping page: Amazon's status and delivery time in the order drawer; the "check by hand" list shrinks to parcels
   Amazon itself has no data for; a freshness line for the Amazon read.
5. Tests with a fake Amazon (no network), and a first live load checked against Seller Central counts.

## Reshipped (built now, without Amazon's data)

Parcels that never arrived but were sent again are taken out of every delay figure and listed in
**Shipping → Checks → Reshipped** with the next step: close the old fulfilment in Shopify (or cancel the Amazon MCF
order). Signals used today:

1. a **replacement order** whose note says "replacement for #NNNN" (49 such orders; 17 old parcels found);
2. a later parcel of the **same order with the same items**;
3. the order note says **reshipped / resent** and a later parcel exists.

With Amazon's data, a second MCF order for the same Shopify order (or a cancelled first one) becomes a fourth signal.

## Open questions

- Do Ridhi and CPC share one Amazon seller account?
- Should Flowmerce later **write** to Shopify (mark an order fulfilled with Amazon's tracking number, close old
  fulfilments of reshipped orders)? That needs the Shopify write scopes we have not enabled.
