# Changelog

Format: newest first. Types: Added, Changed, Fixed, Removed, Architecture.

## 2026-11-19 (Shipping: a delivered order is never an alert)

Verified: 100 shipping tests (new: a no-tracking fulfilment on a delivered order, a last scan that says
"Delivered"), 589 backend tests pass (the 1 failure also fails on 7cd0758), 54 frontend tests, build, smoke test,
no new mypy or ruff findings. Live board: Critical 10 -> 7, Checks 152 -> 63 orders, "Dispatched without tracking
number" 105 -> 18; no delivered order is left in any alert list.

- **Changed** once ANY parcel of an order is delivered (Shopify, carrier, Amazon MCF, or a last scan that says
  "Delivered"), every other open parcel of that order is shown as Delivered and leaves Critical, exceptions, Checks,
  Reshipped and Unfulfilled. # RBP6462: DHL 2375772626 and 7282291785 delivered on 20 Oct; its fulfilment with no
  tracking number (dispatched 17 Nov) no longer shows "Dispatched without tracking number". This replaces the
  narrower rules (same-carrier split, sent after the delivery, still scanning), which kept those parcels open.
- **Changed** a parcel whose carrier's last scan starts with "Delivered" counts as delivered even when its status
  did not catch up.

## 2026-11-19 (Shipping: Unfulfilled tab; unfulfilled orders out of Critical)

Verified: 99 shipping tests (new: unfulfilled orders are never Critical, on their own list with waiting bands),
54 frontend tests (demo: the Unfulfilled tab total = its KPI, the shipment list has no not-dispatched order),
production build. Live board: 721 unfulfilled orders move to the new tab (357 waiting 9+ days, 17 with Amazon);
Critical goes from 367 to 10, all of them dispatched parcels.

- **Added** Shipping > **Unfulfilled** tab (`GET /api/shipping/unfulfilled`): every order with no parcel sent yet
  (Shopify unfulfilled, or with Amazon but not shipped), one row per order, longest waiting first, with the order
  date, days waiting (0-3 / 4-5 / 6-8 / 9+ filter), Amazon's status and the next step. An Overview tile
  "Unfulfilled orders (not sent yet)" opens it.
- **Changed** not-dispatched orders leave the shipment list, Critical, the delay KPIs and Checks; the summary's
  `stage.preDispatch` and the analytics "Not dispatched" bar count the Unfulfilled tab. The "Marked DONE but not
  fulfilled" check still sees them.

## 2026-11-19 (Shipping: an order another carrier delivered leaves Critical / exceptions)

Verified: 94 shipping tests (new: a USPS label that never moved while UPS delivered leaves the delay figures; a
same-carrier parcel, one sent after the delivery, and one still scanning stay), live board: 14 parcels move to
Reshipped (13 Critical 9+ days, 1 Yellow; 1 carrier exception), including #5680.

- **Changed** an order that has arrived counts as Delivered, not Critical or Reshipped: an open parcel is resolved as
  "Delivered" (by the order) when the parcel that replaced it was delivered, or when it is an extra Amazon parcel and
  every parcel on the Shopify order was delivered (#7254: TBA335054863307 said "delivery date unavailable" while
  both items arrived in TBA335061903868 and TBA335580914603). Live: 18 parcels in 17 orders (17 were Critical); the
  Reshipped list keeps only the 3 whose replacement is still on its way.
- **Changed** a parcel sent again by the same carrier counts too ("Delivered by a later parcel"): the delivered
  parcel was sent 3+ days after the stuck one (parcels sent together are a split and stay). # RBP6127 leaves Critical.
- **Fixed** an Amazon parcel missing from the Shopify order was never checked for a second MCF order, so #7254's
  first parcel (MCF 29 Sep, sent again 16 Oct and delivered) stayed Critical.
