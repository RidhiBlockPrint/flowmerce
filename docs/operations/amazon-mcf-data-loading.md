# Amazon MCF data on the Shipping page

Amazon Multi-Channel Fulfillment (MCF) does not tell Shopify when it ships or delivers an order. Flowmerce does not
call Amazon itself (there is no Seller Central API access). The Shipping page reads Amazon's data **only from
Supabase**, the view `ops.amazon_mcf_packages`. Two things can fill it:

1. **The team's MCF tracking Google Sheet** ("Sellora MCF Tracking", tab `Tracking`), copied into
   `ops.amazon_mcf_sheet` by Flowmerce **every day at 09:00 IST**. This is the source in use.
2. Amazon API answers loaded into `ops.amazon_mcf_orders` / `ops.amazon_mcf_tracking` (below). Not in use; when an
   MCF order is in both, the API data wins.

## The daily copy of the MCF sheet (in use)

The sheet is refreshed from Amazon every morning around 04:30-05:00 IST. At 09:00 IST Flowmerce reads it (Google
service account, read-only) and upserts every row into `ops.amazon_mcf_sheet` (key: MCF id + parcel) with the Supabase
service key. Rows are never deleted: an MCF order that later leaves the sheet keeps its last known state.

* If Flowmerce was not running at 09:00, it copies as soon as it starts (after 09:00 IST) and finds today's copy missing.
* A failed copy (sheet not shared, API off) is retried every hour until one succeeds.
* **Sync MCF sheet now** (Shipping > Overview > Data source) runs the same copy at once.
* Each copy is logged in `ops.sync_runs` (source `amazon`, kind `import`, cursor `mcf_sheet`); two copies never run at once.
* The Data source card shows the last copy, the next one, and why the last one failed.
* **Every tab** that has the `MCF id` and `Brand` columns is read (e.g. `Tracking` plus a `History` tab with older MCF
  orders); other tabs are ignored. When the same MCF id + parcel is in two tabs, the most recently checked copy wins.
* `.env` (optional): `AMAZON_MCF_SYNC_AT` (default `09:00`, India time), `AMAZON_MCF_SYNC=off` to stop the daily copy,
  `AMAZON_MCF_SHEET_ID` (default: the Sellora MCF Tracking sheet), `AMAZON_MCF_SHEET_TABS` (comma list; default: every
  tab with the MCF columns).
* **History matters:** Amazon parcels whose tracking was typed into Shopify by hand never get scans in Shopify (only
  orders shipped through the Amazon Fulfillment app do). For those, this sheet is the only source of Amazon's status,
  so it should hold every MCF order of the last 60+ days, not only recent ones.

Columns read, found by their header name (column order may change; renaming `MCF id` or `Brand` stops the copy):
`Brand` (Ridhi / CPC), `Order`, `MCF id`, `Order status`, `Received`, `Speed`, `Parcel`, `Carrier`, `Tracking`,
`Shipped`, `Arrives by`, `Now` (Amazon's tracking status: DELIVERED, IN_TRANSIT, OUT_FOR_DELIVERY, DELAYED,
UNDELIVERABLE), `Last scan`, `Where`, `Delivered (IST)`, `Checked (IST)`, `Flag`, `_lastIso` (time of the last scan, UTC).

The Shopify order is found from the order number in `Order` (or `MCF id`): `RBP8870`, `#8306`, `Shopify #8608 1`,
`SHOP-RBP8862-1`, or a plain 3-6 digit number. When `Order` holds a customer's name or another channel's long id,
the row is matched by its tracking number only, and the name is never copied.

### Setup (once)

1. Supabase SQL editor: run `supabase/111_amazon_mcf_sheet.sql` (after 109). It adds `ops.amazon_mcf_sheet` and adds
   the sheet's rows to the view `ops.amazon_mcf_packages`. Safe to run again; 109 and 111 may be re-run in any order.
2. Google Cloud, the project of Flowmerce's service account: **enable the Google Sheets API**
   (APIs & Services > Library > Google Sheets API > Enable).
3. The sheet: **Share** > add the service account e-mail (in `GOOGLE_SERVICE_ACCOUNT_FILE`'s `client_email`, and shown
   on the Data source card when a copy fails) as **Viewer**. Flowmerce only reads the sheet.
4. Restart Flowmerce, then press **Sync MCF sheet now** once (or wait for 09:00 IST).

## Amazon API intake (not in use)

### One-time setup

Run `supabase/109_amazon_mcf_intake.sql` in the Supabase SQL editor. It creates two tables and one view in `ops`
and changes nothing else. It is safe to run again.

