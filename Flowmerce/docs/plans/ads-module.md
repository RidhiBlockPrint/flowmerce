# Plan: Ads module (Meta Ads + Google Ads, both brands)

Status: **phase 1 built (2026-11-24); phase 2 built 2026-11-24, waiting for `db/central/115_ads.sql` to be run in Supabase; phase 3 (Google Ads) built 2026-11-27 and live for Ridhi (117_ads_google.sql run the same day); Cotton Print Club's Google Ads account is not reachable by the Google login yet (see Things to fix, 1).** Phase 2 also covers what phase 4 listed (rules, Actions, the gap), because the screens already ask for them.

Phase 1 status: The owner approved phase 1 on 2026-11-24: the `/ads`
screens run on sample numbers in the demo copy (`frontend/src/demo/modules/ads.js`) and say "not connected yet" on live
data until phase 2 is live. Besides the phase 1 files, phase 1 changed only 14 key lines in `Flowmerce/.env`
(owner's request, 2026-11-24). Phase 2's files are listed in `docs/FILE_REGISTRY.md` and the changelog.

Changes made while building phase 1, which phase 2 should keep: the Overview shows no combined ROAS when both platforms
are chosen (each platform's ROAS instead) and adds "ad cost per store order" (all ad spend divided by store orders);
the ABO to CBO gap uses the lifetime rule (spend, ROAS and purchases since the ad started); the "weakest step" limits
in the sample data (hook under 20%, CTR under 2.5%, cart rate under 9%, purchases under 8% of carts) are placeholders
still to be agreed.

Roadmap item: E3 "Meta & Google Ads Performance", code name `ads` (`docs/development/roadmap.md`).

## Why

Today the ad numbers are put together by hand into spreadsheets. Three of them define what the team looks at:

| Sheet (24 Oct 2026, Ridhi, Meta only) | What it holds |
|---|---|
| `Ridhi_Meta_Daily_2026-10-24.xlsx` | Summary by period, Road to $20k, Actions, CBO health, Campaigns, Ad sets, Ads, Creative tests ($110), Winners bench, Daily trend 14D, Funnel, Action history, Rules |
| `Ridhi_Creative_Scorecard_24Oct26.xlsx` | Timeline, per-ad Scorecard with video drop-off, New ads under 7 days, Brief, Actions, Competitor ads, D2C inspiration, Glossary |
| `ABO-to-CBO-gap-24-Oct-2026.xlsx` | Proven ads in the testing (ABO) campaigns that are missing from the scaling (CBO) campaigns |

The module shows the same information, comparisons and filters as a live page, for both brands and for Google Ads
as well, so nobody has to rebuild the sheets.

## Decisions already made by the owner (24 Nov 2026)

1. Data comes live from the **Meta Ads API and the Google Ads API, for both brands**. No sheet uploads.
2. Meta and Google live in **one Ads module** with a platform switch, not two modules.
3. Cotton Print Club's Meta ad account is **"Vishwa Brands"**.

## What the accounts return today (read-only check, 2026-11-24)

Run from this computer with the keys in `.env`. Only read requests were made. No tokens were shown or stored
anywhere else.

| Account | Name on the platform | Currency | Account time zone | Result |
|---|---|---|---|---|
| Ridhi Meta | Ridhi Shopify Current | INR | India | Reads. 82 campaigns (13 active), 326 ad sets (81 active), 647 ads (162 active) |
| CPC Meta | Vishwa Brands | USD | Chicago | Reads. 38 campaigns (10 active), 309 ad sets (57 active), 976 ads (126 active) |
| Ridhi Google Ads | RIdhi Block Print, 135-111-7947 | USD | India | Reads. Mostly Performance Max, one brand Search campaign, two Display campaigns; Shopping paused or removed |
| CPC Google Ads | not filled in | n/a | n/a | **Not checked.** The Google login reaches four accounts and none is named Cotton Print Club |

Last 7 days (17 to 23 Nov 2026): Ridhi Meta Rs 1,954,464 spend, 320 purchases, ROAS 1.72. CPC Meta $9,806 spend,
139 purchases, ROAS 1.25. Ridhi Google $855 spend, 54 purchases worth $7,257.

**The API reproduces the sheet.** Re-reading 17 to 23 Oct 2026 for Ridhi Meta gave: spend Rs 1,982,438 ($20,868 at
Rs 95, sheet $20,866), impressions 415,775 (sheet 415,753), outbound clicks 14,393, purchases 297, landing page
views 14,665, ROAS 1.67, add to cart 1,824 and checkouts started 591. Purchases, clicks, page views, carts and
checkouts are identical to the sheet; spend and impressions differ by about 0.01%.

Available from **Meta**: campaigns, ad sets and ads with status and budgets; the attribution setting (7-day click,
1-day view); creative thumbnail, text and video id; daily and per-ad figures; video drop-off at 25/50/75/95/100%,
ThruPlays and average watch time; **3-second video views** (the Scorecard says Meta gives none; it does); split by
placement; the account's change history; history back to October 2023.

Available from **Google Ads**: daily totals; campaigns with type, budget and bid strategy; ad groups; ads;
Performance Max asset groups; keywords; search terms; per-product figures; conversion actions; change history;
history back to at least February 2023.

Not available with the present access: Meta business-level details (needs the `business_management` permission).
The dashboard does not need them.

## Version 1 scope

**In:** one page `/ads` ("Ads" in the sidebar) with brand and platform switches and the tabs below. **Read-only:**
version 1 never changes a budget, a status or anything else in Meta or Google.

**Out (later, each needs its own approval):** the written Brief, Competitor ads and D2C inspiration tabs and the
written "Improvement" advice (these are judgement, not data: Creative Strategist module or a Claude step); alerts
by Slack or email; any action that changes an ad account.

### Switches and tabs

Brand: Ridhi / Cotton Print Club (the page's own switch when the top bar says "All", as on CRO).
Platform: All / Meta / Google. A tab that belongs to one platform is hidden when the other is selected.

| Tab | Platform | What it shows | Replaces |
|---|---|---|---|
| Overview | All, Meta, Google | Spend, Shopify sales, MER, platform ROAS, purchases, orders, AOV, CPA for the chosen period and its comparison; the scaling gate (red / amber / green) with the recommended daily spend; daily trend with each day coloured; progress to the daily sales goal ("Road to $20k"); Meta and Google side by side | Daily: Summary, Road to $20k, Daily trend. Scorecard: Timeline |
| Campaigns | All, Meta, Google | Meta: campaign, then ad set, then ad, with CBO health (delivering ads, top-ad share of spend, budget call). Google: campaign, then ad group or asset group, split by Search / Performance Max / Display / Shopping, brand campaigns marked | Daily: Campaigns, Ad sets, Ads, CBO health |
| Creatives | Meta | Every ad with its verdict, 7-day / 3-day / 14-day / lifetime ROAS, CTR, add-to-cart rate, hook rate and video drop-off; new ads under 7 days with the weakest step; the $110 tests; the winners bench | Scorecard: Scorecard, New ads. Daily: Creative tests, Winners bench |
| Search terms | Google | Keywords, search terms and products with spend, clicks, purchases and value | new |
| Funnel | Meta (full), Google (short) | Impression, click, landing page view, add to cart, checkout started, purchase, each step against the comparison period; Shopify sessions and store conversion rate beside it | Daily: Funnel |
| ABO to CBO gap | Meta | Test-campaign ads that pass the "proven" rule and are not in the matching scaling campaign: Add / Watch / Already in / Stop / Too early | Gap file |
| Actions | All, Meta, Google | Rule-based suggestions (Stop, Refresh, Budget up or down, Iterate) with the figures behind each and the daily budget effect; a status the team sets (open / done / skipped); history | Daily: Actions, Action history |
| Rules | All | Every threshold, target and the rupee rate in one editable place, per brand; the glossary | Daily: Rules. Scorecard: Glossary |

### Filters

Date range with quick picks (Yesterday, Last 3 / 7 / 14 / 28 / 30 days, Month to date, custom) kept in the page
address; campaign; campaign type (Meta: CBO / ABO / catalog / retargeting. Google: Search / Performance Max /
Display / Shopping); product line; status (active / paused / ad set paused); verdict; video or image; minimum
spend; search by ad name, CR code or ad ID.

Product line (quilt, rectangle tablecloth, round, stripe, ...) is read from campaign and ad names. The two brands
name ads differently (Ridhi "CR291 | ...", CPC "Q32 | ...", "TC4 | ..."), so the mapping is a small editable list
per brand, not fixed in code.

### Comparisons

This period against the previous one of the same length; 3-day against 7-day ROAS (direction); lifetime against
the last 7 days (fatigue); Meta against Google; platform-reported sales against Shopify sales; figures with and
without bulk orders; each ad against the account average.

## How each figure is worked out

| Figure | Rule |
|---|---|
| Meta spend, impressions, purchases, purchase value, ROAS | As Meta reports them, 7-day click and 1-day view. Purchases = the `purchase` action |
| Meta add to cart, checkouts started | Meta's combined website + in-app counts (`omni_add_to_cart`, `omni_initiated_checkout`). These are the ones that match the sheets |
| Meta CTR | Outbound clicks divided by impressions (the Scorecard's definition). The Daily sheet uses link clicks; one definition is used everywhere |
| Hook rate | 3-second video views divided by impressions. The old proxy (watched 25%) stays as a second column so old and new numbers can be compared |
| Google spend | Cost as Google reports it |
| Google purchases and value | **Only the purchase conversion action.** Google's own "conversions" total also counts a click action ("Ridhi Shopify (web) click": 17 of 71 in the week checked) |
| Brand search | Shown separately. In the week checked, $5,683 of Ridhi's $7,274 Google conversion value came from the brand Search campaign on $100 of spend, so one blended Google ROAS misleads |
| Shopify sales, orders, AOV | From the store, not from the ad platforms. Planned source: the order copy CRO already keeps in Supabase (`cro.orders`). Which money field equals the sheet's "total sales" is **to be verified at build** |
| MER | Shopify sales divided by **total** ad spend (Meta + Google). The sheets divide by Meta spend only, so the module's MER will be lower than the sheet's |
| Platform sales | Never added together. Meta and Google can both claim the same order; the total is always Shopify's |
| Money | Each account's own currency is stored. Reporting is in US dollars. Only Ridhi Meta is in rupees |
| Days | Each platform's day is that account's own day (Ridhi Meta and Ridhi Google: India. CPC Meta: Chicago). Shopify's day is the store's. The page says so wherever a day's MER is shown |

### Rules (starting point: the Daily sheet's Rules tab)

- **Scaling gate:** green when 3-day MER is at least 2.2 and 7-day at least 2.0 (raise spend up to 20% over 72 hours);
  amber 1.8 to 2.2 (hold, move budget); red below 1.8 (cut 10 to 20%).
- **CBO budget:** raise 10 to 20% when 7-day ROAS is at least 2.2 and 3-day at least 1.8; lower 10 to 20% when 7-day
  is under 1.6 or 3-day under 1.4; otherwise hold; hold when the budget changed in the last 72 hours.
- **$110 test:** under $110 spent = in test; no purchase at $110 = stop; one or more = continue to $220; at $220:
  ROAS under 1.5 stop, at least 2.2 with 3 or more purchases graduate, otherwise iterate.
- **Proven ads ($220 or more lifetime):** scale when 7-day ROAS is at least 2.2 with 5 or more purchases, 3-day at
  least 1.8 and steady frequency; stop when 7-day ROAS is under 1.5 on $110 or more of 7-day spend; iterate between 1.5 and 2.2.
- **Campaign policy:** never suggest pausing a campaign; each CBO keeps 4 to 8 delivering ads.
- **Targets:** Meta ROAS 2.2 or more; MER 2.5 or more (floor 2.2 while scaling).

Every number above is a setting on the Rules tab, per brand. No Google rules exist yet (see open decisions).

## Open decisions (the default applies until the owner says otherwise)

| # | Decision | Proposed default |
|---|---|---|
| 1 | Rupee rate for Ridhi Meta. The sheets disagree: Rs 88 (Daily) and Rs 95 (Scorecard), an 8% difference in MER, CPA and the $110 line | One rate the owner sets on the Rules tab, saved with its start date so past figures do not change when it is updated |
| 2 | Which thresholds are official. The three sheets use ROAS 2.2, 2.5 and 2.0 for "good" | The Daily sheet's Rules tab (above). The Scorecard and Gap labels are mapped onto it so an ad never has two verdicts |
| 3 | Bulk orders. The $8,907 left out on 23 Oct was a manual call | Orders above an amount set on the Rules tab are left out of the "excl. bulk" figures |
| 4 | Cotton Print Club's targets and goal | Start with Ridhi's rule set; its own targets and daily sales goal editable |
| 5 | Google rules and screens. No Google sheet exists | Standard screens as listed above; no automatic Google suggestions until rules are agreed |
| 6 | How much history to load first | 90 days of daily figures per ad, plus each ad's lifetime totals |
| 7 | Screens first or live first | Screens first with sample numbers, so the look is approved before the data work |

## Things to fix or confirm (owner)

1. **Cotton Print Club's Google Ads customer ID** is blank in `.env`, and the Google login may need to be given
   access to that account.
2. **The Meta tokens expire on 20 January 2027.** They are personal login tokens (apps "ERP token" and "ERP Token
   (CPC)") and need renewing about every 60 days. A system-user token from Business Manager does not expire. The
   module will show the days left and warn before expiry.
3. **Ridhi's Meta account reports status code 9**, not the normal 1. Ads are delivering. Check Billing in Ads
   Manager.
4. **Google answered with the developer-token line left blank.** That was not expected; what daily limit applies
   is unknown and must be checked before relying on it.
5. **The "Ads" tab of the Meta Daily sheet is damaged** and could not be read. Not needed for the build (the API
   gives the same data); re-export it only if it holds columns not listed in this plan.
6. **Hosted copy:** the same keys must be added to Render's Environment page before the module works there
   (`docs/operations/hosting-render.md`).

## How it would be built

Same shape as the CRO module. Keys stay in `.env` (and Render's environment), are never stored in Supabase and
never sent to the browser. No personal data is involved: ad accounts hold none, and no customer fields are read.

- **Storage:** a new schema `ads` in the central Supabase database. The page reads from Supabase, never from Meta or
  Google directly, so it stays fast and the hosted copy (512 MB) needs no large in-memory caches.
- **Sync:** a background job reads each account. Proposed: today and yesterday every hour; the last 28 days again
  once a night, because both platforms keep revising recent days as late purchases are attributed.
- **Volume:** about 290 active ads across both Meta accounts, so a few hundred rows a day.
- **No new packages:** both APIs were read with `httpx`, which the project already uses.
- **API versions pinned in settings:** Meta Graph API v27.0 (calls without a version are refused), Google Ads API
  v26.

### Phases and files

Each phase is approved separately. File names follow the existing modules and may be adjusted when the phase is
presented for approval.

**Phase 1: screens with sample numbers (frontend only).**

| File | Change | Why |
|---|---|---|
| `frontend/src/app/ads/page.jsx` | new | the `/ads` route |
| `frontend/src/views/Ads.jsx` | new | the page: switches, tabs, filters |
| `frontend/src/components/ads.jsx` | new | tiles, tables, verdict pills, drop-off bars |
| `frontend/src/lib/ads.js` | new | tab list, formats, filter helpers |
| `frontend/src/demo/modules/ads.js` | new | sample data in the shape the API will return, taken from the sheets |
| `frontend/src/demo/index.js`, `frontend/src/lib/routes.mjs` | edit | register the sample data; add "Ads" to the sidebar |
| `frontend/tests/demo-ads.test.mjs`, `frontend/tests/routes.test.mjs` | new / edit | tests |
| `docs/FILE_REGISTRY.md`, `CHANGELOG.md`, `docs/development/roadmap.md` | edit | documentation |

**Phase 2: database and Meta, both brands.**

| File | Change | Why |
|---|---|---|
| `db/central/115_ads.sql` (+ rollback file, `db/central/README.md`) | new / edit | schema `ads`: accounts, campaigns, ad sets, ads, daily figures, rupee rates, rules, action status, sync state. The owner runs it in Supabase |
| `src/flowmerce/modules/ads/__init__.py`, `config.py` | new | module description; account and key settings per brand |
| `src/flowmerce/modules/ads/meta.py` | new | read-only Meta client |
| `src/flowmerce/modules/ads/data.py`, `sync.py`, `scheduler.py` | new | Supabase reads and writes; the sync; the background job |
| `src/flowmerce/modules/ads/metrics.py`, `service.py`, `api.py` | new | formulas (pure); page answers; `/api/ads/*` routes |
| `src/flowmerce/modules/seo/app.py` | edit | mount the routes and start the job, as done for CRO |
| `tests/unit/ads/` | new | unit tests (no network, no real keys) |
| `docs/development/setup.md`, `docs/operations/hosting-render.md`, `docs/architecture/system-overview.md`, `docs/architecture/folder-structure.md`, a new ADR in `docs/decisions/`, registry, changelog, roadmap | edit / new | documentation |

**Phase 3: Google Ads.** `src/flowmerce/modules/ads/google_ads.py` (new, read-only client), additions to `sync.py`,
`service.py`, `api.py`, the Search terms tab and the combined Overview, tests and documentation.

**Phase 4: rules, Actions and the gap tab.** `src/flowmerce/modules/ads/rules.py` and `gap.py` (new, pure), the
Actions, ABO to CBO gap and Rules tabs, tests and documentation.

**Later:** Claude-written advice and briefs, competitor ads, alerts, and (only with separate approval and wider
token permissions) actions that change an ad account.

## Risks

- **Token expiry** stops the Meta sync on 20 January 2027 unless renewed or replaced (see above).
- **Platform numbers move.** A day's purchases keep changing for up to a week or more; the nightly re-read covers
  this, and the page shows when each account was last read.
- **API versions retire.** Meta and Google each withdraw old versions; the pinned versions need updating a few
  times a year.
- **Ad names carry meaning** (CR code, product, date). Ridhi reuses CR codes across products, so ads are always
  matched by ad ID and post ID, never by CR code alone.
- **Shared database limits.** The central Supabase project's plan limits apply to the new tables as well.

## What was and was not verified

Verified on 2026-11-24 with real read-only requests: both Meta accounts and Ridhi's Google Ads account answer; the
fields listed under "What the accounts return today"; the 17 to 23 Oct figures against the sheet; token type and
expiry; that the app still loads its settings after the `.env` change.

Not verified: Cotton Print Club's Google Ads account; Google's request limits without a developer token; how
Shopify sales in `cro.orders` compare with the sheet's Shopify figures; behaviour on the hosted copy; anything
about the screens, database tables or sync, which do not exist yet.