- **Changed** Checks > Exceptions shows one row per order, with every issue as its own tag (#6927 had a "Carrier
  exception" row and a "No movement" row). The type filter keeps an order that has that tag; `exceptions.total` and
  the type counts count orders, `exceptions.issues` the issues.
- Live board after the change: 153 orders in Checks (191 issues, no order twice); 21 parcels in Reshipped.
- **Changed** a fifth Reshipped signal, "Delivered by another carrier": an undelivered parcel leaves Critical,
  exceptions and every delay figure when a parcel of a different carrier delivered the same order, and the open
  parcel was sent at least 2 days before that delivery with no scan since. It is listed under Checks > Reshipped
  ("close the old fulfilment in Shopify"). Same-carrier parcels (possible splits), parcels sent after the delivery
  (exchanges, more items), parcels still scanning, and parcels with no known carrier stay on the board.

## 2026-11-18 (Fix: delivered DHL parcel on an older order still shown as critical)

Verified: 581 backend tests (new: a hub-only "failure" is Carrier unconfirmed, a failure with carrier events stays
critical, a team Delivered mark clears it), live board: #4434 leaves Critical (440 -> 439), no other parcel changes.

- **Fixed** #4434 (DHL 8695920855, delivered in Charlotte on 9 Oct) was "Critical 9+ days" with a carrier exception.
  The order is older than Shopify's 60-day window (the store app has no `read_all_orders` scope), so Flowmerce sees
  only the hub's copy: Shopify's last word "failure" (25 Oct) and no carrier events, so the earlier "delivered stays
  delivered" fix could not apply. Such a parcel is now **Carrier unconfirmed**: checked by hand on the carrier page and
  closed with the team's Delivered / Lost mark, never counted critical. Python only (`board.py`); no SQL to run.

## 2026-11-18 (Shipping: MCF sheet history; audit findings)

Verified: 583 backend tests (new: every tab with the MCF columns is read, a notes tab is ignored, the newest copy of an
MCF order wins across tabs, tab list from .env), and a live read of the sheet (1,124 rows, tab Tracking).

- **Changed** the daily MCF sheet copy reads every tab that has the `MCF id` and `Brand` columns, so the ERP team can add
  older MCF orders in the same tab or a separate one (e.g. `History`). `AMAZON_MCF_SHEET_TABS` can name the tabs.
- **Audit (read-only):** of 1,289 Amazon parcels whose tracking was typed into Shopify by hand (Sep 136, Oct 652,
  Nov 501), Shopify never receives scans: Shopify does not track Amazon numbers itself; only the Amazon Fulfillment app
  sends scans for orders it ships. The MCF sheet held MCF orders from November only (7 rows from October, none from
  September), so 886 such parcels had no delivery data. Requested: the ERP team adds September-October MCF orders.

## 2026-11-18 (Shipping: Resolved - delivered, lost, returned, refunded leave Critical)

Verified: 580 backend tests (team outcome out of Critical and the active total, kept on a fresh read, undo, bad
outcome refused; carrier "dispose" = lost, Amazon UNDELIVERABLE = returned, a delay stays a delay; a team "lost" parcel
mark moves to Resolved), production build, live board.

- **Checked** the 444 Critical orders against Shopify: none archived, none fully refunded, no returned / lost tags; 421
  are orders Shopify still shows unfulfilled. Delivered parcels and cancelled / fully refunded orders were already out.
- **Added** the team's outcome for an order: **Delivered / Lost / Returned / Refunded** buttons in the order panel
  (saved in Flowmerce with who and when, audited, undoable). The order leaves Critical and every active / delay figure.
- **Added** automatic outcomes from the carrier: "dispose of the shipment" / destroyed / lost = Lost; returned or
  returning to sender, Amazon UNDELIVERABLE = Returned. Live: 6 parcels (#5748, # RBP6808 lost; #6739, #8141, #8268,
  # RBP8257 returned). A team "lost" mark on a parcel also moves it to Resolved.
- **Added** the **Resolved** filter on the Shipments tab, showing each outcome and who set it.

## 2026-11-18 (Fix: parcels Shopify never got a carrier scan for were shown as critical)

Verified: 578 backend tests (new: a named carrier never scanned for 26 days is unconfirmed, one shipped yesterday keeps
its clock, one with real scans stays critical), production build, live board.

- **Fixed** a USPS / DHL / FedEx parcel with no carrier scan at all ran the delay clock and became "Critical 9+ days"
  with no evidence of a delay (e.g. # RBP7437: USPS delivered it on 22 Oct, the number was entered in Shopify on
  23 Oct and Shopify never received a scan). Like Amazon parcels, a parcel with no carrier update 3+ days after
  dispatch is now **Carrier unconfirmed**: checked by hand with the tracking link and the team's Delivered / Lost
  marks, never counted critical. Live: 46 parcels (36 USPS, 8 DHL Express, 1 FedEx, 1 DHL eCommerce); Red 9+ 488 -> 443.

## 2026-11-18 (Fix: delivered DHL parcels shown as critical after a stray carrier event)

Verified: the 105 upgrade test on a local Postgres (24 checks, new: a FAILURE event after DELIVERED keeps the parcel
and its shipment delivered), and the live Shopify data (6 affected DHL parcels).

- **Fixed** in `105_refresh_from_shopify_orders.sql`: the newest carrier event decided a parcel's status, so DHL's stray
  "FAILURE" events (no text, up to 18 days after "Delivered") turned delivered parcels into critical exceptions, e.g.
  # RBP6563, # RBP6411, # RBP6621, # RBP6658 and #7044 at the top of "Most critical". Once the carrier has scanned a
  parcel DELIVERED it now stays delivered, as in Shopify (which keeps its delivery time). Run the updated 105 in
  Supabase; the next refresh corrects the 6 parcels and closes their exceptions.

## 2026-11-18 (Fix: "Request failed (500)" on Refresh now)

Verified: 577 backend tests, production build, and Refresh now through the website: HTTP 200 after 30.2 s (was 500 at
exactly 30.0 s).

- **Fixed** Refresh now (and Sync MCF sheet now) showed "Request failed (500)" although the refresh finished. The
  website forwards `/api/*` to the Python server and Next.js gave up after 30 seconds; a refresh takes 25-35 s (read both
  Shopify stores, merge in Supabase, reload the Shipping data). `frontend/next.config.mjs` now waits up to 3 minutes.
- **Changed** the Shipping data reload runs its four Supabase reads at the same time (14.8 s -> 9.1 s), and the two
  Shopify stores are read at the same time.

## 2026-11-18 (Shipping: the MCF sheet is copied into Supabase daily at 09:00 IST)

Verified: 574 backend tests (09:00 IST schedule and catch-up, copy without names, failed / interrupted / concurrent
runs, Supabase-only reads, works before 111 and without 109, a parcel sent after a replacement order is not
"replaced"), 109 + 111 on a local Postgres (re-run in any order, unpacked-then-packed order, API data wins, closed to
browser keys, one copy at a time), the real sheet's 1,079 rows through table -> view -> board with the same figures as
reading the sheet directly, and the production build.

- **Added** `db/central/111_amazon_mcf_sheet.sql`: `ops.amazon_mcf_sheet` (one row per MCF id + parcel, no names) and
  its rows in `ops.amazon_mcf_packages` (columns `source`, `synced_at` added). 109 no longer replaces the view once
  111's table exists.
- **Added** `shipping/mcf_sync.py`: the daily copy at 09:00 IST (the sheet is refreshed around 04:30-05:00 IST), a
  catch-up copy when the server was off at 09:00, hourly retries after a failure, logged in `ops.sync_runs`.
- **Added** `POST /api/shipping/amazon-mcf/sync` and the **Sync MCF sheet now** button on the Data source card, which
  also shows the last and next copy and why a copy failed.
- **Changed** the Shipping page reads Amazon data only from Supabase; it no longer reads the sheet on a page load.
- **Fixed** a parcel shipped after a replacement order was placed was listed as replaced by it.

## 2026-11-18 (Shipping: Amazon MCF data from the MCF tracking sheet)

Verified: 566 backend tests (sheet column mapping, customer names never kept, IST dates, Supabase-then-sheet fallback,
unreadable-sheet reasons, same-day split is not a reship, Amazon parcel missing from a fulfilled Shopify order,
unfulfillable label, out for delivery), production build, and a dry run of the real sheet (1,079 MCF orders) against
the live board.

- **Added** `shipping/mcf_sheet.py`: reads the team's "Sellora MCF Tracking" Google Sheet through Flowmerce's Google
  service account (read-only scope). Supabase's `ops.amazon_mcf_packages` is used instead once it has rows.
- **Changed** the reship rule for Amazon: a second MCF order counts as a reship only when sent 3+ days after the
  first. In the sheet, 117 of 119 Shopify orders with several MCF orders were same-day splits.
- **Added** the check "Amazon parcel not on the Shopify order" (89 Amazon parcels whose tracking number is missing
  from a Shopify order that shows other tracking numbers, mostly FedEx / DHL).
- **Added** Amazon's OUT_FOR_DELIVERY status and the "Amazon cannot ship it (unfulfillable)" label.
- **Changed** the Data source card: shows the Amazon source (sheet / Supabase), or why the sheet could not be read and
  which service account to share it with.
- Dry-run effect on the live board: about 470 Amazon parcels move to delivered (most had no update in Shopify),
  86 unfulfilled orders become Amazon parcels, "carrier unconfirmed" falls from 1,381 to 1,011.

## 2026-11-17 (Shipping: Amazon MCF data loaded by the team)

Verified: 354 backend tests (Amazon delivery, unfulfilled order with an MCF order, not-shipped MCF order, cancelled MCF order, second MCF order = reship, ambiguous order number left alone), 109 on a local Postgres copy with sample Amazon API answers (including a check that no name, street or phone reaches the view), 54 frontend tests, production build, and the live page without 109 (unchanged).

- **Added** `db/central/109_amazon_mcf_intake.sql`: `ops.amazon_mcf_orders` (getFulfillmentOrder payloads) and `ops.amazon_mcf_tracking` (getPackageTrackingDetails payloads), loaded by the team as JSON, and the read-only view `ops.amazon_mcf_packages` (one row per package, no personal data).
- **Added** `shipping/amazon_mcf.py`: Amazon's word is laid over the board. A parcel with a tracking number Amazon knows takes Amazon's status; **Amazon DELIVERED = delivered in Flowmerce** with Amazon's time and events. An unfulfilled Shopify order with an MCF order becomes Amazon's parcels. A second MCF order for the same Shopify order is a fourth Reshipped signal.
- **Added** the Amazon data state (orders loaded, delivered, last loaded) to the Shipping page's Data source card.
- **Added** `docs/operations/amazon-mcf-data-loading.md` (what to load and how). The direct-read plan is marked replaced.

## 2026-11-17 (Shipping: Reshipped section; Amazon MCF direct-read plan)

Verified: 349 backend tests (reship rules, including "a split shipment is not a reship"), 54 frontend tests, production build, and the Checks tab on live data.

- **Added** the **Reshipped** section (Shipping > Checks, the "Reshipped" filter and an Overview tile): a parcel, or a not-dispatched order, that never arrived but was sent again is taken out of every delay figure and listed with the next step "close the old fulfilment in Shopify (or cancel the Amazon MCF order)". Signals: a replacement order whose note says "replacement for #NNNN" (same store); a later parcel of the same order with the same Shopify items (`ops.shipments.items`); the order note says reshipped / resent and a later parcel exists. First live run: 17 old parcels (11 Ridhi, 6 CPC), all through replacement orders. Notes are read only for orders that mention replacement or reshipping, and only the order number they refer to is kept.
- **Changed** the "note says DONE" list wording: DONE is the team's internal note that the shipping team handled the order, not proof of an Amazon shipment.
- **Checked** MCF tracking in Shopify: of the hub's Amazon packages with a tracking number, 99 have it in the Shopify order, 16 have no Shopify fulfilment, 3 have a different number. Of 2,071 Amazon / MCF parcels in Shopify, 764 got a delivery update and 1,283 never had any.
- **Added** `docs/plans/amazon-mcf-direct-read.md`: reading Amazon MCF through the Selling Partner API so that an order Amazon delivered is shown as delivered (matched by tracking number), with what to set up in Seller Central.

## 2026-11-17 (Shipping: Amazon MCF status from the hub)

Verified: 347 backend tests, 54 frontend tests, production build, 108 on a local Postgres copy (run twice), and the live board after 108 was run in Supabase.

- **Added** `db/central/108_flow_board_amazon.sql`: `ops.flow_board` gains `amazon_status`, `amazon_at`, `amazon_ref`, `amazon_tracking`, `amazon_checked_at` from the hub's own Amazon (MCF) check in `public.hub_orders` (packages with route `mcf`). An order Shopify shows as unfulfilled but Amazon has a package for becomes one `amazon` row per package instead of a "not dispatched" order. Supabase has no other Amazon table (checked with `supabase/find_amazon_tables.sql`).
- **Changed** the rules: an order Amazon shipped counts as dispatched (Amazon's tracking number and link); a parcel sent through Amazon (MCF, Amazon or unnamed carrier) with no carrier update is "check by hand", because Amazon reports delivery to neither Shopify nor Flowmerce; a package Amazon has not shipped keeps the clock from the order date.
- **Added** the problem type "Shipped by Amazon, unfulfilled in Shopify" (next step: mark it fulfilled in Shopify with Amazon's tracking number), an "Amazon says" column in the "note says DONE" list, and Amazon's status in the order drawer.
- **Note** coverage: the hub's Amazon data starts about 12 Oct 2026 and has no delivery status. At the first run: 22 unfulfilled orders have an Amazon package (16 shipped by Amazon), 18 of 163 "note says DONE" orders have an Amazon record. Full coverage needs Amazon's own data (Selling Partner API).

## 2026-11-17 (Shipping: the redesigned page on real data)

Verified: 345 backend tests (15 new for the page's rules), 54 frontend tests, production build, the new view on a local Postgres copy, and every tab opened in a browser against the live Supabase data (Overview, Shipments with filters, order drawer with the carrier timeline, Checks and exceptions, Analytics; a team flag set and removed again).

- **Added** `db/central/107_flow_board.sql` (also in `supabase/` and the one-file setup): the read-only view `ops.flow_board`, one row per tracking number, per fulfilment without a tracking number, and per undispatched order from the last 60 days. From the hub's order copy it takes only the destination city and state and a yes/no "note says DONE"; never the note text, names, street addresses, e-mails or phone numbers.
- **Added** `shipping/board.py`: days-in-stage categories (clock from order date before dispatch, from dispatch date after), no movement (5+ days without a scan), carrier unconfirmed (Amazon / unknown carrier with no carrier update; checked by hand, never critical), value at risk (order totals, each order once), "note says DONE but not fulfilled", six exception types, delivery performance (on time = by the end of the promised day; parcels without a promised date are left out of the share), carrier scorecard, CSV exports and the tracking-sheet preview (writes nothing). Cancelled and refunded orders are left out.
- **Changed** `/api/shipping/summary`, `/shipments` and `/shipments/{order}` to the new page's shapes; **added** `/analytics`, `/checks`, `/export/{shipments,escalation,verify}`, `/import/sample`, `/import/preview`, `/shipments/{order}/note`. The earlier per-parcel detail moved to `/api/shipping/parcel/{tracking_id}`. Refresh, team marks, `/carriers`, `/diagnostics` and `/export.csv` are unchanged.
- **Added** team actions on an order (checked, flagged for escalation, notes), stored in Flowmerce's own database (new migration: `shipping_order_marks`, `shipping_order_notes`) and written to the audit log; flagged orders join the escalation list. The order drawer also records team marks on parcels checked by hand.
- **Changed** the Shipping page to the redesigned frontend page with a Refresh now button and the real data-source status.
- **Changed** loading: the whole board is read once (about 14 seconds) and kept until the next refresh; the 15-minute refresh reloads it in the background, so pages do not wait. A team mark updates the kept copy at once.
- **Note** about 440 of the ~520 critical items are orders not yet marked fulfilled in Shopify 9+ days after ordering (many are also in "note says DONE but not fulfilled").

## 2026-11-17 (New look from the redesigned frontend, on real data)

Verified: 330 backend tests, 54 frontend tests, production build, and every page opened in a browser against the real backend (Home, Articles and an article, Topics, Publishing, SEO & traffic, Automation, Settings: Integrations, Brands, Data, Audit log, Shipping).

- **Changed** the web interface to the redesigned frontend from `D:\Flowmerce\frontend` (new sidebar and menu, Home, Articles, Settings section). It runs on **real data by default**; the synthetic demo data only appears if `NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=demo` is set on purpose. The old frontend is kept in `backups/frontend-before-redesign-20261117-154329/`.
- **Changed** old addresses (`/blogs`, `/seo`, `/workspace`, `/integrations`, `/audit`) now redirect to their new pages; their page files were removed.
- **Kept** the working Shipping page (Supabase, Refresh now, problems, carriers) inside the new layout. The redesign's own Shipping page (days-in-stage buckets, value at risk, checks, notes) is not used yet: the backend has no endpoints for it.
- **Added** to `GET /api/home`: article counts per brand, the daily Search Console clicks trend, and a Shipping snapshot (`shipping.service.home_snapshot`: parcels on the way, delivered in 30 days, delivery problems, no carrier updates, the four oldest open problems). The snapshot is `null` if Supabase is not set up or unreachable, so Shipping can never break Home.
- **Changed** demo wording that showed on real data (page title, Home labels, a Shopify draft hint in the article editor).

## 2026-11-17 (Shipping reads Shopify directly)

Verified: 39 Shipping unit tests pass; the new `105` tested on a local PostgreSQL 17 (upgrade over the earlier setup and fresh install; 20 checks incl. carrier events, real delivery time, ETA, cancelled fulfillments, delay opening/closing, no change on a second run). Ridhi's Shopify app answers on all 11 scopes. **Not yet verified:** `105` re-run in Supabase and the first live Ridhi load (owner step first); CPC keys still pending.

- **Added** `modules/shipping/shopify_source.py`: reads orders, fulfillments, tracking, line items and carrier events straight from each store's Shopify Admin API with the keys in `.env` (RIDHI_/CPC_SHOPIFY_*). Keys never go to Supabase; no customer details are read. First run per store: one bulk export of the last 60 days; later runs: changes since the last run plus a 2-hourly re-check of open parcels. One store failing never stops the other.
- **Added** `ops.shopify_orders` (in `105`) holding what Flowmerce read from Shopify; `ops.refresh_from_shopify_orders()` now prefers it over `public.orders.raw` for the same order: the newest carrier event decides the status, Shopify's own delivery time and ETA are used, and each carrier event becomes a scan (placeholder status scans are removed once real events exist). Carrier problems close when tracking moves on.
- **Changed** `service.refresh()` reads Shopify first, then merges; freshness pills add "Shopify direct (RBP/CPC)"; refresh toast names a store that could not be read. Added `scripts/shipping_refresh.py`.

## 2026-11-17 (Shipping reads the hub's public tables)

Verified: 32 Shipping unit tests pass; frontend production build passes; in-process API smoke test passes. `105_refresh_from_shopify_orders.sql` tested on a local PostgreSQL 17 with a copy of the live `public.orders` / `public.sync_runs` / `public.stores` data: fresh install and upgrade over the earlier setup both work, first refresh builds 1,690 shipments / 1,695 tracking numbers in about 0.5 s, a second refresh changes nothing, status changes, cancellations, exception closing and team marks behave as described. **Not yet verified:** the new SQL has not been run in Supabase (owner step); the full SEO pytest suite was not run (pytest not installed in `.venv`).

- **Fixed** every Shipping refresh failing with `column s.carrier_name does not exist`: the refresh expected the old tracker tables (`public.shipments` with tracker columns, `public.order_checks`, `public.manual_status`), which this database does not have.
- **Changed** the refresh to `ops.refresh_from_shopify_orders()` (`db/central/105_refresh_from_shopify_orders.sql`): reads `public.orders` and the Shopify fulfillments in `public.orders.raw`, plus the hub's `public.sync_runs` for freshness, for both stores. Still never writes to `public.*`. Shopify's `shipment_status` words are mapped through `ops.status_map`; each new word becomes one scan row timed by Shopify's update of the fulfillment; "delivered" uses that time and stays not carrier-confirmed. Fulfillments stored with only `createdAt` (5,051 on 2026-11-17) are skipped and reported as `fulfillments_incomplete`.
- **Changed** `ops.set_team_mark()` moved into `105`; `080_security.sql` grants read on `public.stores/orders/sync_runs` (not the tracker tables); `110_validate.sql` sections D–I check the new source; Shipping page freshness pills show "Flowmerce refresh" and the hub's "Shopify nightly check" per store, and the refresh toast reports skipped fulfillments.
- **Removed** `db/central/100_tracker_refresh.sql` and `ops.refresh_from_tracker()` (dropped by `105`); `SHIPPING_TRACKER_STORE` setting.
- **Added** `docs/shipping-schema-needs.md` (repo root `docs/`): what the hub's schema fails to capture for shipping and what to add.

## 2026-11-17 (Shipping module on the central Supabase database)

Verified: 27 Shipping unit tests pass (`python -m unittest discover -s tests/unit/shipping`); frontend production build passes; in-process API smoke test passes (SEO routes 200, Shipping reports `schema_missing` until the SQL is run). **Not yet verified:** the SQL has not been run in Supabase; the full SEO pytest suite was not run (pytest not installed in `.venv`).

- **Added** Shipping module `src/flowmerce/modules/shipping/` (Supabase REST client on `httpx`, rules, service, `/api/shipping/*` routes, 15-minute background refresh) and the `/shipping` page (Overview, Shipments, Problems, Carriers, detail drawer with scan history, team check, CSV export with formula guard).
- **Architecture** central database SQL in `db/central/` (schemas `ops` + `seo`), one-file `supabase_setup.sql`, repeatable `ops.refresh_from_tracker()` that never writes the tracker's `public.*` tables. See `docs/architecture/central-database.md`.
- **Fixed** (in Flowmerce's view of the data) parcels Shopify reports as `NOT_DELIVERED` / `DELAYED` being shown as "fulfilled" by the tracker; deliveries reported only by Shopify are now labelled not carrier-confirmed; carrier spellings unified.
- **Changed** `seo/app.py` mounts the Shipping routes and starts its refresher inside guards, so a Shipping failure cannot stop SEO. Sidebar gains an Operations → Shipping entry.
- **Added** `.env.example` Shipping variables (names only); scripts `shipping_inspect_supabase.py`, `shipping_smoke.py`, `build_supabase_setup.py`.

## 2026-11-14 (Batch A: data accuracy and sync reliability)

Code and tests written; **tests not yet run** (the development shell is blocked by the TEMP/TMP setting). Not verified against live Shopify or Google.

- **Fixed** Search Console URL variants (www/non-www, http/https, `?query`, trailing slash) overwriting each other: rows are now added together per page before saving (position weighted by impressions), as GA4 already did. Applies to the days each routine sync re-reads; older stored days change only through a reviewed re-sync.
- **Changed** demo data to an explicit demo mode (`DEMO_MODE`, default `false`). Normal mode reads only live-API and imported rows, never demo rows, even for a brand with no real data (the report says why it is empty). Demo mode reads demo rows only, so one report never mixes the two; loading demo data is refused outside demo mode; Home never shows synthetic figures; exports never contain demo rows in either mode; a banner marks every page in demo mode (`/api/auth/me` and `/api/home` return `demoMode`).
- **Fixed** the article "By article" view showing 0 for hidden drafts or articles published after the range: shown as no value.
- **Fixed** a failed scheduled refresh waiting 6 hours: retries after 30 min, 1 h, 2 h, 4 h, then every 6 h; the 6-hour timer counts successful runs only.
- **Fixed** two syncs of the same source and brand running at once (scheduler and Sync now): the second is refused with 409.
- **Fixed** integrations stuck on "syncing" after the server stopped mid-sync: marked interrupted at startup (last success kept).
- **Fixed** product pruning when the Shopify listing stopped at its page limit, the public feed assuming 50 entries per page, and Shopify's `Retry-After` being ignored.
- **Added** separate tracking of authentication, API access, sync and data received: the Test button stores its result (`details.lastCheck`) without touching the sync status; syncs store row counts, the latest data date and any gap; `GET /api/integrations` returns a `health` block per integration.
- **Added** an explanation for empty analytics ranges (`source.state`: not set up, not synced, syncing, sync failed, no rows, partial).
- **Added** `article.shopify_sync` (current sync path: Admin API or public feed) next to the unchanged `origin`, and `article.unpublished_in_shopify` (published here but hidden in Shopify; flagged and audited, never demoted automatically). Imported Shopify drafts are refreshed from Shopify only while nobody has edited them in Flowmerce.
- **Added** `python -m flowmerce.modules.seo.maintenance` (`db-report` read-only, `backup` verified, `resync-preview`, `resync-apply --confirm`) and `db.backup_database`.
- **Changed** `GA4_PROPERTY_ID` accepts `properties/123` and uses the number.
- No database schema change; no migration added.

## 2026-11-14 (Shopify: Dev Dashboard app credentials)

- **Added** client-credentials sign-in for the SEO module's Shopify connection: when `RIDHI_SHOPIFY_ADMIN_TOKEN` / `CPC_SHOPIFY_ADMIN_TOKEN` is empty, `<BRAND>_SHOPIFY_CLIENT_ID` and `<BRAND>_SHOPIFY_CLIENT_SECRET` (a Dev Dashboard app in the same organisation as the store) are exchanged for a short-lived Admin API token, cached in memory and refreshed once on a 401. A static `shpat_…` token still takes precedence. Settings documented in `.env.example`.
- Checked against the Ridhi store: shop found, `news` blog with 21 articles, 586 active products.
- 3 new tests (463 in total).

## 2026-11-07 (Flowmerce logo)

- **Added** the approved Flowmerce logo ("Concept B, Thread F") as `frontend/src/components/Logo.jsx` (`Logo`, `LogoMark`, `AppIcon`) with light and dark colour sets driven by `--fl-*` CSS variables in `globals.css`, and static SVGs in `frontend/public/brand/` (mark, logo, logo with tagline, on dark and on light; app icon).
- **Changed** the sidebar, loading splash and sign-in panel to use it, and replaced `frontend/public/favicon.svg` with the new app icon. The old four-petal mark was removed from `Icon.jsx`.
- Rebuilt by hand from the approved PNG image; swap in the designer's vector files when available.

## 2026-11-04 (AI job bridge: review fixes, round 5)

- **Fixed** a concurrency race in worker-health tracking: the dispatch failure and its `mark_error` now run in one transaction (both or neither), and `integrations/status.py` `mark_success` / `mark_error` accept an optional `at` (the moment the outcome was observed) so a delayed, older result can never overwrite a newer one (a tie goes to success; the failure audit line is written only when the row is). Callers that pass no `at` behave exactly as before; no schema change.
- 7 new tests (460 in total).

## 2026-11-04 (AI job bridge: review fixes, round 4)

- **Fixed** dispatch-failure handling in `_dispatch()`: the status check followed by a separate health update is gone. A dispatch error now goes straight to `_after_failure()` with the dispatch lease token, and the worker is marked unavailable only if that call actually applied a failure to this dispatch attempt. A worker that already reported `succeeded` or `failed` (or a job cancelled meanwhile) keeps its terminal state and result, uses no retry, and is not marked unavailable.
- 4 new tests (453 in total).

## 2026-11-04 (AI job bridge: review fixes, round 3)

- **Fixed** a callback-versus-dispatch race: a valid worker callback now releases the dispatch lease token (only the worker's inactivity deadline remains), so a dispatch request that times out afterwards cannot requeue or fail a job the worker is running; a late acknowledgement only fills missing identifiers and never overwrites newer callback state.
- **Fixed** the pause bypass: the runner no longer claims a paused brand's pending jobs, a manual retry of a paused brand's job is 423 `paused`, running jobs are not interrupted, cancelling still works, and resuming releases waiting jobs immediately. The dashboard shows "waiting: automation is paused" and disables Retry for a paused brand.
- **Fixed** malformed fields: `event_type` and `status` (callbacks) and `status` (worker acknowledgements) are type-checked before dictionary/set membership, so lists and objects give a controlled 400 / `invalid_response` instead of a `TypeError`.
- 76 new tests (449 in total).

## 2026-11-04 (AI job bridge: review fixes)

- **Fixed** synchronous Claude paths: `workflow.run_stage()` now queues topic research and content generation as AI jobs (`create_job`) instead of calling Claude in the request; the inline runners were removed so nothing can bypass the queue. Same for the topic "Draft with Claude" button (`POST /api/topics/{id}/article` answers 202 with the job, `articleId: null`) and the retry of an old failed AI run. Permissions, brand validation, pause and human approval are unchanged; non-AI stages run as before. The stage setup gap now accepts an external worker as a valid method. Automation shows "Queue AI job", opens the created job's status, and follows it; Topics sends you to Automation.
- **Fixed** lease ownership: every claim gets a unique lease token; every execution-side write requires that token **and** an unexpired lease; shutdown releases only its own runner's claims. Regression test with a real `Runner` (claim, expire, reclaim, stale result rejected).
- **Fixed** external worker readiness: `WORKFLOW_WEBHOOK_SECRET` is required (provider status `missing: webhook_secret`, 412 on creation, waiting jobs are not dispatched); an unsafe `AI_CALLBACK_URL` is reported; the secret is never sent to the worker.
- **Fixed** idempotency: a key is bound to a fingerprint of brand, task type and normalised input (409 `idempotency_conflict` on any difference); replays survive a used-up topic; concurrent duplicates are safe.
- **Fixed** topic count: a topic research job records its requested (or default) count and a result with more topics is rejected with nothing created.
- 54 new tests (373 in total).

## 2026-11-04 (AI job bridge: Flowmerce <-> Claude)

- **Added** persistent AI jobs ([ADR 0009](docs/decisions/0009-ai-job-bridge.md)): migration 2 adds `ai_jobs` and `ai_job_events` (additive; existing data untouched); `services/ai_jobs.py` (state machine, de-duplication by idempotency key or active input, atomic claim with leases, bounded runner, recovery, graceful shutdown, retry policy), `services/ai_results.py` (strict result validation; results become `proposed` topics or one `draft` article only), `integrations/ai_worker.py` (external worker contract v1: https/loopback only, bearer token, `Idempotency-Key`, no redirects, retry classification, `Retry-After`, bounded backoff).
- **Added** API `GET/POST /api/ai/jobs`, `GET /api/ai/jobs/{id}`, `POST .../retry`, `POST .../cancel`; an **AI jobs** card on Automation (provider state, progress, history, retry, cancel, new job) and an **AI job execution** card on Integrations. With no executor configured, job creation answers 412 `pending_setup` and creates nothing.
- **Changed** `POST /api/hooks/workflow`: the secret is checked before the body is read; the body is capped at 64 KB of actual bytes (413 otherwise); a body with `job_id` is an AI job callback (strict fields, `event_id` idempotency, per-job `sequence` ordering, stale/finished/out-of-order rejection, progress never backwards, one transaction, audited). Same route and `X-Workflow-Secret` header.
- **Changed (behaviour)** the legacy webhook body (no `job_id`): an invalid or missing `status` is now 400 instead of silently `succeeded`; `result` is refused; timestamps are validated. It still logs one run row per call and is due for retirement (roadmap F15).
- **Changed** `integrations/claude.py`: classified errors (`ClaudeError`, still a `RuntimeError`), explicit timeout, bounded retries for rate limits / 5xx / connection errors (never auth, invalid request or timeouts), usage metadata without prompts or keys. `workflow.py` shares its context builders with AI jobs; a run that belongs to an AI job is retried from the AI jobs list; the startup sweep leaves active jobs' runs to the job recovery.
- **Not done / not verified:** no live Anthropic or worker call was made (tests use a mocked Claude and a loopback fake worker); no standalone worker service; single process per SQLite file only; no in-app rate limiting (gateway job).
- 241 new tests (319 in total).

## 2026-11-04 (Shipping module removed)

- **Removed** the whole Shipping module so it can be built separately on another device and merged back later: `modules/shipping`, the `/shipping` pages and components, its tests, `scripts/import_shipping_data.py`, `db/master_shipping.sql`, ADRs 0007 and 0008, the `SHIPPING_*`, SMTP, `ALERT_*`, Supabase and `TRACK17` settings in `.env.example`, the `shipping:update` permission, the shipping sync in the scheduler and the shipping checks in `scripts/ci_smoke.py`.
- Removed the six `shipping_*` tables from `data/blog-ops.sqlite` and moved `data/master.sqlite`, `data/shipments.json`, the shipping backups and the incoming tracker folders out of the repository (copy kept outside it).
- Left the planning documents (`docs/01`-`03`, `db/schema.sql`, `architecture-map.html`, product handoff) unchanged: they describe the target design.

## 2026-10-31 (Shipping: master database schema, schema only)

- Added the planned **master database schema** from the owner's "Ridhi Shopify Database" design ([ADR 0008](docs/decisions/0008-master-database-for-shipping.md)): the tables `stores`, `orders`, `items`, `shipments` and `events` with the design's names and columns, created empty in `data/master.sqlite` at startup, plus the matching Postgres DDL for Supabase (`db/master_shipping.sql`). **Nothing fills the tables.**
- Removed an overreach from the first attempt (a Shopify sync into the tables, a "Sync master data" card, API endpoints and a 6-hourly background job). The filled database (54 MB, with customer details) was moved to `backups/` and not deleted.
- 3 schema tests.

## 2026-10-31 (Shipping rebuilt around orders, and the rules added since)

Owner decisions: classify by delivery status, delay measured in days from the fulfilled date, the same days for every carrier.

- **Order-level model** (`modules/shipping/orders.py`, `/api/shipping/orders...`): every order is in one group: Delivered, In transit (0-3 days), Delayed (yellow 4-5, orange 6-8, red 9-12, critical 13+), Not refreshed, Unfulfilled, Lost / missing (team mark, or no carrier update for 14+ days), No tracking ID and No carrier tracking. Needs action is an overlay: no scan for 5+ days and a delivery that took 13+ days. Pages: Overview, Orders (with an order drawer and a team check per shipment) and Analytics (transit time per carrier).
- **Unfulfilled** orders are their own section with no delay tier: the app tracks the shipment, so the clock starts when the order is marked fulfilled.
- **Delivered by rule:** an order whose note says DONE while Shopify shows it unfulfilled is Amazon MCF and counts as delivered once 5+ days old (tag "Amazon MCF"); a mixed order whose partner-carrier parcels (DHL, USPS, FedEx, ...) are delivered and whose only open parcels are Amazon's counts as delivered (tag "Amazon part unconfirmed"). A team mark of lost still wins.
- **Not refreshed:** Shopify only returns orders from the last 60 days, so an older open order stops updating (e.g. #4368). Such an order is no longer counted as In transit / Delayed; the real fix is the `read_all_orders` scope.
- **Tracking-service lookup** (`tracking.py`, "Check with tracking service", `TRACK17_API_KEY`) for parcels Shopify never marks delivered. Not verified against the live service.
- Tried and **reverted** at the owner's request: counting archived Shopify orders as delivered (it emptied Delayed), keeping lost/missing out of every total, hiding phantom rows with a re-check button.
- Current data (orders): delivered 2,985; in transit 209; delayed 322; not refreshed 10; unfulfilled 392; lost / missing 16; needs action 29.

## 2026-10-30 (Shipping: packages fulfilled by hand)

- New category **"Fulfilled by hand, tracked package delivered"** (`covered`). A package with no tracking number (marked fulfilled by hand in Shopify, e.g. MCF orders) used to stay "carrier unconfirmed" even when the order's tracked packages were delivered. It is now covered when Shopify says the whole order is FULFILLED and every package that has a tracking number is delivered. It leaves the unconfirmed queue and the active counts, has its own tag, count (Overview legend, Shipments tile, quick view, Checks tile) and `view=covered` filter, and a team mark on the package still overrides it. Nothing is changed in Shopify or deleted. On the current data: 108 packages covered, unconfirmed 811 -> 700 (e.g. order #5311). Amazon tracking is a separate piece of work.

## 2026-10-30 (Shipping live data import)

- Imported the live tracker data from Supabase (read-only): 4,409 shipments, 35 sync runs, 3,753 order checks, 38 manual marks; the 104 stale rows from the old 17 Oct snapshot were removed with the new `--prune` option (backups taken first). Counts now match the owner's live dashboard (1,089 active, 786 unconfirmed, 21 stuck, 195 on track, 32 yellow; critical and orange differ by one because a shipment crossed a threshold between the screenshot and the import).

## 2026-10-30 (Shipping data capture, second pass)

### Fixed / Added
- Compared with the owner's live tracker screenshots: the classification logic matches the original dashboard exactly (cross-checked against the original JavaScript on the same file: identical counts), so the differences came from data. The delivered `shipments.json` is a 17 Oct snapshot (the newer zip's copy is byte-identical), and the live dashboard also reads Supabase tables that were not in either zip.
- Ported the newer tracker code: order total / currency on every shipment (value at risk), order checks (Shopify note, fulfilment and financial status) saved on each sync, cancelled / refunded orders left out, hourly refresh when credentials are set, the daily alert digest (`alerts.py`, manual `POST /api/shipping/alerts/send`; needs SMTP in `.env`, nothing is scheduled).
- `scripts/import_shipping_data.py --from-supabase`: read-only copy of shipments, sync runs, order checks and manual status from Supabase (needs `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`; dry run, backup and verification as before). Schema version 2 adds the new columns to existing databases.
- Overview: "Since your last visit" banner, Print summary, a 7 / 30 day / all-dates range for the weekly chart, and a Delivered link.
- Tests: 12 new (order totals, order checks, schema upgrade, Supabase import with a fake server, alert digest).

### Not done
- Command palette (Ctrl+K), notifications bell and the dark theme toggle from the original dashboard; the live Supabase data itself (needs the owner's credentials or exports).

## 2026-10-30 (Shipping module)

### Added
- **Shipping module** integrated from the delayed-order-tracker project ([ADR 0007](docs/decisions/0007-shipping-module-and-database.md)): `src/flowmerce/modules/shipping/` (repo, schema, aging, normalize, carriers, shopify, sync, service, importer, api), endpoints under `/api/shipping/...`, and the `/shipping` pages (overview, shipments, analytics, checks) in Flowmerce's design with a shipment drawer, quick views, filters, server-side paging, CSV exports (escalation, verify, filtered), team check for Amazon/unknown carriers, notes and a Home card.
- Five `shipping_*` tables in the Flowmerce SQLite database (SEO schema untouched); `scripts/import_shipping_data.py` (dry run, backup, verification). 3,524 shipments and 5 sync runs imported and verified.
- Read-only Shopify sync (`read_orders`, `read_fulfillments`, client-credentials token); scheduler refresh every 12 hours when credentials exist; `shipping:update` permission; `SHIPPING_*` settings in `.env.example`.
- Ported tracker tests (42) and new HTTP tests; `ci_smoke.py` checks the shipping API and routes.

### Changed
- Lost on purpose: the Supabase login, the GitHub Actions daily trigger and the Chart.js CDN; notes moved from browser storage to the database. Ruff and mypy exceptions added for the ported code (roadmap B8).

### Validation
- `pytest -q` 129 passed; `ruff check .` and `mypy` pass; `npm run build` succeeds; `ci_smoke.py --web` all 42 checks pass; browser check on the real imported data (overview, shipments with filters, paging and drawer, analytics, checks).
- **Not verified:** a live Shopify sync, `manual_status` / `order_checks` data, Supabase, and the GitHub CI run.

## 2026-10-30 (Ridhi keyword workbook, read-only)

### Added
- `modules/seo/services/keyword_file.py` and `GET /api/keyword-file`: read the newest `data/ridhi-keyword-db-*.xlsx` (sheets Keyword DB, New keywords, Opportunities) without writing to the database or the file. Numbers are taken only from the sheet (blank stays blank). Ridhi only.
- `frontend/src/views/KeywordFile.jsx`: "Ridhi keyword research" section on Topics & keywords (All / Opportunities / New this run, cluster filter, search, volume, KD, Search Console figures, recommended action).
- `tests/unit/seo/test_keyword_file.py`.

### Validation
- `pytest -q` 78 passed, `ruff` and `mypy` pass, `npm run build` succeeds; browser check against the real workbook showed 170 keywords (44 opportunities, 55 new).

## 2026-10-29 (Next.js JavaScript frontend, one launcher)

### Changed
- **Frontend migrated from Vite + React Router + TypeScript to Next.js 15 (App Router) + React 19 in JavaScript/JSX only** ([ADR 0006](docs/decisions/0006-nextjs-javascript-frontend.md)). All 33 files under `frontend/web/src` were converted to `.js`/`.jsx` under `frontend/src` (`pages/` became `views/` so it cannot clash with Next.js's Pages Router) and routing moved to real route folders in `frontend/src/app/` (`blogs/[id]`, `workspace/[brand]`, ...). `frontend/web/` (including `index.html`, `tsconfig.json`, `dist/`), `vite.config.ts`, `main.tsx` and `App.tsx` were removed; `package.json` now depends on `next`, `react` and `react-dom` only, with scripts bound to `127.0.0.1`.
- `frontend/next.config.mjs` forwards `/api/*` to `http://127.0.0.1:8787`, redirects `/login` to Home and adds basic security headers. `components/Providers.jsx` loads the local operator (`/api/auth/me`) and opens the dashboard directly.
- **Only working pages are visible.** The sidebar and Home list Home and the SEO & Blog pages. Planned projects, shared "planned" pages, future-scope entries and Home's demonstration-data mode were removed from the UI; unknown addresses (including `/users`, `/shipping`, `/approvals`) show a not-found page with a link to Home. `Login`, `Planned` and `Users` sources are kept but not mounted. No database rows were touched.
- `modules/seo/app.py` no longer serves `frontend/web/dist` (API only; strict `default-src 'none'` CSP on its responses).
- `scripts/run_flowmerce.py` (new) starts the API on 127.0.0.1:8787 and Next.js on 127.0.0.1:3000, opens the browser and stops both on Ctrl+C, with clear errors for missing Node/npm, failed installs and busy ports. `scripts/run_seo.py` forwards to it; `run_seo.bat` calls the new launcher.
- `scripts/ci_smoke.py` rewritten for local operator mode (no sign-in; `--web` also starts the built frontend and checks its routes). `.github/workflows/ci.yml`: the frontend job runs `npm ci` and `npm run build` (no type-check); the smoke job builds the frontend and runs `ci_smoke.py --web`. `.gitignore`: `frontend/.next/`, `frontend/out/`.
- Documentation: `PROJECT_RULES.md` (Python backend, Next.js/JavaScript frontend), README, setup, roadmap, system overview, folder structure, file registry, CI and troubleshooting guides, ADR 0002 note, ADR 0005 update and new ADR 0006.

### Added
- `tests/unit/test_frontend_javascript_only.py`: fails if TypeScript or Vite files or dependencies return, if the App Router routes are missing, or if unfinished pages are mounted.

### Validation
- `pytest -q`: 75 passed. `ruff check .` and `mypy`: pass. `npm run build` (Next.js 15.5.28): succeeded. `python scripts/ci_smoke.py --web`: all 35 checks passed (run on port 8799). A browser check on an isolated instance confirmed `/login` lands on Home with no sign-in, Home shows real empty records and the sidebar lists only working pages.
- **Not verified:** a full `run_flowmerce.py` start on ports 8787/3000 (an older API process, not started by this work, occupied 8787 and was left running; only the "port in use" error path was exercised), the GitHub CI run, a connection from another computer, and anything against the real database or live services.

### Not done
- No frontend unit tests or linting; Next.js 16 not adopted; `.env.example` may still mention the ignored `ADMIN_PASSWORD`; the `Host`-header check against DNS rebinding (F14).

## 2026-10-29 (local operator mode)

### Changed
- **No sign-in; local computer only** ([ADR 0005](docs/decisions/0005-local-operator-mode.md)). The dashboard opens without an email, password or session. `modules/seo/app.py` refuses every request that does not come from a loopback address (403 `local_only`) before serving the dashboard, its assets or any API path; missing or unparsable addresses fail closed and forwarded-IP headers are ignored. The only exemption is `POST /api/hooks/workflow`, which keeps its own `X-Workflow-Secret` check. The CSRF header, permission checks, audit log and live-publishing safeguards are unchanged.
- Local requests act as the first active administrator record (`auth.local_operator`). `GET /api/auth/me` returns it with its permissions; `POST /api/auth/login` and `/api/auth/password` answer 410 and verify nothing; `/api/auth/logout` is harmless.
- First-run bootstrap creates an administrator record if no active administrator exists, even when other users exist, and never generates, shows, logs or writes a password (`ADMIN_PASSWORD` is ignored; an old `data/initial-admin.txt` is left in place and unused).
- Frontend: `App.tsx` loads the operator and opens the dashboard directly (`/login` redirects to Home); `Shell.tsx` shows a "Local operator mode" indicator instead of the account menu, password change and sign-out; `Users.tsx` is a read-only list with a note.
- Tests: `tests/integration/seo/test_http.py` rewritten and `test_home.py` updated for loopback and remote clients; `tests/fixtures/seo.py` gained client helpers.

### Validation
- 70 Python tests pass (34 before), `ruff check .` and mypy pass, `npm run typecheck` exit 0, `npm run build` succeeded. A browser check on an isolated test instance confirmed the dashboard opens directly, `/login` redirects, the controls are gone and the existing SEO pages load.
- **Failing / not verified:** `scripts/ci_smoke.py` now fails (it signs in with the old first-run password), so the CI `Smoke test` job would fail if pushed; a connection from another computer over a real network was not tried; nothing was run against the real database.

### Not done
- `scripts/ci_smoke.py`, `docs/operations/ci-cd.md`, `docs/operations/troubleshooting.md` and `.env.example` still describe sign-in (outside the approved files). `Login.tsx` is unused but kept. A `Host`-header check against DNS rebinding was not added.

## 2026-10-29 (CI, Stage A)

### Added
- `.github/workflows/ci.yml`: continuous integration on GitHub Actions. Jobs: `Python 3.12` and `Python 3.14` (`pip install -e ".[dev,seo]"`, `ruff check .`, `mypy`, `pytest -q`); `Frontend` (Node 24, `npm ci`, `npm run typecheck`, `npm run build`, built UI saved as an artifact); `Smoke test` (boots the app on a throwaway folder). No secrets, read-only permissions, Actions pinned to commit hashes.
- `.github/dependabot.yml`: weekly update pull requests for pip, npm and GitHub Actions.
- `scripts/ci_smoke.py`: Python smoke test (12 checks) usable locally and in CI.
- `docs/operations/ci-cd.md` and `docs/decisions/0004-ci-cd-github-actions.md`.

### Changed
- Roadmap F1 (CI) now Implemented, not yet run on GitHub; new F12 (deployment) recorded as Planned and awaiting approval. README, setup and file registry updated.

### Validation
- `scripts/ci_smoke.py` ran locally twice (with and without the built UI): all checks passed, no temporary folders left behind; `ruff check .` passes; the 34 Python tests, mypy, `npm run typecheck` and the build still pass. The pinned Action hashes were verified against GitHub's API.
- **Not validated:** the workflows have not run on GitHub; the YAML could not be machine-parsed locally; Python 3.12 and Linux have not been exercised.

### Not done
- Deployment, release artifacts and a container image (not approved); GitHub settings (branch protection, Dependabot alerts) are manual steps for the owner; `docs/architecture/folder-structure.md` does not yet list the new `.github/` folder.

## 2026-10-29 (Home: real SEO data, Stage 1)

### Added
- `GET /api/home` (`modules/seo/api.py`, new `modules/seo/services/home.py`): a read-only summary of real SEO & Blog records for the Home page. It needs the `view` permission, supports `?brand=`, and returns a fixed 28-day metric window ending 3 days before today, each metric with its source. Approvals use the same role filtering as `/api/tasks` (review, publish authorization and topic decisions only). Alerts reuse the existing alert logic; jobs come from `workflow_runs`; syncs from `integration_status` (attempted integrations only, no error text). "Latest reports" is always empty with an explanation, because dated reports do not exist. Figures from synthetic demo fixtures are never returned as metrics: they are withheld and flagged (`withheld`, `demoFixturesLoaded`).
- `tests/integration/seo/test_home.py`: 11 tests (authentication, permission, role filtering, brand filter, unavailable sources, real-versus-demo separation, no secrets, no mutation).

### Changed
- `modules/seo/api.py`: the task-building logic of `/api/tasks` moved into `_tasks_for()` (behaviour unchanged) so `/api/tasks` and `/api/home` agree.
- `frontend/web/src/lib/home.ts`, `pages/Home.tsx`: demo mode now defaults to OFF; with it off Home shows real records from `/api/home` (with loading, error and empty states), with it on it shows a small synthetic sample and makes no request. The two are never mixed. The fictional Meta ads, shipment, conversion and landing-page demo rows were removed; the sample covers only the SEO & Blog project and every row says "Sample".
- `frontend/web/src/components/Shell.tsx`: `/publishing` is requested only on SEO pages, `/tasks` only on SEO pages and Home, and the Tasks control is shown only there (previously both ran on every route change).
- `frontend/web/src/pages/Login.tsx`: sign-in tagline "Ecommerce in a Flow." and description "A shared workspace for your e-commerce operations and growth."

### Validation
- 34 Python tests pass (23 existing + 11 new), `ruff check .` and mypy pass; `npm run typecheck` exit 0; `npm run build` succeeded. Browser checks on an isolated test instance (temporary folder, seeded test records, no `.env`): sign-in text, demo off by default, real values and sources, CPC demo fixtures withheld, request counts per route, demo mode on and off. Not run against real data or live accounts.

### Not done
- The Planned project cards still say "Latest report: No reports yet" (`components/home.tsx` was outside the approved scope). Home still has no data for the unbuilt projects, by design.

## 2026-10-29 (branding fix)

### Changed
- `frontend/web/src/pages/Login.tsx`: sign-in page heading "Blog Ops" -> "Flowmerce". `frontend/web/src/styles.css`: first-line comment updated. `frontend/package.json`: name `flowmerce-web` and an accurate description (the UI must be built; `dist/` is git-ignored).
- Roadmap F8 updated.

### Not changed
- `package-lock.json` (its root name is still `blog-ops`); the blog-specific sign-in tagline.

### Validation
- `npm ci --dry-run` exit 0 and lockfile unchanged; `npm run typecheck` exit 0; `npm run build` succeeded and the built assets contain no "Blog Ops"; 23 Python tests and ruff pass. The sign-in page was not re-opened in a browser.

## 2026-10-29 (main dashboard)

### Added
- Shared application shell and Home / Morning Brief page in `frontend/web/src`: `lib/routes.ts`, `lib/home.ts`, `pages/Home.tsx`, `pages/Planned.tsx`, `components/home.tsx`. Home shows module cards for the six projects (real status chips), demonstration-only metrics, approvals, alerts, reports and job activity (all badged "Demo", switchable off to show empty states), and quick navigation. Unbuilt pages and Merchandising Automation (future scope) use a shared "Planned" page with no controls.
- Icons `home`, `library`, `settings`.

### Changed
- `Shell.tsx`: Flowmerce name and tagline "Ecommerce in a Flow"; sidebar generated from the route registry; SEO pages grouped under SEO & Blog Content; date picker and search only on SEO pages; skip-to-content link.
- `App.tsx`: `/` is now Home; the former Overview is at `/seo`; all other SEO addresses unchanged.
- `index.html` title; `styles.css` additions (reuses existing tokens).
- `docs/development/setup.md` (Node and git-ignored `dist` instructions), README, folder structure, system overview, file registry, roadmap (module names and order from the handoff, priorities reconciled).

### Not done
- Backend data for Home (no API, no live integrations, no approvals or jobs); dark theme; sign-in page still says "Blog Ops"; no frontend lint or tests; not checked with real data.

### Validation
- `npm run typecheck` exit 0; `npm run build` succeeded; 23 Python tests, ruff and mypy pass; browser checks on an isolated test instance (all routes, brand switching, phone and tablet widths, keyboard focus). One contrast defect found and fixed (status tag text 2.77:1 to 4.99:1).

## 2026-10-29 (approval policy)

### Added
- `PROJECT_RULES.md` section 11: phase-based file-modification policy. Setup-phase permission has ended; every product-development change now needs the owner's explicit approval. Documentation only.

## 2026-10-29 (product handoff)

### Added
- `docs/product/Flowmerce_Project_Handoff.md`: the owner's product specification, copied unchanged from Downloads (identical per byte comparison). Documentation only.

## 2026-10-29 (module priority)

### Changed
- `docs/development/roadmap.md`: recorded the owner's decision that SEO & Blog Automation is the first module, added a blueprint-vs-code gap table for it, updated the recommended next task. Documentation only.

## 2026-10-29 (rules and roadmap)

### Added
- `PROJECT_RULES.md`: permanent engineering rules, approval requirements, reporting and handover rules (records existing ADR 0001/0002 approvals; decides nothing new).
- `docs/development/roadmap.md`: actual status of every component, open decisions (SQLite vs PostgreSQL, UI framework, module priority) and last check evidence. Documentation only; no code, test, schema, frontend or dependency changes.

### Changed
- `README.md`, `docs/FILE_REGISTRY.md`: links and entries for the two new files.

## 2026-10-29 (GitHub)

### Added
- Remote `origin` = `https://github.com/RidhiBlockPrint/Flowmerce.git`. The remote's placeholder initial commit was merged (our README kept) and `main` pushed as a fast-forward, tracking `origin/main`.

## 2026-10-29 (git)

### Added
- Git repository initialised on branch `main` with one initial commit; `.env`, `data/`, `backups/` and `.venv/` verified as ignored.

## 2026-10-29 (blog-ops removed)

### Removed
- Original `blog-ops/` folder (code duplicated in `src/flowmerce/modules/seo` and `frontend/`). Its `make_zip.py` and local `.venv` were not carried over.

### Changed
- `.env`, `data/` and `backups/` moved from `blog-ops/` to the repository root (verified byte-for-byte; the module opened the database and found 1 user). `.gitignore` and ruff exclusions no longer mention `blog-ops`. README, setup, troubleshooting, system overview, folder structure, registry and ADR 0003 updated.

### Validation
- 23 tests pass after the removal.

## 2026-10-29 (verification)

### Fixed
- `pyproject.toml`: added the legacy `blog-ops/` folder to ruff `extend-exclude`; `ruff check .` previously reported 829 errors, all in that untouched copy. Now passes.

### Fixed (migration completed)
- Copied the missing backend files (`auth`, `config`, `db`, `permissions`, `util`, `cli`, `main`, `services/*`, `integrations/*`) from `blog-ops/backend` into `src/flowmerce/modules/seo/`; `config.ROOT` now resolves to the repository root (override `FLOWMERCE_ROOT`); `cli.py`/`main.py` docstrings point at the new module path.
- Migrated the tests: `blog-ops/tests` -> `tests/unit/seo/test_core.py`, `tests/integration/seo/test_http.py`, fixtures in `tests/fixtures/seo.py` (registered via new `tests/conftest.py`; imports `backend.` -> `flowmerce.modules.seo.`).
- Validation: 23 tests pass, `ruff check .` and strict `mypy` pass, and a smoke test of `startup()` returned 200 for `/` and `/api/docs` with a temporary data dir.

### Found, not fixed
- The entry below lists migrated tests (`tests/unit/seo`, `tests/integration/seo`, `tests/fixtures/seo.py`) and a "23 tests pass" result. Those test files are not on disk; `pytest` collects 8 tests (all foundation tests) and they pass. Original tests remain in `blog-ops/tests/`. Needs a decision on re-migrating them.
- The test `test_python_dash_m_health` requires `pip install -e .` (use a venv); it fails against a bare interpreter.

## 2026-10-29 (later): blog-ops migrated into the new structure

### Architecture
- `blog-ops/backend` copied to `src/flowmerce/modules/seo` (relative imports unchanged); `blog-ops/web` + npm/Vite config copied to `frontend/`; tests split into `tests/unit/seo`, `tests/integration/seo` with shared fixtures in `tests/fixtures/seo.py`.
- Integrations (`shopify`, `google`, `claude`, status) stay inside `modules/seo/integrations` for now: they import the seo module's config and error types, so moving them to the top-level `integrations/` would invert the dependency direction.

### Changed
- `modules/seo/config.py`: `ROOT` is now the repository root (override `FLOWMERCE_ROOT`); `.env` and `data/` are read from there. `modules/seo/app.py` serves `frontend/web/dist`.
- `run.py` -> `scripts/run_seo.py` (installs `.[seo]` from `pyproject.toml`); `run.bat` -> `scripts/run_seo.bat`; `.vscode/` and `.env.example` merged into the root.
- `pyproject.toml`: new `seo` extra (dependencies from `blog-ops/requirements.txt`), pytest import mode and paths, ruff/mypy exclusions for legacy code.

### Not done
- Original `blog-ops/` not removed; `make_zip.py` not migrated; `.env`, `data/` and backups not copied (secrets/data); frontend not rebuilt or type-checked (no Node run); no git repository initialised.

### Validation
- 23 tests pass (15 migrated blog-ops tests + 8 foundation tests) on Python 3.13; the baseline of the original blog-ops was 15/15. Server smoke test: `/` and `/api/docs` return 200 with a temporary data directory.

## 2026-10-29

### Added
- Python engineering foundation: `pyproject.toml`, `src/flowmerce/` package (`config`, `core`, `modules`, `main`), CLI commands `version` and `health`.
- Tests: 4 settings tests, 3 CLI unit tests, 1 process-level integration test.
- Root `.gitignore` and `.env.example`.
- Documentation set under `docs/` (architecture, development, operations, FILE_REGISTRY, ADRs 0001-0003).

### Changed
- Root `README.md` rewritten to describe real status. The previous version (planning-draft status and file table) is preserved verbatim as `docs/architecture/planning-v0.1-readme.md`.

### Architecture
- ADR 0001: Python-first. ADR 0002: owner-approved exceptions (TypeScript/JavaScript for web UI, SQL for schema). ADR 0003 (proposed): migrate `blog-ops` into the new structure.