### What to load

Two tables. Each row holds Amazon's answer **as it comes from the API (JSON), unchanged**. Field names are those of
Amazon's Selling Partner API, Fulfillment Outbound v2020-07-01.

### `ops.amazon_mcf_orders`: one row per MCF order

| column | what to put |
|---|---|
| `seller_fulfillment_order_id` | the MCF order id (`fulfillmentOrder.sellerFulfillmentOrderId`) |
| `store` | `RBP` (Ridhi) or `CPC`; may be left empty (then an id containing `RBP` / `SHOP-R` means Ridhi) |
| `payload` | the whole `getFulfillmentOrder` payload: `{ "fulfillmentOrder": …, "fulfillmentOrderItems": […], "fulfillmentShipments": […] }` |

Fields Flowmerce uses from it: `fulfillmentOrder.displayableOrderId` (**the Shopify order number**: this is how the
MCF order is matched to the Shopify order), `fulfillmentOrderStatus`, `receivedDate`, `statusUpdatedDate`,
`fulfillmentOrderItems[].sellerSku / quantity`, and per shipment `fulfillmentShipmentStatus`, `shippingDate`,
`estimatedArrivalDate`, `fulfillmentShipmentPackage[].packageNumber / carrierCode / trackingNumber`.

### `ops.amazon_mcf_tracking`: one row per package

| column | what to put |
|---|---|
| `package_number` | the package number (`packageNumber`, as text) |
| `payload` | the whole `getPackageTrackingDetails` payload |

Fields Flowmerce uses: `trackingNumber`, `carrierCode`, `currentStatus` (`DELIVERED`, `IN_TRANSIT`, `DELAYED`,
`RETURNED`, ...), `currentStatusDescription`, `estimatedArrivalDate`, and `trackingEvents[]`
(`eventDate`, `eventCode`, `eventDescription`, `eventAddress.city / state / country`).

### Loading again

Load again whenever Amazon has news (for example daily, or every few hours for open orders). Replace the old row:

```sql
insert into ops.amazon_mcf_orders (seller_fulfillment_order_id, store, payload)
values ('SHOP-RBP7885-1', 'RBP', '{ ...getFulfillmentOrder payload... }'::jsonb)
on conflict (seller_fulfillment_order_id) do update set payload = excluded.payload, store = excluded.store, fetched_at = now();

insert into ops.amazon_mcf_tracking (package_number, payload)
values ('123456789', '{ ...getPackageTrackingDetails payload... }'::jsonb)
on conflict (package_number) do update set payload = excluded.payload, fetched_at = now();
```

A loader using the Supabase service key (server side only) can do the same through the REST API with
`Prefer: resolution=merge-duplicates` and `Content-Profile: ops`.

## What Flowmerce does with it

- A Shopify parcel whose **tracking number** Amazon knows takes Amazon's status. **Amazon says DELIVERED → delivered
  in Flowmerce**, with Amazon's delivery time; Amazon's tracking events appear in the order's timeline.
- An order Shopify shows as **unfulfilled** with an MCF order for it becomes Amazon's parcel(s): shipped (with the
  tracking number and a tracking link) or "with Amazon, not shipped yet" (the delay clock keeps running from the
  order date). A cancelled MCF order is ignored.
- A **second MCF order** sent 3 or more days after the first moves the first one's undelivered parcels to
  **Reshipped**. MCF orders created the same day are one order split into several parcels, not a reship.
- An **Amazon parcel missing from the Shopify order** (Shopify shows the order fulfilled, with other tracking numbers)
  is added to the board and listed under Checks as "Amazon parcel not on the Shopify order": check whether the order
  was split or sent twice, and add the Amazon tracking number to the Shopify order.
- An MCF order Amazon marks **Unfulfillable** leaves the order "not dispatched", labelled "Amazon cannot ship it".
- The Shipping page's **Data source** card shows how many MCF orders are loaded, how many packages Amazon reports
  delivered, and when the data was last loaded.

## Privacy

The sheet holds customer names (sometimes in `Order`) and delivery cities. Flowmerce keeps only order numbers, tracking
data and the city / state of the last scan; it never keeps names or the tracking links, and never writes to the sheet.

The `payload` may contain the customer's name, address and phone number (`destinationAddress`, `shipToAddress`,
`signedForBy`). Flowmerce never reads those: it reads only the view `ops.amazon_mcf_packages`, which keeps no name,
street address, phone or e-mail (city and state of tracking events only). The tables are closed to the browser keys
(row-level security on, no access for `anon` / `authenticated`).
