# Changelog

Format: newest first. Types: Added, Changed, Fixed, Removed, Architecture.

## 2026-11-27 (Home: the CEO dashboard, layout "A · Bento"; one colour theme for every dashboard)

Owner requests 2026-11-27: Home showed only sales; it should show what is going on in the business for the CEO, with
the Meta and Google Ads figures of both brands; no headline sentence and no recommendations; one dashboard that adds
both brands on All and shows one brand on Ridhi or CPC; the CRO Overview's colours on every dashboard; and, after a
first version copied the CRO Overview too closely, three researched layouts to choose from
(`design-mockups/home-ceo/`: A Bento, B Briefing, C Chart first). The owner chose **A · Bento**. Verified on demo data
only: frontend tests 131 passed (4 Home tests), CRO and Ads unit tests 242 passed (14 new), ruff and mypy --strict
clean on the changed Python, production build passes, and in the browser (All, Ridhi and CPC on every period).
**Not yet seen with live data.** Creative Strategist has no demo data, so its new colours were not seen.

- **Changed** Home is the Bento dashboard, the same for All, Ridhi and CPC, with a period switch (Today, Yesterday,
  7 days, 30 days, Month to date) against the period before: a large Sales tile (total sales, the days drawn against
  the days before, net / returns / discounts), Orders, Average order, Conversion (on the last 28 days' usual band) and
  Visits tiles, a wide Ads tile (ad spend and its Meta / Google split, sales per $1 of ads on the cut back / hold /
  grow zones with the target, ad cost per order), the brands' share of sales (one brand: Meta's and Google's share of
  the ad spend), the month's goal and pace, and a row of operations figures (delivery problems, on time, decisions
  waiting, data freshness). Figures only; the to-do list, content pipeline, blog clicks, brand report and automation
  runs stay under "Show more".
- **Added** `GET /api/cro/home-period?brand=&period=` (`cro/company.py`): one store's CRO figures for the period, or
  both stores added together: orders, sales, visits, checkouts and monthly goals are added; conversion, average order
  and revenue per visit are worked out again from the sums (never averaged); too-early is judged on the totals; only
  days both stores have reached are shown. Also the sales chart (at least 14 days, with the days before), the daily
  figures, each brand's share of sales and the month's goal. Demo answer too; the demo stores have sample monthly goals
  (demo data version 6).
- **Added** `GET /api/ads/company` also returns `platforms`: each platform's spend over both brands and its share (spend
  can be added; what a platform claims as sales, and its ROAS, stays per brand). Demo answer too.
- **Changed** One colour theme for every dashboard, taken from the CRO Overview (`--theme-*` in `globals.css`): sage
  green good, amber usual, salmon below usual (with stronger steps for thin lines), navy for the figure in focus and its
  light blue for the rest. Moved onto it: the Ads Overview (spend call stripes and dot, cut back / hold / grow meter,
  goal ring and bars, charts and sparklines, funnel and drop-off bars), SEO & Blog's ring and meters, Creative
  Strategist's tiles and charts, Shipping's age-band ring, and Home. Text keeps the darker green / brown / red inks.
  Still to do: three small charts inside `views/Shipping.jsx` (on-time bar, delivery-time and delivered bars), held
  back while the FedEx work in that file is not committed.

## 2026-11-27 (Ads: "All" in the top bar shows both brands together)

Owner report 2026-11-27 (screen recording): on the Ads page "All" and "Ridhi" showed the same figures, because Ads
showed one brand at a time and quietly fell back to Ridhi. Owner decision: both brands combined. Verified: Ads tests 85
passed, demo tests (Ads 19), frontend tests 127 passed, and in the browser on demo and real data (20 to 26 Nov: company
ad spend $30,842 = Ridhi $22,461 + CPC $8,381, store sales $54,011, company MER 1.75 against 2.05 the week before).

- **Added** The company view on the Ads Overview (top bar on All, page switch "Both", the default there): company ad
  spend (Meta and Google, both brands), both stores' sales, company MER and ad cost per order with their change and
  trend; one card per brand with its own spend call, spend, sales, MER, share of company spend, Meta / Google split and
  daily goal, and "Open" to go to that brand; the days, with each brand's MER. `GET /api/ads/company` (and the demo).
- **Changed** Only spend, store sales and orders are added across brands; platform-claimed sales, ROAS, rules and goals
  stay per brand. Campaigns, Creatives, Funnel, Actions and the other tabs stay one brand at a time (Ridhi / CPC).

## 2026-11-27 (Ads phase 3: Google Ads next to Meta)

Owner request 2026-11-27: start phase 3 (Google Ads). Read-only checks of the Google login on 27 Nov: it reaches Ridhi's
account (135-111-7947, USD, India time) without a developer token, a second unused "Ridhi Block Print" account, a manager
account with no accounts under it, and one closed account; **no Cotton Print Club account**. Ridhi, 20 to 26 Nov: $854.43
spent, 56.8 purchases worth $7,105.64; the new client reproduces those figures exactly. Verified: Ads tests 83 passed
(25 new, no network), ruff and mypy clean on Ads, frontend tests 126 passed, a production build. Verified on
real data after the owner ran `db/central/117_ads_google.sql`: the first Ridhi read (30 Aug to 27 Nov, 7,465 rows,
49 s) stores $854.44 / 56.8 purchases / $7,105.64 for 20 to 26 Nov, and the Overview, Campaigns and Search terms tabs
show it (86% of Google's claimed sales came from brand search, on $104 of $854).

- **Added** `modules/ads/google_ads.py`: a read-only Google Ads API client (v26, REST): account, campaigns, and daily
  figures per campaign, ad or asset group, search term, keyword and product. Purchases are Google's primary purchase
  conversions; the "Ridhi Shopify (web) click" action (filed as a purchase, worth $1) and the secondary web purchase tag
  (the same orders again) are left out.
- **Added** `modules/ads/google_sync.py` and `db/central/117_ads_google.sql` (`ads.g_campaigns`, `ads.g_daily`, functions
  g_replace, g_days, g_sum): the hourly job reads each brand's Google account after its Meta account, 90 days on the
  first run, 28 days nightly, 3 days otherwise.
- **Changed** Overview: "All" adds Google spend to Meta's; MER, cost per order, the goal's spend and the spend call use
  both. Meta and Google each keep their own ROAS (claimed sales are never added together). The spend call waits until
  both accounts are read to the range's end.
- **Changed** Campaigns, Funnel and Search terms show Google: campaign type (Performance Max, Search, Display, ...), brand
  search marked, ad groups and asset groups under each campaign; Google's impressions, clicks and purchases; keywords,
  search terms and products with the share of Google's sales that came from brand search.
- **Changed** A brand without a Google account says so calmly (which `.env` line is missing, or that the first read has not
  finished) instead of a red "could not load" box. "All" still works with Meta only.
- **Fixed** The background job brought the next round forward (5 minutes) after any failure, re-reading every account;
  failures that waiting does not fix (no access, closed account, refused sign-in) now wait for the normal round, and
  missing Google tables are a calm "waiting", so Meta's hourly allowance is not spent on retries.

## 2026-11-25 (Creative Strategist: Claude writes the creative)

Owner request 2026-11-25, from a product spec the owner shared (purpose, what it monitors, main outputs). Read against
the repository's own handoff (section 3.4) first: the spec is more concrete than the handoff and adds product context,
UGC scripts, carousels, Reels and Stories, and fresh variations from winning concepts. This change covers the output
half. Verified: the Python suite (876 tests, 24 new, all passing), ruff on every new file, `mypy --strict` with no
error in either new module, the route tests through the real application, and **three calls to the live Claude API**
with the owner's approval (two billed, $0.65 in total on a $3.00 daily limit). The third produced four concepts across
the funnel, every field filled, a 63-word summary and a 31-word caveat, with the brand guide's own forbidden claims
("thread count", "women artisans", "exotic, ethnic or tribal") appearing in each concept's do-not-say list and the
offer stated only on the bottom-of-funnel concept, citing the published store policy. **Not verified:** the live read
path from a real ad account, since the figures Claude saw were the samples.

- **Added** `modules/creative/prompts.py`: the two asks and their JSON schemas. A **creative pack** gives 3-5 concepts,
  each with a hook, two or three alternative hooks, the angle and the figures behind it, a static ad, a 3-5 frame
  carousel, a 15-30 second Reel shot list, a UGC creator brief with the claims it must not make, and a one-variable
  test. **Variations** rework one concept that already performs, changing a single variable.
- **Added** `modules/creative/generate.py`: the call itself, in a background thread like CRO's action plan, with the
  answer cleaned before it is stored (an unknown enum, a wrong type or a missing object becomes a safe default, never
  invented text) and one pack kept per store in `app_settings`.
- **Fixed** The output schema asked for content that structured outputs cannot enforce. The first live call obeyed
  the schema and still returned one concept with an empty Reel shot list, no UGC talking points and no test variants,
  because `required` is satisfied by an empty array; adding `minItems: 3` then had the second call refused outright
  ("For 'array' type, 'minItems' values other than 0 or 1 are not supported"). Structured outputs accept `minItems` of
  0 or 1 and no `maxItems` at all, so every array now carries `minItems: 1` (which does force content), the counts are
  stated as hard rules in the prompt, and the ceilings are applied in `clean_pack`. A test walks both schemas and
  fails on any array constraint the API would refuse, so this costs no further round trips to discover.
- **Added** Routes `GET /api/creative/pack` (reads, never spends), `POST /api/creative/pack` (asks Claude in the
  background) and `POST /api/creative/variations` (answers in the request, stores nothing). Both writes are audited.
- **Added** `ai_budget.ESTIMATE_USD` entries `creative_pack` (0.60) and `creative_variations` (0.20), so the existing
  daily Claude limit refuses a request that does not fit before anything is sent.
- **Changed** Only a brand's voice and claims files are sent to Claude, capped at 30,000 characters. Ridhi's full
  knowledge set is about 195,000 characters; the master brief and the AEO playbook say little about ad copy and would
  cost more per call than the answer is worth.
- **Fixed** The samples broke the brand guide, which the first live call flagged: "Flat 50% off" exceeds the guide's
  "up to 40% off", "free shipping over 1999" contradicts free standard shipping on all orders, the copy was in Hindi
  for a brand whose guide sets US customers aged 35-70, and the figures were in rupees for stores that sell in USD.
  All four are corrected. In dollars a $1,000 spend floor is a real bar for a brand of this size, so several sample
  groups are now honestly marked "too early to judge" instead of all being judged.
- **Fixed** The sample figures and concepts now talk about tablecloths and pillow covers. Read from Shopify on
  2026-11-25: Ridhi has 1,045 products (196 tablecloths, 88 pillow covers, placemats, napkins, runners) and Cotton
  Print Club 493. The samples written earlier that day were about clothing, which made the page look like it belonged
  to another shop.
- **Architecture** The spec's "product, print, color, category and season" is **not built**, because the data is not
  there to build it on. Read-only from Shopify on 2026-11-25: `productType` is empty on 569 of Ridhi's 1,045 products
  and 361 of CPC's 493, and is inconsistently cased where it is set ("quilt" beside "Pillow Cover"); colour and print
  appear only inside the product title, where the most common opening words are "Block", "Hand", "Cotton" and
  "Ruffle", so a first-word rule would not find a colour; the only variant option is Size; and season is recorded
  nowhere, since tags such as "Thanksgiving Table Cover" sit on 58 of any 60 products and so carry no information.
  Season would have to be derived from sales history instead. Left with the owner: whether the team will fill in
  category and colour in Shopify, or whether Flowmerce should guess from the title and label the guess as one.
- **Architecture** No AI output is written to Supabase. A pack lives in the local `app_settings` table like CRO's
  plan; saving a concept to `creative.concept` waits until `116_creative.sql` has actually been run.

## 2026-11-25 (Ads and Creative Strategist: read-only foundation, demo mode)

Owner request 2026-11-25: build the AI-powered marketing intelligence tool, starting with what can be done before the
manager hands over the Meta and Google Ads credentials. Read-only throughout: nothing in this change creates, pauses
or alters an ad, a budget or a campaign, and the Meta write scope (`ads_management`) is deliberately not asked for.
Verified: the Python suite (852 tests, 63 new, all passing), ruff on every new file, `mypy --strict` with no error in
either new module, the eight route tests that drive the real application, and the local app itself: the API was started on 127.0.0.1 and every new route answered 200 with demo figures, checked from the terminal and from /api/docs in a browser. **Not verified:** nothing has been run
against a live Meta or Google Ads account, and neither new SQL file has been run in Supabase, so the live read path
is written but untested. The pre-existing `mypy` findings in `modules/shipping/` and the project-wide ruff findings
in legacy files are unchanged.

- **Added** `db/central/115_ads.sql`: schema `ads` with `ad_account`, `campaign`, `ad_group`, `ad` (keeping the ad's
  own headline and body, which Creative Strategist reads), `daily_metric` (one row per day per entity, with the
  platform's own purchase figures), `sync_state`, the `begin_sync`/`end_sync` lock pair modelled on CRO's, and the
  `v_ad_daily` view. RLS on with no policies, service_role only, like 080 and 112.
- **Added** `db/central/116_creative.sql`: schema `creative` with `insight`, `concept`, `brief` and `test`, plus
  `delete_concept` and `delete_test`. A brief cannot leave draft without a recorded approver, and a test cannot be
  concluded without a learning, because the loop depends on that learning.
- **Added** `src/flowmerce/modules/ads/`: credentials read per store from `.env`, a Meta Marketing API client (pinned
  Graph version, cursor paging, insights with `time_increment=1`, purchases read as `omni_purchase` falling back to
  `purchase`, and the `x-fb-ads-insights-throttle` header read so a sync can slow down), a Google Ads REST client
  (refresh-token exchange with an in-memory access token, `googleAds:searchStream`, `listAccessibleCustomers`, GAQL
  reads, micros converted to currency), a connection status that calls no platform, and a per-platform spend and
  performance summary. Routes `/api/ads/status` and `/api/ads/summary`.
- **Added** `src/flowmerce/modules/creative/`: grouping of ad-level figures by creative format, by hook (the first six
  words of the ad's copy, normalised so the same opening groups together) and by platform, with CTR, ROAS, CPA, hook
  rate and hold rate, and a best/worst/median comparison that ignores groups with too little data. Briefs are written
  by rule for now, not by a model. Routes `/api/creative/insights`, `/concepts` and `/concepts/{id}/brief`.
- **Added** `scripts/ads_check_access.py`: a read-only check to run once the credentials arrive. It lists what is
  missing, which accounts the credentials can see, and the recent spend. It prints no token, secret or URL.
- **Fixed** Hook rate is left empty for a group with no video views at all (an image or a search ad)
  instead of being reported as 0%. Found by running the local app on 2026-11-25: a flat 0% put still
  images into the "best and worst video opening" comparison, where they came last by definition. A
  hook-rate comparison now weighs only the formats that actually have video.
- **Added** Demo mode for both modules: while no ad account is connected, every answer is built from fixed sample
  figures and carries `"source": "demo"`, so the pages can be built and reviewed first. `DEMO_MODE=true` forces it on
  and `ADS_DEMO=false` cannot defeat it.
- **Changed** `modules/seo/app.py` mounts the two new routers the way Shipping and CRO are mounted: if either module
  fails to import, the others still start. Because that makes a broken module silent, the route tests drive the real
  application to prove both are actually mounted.
- **Changed** `pyproject.toml`: ruff's test-only ignores now include `S105`/`S106`, since the API client tests hand
  the clients obviously fake tokens ("test-token", "client-secret"); a real credential in a test would be the bug.
- **Architecture** Google Ads developer tokens were sunset on 2026-09-09 and API access now follows the Google Cloud
  project that issued the OAuth credentials. The header is accepted but ignored today and Google says it will be
  rejected in a future major version, so the client never sends one. What matters instead is the project's access
  level: at Test level a production account cannot be read at all, and the API answers
  `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`. This replaces the developer-token plan in
  `docs/02-connectors-and-apis.md` section 3.2 and is the open roadmap item B7 ("Google Ads developer token level")
  in a new form: the question is now which access level the Cloud project holds.
- **Architecture** Both ad APIs are called over REST with `httpx`, already a project dependency. Google's official
  `google-ads` package would be a new dependency, which the project rules require the owner to approve first.
## 2026-11-24 (Ads pages about twice as fast; repeat visits instant; Home asks for sales once)

Owner request 2026-11-24: test the loading speed of every page, newly built ones especially, then speed up Ads. Measured
on a production build with real data: every page outside Ads was ready in 0.2-1.5 s; the Ads tabs took 1.5-4.7 s
because each answer made 2-10 Supabase round trips one after another, at 0.3-0.9 s each. Verified: Python suite (872
passed, 3 new Ads tests), ruff and mypy clean on Ads, frontend tests (121 passed), Ads answers timed against the real
database, and Home in the browser (production build).

- **Changed** Ads answers are kept 5 minutes (at most 24, a few MB; `ads/data.py answer`), cleared by every change (rules,
  rupee rate, marked suggestions) and every Meta read: repeat visits went from 0.7-2.8 s to instant.
- **Changed** Ads reads that do not depend on each other go out at the same time (account and rules; Meta days, store
  days, newest saved day and rate; the campaign, ad set and ad lists; ads and marks), and the account, rules, rupee
  rate and newest saved day are kept 5 minutes. First visit after a Meta read: Overview tab 4.7 s to 2.2 s (Ridhi) and
  3.0 s to 1.5 s (CPC), its figures in about 0.8 s; other tabs 0.4-1.3 s (were 1.5-2.5 s).
- **Fixed** Home asked `/api/cro/home` twice: the sales card was built in a different place while Home loaded, so it was
  built again (and fetched again) when Home arrived. It now keeps its place; Home is ready in 0.2-0.4 s (was 1.3 s).

## 2026-11-24 (Ads: the Overview redesigned for directors and heads of department)

Owner request 2026-11-24: drop the small lines under the figures, make the change and "was" values readable at a glance,
make the page less plain (like the CRO Overview), make the $20,000 goal editable and eye-catching, explain the scaling
gate, and lead with what helps plan today's work. Verified: Ads Python tests (58 passed), ruff and mypy clean, frontend
tests (121 passed), and in the browser on demo data (1440 wide and tablet, no sideways scroll, no console errors, the goal
edited and saved) and on real data from the local backend (Ridhi).

- **Changed** The Overview opens with "Today's plan": the spend call in plain words ("Cut ad spend by about 15%", "Keep
  total spend steady", "Room to spend up to 20% more"), today's daily spend against the suggested one, a meter of store
  sales per $1 of ads with the 3-day and 7-day figures on the cut back / hold / grow zones, and the top 4 open suggestions
  from the Actions tab. It replaces the "scaling gate" panel (`components/adsOverview.jsx`, new).
- **Changed** Four headline figures (ad spend, store sales, MER, Meta ROAS) in large type with a coloured change chip, the
  earlier value in bold and a 14-day sparkline; four smaller ones under them. Definitions moved into the (i) tooltips.
- **Changed** The daily sales goal is an animated ring and bar, edited in place ("Change goal", saved to the Rules), with
  what is still missing, the spend now, the spend the goal needs, and the last 7 days as columns against the goal line.
- **Changed** The last 14 days use the CRO day tiles (sales, MER, coloured bar; click a day to open it).
- **Fixed** A missing MER (Meta days not saved yet) no longer reads as "cut back": the gate says "No spend call yet"
  (`state: "unknown"`) when either figure is missing or the last days' ad spend is not all saved. `GET /api/ads/overview`
  also returns `meta_saved_to`, and the plan says so when Meta's figures stop before the range ends.
- **Removed** `GatePanel`, `DayStrip` and `GoalBar` from `components/ads.jsx` (replaced by the above).

## 2026-11-24 (Calendars: any month and year, scrolling between months; the overview's calendar is interactive)

Owner request 2026-11-24: the calendar should move to any month and year, show that month's events and let you schedule
there, like a full calendar; the SEO & Blog overview's calendar should be interactive, not static. Verified: the Python
suite (869 passed, with 2 new API tests), the frontend tests (121 passed), a production build, and in the browser (demo,
1920 x 945): the month picker jumps to March next year with its events, one scroll over the month moves exactly one
month without scrolling the page, and clicking a day on the overview shows its blogs with Open and Cancel.

- **Added** Month navigation on both calendars (`components/calendar.jsx`): arrows, the month name as a button that opens
  a year with its twelve months (any year), Today, PageUp / PageDown, and the mouse wheel or trackpad over the calendar
  (one month per scroll).
- **Changed** The overview's blog calendar is interactive: any month, click a day to see its events and blogs beside the
  month (status, message, quality, Open article, Cancel / Stop), and "Blog on a day" / "Blog on this day" open the same
  form as the Content calendar.
- **Changed** `GET /api/calendar` also returns the blog slots in its range (`slots`) and `today`, so a far month shows
  the blogs put on it. The Content calendar reads them from there.
- **Added** The demo answers `GET /api/calendar` (built-in events for any year, the demo's blogs and tasks), so the
  Content calendar and the overview's calendar work in the demo too.

## 2026-11-24 (Every module: no tab strips on pages; a stronger sidebar)

Owner request 2026-11-24: remove the tab bar under each module's title (the left sidebar already has those pages), and
make the sidebar show the modules as important. Verified: the frontend tests (120 passed, with new ones for the menu),
a production build, and in the browser (demo): CRO, Ads, Shipping, Topics / Keywords and the SEO & traffic pages, with no
console errors. The Ads session (editing Ads.jsx, Cro.jsx and globals.css at the same time) agreed the edits first.

- **Removed** The tab strips on Shipping, Conversion (CRO), Ads, Topics & keywords and SEO & traffic. The sidebar is the
  way between them; each page's title now names the tab on screen, under the module's name (`lib/routes.mjs tabLabel`).
  The article editor keeps its Edit / Preview / Review / Publishing tabs (they belong to one article).
- **Changed** Topics, Keywords, Search Console, GA4 traffic and Traffic by article are their own entries under SEO & Blog
  → Advanced (they were tabs). A page's first listed tab is its default (`defaultTab`), so links stay short.
- **Changed** The sidebar: each module has its own colour (from the logo's threads: SEO & Blog coral, Shipping blue,
  CRO green, Ads purple), a colour tile with its icon, its name and a one-line description; the open module is a tinted
  panel holding its pages, with a rail and a raised pill for the page on screen; counts sit on the module's tile; Home
  is drawn the same way and the modules sit under a "Modules" heading. Sidebar 260 px wide.

## 2026-11-24 (SEO & Blog: put a topic on a day; the content calendar on one screen)

Owner requests 2026-11-24: (1) the calendar should fit on one page; (2) the calendar should take topics for a day, and
Flowmerce should draft the blog and do everything else by itself, publishing it on that day. Owner decision (asked): the
written blog still waits for one click (Authorize) before it goes to Shopify; nothing is published unread.
Verified: the full Python suite (859 passed) and the frontend tests (111 passed); in the browser on a throwaway copy of
this computer's database with no API keys, at 1920 x 945: the month, the side panel and the List view fit the window
exactly, and a topic put on 3 Dec shows on the calendar ("Claude writes it on 28 Nov") and in the Blog pipeline.

- **Added** "Blog on a day" (`POST /api/blog/slots`; calendar header, a day's panel, "Blog for this" on an event, and
  "Put on a day…" on a topic in the Blog pipeline): a new or existing topic and a go-live day. Flowmerce writes it 5 days
  before (at once if sooner) with the automatic blog chain (draft, images, quality check, one revision, approval) and
  makes a publish request for 10:00 that day, waiting for Authorize. It runs even while automatic blogs are switched off,
  but waits while automation is paused for the brand. A topic already written by hand is put forward for the day instead.
  One blog per brand per day; a planned automatic blog on that day becomes the topic's blog.
- **Changed** The content calendar fits the window: the day cells share the height left on screen, the "Next 14 days"
  strip is gone, the side panel has tabs (This day, Coming up, Claude limit) and scrolls inside itself, and the schedule
  table is the "List" view.
- **Architecture** `auto_blogs.topic_id` is added by `db.EXTRA_COLUMNS` (added once if missing) instead of a numbered
  migration, so it does not depend on the image-prompt migrations that are not committed yet.
- **Fixed** Tests no longer read the developer's `ALLOW_LIVE_PUBLISH` from `.env` (`tests/fixtures/seo.py` sets it off);
  switching live publishing on in `.env` had made 4 SEO tests fail.

## 2026-11-24 (Ads and CRO: Shopify-style date picker and "Compare to")

Owner request 2026-11-24: the Ads page should filter dates like the CRO picker built on the `worktree-team-logins`
branch (commit 7ad11ee), with a real comparison choice instead of a single on/off box. The owner chose to bring that
picker over and share it. Only its date-picker parts were brought over (the same commit's other CRO changes, the
removed "What to do next" card, sentences under the conversion rate and landing-page countries, stay on the branch, and
it also needs earlier unmerged CRO commits). Verified: frontend tests 119 passed, CRO tests 130 and Ads tests 58
passed, ruff and mypy --strict on both modules, and in the browser on real data (CPC): picking Last 30 days and
"Previous year (match day of week)" changes the address and the requests; CRO opens with the picker, older links
(`?r=last7`) still work, no console errors.

- **Added** `frontend/src/components/croDates.jsx` and `tests/cro-dates.test.mjs` (from the branch, unchanged): the
  date picker (Today, Yesterday, Last..., Period to date, Black Friday Cyber Monday, Quarters, Custom range; two-month
  calendar; Apply) and "Compare to" (Previous period, Previous year, Previous year (match day of week), Custom, No
  comparison). Its styles are appended to `app/globals.css`.
- **Changed** CRO: `lib/cro.js`, `components/cro.jsx`, `modules/cro/periods.py`, `service.py`, `api.py` and
  `tests/unit/cro/test_ranges.py` as on the branch; `views/Cro.jsx` and `demo/modules/cro.js` take only the range and
  comparison parts.
- **Changed** Ads: the range bar is the same picker; every range tab compares (the Campaigns and Creatives "before"
  columns follow it); `/api/ads/*` take `compare` = previous, previous_year, previous_year_dow, custom (`cfrom=`) or
  none; a range may end today (still running); a comparison before the first loaded day says so.

## 2026-11-24 (Ads module, phase 2: Meta data, database and routes; not yet run live)

Owner approved phase 2 of `docs/plans/ads-module.md` on 2026-11-24. Verified: the 48 new Ads unit tests and the full
Python suite (848 passed; 4 SEO tests about the live-publishing switch fail, not related to Ads), ruff and mypy
--strict on the new module, and read-only runs against both real Meta accounts: the sync and every page answer worked
on real Meta data and real `cro.orders`, with schema `ads` stood in by an in-memory copy (nothing was written). Ridhi's
17-23 Oct added up from ad-level rows reproduces the Daily sheet (spend Rs 1,982,437.52, 297 purchases, 14,665 page
views, 1,824 carts, 591 checkouts). Not done: `115_ads.sql` has not been run (no local PostgreSQL to run it on first).

- **Added** `src/flowmerce/modules/ads/`: read-only Meta client, hourly background sync into schema `ads` (90 days
  first, 28 days nightly, 3 days otherwise), the rules, and `/api/ads/*` (settings, overview, campaigns, creatives,
  funnel, gap, actions, rules, sync) answering the `/ads` screens with real figures. Google Ads answers "not connected
  yet" (phase 3); "All" uses Meta spend only and says so.
- **Added** `db/central/115_ads.sql` (+ rollback): schema `ads`. Store sales are orders as placed from `cro.orders`, by
  the store's day in Shopify's time zone (New York for Ridhi, Phoenix for CPC); `ops.stores.timezone` says Los Angeles
  for both and is not used.
- **Added** ADR 0011 (how ad data is read and kept).
- **Changed** `modules/seo/app.py`: mounts `/api/ads` and starts the Ads background job, like Shipping and CRO.
- **Changed** from the plan: the Funnel's second step is link clicks (the Daily sheet's funnel), not outbound clicks;
  video length is not read (Meta refuses it to an `ads_read` token).
- **Changed** after the first live reads (same day): Meta requests are retried 3 times with pauses after a network
  failure (5, 15, 45 s; a connection that does not open in 15 s counts as failed); the background job tries again
  after 5 minutes when an account failed or was locked, instead of waiting the full hour; a first load stopped
  part-way keeps what it saved when that reaches into the last 28 days; the Overview says how far Meta figures are
  saved when that is short of the chosen days. Owner approved two screen fixes in `views/Ads.jsx`: long real
  ad and campaign names end in "..." (full name on hover) so tables fit their card, and the ad detail no longer
  prints a video length Meta does not give. Checked on real data for both brands; the backend changes apply after
  the next restart.

## 2026-11-24 (Ads module, phase 1: the screens, on sample numbers)

Owner approved phase 1 of `docs/plans/ads-module.md` on 2026-11-24: the Ads screens, run on sample numbers before the
live Meta and Google data is connected. Verified: the frontend tests (110 passed: 93 before, 17 new), the frontend
JavaScript-only check, and in the browser on the demo copy: every tab for both brands and all three platform choices,
expanding campaigns and ads, marking a suggestion done, saving the rules, a layout check of each tab for sections that
end unevenly or tables wider than their card, and phone width. Not done: no backend, database table or live data; with
real data the page says Ads is not connected yet.

- **Added** Ads (`/ads`, sidebar "Ads"): Meta and Google Ads next to the store's own sales, one brand at a time, with a
  platform switch (All / Meta / Google) and any date range of complete days with its comparison, all kept in the
  address. Tabs: Overview (spend, store sales, MER on all ad spend, orders, each platform's ROAS, ad cost per store
  order, the scaling gate, the road to the daily sales goal, days coloured by MER, Meta and Google side by side),
  Campaigns (CBO health with the budget call; every campaign with its ad sets), Creatives (Meta: every ad's verdict
  and reason, 3-day / lifetime ROAS, CTR, cart rate, hook and video drop-off, weakest step; new ads, tests and the
  winners bench), Funnel, Actions (rule-based suggestions the team marks done or skipped, with a history), and under
  Advanced: Search terms (Google), ABO to CBO gap (Meta) and Rules (every threshold, the rupee rate, the daily goal and
  the bulk-order limit, per brand). Read-only toward the ad accounts.
- **Added** Sample data for every `/api/ads/*` route (`frontend/src/demo/modules/ads.js`): invented "Demo" accounts,
  campaigns and ads, no real account names or figures. The demo's browser snapshot version is now 5.

## 2026-11-24 (SEO & Blog: drafts stay in Flowmerce, one Blog pipeline page, stop and cancel Claude, no empty space)

Owner requests 2026-11-24: (1) a way to pause "Write a blog", or an explanation of what it does; (2) the blog steps are
spread over several pages (topic in one, draft in another, and a drafted blog could not be found or scheduled); (3) do not
push drafts to Shopify's hidden section, only an authorized publish or schedule goes to Shopify; (4) the calendar has no
way to cancel a Claude task for a day; (5) no empty space under, above or beside any section, in any module.
Verified: the full Python suite (804 passed), the frontend tests (93 passed), and in the browser (demo, plus the real app
on a throwaway copy of this computer's database with no API keys): calendar cancel, the Blog pipeline from review to
Schedule…, Write a blog → Stop, and a layout check of every page for sections ending unevenly.

- **Added** Blog pipeline (`/pipeline`, SEO & Blog): every blog in building order on one page, 1 Topics, 2 Claude is
  writing, 3 Drafts & review, 4 Ready to schedule, 5 Scheduled, 6 Live, with each step's button beside the blog. It
  replaces Write it yourself (`/write` redirects here). The SEO & Blog menu now follows the same order: Overview, Blog
  pipeline, Content calendar, Publishing, Articles.
- **Added** "Schedule…" (pipeline and the article's Publishing tab): pick the go-live date and time; an admin can also
  authorize it in the same step by typing PUBLISH. Once authorized it goes to Shopify hidden until that time.
- **Added** Stop for "Write a blog" while it runs, and for any Claude task in the pipeline: unfinished Claude jobs are
  cancelled, nothing is approved (`POST /api/autopilot/{id}/stop`). "Pause automatic blogs" is also on the calendar.
- **Added** Cancel on the calendar: "Cancel this blog" for a planned automatic blog, "Stop writing" for one Claude is
  writing (`POST /api/blog/slots/{id}/cancel`; the old `/skip` still works), and "Cancel" (with "Plan again") for research,
  draft and publish tasks.
- **Changed** Drafts never go to Shopify. Write a blog, the automatic blogs, calendar drafting tasks and the 6-hour rule
  approve the blog and keep it in Flowmerce. Articles already saved to Shopify as hidden drafts before today stay there
  (Flowmerce updates them by handle when they are published).
- **Removed** "Save as hidden Shopify draft" (editor button, `POST /api/articles/{id}/shopify-draft`, the `shopify:draft`
  permission) and the Automation stage "Shopify draft".
- **Changed** No empty space beside or under sections, app-wide (`globals.css`): side-by-side columns end level, the
  calendar's day cells grow to match the day panel, cards in a row are the same height, and the article editor's side
  panel travels with the editor. Written into `docs/development/coding-standards.md` for new modules.

## 2026-11-24 (SEO & Blog: scheduled publishing goes to Shopify hidden, with a visibility date)

Owner report 2026-11-24: authorizing a scheduled blog failed with "Shopify rejected the publish: article Can't set
isPublished to true and also set a future publish date." Owner's rule: an authorized schedule saves the article in
Shopify as hidden, with Shopify set to make it visible at the chosen date and time.
Verified: 4 new unit tests (`tests/unit/seo/test_publish_schedule.py`), the full Python suite (802 passed) and the
frontend tests (93 passed). Not yet tried against a real Shopify store.

- **Fixed** Scheduling sent `isPublished: true` with the future `publishDate`, which Shopify refuses. A schedule now sends
  `isPublished: false` + `publishDate`, and fails with a clear message if Shopify does not keep the date.
- **Changed** A scheduled article is no longer marked live until Shopify shows it (the Shopify sync switches it to
  published then). It is not listed as a Shopify draft, and "Save as hidden Shopify draft" is refused for it so a draft
  save cannot change or clear the schedule.

## 2026-11-24 (CRO: Shopify-style date picker and comparison; tidier Overview)

Owner requests 2026-11-24: a date picker and comparison like Shopify's; remove the sentences under the conversion
rate; remove the Overview's "What to do next" card. Verified: CRO tests (143, 1 new), ruff and mypy --strict on the CRO
module, the Python suite (only the older `test_unfinished_pages_are_not_mounted` failure), frontend tests (104, 6 new),
the API smoke test, `next build`, and demo mode in the browser (presets, Last N, calendar pick, Apply, custom
comparison, phone width without sideways scroll). Not checked on live data: the new comparisons' figures.

- **Changed** The CRO date bar is a Shopify-style picker (`frontend/src/components/croDates.jsx`): one button with the
  range's name opens the presets on the left as a parent-child tree (Today, Yesterday; Last > 7 / 30 / 90 / 365 days,
  last week, month, quarter, year; Period to date > week, month, quarter, year to date; Black Friday Cyber Monday >
  years; Quarters > the last five; Custom range) and the start and end dates with a two-month calendar on the right;
  nothing changes until Apply. The panel moves left when it would run past the window. "Compare to" offers Shopify's
  five choices: Previous period (now the default, as in Shopify, instead of the 4-week weekday average for one day),
  Previous year, Previous year (match day of week), Custom (pick the first day; same length) or No comparison; older
  links with "a week earlier" or "4-week average" still open. The chosen comparison stays when the dates change.
  Ranges that move with time keep their key in the address (`?r=last-30-days`, `mtd`, `q-2026-3`, `bfcm-2025`); older
  links (`last7`, `this_month`...) still work.
- **Added** Comparisons `previous_year`, `previous_year_dow` and `custom` (with `cfrom`, the first day) in
  `modules/cro/periods.range_plan`, `service.RangeQuery.compare_from` and every CRO report's `?cfrom=`; the demo
  answers them too.
- **Removed** The sentences under the Overview's conversion rate ("of visits ended in an order", "Better than N of the
  last 28 days"); only the reason for a missing rate (today is not complete) is still shown.
- **Removed** The Overview's "What to do next" card (with its tick-boxes); Claude's plan and the checks stay on the
  Recommendations tab. The Overview no longer asks for recommendations or Claude's plan.
- **Changed** A landing page's deep dive now covers the whole window (its cards in a centred column up to 1,200 px)
  instead of a panel on the left.
- **Removed** "Top countries (month on month)" from a landing page's deep dive, with its two Shopify queries
  (`landing_detail.page_detail` no longer returns `countries`). Countries by store stay on the Conversion tab.

## 2026-11-23 (Shipping and CRO: no tab bar under the title)

Owner request 2026-11-23: the tab bars on Shipping (Overview, Shipments, Hand checks) and CRO (Overview, Conversion,
Landing pages, ...) repeat the sidebar's module menu, so they are removed.

- **Removed** The tab bar (and its "Advanced" toggle) on the Shipping and Conversion (CRO) pages. Every section is still
  opened from the sidebar (Advanced sections from its Advanced group) and by links on the pages; addresses (`?tab=`) are
  unchanged. The page title now names the open section, e.g. "Shipping · Hand checks".

## 2026-11-23 (Before pushing today's CRO work: hosted memory, Claude cost estimate, demo answers)

Owner: test today's work and push it to main, but first fix the concerns found. Today's CRO work runs more Shopify
reports at once on a hosted app that ran out of memory this morning, a deep Claude plan costs more than its pre-call
estimate, and the public demo (GitHub Pages) had no answers for the new routes.
Verified: the Python suite (only the older failure `test_unfinished_pages_are_not_mounted`), `ruff check .` and mypy
with no new errors (the older ones are all in the shipping module), CRO tests (141), frontend tests (96, 5 new), the API
smoke test, a Next.js build, and demo mode in the browser (landing pages' six views, the deep dive and Recommendations
without errors). Not verified: memory on Render after the deploy (watch its Metrics and Events), the container build
(no Docker on this computer; CI builds it).

- **Added** `CRO_READ_WORKERS` (default 8, 1-16): how many ShopifyQL queries one CRO report runs at the same time
  (`traffic.run_many`). The hosted image sets 3, so the deep recommendations and the landing page deep dive start
  fewer threads at once on Render's 512 MB.
- **Changed** The pre-call estimate of a CRO Claude plan (`ai_budget.ESTIMATE_USD["cro_advice"]`) from $0.30 to $0.60:
  the deep plan cost $0.37-0.59 a store in its first runs, so a call no longer overshoots today's limit.
- **Added** Demo answers (`frontend/src/demo/modules/cro.js`) for `/cro/store-notes`, `/cro/landing-compare`,
  `/cro/landing-funnel`, `/cro/landing-daily` and `/cro/landing-page`, worked out from the demo's own days, with tests
  (`frontend/tests/cro-landing.test.mjs`). The demo's landing page list is one list (`DEMO_PAGES`).

## 2026-11-23 (CRO: each landing page's own funnel in its deep dive)

Owner request 2026-11-23: see the funnel landing page wise. Verified: CRO tests (141; the deep-dive test now also
checks the page funnel, which caught a name clash in `funnel_counts` before it shipped), ruff and mypy --strict on the
CRO module, frontend tests (91), and the local app with live Ridhi data: /collections/quilts shows 3,085 visits, 1,026
viewed a product, 116 added to cart, 50 reached checkout, 28 purchased, as in Funnel by page; the Mobile switch shows
2,652 visits, as in the devices table; MoM works; no console errors.

- **Added** "Funnel for this page" in each landing page's deep dive (under What changed): visits, viewed a product,
  added to cart, reached checkout and purchased, each with its count, share of visits and share of the step before,
  a grey bar for the other period and the change in points; WoW or MoM; all devices or one (Mobile, Desktop, Tablet);
  checkout abandonment and purchase rate below. `landing_detail.page_detail` asks Shopify for the page's funnel by
  device and product view for both weeks and both months (4 more queries); `page_funnel` adds it up.

## 2026-11-23 (CRO: landing pages in six views, with funnel by page and date-wise)

Owner request 2026-11-23: the Landing pages tab gets the CRO prototype's six views. Verified: CRO tests (141, 2 new),
ruff and mypy --strict on the CRO module, frontend tests (91), and the local app with live Ridhi data on a second, quiet
API: funnel by page and date-wise match the prototype (for example /collections/quilts 3,085 sessions, 1,026 viewed a
product, 116 added to cart, 50 reached checkout, 28 purchased; date-wise 30-day totals 19,193 / 5,893 / 5,331 / ...),
choosing pages works through the API and an unsafe path is refused. Not checked: CPC, demo mode (no answers for the new
routes).

- **Changed** The Landing pages tab shows six views: 1. All landing pages (tiles and the page table), 2. Week / Month
  compare, 3. Funnel by page, 4. Date-wise, 5. Page type, source, device, 6. Page × source grids. 1, 5 and 6 follow the
  date range above as before; 2, 3 and 4 use fixed windows of complete days. Every page name opens its deep dive.
- **Added** Funnel by page (`GET /api/cro/landing-funnel?mode=week|month`, `landing_detail.funnel_pages`): every
  landing page's sessions, viewed a product, added to cart, reached checkout and purchased, each as a share of sessions
  with its change and as a count with the share of the step before; five sorts (sessions, best purchase rate, biggest
  purchase-rate drop, biggest add-to-cart drop, most checkout abandonment).
- **Added** Date-wise (`GET /api/cro/landing-daily?paths=`, `landing_detail.pages_daily`): dates down, pages across,
  one metric at a time (sessions, conversion, bounce, add to cart, orders, revenue, revenue per visit), 7/14/30/60
  days with a total / average row and CSV; the busiest 8 pages of the last 30 days to start, pages removed with × or
  added from a search of the busiest 200 (up to 12).

## 2026-11-23 (CRO: landing pages week on week, month on month and a deep dive per page)

Owner request 2026-11-23: compare landing pages week on week and month on month, and give a deep dive for every
landing page; the deep dive opens in a side panel (first on the right; the owner then asked for the left). Laid out like the CRO prototype's "Week /
Month compare" and page deep dive. Verified: CRO tests (139, 4 new), ruff and mypy --strict on the CRO module,
frontend tests (91), and the local app with live Ridhi data on a second, quiet API: the compare table and the deep dive
of /collections/quilts match the prototype's figures (for example 3,085 vs 3,959 sessions, -22.1%; 7 Nov: 525
sessions, 47.24% bounce, 1.71% conversion, $1,592), desktop and phone width, no console errors. Not checked: CPC, and
demo mode (it has no answer for the new routes, so the views show an error there).

- **Added** `modules/cro/landing_detail.py` with `GET /api/cro/landing-compare?mode=week|month` (every landing page
  Shopify lists, up to 200: sessions, bounce, add to cart, conversion, orders, revenue, revenue per visit, both periods
  and the change; pages under 100 visits in either period marked low data) and `GET /api/cro/landing-page?path=` (one
  page: 60 days by day, week and month compare, traffic sources and devices WoW and MoM, countries MoM, what changed).
  Complete days ending yesterday, bots left out. The path is checked before it goes into ShopifyQL.
- **Added** `frontend/src/components/croLanding.jsx`: on the Landing pages tab a switch between "All landing pages" and
  "Week / Month compare" (page-type filter, six sorts); a page name or "Deep dive" opens the page's deep dive in a
  left-side panel: what changed, WoW and MoM side by side, date-wise 7/14/30/60 days with CSV download, the 60-day
  trend, traffic sources, devices and top countries.

## 2026-11-23 (CRO: Claude's recommendations become a data-driven deep dive)

Owner request 2026-11-23: the recommendations were too simple and generic; they must be deep, data-driven and
actionable. Phase 1 (Claude's plan) approved and done; phase 2 (deeper rule-based checks) not started. Why the plans
were generic: Claude saw only part of the figures (no landing pages, GA4 product views, payments, free shipping,
discount codes, customers, page speed, site search, hours), the prompt capped every field at a few words, and Claude
knew nothing about the store's setup, so it guessed (for example "switch on abandoned-checkout emails").
Verified: CRO unit tests (132, 4 new), ruff and mypy --strict on the CRO module, frontend tests (91), `next build`.
The whole Python suite has one failure that predates this (`test_unfinished_pages_are_not_mounted`). Not verified:
a real run against the Claude API (costs money; the owner presses Refresh), and the new card on screen with a real plan.

- **Changed** `modules/cro/ai_advice.py`: Claude reads every CRO report for the last 30 complete days against the 30
  before, compact and without customer details, plus the rule-based findings with the team's status. A new prompt asks
  for root causes found by combining reports, a conservative money impact with its arithmetic, exact targets and
  steps, and how to measure each action; it forbids generic advice and advice that assumes setup Claude cannot see.
  Each action now has target, diagnosis, evidence lines, `impact_usd` and `impact_math`, steps, measure (metric,
  baseline, goal, check after N days), experiment metric and page, confidence and what to check first. Claude runs at
  high effort. Plans are saved as version 2; an older plan from today no longer stops the once-a-day automatic ask.
- **Added** Store notes for Claude: `GET/PUT /api/cro/store-notes` (audited), kept per store in `app_settings`
  (`cro_notes:<brand>`, up to 3,000 characters), sent to Claude with the figures; a card under the plan on
  Recommendations (hidden in demo mode, which has no answer for it yet).
- **Changed** Recommendations tab: the plan's summary and total money at stake; each action shows target, money at
  stake, diagnosis, the numbers, how to know it worked, confidence, what to check first and "Start experiment" (fills
  the Experiments form). The Overview's "What to do next" shows each action's money at stake. Older plans keep their
  layout with a note to Refresh.
- **Note** A deep-dive plan costs more than the earlier ones ($0.07-0.09): the first real one (Ridhi, 23 Nov) cost
  $0.59. The pre-call estimate in `seo/services/ai_budget.py` (0.30) was left unchanged.
- **Changed** (same day, owner: the cards looked spread out and confusing) Each action is now folded to one heading
  line (number, instruction, target, effort, confidence, area, money at stake); the first one is open. Opened, it reads
  in one fixed order: problem, check first, what to do, measure with "Start experiment", and the numbers and the money
  arithmetic behind a "show" link. The prompt now caps each field (for example diagnosis 2 sentences, 3-5 evidence lines
  of up to 20 words, 3-5 one-sentence steps) so new plans stay short; plans already saved keep their longer text until
  Refresh. Checked on the local app (desktop and phone width, no sideways scroll, no console errors) with the saved
  Ridhi plan.
- **Changed** (same day, owner: "phase 1 again on the full recommendation system, include all landing pages") Phase 2
  done together with this. The rule-based Ranked checks are now deep too (`modules/cro/recommendations.py`): each has
  a problem (diagnosis), steps naming the page, product, device or term, a measure and the experiment metric and page.
  Every landing page Shopify lists (up to 200) is checked; a poorly converting page is diagnosed from its own rates
  against the store's: a content page with no route to products, visitors leaving at once (bounce), browsing without
  adding to cart, or adding to cart and not buying, each with its own steps. Contact, help, policy, account and cart
  pages are left out. New checks with a money estimate where the figures allow: the funnel step that breaks on one
  device, orders just under the free-shipping amount, searches that find nothing or get few clicks, discounts given
  without a code, products refunded at twice the store's rate; without one: slow mobile page types and products
  bought together. `service.recommendation_list` also reads the funnel per device, page speed and site search, discount
  codes and the Products tab report (all at once with the other reads). Claude now gets every landing page with
  enough visits (not the busiest 25) and is told to read all of them and group pages with a shared cause.
  The Ranked checks use the same folded card as Claude's plan (status buttons inside). Verified: CRO tests (135, 3 new),
  ruff and mypy --strict on the CRO module, frontend tests (91); a live read of Ridhi's checks on a second, quiet API
  (72 checks in 7 s, no source skipped).

## 2026-11-23 (Shipping: one section per order, clock from the last scan, dispatched parcels only)

Owner request 2026-11-23, after reviewing every separation rule of the Shipping page: stop tracking orders that are not
sent yet; a carrier scan resets the clock; an order must appear in one list only (checking Critical, No movement and
Exceptions meant checking the same order several times); "Carrier unconfirmed" was confusing (it listed parcels with a
carrier and a tracking number), so it becomes "Tracking missing", and a number no carrier ever reported on is "Invalid
tracking"; delivered by any source means delivered. Decided with the owner: every band (Critical included) counts from
the last scan; strict one place per order; orders older than 60 days are loaded from Shopify, and the board tracks open
parcels dispatched in the last 120 days (a no-limit dry run would have added ~1,775 open parcels back to 2022).
Verified: 114 shipping unit tests, the full Python suite (781 passed; the one failure, `app/login` existing, is from
the 18 Nov sign-in commit and unrelated), and the board built from the live Supabase data (501 active parcels: 117 on
track, 288 yellow, 3 orange, 8 critical, 9 tracking missing, 30 invalid tracking, 46 fix in Shopify).

- **Changed** The clock: days since the last carrier scan (since dispatch while there is none). On track 0-3, Yellow 4-5,
  Orange 6-8, Critical 9+. The Grey band (orders not sent) is gone.
- **Changed** One section per order, first that applies to any of its parcels: Tracking missing > Invalid tracking (a
  number with no carrier status or scan 3+ days after dispatch, whatever the carrier) > Fix in Shopify (Amazon shipped
  but Shopify unfulfilled, an Amazon parcel the Shopify order does not list, a tracking number on two parcels) >
  Critical > Orange > Yellow > On track. The order's other parcels are listed with it ("this parcel: ..." in the label).
- **Changed** Delivered by any evidence (status, a last scan saying "Delivered", Amazon's word on the order, a team mark
  or outcome, another parcel, a shared number) is plain Delivered: in no list, never under Resolved.
- **Changed** Team marks (Delivered / Lost / Couldn't deliver / Still in transit) can be recorded on any open parcel;
  Lost and Couldn't deliver move it to Resolved.
- **Changed** "Checks and exceptions" tab is now "Hand checks": one row per order in the three hand-check sections.
  Home's "Delivery problems" = Critical + hand checks.
- **Removed** The Unfulfilled tab and `/api/shipping/unfulfilled`; orders not sent yet (Shopify unfulfilled, or with
  Amazon but not shipped, or a cancelled / unfulfillable Amazon order) are not shown anywhere.
- **Removed** No movement, Carrier exceptions, Carrier unconfirmed, Scan missing, Past promised date and Delivered but
  not marked (filters, KPIs, check types); the "Marked DONE but not fulfilled" list; the verify list and
  `/api/shipping/export/verify`; the "Stuck first" sort.
- **Added** `shopify_source.backfill_store()` and `scripts/shipping_backfill.py` (dry run by default, `--write` to store):
  loads each store's orders placed 60 to 120 days ago once (both store apps hold `read_all_orders`). Open parcels of
  orders older than 60 days are re-read from Shopify once a day (newer ones every 2 hours, as before). A dry run on
  23 Nov found 2,810 (RBP) and 1,331 (CPC) such orders not yet stored, 449 of their parcels not delivered in Shopify.
- **Changed** Open parcels dispatched more than 120 days ago (`board.TRACK_DAYS`) are not listed.

## 2026-11-23 (SEO & Blog: automatic featured images from an image API)

Owner request 2026-11-23: a fully automatic chain, Claude writes the prompt, an image API makes the picture with the real
product photo, and the picture becomes the blog's featured image. Verified with stand-ins only (12 new tests; the SEO
unit and integration tests show only the 3 older failures plus the local CLI one; frontend tests 93 and build; both
screens in demo mode; migration 9 on a copy of the local database). Not run against a real image API: no key yet.
Both stores' Shopify apps already have the write_files permission the upload needs (checked read-only).

- **Added** `integrations/image_gen.py`: Google Gemini (`GEMINI_API_KEY`, default model `gemini-3-pro-image`, Nano Banana
  Pro, about $0.134 a picture) or OpenAI (`OPENAI_API_KEY`, default `gpt-image-2`, exact WIDTHxHEIGHT); `IMAGE_PROVIDER`
  and `IMAGE_MODEL` to choose. Request formats from the providers' documentation of 2026-11-23 (Gemini's newer
  `interactions` endpoint); answers are read defensively and the picture's type comes from its bytes.
- **Added** `services/ai_images.py`: after each prompt, the picture is made, stored in Shopify Files, checked by Claude
  against the real product photo (about $0.04; a failed check is made once more, then left to a person), and attached
  as the featured image of articles still being written. Articles in review, approved, scheduled or live keep their
  image; the new one waits in the editor ("Use this picture"). Optional Pinterest picture. Limits: pictures a day
  (default 10) and dollars a month (default $25), kept in the new table `image_generations` (migration 9).
- **Changed** Automatic blogs wait (at most 45 minutes) for their picture before they are approved and saved as hidden
  Shopify drafts, so the picture is part of the approved content; new autopilot step `image`.
- **Changed** Migration 8 is back to its first form (the local database already ran it); the Pinterest prompt and payoff
  columns moved to migration 9.
- **Added** Editor: an "AI picture" section (preview, print check, Use this picture, Make a new picture). SEO & Blog:
  "Automatic pictures" switches (on/off, print check, Pinterest) and the daily and monthly limits.

## 2026-11-23 (SEO & Blog: AI image prompts for featured images)

Owner request 2026-11-23: write one prompt per blog that any AI image tool (ChatGPT, Gemini, …) can use to make the
featured image, built from the store's existing images and the article; sized for each store's blog page; different
for every article; made for every new draft, with an option for past drafts and live blogs. Verified: 11 new tests,
the SEO unit and integration tests (the same 3 integration failures as on main before this change), the frontend tests
(91) and build, and both screens in demo mode. Tried with real Claude on a copy of the local database (2 articles per
store, about $0.37 in all, recorded only in the copy): styles $0.06 per brand, prompts $0.04-0.09 each. Fixes from that
trial: product matching ranks by product type and name (a quilt article had been given a lampshade), Claude names
products instead of photo numbers, and the brand's writing "Never" note is no longer pasted into image prompts. Prompts
for a brand whose automation is paused wait until it is resumed; the screens say so. Then two prompts were run in Google Nano Banana Pro
(through the ElevenLabs Creative connection, with the real product photo attached): both kept the print faithfully and
came out at the right size; the runner picture copied the product photo's layout, so prompts now say to take only the
product from the photo, and the steps say to set the aspect ratio in the tool (image tools often copy the photo's shape).
After the owner's review as a professional blog editor (clean but catalogue-like, the picture did not show the answer, no
human moment, nothing for Pinterest), Claude's brief now asks for the article's payoff shown in the picture, a moment
with hands or a partly seen person (faces out of frame), editorial framing (never the centred catalogue shot), a little
natural imperfection and one focal point that reads small; and every article also gets a tall Pinterest pin prompt
(2:3, 1,000 × 1,500, calm space at the top for a title). Banner safe zones now also allow for the wide crop of social
link previews. Re-run on the 2 test articles: about $0.10 each. The new images were not generated: the ElevenLabs
account's free plan reached its daily image limit.

- **Added** `services/image_prompts.py`, table `image_prompts` (migration 8) and `/api/articles/{id}/image-prompt`,
  `/api/image-prompts`, `/api/image-prompts/backfill` (and `/cancel`), `/api/image-prompts/style`.
- **Added** The brand's visual style: Claude reads up to 12 photos the store already uses (live blog banners, then
  product photos) and describes light, palette, surfaces, props, composition and mood. Read once, kept 60 days,
  "Read the photos again" redoes it (about $0.15).
- **Added** A prompt per article (about $0.10): from the title, keyword, summary, headings and opening, the visual style,
  up to 4 matching product photos (at most 2 used as references) and the last 30 concepts used for the brand, which it
  must not repeat. Flowmerce adds the size, the reference-photo instruction and the exclusions itself. Sizes measured on
  the live themes: Ridhi (Yuva) square 1:1, 2048 × 2048; CPC (Nimbus) 4:3, 2400 × 1800 with a safe zone for the 10:7
  article banner. Recommended tool: Google Gemini (Nano Banana Pro), because it keeps a real product photo most faithfully.
- **Added** Every article created from 2026-11-23 on is queued once it has 150 words (Claude drafts and articles written
  in Flowmerce). Shopify imports and older articles: "Create prompts for past drafts / live blogs" on SEO & Blog. Past
  articles only run when today's Claude limit still has room for one automatic blog, so they never hold up new work.
- **Added** Article editor, Featured image card: the prompt with Copy, the photos to attach, suggested alt text ("Use
  it") and file name, the tool and steps. The image preview now uses the store's shape instead of 16:9.
- **Changed** `claude._structured` accepts content blocks (text and images by link).
- Brand rule kept (Ridhi master brief): a real product appears only from its real photo as a reference; a generated
  picture is never presented as a photograph of the actual item.

## 2026-11-23 (Fix: hosted app crashing out of memory)

The live app on Render showed "Request failed (503)". Render's events: since the 2026-11-21 18:56 deploy the instance
ran out of memory (over 512 MB) at 09:35 and 10:24 and failed its health check at 10:07 and 10:52; each time Render
restarted it and pages answered 503 for about 30 s. The CRO speed-ups keep more in memory: up to 4,000 Shopify answers
for 6 hours, and a warm-up that reads every CRO tab's default view after each 15-minute round. Fine locally, too much
beside Next.js and Litestream in 512 MB. Verified: CRO tests (129, 1 new), the Python suite (only the older failure
`test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the CRO module. Not verified before pushing: memory
on Render itself (watch its Metrics and Events after the deploy).

- **Added** `CRO_WARM_VIEWS` (default `true`): `false` skips the warm-up after each round; pages read Shopify when
  opened (first visit to a CRO tab about 1-2 s slower). The order sync, alarms and product list still run.
- **Added** `CRO_CACHE_MAX` (default `4000`): how many ShopifyQL answers are kept in memory.
- **Changed** The hosted image (Dockerfile) sets `CRO_WARM_VIEWS=false`, `CRO_CACHE_MAX=500` and
  `MALLOC_ARENA_MAX=2` (glibc otherwise gives each of the app's many threads its own memory arena). The local app is
  unchanged.

## 2026-11-21 (CRO: faster pages and filter changes)

Owner request 2026-11-21: data showing, page loading and filter changes were too slow; check desktop and mobile and
make it faster locally before pushing. Pushed to main together with the Overview tiles below, after the owner's
go-ahead. Measured on the local app (production build, live Ridhi data) before and after, the same way (browser timings
of the page and its requests):

| | Before | After |
|---|---|---|
| Overview, normal visit | 2.9 s (4.3 s on a fresh load) | 0.9 s (0.3 s when its answers are cached) |
| Overview, range not seen yet | 2.5 s behind the loading placeholder | 0.6-0.8 s, the page stays and changes at once |
| Overview, range seen before | 2.5 s (all 17 requests sent again) | 0.1 s (only the range's own requests) |
| First visit: Landing pages / Products / Sales | 2.1 / 1.5 / 1.4 s | 0.13 / 0.11 / 0.13 s |
| First visit: Cart & checkout / Conversion | 2.4 / 0.3 s | 0.8 / 0.15 s |

Why it was slow: every CRO page waited about 2 s for /cro/settings before asking for any figures; a range change
rebuilt the Overview; Shopify answers were kept only 10 minutes and several reads ran one after another; Supabase
(about 0.4 s a request from here) reopened its secure connections after 5 s idle (about 1 s a request then); and Shopify
allows each store 1,000 report (ShopifyQL) points a minute (a query costs 2-22), so bursts of uncached queries were
throttled (reads then waited 25-45 s). Verified: CRO tests (128, 7 new), the whole Python suite (one failure that
predates this: `test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the CRO module, frontend tests (91),
`next build`, demo mode on desktop and phone width (no sideways scroll), and the local app as above. A first view of
a range that is neither the default nor seen in the last 6 hours still reads Shopify (about 0.6-2 s).

- **Changed** CRO pages no longer wait for /cro/settings: each store's timezone is known up front
  (`storeTimezone` in `lib/cro.js`; the one settings reports wins when it answers), so the figures are asked at once.
- **Changed** the Overview keeps its page on screen (dimmed after 350 ms) while a new range loads and then changes all
  at once, without the loading placeholder; requests that do not depend on the range are not sent again (it was
  rebuilt for every range). Other tabs dim a card that is loading a new answer instead of showing old figures as new.
- **Changed** Shopify answers for days that are over and settled (3 hours after the store's midnight) are kept 6 hours
  instead of 10 minutes; answers that reach today keep 10 minutes. GA4 answers likewise once GA4 has finished a day
  (2 days). At most 4,000 answers are kept.
- **Added** a background warm-up (`service.warm_views`, in every 15-minute round after all stores' order sync and
  alarms, so it never delays them; the first round runs 30 s after start-up): every CRO tab's default view (yesterday
  against the 4-week average) and the Overview's other cards are read one at a time, pausing 2 s after each read that
  went to Shopify so pages opened meanwhile keep most of the per-minute budget (measured: about 65 s a store with
  nothing cached, a few seconds afterwards).
- **Changed** Supabase connections for CRO are kept open 55 s between requests (httpx closed them after 5 s), and the
  small page reads (sync state, settings, statuses, change log) are reused for 2 minutes instead of 30 s; any change
  made in the app still forgets them at once. Every change-log window (60, 63, 90, 365 days) is cut from one read.
- **Changed** reads that ran one after another now run together: the conversion trend's four Shopify queries, the KPI
  overview's sales report and conversion read, /cro/settings' Supabase reads, and the recommendation list's Shopify and
  Supabase reads. A query group runs up to 8 queries at once (was 4); the shared read pool has 24 threads (was 6).
- **Fixed** the Net sales chart's controls on phones (they pushed the page up to 18 px wider).

## 2026-11-21 (CRO Overview: Sales and Site health tiles)

Owner approval 2026-11-21 (design canvas "CRO Overview Drafts", artboard 12). Pushed to main together with the speed
work above. Verified: frontend tests (91), `next build`, the Overview in demo mode on desktop (the three top columns now
end level) and phone width (no sideways scroll).

- **Added** two tiles above Orders and Visits on the CRO Overview (`SalesTile`, `HealthTile` in
  `components/croOverview.jsx`), so the space beside Store conversion is no longer empty: Sales (total sales for the
  chosen days against the comparison, and a ring of where the gross sales went: net sales, returns, discounts) and
  Site health (mobile LCP / INP / CLS as rings of good page loads, coloured by Google's rating, and how site searchers
  convert, for the 7 days ending two days ago, because Shopify publishes page speed 1-2 days late). The Overview reads
  two more answers it already had routes for (`/cro/sales-breakdown`, `/cro/site-health`) and still appears all at once.
- **Fixed** the Net sales chart's controls on phones: they wrap instead of pushing the page 18 px wider.

## 2026-11-21 (CRO: batch 5, new vs returning customers; page loading)

Owner approvals 2026-11-21: batch 5 plan with the recommended answers and its sample screens (design canvas "CRO Overview
Drafts", artboards 10 and 11); then, for this push, the CRO emails (alarm and daily numbers emails, the Alarms tab's
email setup) and the path to the first purchase (it needs the same migration) are held back for more work on Monday
and are not in this commit. No `read_customers` scope and no customer identity. Pushed together with batches 1-4 after
testing: CRO tests (122), the whole Python unit suite (one failure that predates this:
`test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the CRO module, frontend tests (91) and `next build`;
the reads were run against both live stores (read-only).

- **Added** `src/flowmerce/modules/cro/customers.py` and `GET /api/cro/customers` (default: last 28 complete days):
  new vs returning customers from Shopify's sales report (`new_or_returning_customer`: orders, share, net sales,
  average order) and its returning customer rate, against the comparison. Shopify decides who is new or returning.
- **Changed** the Sales tab: a New vs returning customers card below Discount codes.
- **Changed** page loading: the background job keeps each store's Shopify product list cached (read at start-up and
  again when under an hour of its 6 hours is left, `shopify.warm_catalog`), so the Products tab and the
  recommendations (which the Overview waits for) no longer pay the ~2 s it takes to read.
- **Changed** `conversion.run`: a ShopifyQL query already being read is not asked again (a second caller waits for that
  answer; the Overview asks some figures twice), and at most 10 run at once per store.
- Measured on both live stores (read-only): every CRO read answers in about 0.1 s warm; with nothing cached the
  Overview took 3.6-3.8 s (its slowest read is the recommendations) and other tabs 0.6-2.8 s. Firing every tab at once
  with nothing cached, right after many test runs, made Shopify throttle report queries (reads waited 25-45 s, a few
  failed with an explained error); a cap of 6 parallel queries did not prevent it and slowed the Overview to 5.8 s, so
  the cap is kept at 10. Answers stay cached 10 minutes (`CRO_CACHE_SECONDS`).

## 2026-11-21 (CRO: batch 4, deeper product analysis from Shopify and GA4)

Owner approvals 2026-11-21: batch 4 plan; product views from GA4 instead of Microsoft Clarity (money and orders from
Shopify, GA4 only for what Shopify cannot see: views and add-to-carts per product); the sample screens (design canvas
"CRO Overview Drafts", artboards 8 Products and 9 Sales). Built together with batches 1-3, to be committed together
after testing. Verified: CRO tests (119, 13 new in `tests/unit/cro/test_products_deeper.py`), ruff and mypy --strict on
the CRO module, frontend tests (90, 4 new in `tests/cro-batch4.test.mjs`) and `next build`. Product insights, discount
codes and the recommendations were run read-only against both live stores; both tabs were checked in the browser in
demo mode on desktop and phone width (no sideways page scroll). Not yet seen with live data in the full app. No new
table or setting: GA4 uses the SEO module's existing Google service account and GA4 property ids.

- **Added** `src/flowmerce/modules/cro/products.py`: Shopify's sales per product id (gross, discounts, refunds, net,
  items, orders), refunds per product, discount codes (with vs without a code; an order with two codes is under both
  codes, so "with a code" = all orders - orders without one), products bought together (pairs in the same order, share
  of the first product's orders, how many times more often than chance), price bands by each product's "from" price,
  and GA4 product views and add-to-carts (GA4's item id holds the Shopify product id, so products match by id).
- **Added** product groups (Stars, Hidden gems, Leaky, Dead weight): each product's conversion (orders / GA4 views over
  the same days) against its own category, with the small-sample adjustment (orders + 200 x category rate) / (views +
  200); a category with fewer than 3 viewed products is compared with all products, and a category where nothing sold
  makes no Star. The leaky pages are ranked by money left on the table (views x conversion gap x price). Groups wait
  until GA4 has 7 days of views in the range (CPC's GA4 only started on 19 Nov) and say so; everything else shows.
- **Added** leaky products to Recommendations (the top five with $50+ left on the table), ranked with the other
  impact-ranked checks.
- **Added** routes `GET /api/cro/product-insights` and `GET /api/cro/discount-codes` (default: last 28 complete
  days); `shopify.product_catalog()` reads each product's title, type and lowest variant price (cached 6 hours).
- **Changed** the Products tab to the approved design: the four groups (clicking one filters the table), fix first,
  refunds per product (highest rate / most refunded), price bands, bought together, and every product with net sales,
  refund %, views, add to cart, conversion and group. Removed: the top / middle / low thirds ring and the best-sellers
  list (the groups and the table, sorted by net sales, replace them).
- **Added** a Discount codes card on the Sales tab: orders with vs without a code against the comparison, and the top
  codes (sortable by orders or average order) with their average order against orders without a code.
- Note: CPC's GA4 property is on Pacific time while the store is on Arizona time (a one-hour shift at each day's edge);
  Ridhi's matches. Napkins convert far above other categories (often added from a tablecloth page without a napkin
  page view), which can make an ordinary napkin look leaky.

## 2026-11-21 (CRO: batch 3, and the approved screen designs for batches 1-3)

Owner approvals 2026-11-21: batch 3 plan; the sample screens (design canvas "CRO Overview Drafts", row "Batches 1-3")
for Conversion, Landing pages, Cart & checkout (with four extra improvements), Site health, Recommendations and
Experiments; Site health, Recommendations and Experiments go under Advanced; the Overview's design stays as it is (only
new content is added). Built together with batches 1 and 2, to be committed together after testing. Verified: CRO tests
(106, 10 new in `tests/unit/cro/test_recommendations_experiments.py`), the whole Python unit suite (one failure that
predates this: `test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the CRO module, frontend tests (86,
5 new in `tests/cro-batch3.test.mjs`) and `next build`. The recommendation list and experiment results were run
read-only against the live Ridhi store. Every changed screen was checked in the browser in demo mode, on desktop and
phone width (no sideways page scroll). Not yet seen with live data in the full app, and `db/central/114` has not been
run in Supabase yet: until it is, statuses, experiments and the saved free-shipping amount explain that it is missing.

- **Added** `db/central/114_cro_tracking.sql`: `cro.recommendation_status` (the team's status per recommendation
  key), `cro.experiments` (the experiment log) with `cro.delete_experiment()`, and
  `cro.store_settings.free_shipping_threshold`. Run it in Supabase after 112 and 113.
- **Changed** Recommendations (now under Advanced): Claude's plan stays on top; below it every check is ranked by an
  estimated money impact over the last 28 days (visits x conversion gap x average order), with fix / promote / test,
  effort, the evidence and the formula. New checks from the prototype: landing pages converting well below the store,
  bounce jumps with falling conversion, pages and sources worth more traffic, weak devices and sources, the store
  converting less than before, and payment methods failing more than the rest. Each item has Open / In progress /
  Done / Ignore, saved for the whole team; done and ignored items leave the Overview's "What to do next".
- **Added** an Experiments tab (under Advanced): the team logs a test (name, expectation, metric, dates, optional
  landing page, owner), or starts one from a recommendation; the result comes from Shopify, comparing the test days with
  the same number of days just before, with a two-proportion confidence (a win or loss only at 95% and 200+ visits a
  side) and the change-log entries of those days.
- **Changed** Conversion, Landing pages, Cart & checkout and Site health to the approved designs: the full funnel with
  the comparison as grey bars, sortable device and channel tables with the change against the comparison, places side
  by side; landing-page tiles (the bounce tile filters the table), search / type filter / sort, and a grid with
  conversion, add to cart or bounce against the grid's own "All" row and column; Site health as rating-coloured tiles.
- **Changed** Cart & checkout (owner's improvements): an abandonment chart with a tooltip per day, change-log markers
  and the earlier days dashed (replacing the two abandonment charts); payments as share bars with a success chip each and
  the change against the comparison; order values and items per order side by side as compact rows; a line at the
  free-shipping amount, which is now typed on the card and saved per store for everyone (`.env` stays a fallback).
- **Changed** the CRO menu: Landing pages joins the everyday tabs; Site health, Recommendations and Experiments are under
  Advanced, on the page and in the sidebar.
- **Added** routes `POST /api/cro/recommendations/status`, `GET/POST /api/cro/experiments`,
  `PATCH/DELETE /api/cro/experiments/{id}`; `PATCH /api/cro/settings` also takes `free_shipping_threshold`. Demo mode
  answers all of them.

## 2026-11-21 (CRO: new views from the new CRO prototype, batch 2)

Owner request, batch 2 of 5 (built together with batch 1; both to be committed together after testing). Verified: CRO
tests (96, 22 new in `tests/unit/cro/test_traffic.py` and `test_landing_site.py`), the whole Python unit suite (one
failure that predates this: `test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the CRO module, frontend
tests (81, 7 new in `tests/cro-batch2.test.mjs`) and `next build`. Every new report was run read-only against the live
Ridhi store (each answers in under 2 s; every ShopifyQL dataset used also answers for CPC). The new tabs and cards were
checked in the browser in demo mode, on desktop and phone width (no sideways page scroll). Not yet seen in the full app
with live data (the local API was not running) and not yet on the hosted app.

- **Added** a Landing pages tab: per landing page its visits, bounce rate, add-to-cart and conversion rate, revenue and
  revenue per visit (ShopifyQL `sales` by the order's landing page), top traffic source, and a warning when a page's
  bounce rate is 5+ points above the comparison; bounce and conversion by page type, traffic source or device; and a
  pages x traffic source (or page type x device) grid shaded against its average.
- **Added** a Site health tab: page speed (Google's Core Web Vitals at the 75th percentile, with Google's ratings) by
  device against the comparison, by page type and for the busiest mobile pages, with a daily mobile trend; and site
  search (share of visits that search, how searchers convert against everyone else, top searches, searches that found
  nothing). Shopify publishes both about 1-2 days late; the tab says so when nothing is out yet.
- **Added** to the Conversion tab: traffic sources with revenue per visit, and conversion by country and US state.
- **Added** to Cart & checkout: payment methods and wallets with the payment success rate, items per order, and order
  values in $25 bars. With a free-shipping amount set (`CRO_FREE_SHIPPING_RBP` / `CRO_FREE_SHIPPING_CPC` in `.env`), the
  bars just under it are marked and the share of orders just short of it is shown; not set yet.
- **Added** to the Overview: revenue per visit (complete days only), "What moved orders" (each change in purchases split
  into a visits part and a conversion part, by device and source, as the three biggest sentences), the best hours to
  sell (conversion by weekday and hour over the last 28 days, store time; orders by hour when Shopify's hourly visits
  cannot be read), and average order value by day with sales by channel.
- **Added** routes `/api/cro/landing-pages`, `/landing-grids`, `/traffic-changes`, `/geo`, `/site-health`,
  `/overview-trends`, `/checkout-extras`, `/buy-heatmap`; `/api/cro/overview` also returns `sessions` and
  `revenue_per_session`. Demo mode answers all of them (and batch 1's device funnel).
- Not done: the two new tabs are not yet in the sidebar's CRO list (`frontend/src/lib/routes.mjs` was outside the
  approved files); they are on the CRO page's tab bar.

## 2026-11-21 (CRO: figures that match Shopify, from the new CRO prototype, batch 1)

Owner request: bring the new features of the updated CRO prototype (cro-automation-main) into the CRO module, batch 1
of 5 (still to come: new views, recommendation status and experiments, deeper product analysis, and email or
customer-data features that need an owner decision). Verified: CRO tests (74, 7 new), the whole Python
unit suite (one failure that predates this: `test_unfinished_pages_are_not_mounted`), ruff and mypy --strict on the
CRO module, frontend tests (74) and `next build`. Run read-only against the live Ridhi store: every new ShopifyQL query
answers, bots were about 9-10% of the sessions counted before, and for 14-20 Nov the device funnel's sessions equal
the daily totals. The Conversion tab's funnel was checked in the browser (desktop and phone) with those live figures.
Not run in the full app (the local API was not running) and not yet on the hosted app.

- **Fixed** sessions, conversion rate, the funnel and the device/channel split leave bots out
  (`human_or_bot_session = 'Human'`), as Shopify Analytics does, so they match Shopify's own reports.
- **Changed** revenue on the Overview, the sales breakdown and the sales chart come from Shopify's sales report
  (ShopifyQL `sales`), which counts a refund on the day it was made, not on the day of the order. Orders and average
  order value stay from the order copy. Ranges that reach today keep the order copy for today (and for the comparison
  day lined up with it), because that comparison stops at the same time of day. If Shopify does not answer, the order
  copy is used as before; the answers say which was used (`revenue_source` / `source`).
- **Changed** the conversion-rate alarm compares yesterday with the average of the same weekday over the 4 weeks before
  (was: the day before). Days with fewer than 30 sessions are not judged, and it needs at least 3 usable past weeks.
  The recommendations and Home still compare with the day before.
- **Added** the Conversion tab's funnel has a "Viewed a product" step and an All / Mobile / Desktop / Tablet switch,
  with each step's change in points against the comparison (`funnel` and `baseline_funnel` in `/api/cro/conversion`).

## 2026-11-21 (One Python version everywhere: 3.14)

Owner decision ([ADR 0010](docs/decisions/0010-one-python-version.md)). Before: the hosted app ran Python 3.12, this
computer 3.14.7, CI both, and the docs said 3.10+, 3.12+ or 3.13.

- **Changed** the hosted image (`Dockerfile`) runs `python:3.14-slim-trixie` (was 3.12).
- **Changed** `pyproject.toml`: `requires-python = ">=3.14,<3.15"`; mypy checks for 3.14 (ruff follows
  `requires-python`).
- **Changed** CI runs lint, types, tests and the smoke test on 3.14 only (one Python job instead of two).
- **Changed** `scripts/run_flowmerce.py` stops with a clear message on any Python other than 3.14 (it accepted 3.10+).
- **Added** `.python-version` (3.14) and ADR 0010; README, setup, coding standards, architecture and CI/CD docs updated.

## 2026-11-21 (Every page appears all at once)

Owner request. Verified: frontend tests (74, 6 new in `tests/load-gate.test.mjs`) and `next build` pass; checked in
the browser in demo mode (each request answers after 90-250 ms) by moving between Home, Shipping, CRO and its tabs,
Blog, Articles, Topics, Calendar, Publishing, Analytics, Automation, Brands and Write: each showed one placeholder,
then the whole page, with nothing arriving afterwards; revisits and tabs needing no new data showed at once; the
article editor kept unsaved text across its tabs; a brand switch on an open page did not bring the placeholder back.
Not checked with live data (the local app was not running).

- **Changed** every page (and every `?tab=`) appears all at once: one placeholder until the data it asked for on
  opening has answered, then the whole page, with entrance animations playing on show. Built into the shared loader
  (`useApi` reports first loads to `components/LoadGate.jsx`, bookkeeping in `lib/loadGate.js`), so no page was edited.
  Remembered answers show at once; filter changes keep the page up; after 10 s a page shows whatever is still loading.
  Data fetched outside `useApi` (Audit page, a few widgets) still fills in on its own.

## 2026-11-20 (Smooth background; CRO Overview appears all at once)

Owner request. Verified: frontend tests (68) and `next build` pass; checked in the browser on a preview server with live
data, in development and production mode: the background is drawn by the worker (one canvas), the worker file ships in
the build, no console errors; switching the Overview's range shows one placeholder, then every part at once (1.4 s).
Not checked: the page fallback in a browser without OffscreenCanvas.

- **Fixed** the moving background stuttered: it drew only 15 frames a second and on the page's own thread, so page
  work held it up. It now draws every frame, moves by elapsed time, and runs in a Web Worker on an OffscreenCanvas
  (`components/ambient.worker.js`); browsers without that draw the same thing on the page.
- **Changed** CRO Overview appears all at once: one placeholder shaped like the page until every request has answered
  (an error shows in its own card), instead of cards arriving one by one. A new range waits the same way. The monthly
  goal is loaded with the rest.

## 2026-11-20 (CRO Overview rebuilt as design A2)

Owner request: build design A2 (the approved "Gauge trio" in the content calendar's colours). Verified: frontend tests
(68, 6 new in `tests/cro-overview.test.mjs`) and `next build` pass; checked in the browser on a preview server with
live data for Ridhi and CPC: a single day, last 7 days, picking a day from the strip, the chart's 7/14/28 days, area,
bars, table and the hover tooltip, and phone width. Not checked: the CSV download in a browser, and demo mode.

- **Changed** CRO Overview layout: a "Last 14 days" strip like the calendar's (orders per day, a line coloured by how
  well the day converted; click a day to look at it), then three cards: orders with the last 7 days as blocks, store
  conversion as a gauge with the store's own bands over the last 28 days (below usual, usual, strong) and its rank,
  revenue and average order, and visits by day coloured by conversion (14 or 28 days, hover for the day's figures).
- **Changed** the sales chart: the last 7, 14 or 28 days of the chosen range against the same number of days before,
  calendar events (Halloween, Diwali, ...) shaded, the busiest day labelled, a dotted daily average, a tooltip with both
  periods and the change, area/bars/table, net sales/total sales/orders, CSV download and an 8-week strip showing the
  part drawn. Store changes in those days are still listed under it.
- **Changed** shopper journey, "What to do next" and the monthly goal use the calendar's lane chips (impact, area,
  priority); the goal has its own card. The tinted tiles, the gradient score card and the ring journey are removed.
- **Added** `lib/cro.js` helpers for the Overview (`salesWindow`, `conversionScale`, `conversionBand`, `niceAxis`,
  `toCsv`) with tests.

## 2026-11-20 (Article editor: Claude box in the side panel)

Verified: frontend tests and `next build` pass; checked in the browser on the local app (article 50).

- **Changed** article editor: "Claude instructions" (revise this draft, standing instructions) is the first box in the
  right-hand panel, so it is reachable without scrolling past the article. Owner request.
- **Removed** the "Ownership" box (assignee, topic, first imported, kept in step via, created, last saved) from the
  editor's side panel. Owner request.
- **Changed** the Claude box is only a text box and an "Ask Claude to revise" button: the title, help texts, the
  Claude spend line, the brand-documents list and the "Standing instructions" editor are gone. Saved standing
  instructions still go with every Claude request; they are edited under Settings → Brands. Owner request.
- **Changed** Settings → Brands → "Voice and automation": a "Standing instructions for Claude" box and the list of brand
  documents Claude reads (moved from the article editor). Saved with the other brand settings; admins only.

## 2026-11-20 (Design round 3 built: CRO store pulse, checkout health, calendar day panel)

Owner request: build the three round-3 samples (`design-mockups/redesign-samples-v3.html`). Verified: CRO backend tests
(67, 3 new in `tests/unit/cro/test_goals.py`), ruff and `mypy --strict` for `modules/cro`, frontend tests, `next build`;
checked in the browser on the local app with live data: CRO Overview and Cart & checkout, and the calendar's Month,
2 weeks and Agenda views with the day panel. A monthly goal was not saved (that is the owner's figure to enter).

- **Changed** CRO Overview is a "store pulse": a score card with three rings (visits; carts that reached checkout;
  checkouts that paid) around the conversion rate, a mood line, the revenue, and the month's revenue goal as a bar with
  today's pace mark (set or change the goal on the card). Four tinted tiles (orders, conversion, average order,
  sessions) with small trend lines and a hover note on what each means. The journey as four steps, each with a ring of
  the share that got through from the step before and how many left. "What to do next" can be ticked off (remembered
  in this browser for that plan).
- **Changed** CRO Cart & checkout: a checkout health score out of 100 from four checks (carts kept, checkouts finished,
  visits that bought, mobile against desktop; 25 points each in proportion to the typical store), half-circle gauges
  with the typical store marked (green when better, red when behind), and the day charts in blue and umber with a filled
  area, a dashed "Typical" line and the best and worst day marked. Device and channel splits are coloured bars of the
  share of sessions with each one's conversion rate. Conversion tab charts get the same reference line and markers.
- **Changed** content calendar: filter chips for each kind of item and each brand; the selected day sits beside the
  calendar (under it on narrow screens) as a timeline with times, then "Schedule another task" with the cost of a
  Claude task; hovering an item lights up the other steps of the same blog; each event's chain shows research, draft
  and live progress; a bar on each day shows how full it is; Month, 2 weeks and Agenda views.
- **Added** `GET/PUT /api/cro/goal?brand=` (`modules/cro/goals.py`, kept in `app_settings` as `cro_goal:<brand>`,
  audited); `api.put` in `lib/api.js`; `Gauge` in `components/motion.jsx`; `LineChart` options `refLine`, `area`,
  `extremes`; sparklines draw themselves.

## 2026-11-20 (Content calendar: colour lanes and a day panel)

Verified: frontend tests, SEO backend tests and `next build` pass; checked in the browser on the local app (month grid,
two-week strip, the 24 Nov day panel and its schedule form). Owner request after the design samples.

- **Changed** Content calendar: every kind of item has its own colour (event, publish by, research, draft, publish
  request, goes live, automatic blog) with a brand dot; a "Next 14 days" strip sits on top (today in ink, one bar per
  kind of item); days lift on hover and items pop in. The automatic blogs (`/api/blog/overview`) are on the calendar too;
  their own publish request and go-live are not listed a second time.
- **Added** clicking a day opens a panel: first "What Flowmerce does this day" (each item with its state, message and
  next step: Skip, Remove, Open article), then "Schedule another task" for that day (the same form as "Schedule a
  task"; past days cannot take a new task).
- **Fixed** an article whose publish request still waits for a reviewer no longer reads "Scheduled on Shopify"; it says it
  goes live once a reviewer authorizes it (`/api/calendar` `scheduledPublishes` now carries the article status).

## 2026-11-20 (Clearer CRO action plan; featured image from a link or the computer)

Verified: backend unit tests pass except the existing `test_unfinished_pages_are_not_mounted` (5 new in
`tests/unit/seo/test_image_upload.py`); frontend tests and `next build` pass. Checked in the browser on the local app:
CRO Recommendations and the article editor's Featured image card. **Not run live:** an upload from the computer. The
stores' Shopify access tokens do not have the `write_files` scope (checked read-only), so until it is added an upload
shows how to add it and asks for a link instead.

- **Changed** CRO Recommendations: the summary paragraph under "Claude's action plan" is gone. Each action is a numbered
  card: the instruction as its heading, impact and effort tags, then "What to do" (numbered steps) beside "Why" (one
  line) and "The numbers" (short bullets), and what it improves. Claude is asked for shorter fields from now on (a title
  of up to 10 words, a one-sentence reason, 2-4 figures). The Overview's "What to do next" shows the same numbers.
- **Changed** article editor, Featured image: "Choose from N products" is replaced by "From a link" (paste any https://
  image address) and "From your computer" (drop or choose a JPG, PNG, WebP or GIF up to 15 MB). An uploaded file is
  stored in the brand's Shopify Files and its CDN address becomes the image URL. Also "Remove image".
- **Added** `POST /api/images/upload?brand=&filename=&alt=` (raw file body, no new dependency), `services/images.py`
  (type checked from the file's first bytes, size limit, audit), `integrations/shopify.upload_image` (staged upload,
  fileCreate, waits for processing). Needs the Shopify scope `write_files`.

## 2026-11-20 (Claude CRO action plan; automatic blogs; SEO & Blog overview; Advanced menus; motion everywhere)

Owner requests of 2026-11-20 and decisions taken the same day: automatic blogs stay HIDDEN Shopify drafts until a reviewer
authorizes them; two a week per brand (Tuesday and Friday); rarely used pages go into an "Advanced" group inside each
module; automatic blogs are OFF until an admin starts them in ONE copy of Flowmerce (this computer or the hosted copy).
Verified: backend unit tests pass except the existing `test_unfinished_pages_are_not_mounted` (13 new: 8 in
`tests/unit/seo/test_auto_blog.py`, 5 in `tests/unit/cro/test_ai_advice.py`); ruff and `mypy --strict` clean for
`modules/cro`; frontend tests pass; `next build` passes. See the session report for what was checked in the browser.
Not run live: an automatic blog end to end (it is off), and the Claude CRO plan was tried only as far as noted in the report.

- **Added** CRO Recommendations: "Claude's action plan". Claude reads the store's last 30 days (orders, revenue,
  conversion funnel, device and channel split, products, order health, the rule-based findings, the change log; no
  customer details) and returns up to 8 ranked actions with impact, effort, the figures behind each and the steps. Same
  ANTHROPIC_API_KEY and the same daily Claude limit as SEO & Blog (kind `cro_advice`, about $0.30). Opening the tab asks
  once a day per store; Refresh asks again. The Overview's "What to do next" shows its top 3. `GET/POST /api/cro/ai-advice`.
- **Added** automatic blogs (`services/auto_blog.py`): two slots a week per brand, 4 weeks ahead. Five days before a slot,
  "Write a blog" runs with no person involved (topic research with upcoming events, topic and keywords picked, draft with
  every field filled), then Flowmerce adds up to 3 product photos to the body, runs the new quality check, sends what
  Claude can fix back once, approves it as "Flowmerce (auto)", saves a hidden Shopify draft and puts a publish request for
  the slot's day on the content calendar. Nothing goes live without a reviewer. About $2 of Claude per blog.
- **Added** the AEO / GEO / LLMO quality check (`services/answer_checks.py`): required fields, SEO, answer engines (direct
  answer first, question headings, FAQ, lists), AI search (facts and figures, brand named, sources, product links) and AI
  readability (short paragraphs, descriptive headings, images with alt text). `GET /api/articles/{id}/answer-checks`.
- **Added** SEO & Blog → Overview (`/blog`): the blogs of the next 4 weeks as a ring, figures beside it (waiting for a
  reviewer, live in 30 days, average quality, projected monthly clicks at today's Search Console clicks per live
  article (none until there are 28 days of data and 3 live articles), Claude cost), a
  five-week blog calendar, "Coming up" rows with quality by group, Skip, and Start / Pause automatic blogs.
- **Added** SEO & Blog → Advanced → Write it yourself (`/write`): the manual tools in order (topic, approval, draft,
  images and checks, review, publish), each opening its page.
- **Changed** the sidebar: every module lists its everyday pages and a collapsed "Advanced" group. SEO & Blog: Overview,
  Articles, Content calendar, Publishing; Advanced: Write it yourself, Topics & keywords, SEO & traffic, Automation.
  Shipping and Conversion (CRO) list their tabs; Advanced: Shipping Analytics; CRO Alarms and Change log. Tab bars
  keep the same tabs behind an "Advanced" toggle.
- **Changed** Shipping Overview: the subtitle, the "Good afternoon. N orders need you today." heading and the summary
  paragraph under it are gone; the cards and charts are unchanged; "Escalation list (CSV)" stays when there are critical
  orders.
- **Changed** CRO visuals: a visitor-journey card (conversion ring against the typical store, funnel bars), abandonment
  rings on Cart & checkout, a revenue-by-product-group ring and best-seller bars on Products, an order-health ring on Sales.
- **Changed** motion across the app (`components/motion.jsx`, CSS "motion, second pass"): figures count up, rings and
  lines draw themselves, bars grow, cards arrive one after another, the active tab's underline slides in, critical
  pills pulse. The count-up writes into its own text node (no re-render per frame) and everything is off for reduced
  motion; tab and filter changes do not wait on any of it.
- **Architecture** SQLite migration 7: table `auto_blogs`; `autopilot_runs.slot_id`, `autopilot_runs.revise_job_id`
  (autopilot step `revise`). Settings `app_settings` keys `auto_blog` and `cro_advice:<brand>`. `ai_budget.ESTIMATE_USD`
  gains `cro_advice`.

## 2026-11-20 (Faster tab and filter changes)

Measured on the hosted copy before the change: a filter click 0.35-0.45 s, a tab 0.4-1.1 s, the first view after 5
idle minutes up to 2.7 s. Verified: 113 shipping tests (2 rewritten for the new board rule, 2 new) and all backend unit
tests pass except the existing `test_unfinished_pages_are_not_mounted`; 54 frontend tests; Next.js build. Checked in the
browser on a local copy (tabs, filter chips, sort, reload, browser Back, Articles filter): Overview 166-213 ms → 27-74 ms,
Analytics 112-125 ms → 38-63 ms locally. Not yet measured on the hosted copy.

- **Fixed** a tab, filter, sort or page click no longer asks the server for the page again before loading its data
  (`lib/nav.js` uses the browser's history API, which Next.js watches, instead of `router.replace`). One round trip less
  per click (~135 ms hosted), and the tab or chip highlights at once.
- **Changed** a list, tab or filter already opened in this browser tab shows its last answer straight away while a fresh
  one loads (`lib/api.js` `useApi`, up to 60 answers); any save, edit or delete empties this memory.
- **Changed** Shipping works out the Overview, Checks, Unfulfilled and Analytics figures once per built board instead of on
  every request (`board.py` `_memoized`; 0.3-0.7 s each on the hosting's CPU, and one such request held up the others).
- **Changed** a Shipping board older than 5 minutes, or from before a data refresh, keeps answering while its replacement
  is built in the background; pages only wait for a brand's first board, Refresh now, or a team mark or outcome.

## 2026-11-20 (Faster pages; fuller Home Shipping card and Shipping overview)

Verified: backend 687 passed, 1 failed (the existing `test_unfinished_pages_are_not_mounted`); 10 new CRO tests in
`tests/unit/cro/test_reads.py`; ruff and `mypy --strict` clean for `modules/cro`; frontend tests pass; `next build`
passes. Timed read-only on live data: CRO's order copy loads in 2.2 s for
Ridhi (was 6.7 s) and 1.7 s for CPC (was 3.1 s); repeated CRO settings / alarms / Home reads 0.01 s (were 0.8 / 1.9 /
0.5 s). Checked in the browser with a preview build reading the live API (port 3001, deleted afterwards): Home,
Shipping overview and Analytics at 1440 and 1200 px and at phone width (no sideways scroll). Remembered answers in
`useApi` come from commit c5d575b (another session), not from this change. **Not yet in the running app:** it needs a
restart.

- **Changed** CRO keeps its order copy ready: once older than 2 minutes it is still shown at once and reloaded in the
  background (a copy older than 30 minutes is reloaded first). Both stores are loaded, with the Home summary, when
  Flowmerce starts. Pages of orders and line items are read at the same time, and Home reads both stores at once.
- **Changed** CRO settings, alarm rules, alerts, change log and sync state are kept for 30 seconds and forgotten on
  every change Flowmerce makes to them (and after each order sync). Alarm checks and the sync lock still read the
  database every time.
- **Changed** the moving background draws about 15 frames a second instead of 60 (same look, a quarter of the work);
  page and card fade-ins take 0.2 s instead of up to 0.6 s.
- **Changed** Home: the Shipping card is as tall as Sales and shows active parcels by age (ring and legend), delivered
  and on time in 30 days, delivery problems, and the oldest delivery problems (each opens the order).
- **Changed** the ring cards (Active shipments, Articles live): the total sits inside a larger ring, the label and pill
  on top, and each legend row has a bar and a percentage of its share.
- **Changed** Shipping overview tiles each show a small picture: on-time against the 90% goal, delivery days (1-2 to
  9+), critical parcels by carrier, and delivered by week.
- **Changed** the article editor never shows a remembered copy of an article: `useApi(path, { remember: false })`
  (on top of c5d575b's remembered answers) always loads it fresh and does not keep it.
- **Fixed** Shipping Analytics: "Value at risk" no longer sits alone on a second row (one row of seven on wide
  screens, 4 + 3 otherwise).

## 2026-11-19 (Shipping: delivered in Shopify means delivered in Flowmerce)

- **Fixed** an order Shopify shows as delivered could stay on the Shipping board as "no tracking / pending" (CPC #6948).
  Two causes: (1) Flowmerce's own Shopify copy was last read before the delivery, and the order then passed the 60-day
  limit of Flowmerce's Shopify keys, so the copy never updated, while the refresh ignored the hub's newer "delivered".
  `ops.refresh_from_shopify_orders()` (105) now counts a fulfilment as delivered when the hub's copy of it says so,
  unless Shopify cancelled it. (2) Two orders sent in one parcel share one tracking number (#6948 and #6949), but
  only one of them owned the tracking row, so the other showed "Tracking missing". `ops.flow_board` (108) now gives
  that order the shared parcel's number, status and last scan, plus the real dispatch time instead of the time
  Flowmerce stored the row. The board resolves both orders as Delivered once the shared number is delivered.
- **Fixed** any tracking number on a parcel's Shopify fulfilment now counts, not only the one its row shows: CPC #8446
  lists TBA336415473219 (delivered by Amazon on 18 Nov), whose tracking row belongs to #8426, and stayed on the board.
- **Fixed** "Marked DONE by the team, but Shopify shows not fulfilled" (Checks tab) listed delivered orders, many marked
  critical with "Package delivered near the front door" from Amazon (114 rows, now 47). Delivered orders, by any
  source, are left out.
- **Fixed** dispatch time is the earlier of the Shopify fulfilment and the carrier's first movement (108): # RBP8183 went
  out through Amazon on 5 Nov but was entered in Shopify on 19 Nov, and showed "On track, 0 days".
- **Fixed** the age figures add up to the active total: the Overview ring, "Shipments by age" and "Aging by carrier"
  now include the parcels no carrier reports on ("Unconfirmed", 58), and the Overview headline names every open-check
  type (it named 4 of 8, so 53 orders read as 41).
- **Fixed** the team's "still in transit" count no longer includes a parcel whose order was delivered after the mark
  (# RBP7010); the order drawer shows the Amazon (MCF) line only on the Amazon parcel, not on a FedEx parcel of the same
  order; the drawer has side padding (its text touched or was cut at the left edge on narrow screens).
  **Run `db/central/105_refresh_from_shopify_orders.sql` and `108_flow_board_amazon.sql` (or `supabase_setup.sql`) in the
  Supabase SQL editor.** 108 changed again after the first run today, so run it once more.

## 2026-11-19 (Shorter lists on Content calendar and Publishing)

- **Changed** long lists no longer stretch the page; they use the same Previous / Next pager as the other lists.
  Content calendar: "Coming up" shows 5 events per page (it used to stop at 8, so every upcoming event can now be
  reached) and "Schedule this month" 10 rows per page. Publishing: Failed, Waiting for authorization, Ready to request,
  Scheduled by Flowmerce, Scheduled in Shopify and Unpublished in Shopify show 5 per page. Display only; no data or
  behaviour changed.

## 2026-11-19 (Blog: one-click "Write a blog", the 6-hour rule, calmer pages)

Verified: 620 backend tests pass (new: 8 autopilot / 6-hour-rule tests; the 1 failure is the existing
`test_unfinished_pages_are_not_mounted`; `tests/unit/cro`, another session's work in progress, was not run), 54 frontend
tests, Next.js build. Home, Automation, Shipping and Articles checked in the browser on a copy of the data. "Write a blog"
was not clicked live (it would have saved a real hidden draft to Shopify); its chain is covered by tests.

- **Added** "Write a blog" (Articles, Content calendar, Automation): one click runs topic research, picks and approves the
  best new topic, writes the draft, picks an image if needed, approves it and saves it as a HIDDEN Shopify draft, with live
  progress. About $1.20 of the daily limit; one run per brand at a time. Owner decision 2026-11-19.
- **Added** the 6-hour rule: an article scheduled on the content calendar that nobody approved by 6 hours before its
  publish time is approved automatically and saved as a hidden Shopify draft. Nothing is ever published automatically; an
  article a reviewer sent back with changes requested is never auto-approved.
- **Changed** calendar drafting tasks run the same chain (they also approve the event's proposed topic).
- **Changed** every automatic approval is recorded as "Flowmerce (auto)" in review history, topic notes and the audit log.
  Claude is told that automatic approval of hidden drafts is allowed, so it does not flag it.
- **Changed** page subtitles are one short line. Pages, cards and dialogs animate in gently; buttons and cards respond to
  hover and clicks; all motion is off when the computer asks for reduced motion.
- **Changed** Home, SEO & traffic, Automation and Shipping show only the daily essentials; the rest is under "Show more"
  (remembered per browser). Automation shows only stages that need attention.
- **Architecture** new table `autopilot_runs` (migration 6). New `services/autopilot.py`, `components/More.jsx`.

## 2026-11-20 (CRO: any date range; sales first on Home)

Verified: 49 CRO backend tests pass (10 new in `tests/unit/cro/test_ranges.py`); full backend suite 677 passed, 1 failed
(the existing `test_unfinished_pages_are_not_mounted`); ruff and `mypy --strict` clean for `modules/cro`; frontend
tests 61 pass (2 new); `next build` passes. Read-only live check through the service layer: 1-15 Nov for Ridhi gave
876 orders against 714 in the 15 days before, conversion 1.98% against 1.54%, and Shopify accepted the date-based
ShopifyQL queries; the Home summary answered for both stores. Checked in the browser in demo mode (preview on port
3001, deleted afterwards): Home order, the range picker, a custom 2-15 Nov range, and the phone layout of both
pages. **Not yet seen in the running app:** it needs a restart to load the new backend and frontend.

- **Added** any date range on the CRO page: quick picks (Today, Yesterday, Last 7 / 14 / 30 days, This month,
  Last month) and "Pick dates..." (a calendar from-to; the same day twice = one day). Compare with the previous
  period of the same length, the same days a week earlier, the 4-week weekday average (single day) or nothing.
  The range is in the address (`?r=custom&from=...&to=...&cmp=...`) and applies to Overview, Conversion,
  Cart & checkout, Products and Sales. Quick picks use the store's own "today" (Shopify timezone).
- **Added** API: `from`, `to` (YYYY-MM-DD) and `compare` on `/api/cro/overview`, `sales-breakdown`, `sales-trend`,
  `order-health`, `products`, `conversion`, `segments` (the older `period` / `days` still work); ShopifyQL by
  explicit dates; ranges up to 366 days; orders older than the 63-day snapshot are read on demand.
- **Added** `GET /api/cro/home`: per store, yesterday and today so far (orders and net sales against the 4-week
  weekday average / same time last week), yesterday's conversion rate and the last 14 days. It never fails: a store
  that cannot be read says why.
- **Changed** Home: Sales (daily orders and net sales, Ridhi and CPC separate, 14-day charts) on the left and the
  Shipping snapshot on the right come first, then Today's to-do, then the SEO & Blog block (content pipeline,
  article journey). Sales also shows while the SEO data is loading or failed. The two shipping figures that were
  in the SEO block are removed (they are in the Shipping card above).
- **Added** a note when a range starts before CRO's order copy (20 Sep 2026 for Ridhi): order figures before then
  are missing; sessions and conversion are complete.
- **Changed** the Overview sales chart can show net sales, total sales or orders; store changes logged in the
  chosen days are listed under it.

## 2026-11-20 (CRO module, phase 3: the Conversion (CRO) page)

Verified: frontend tests 59 pass (5 new in `tests/demo-cro.test.mjs`; `routes.test.mjs` and `demo-all.test.mjs` extended);
`next build` passes (`/cro` 9.5 kB). Checked in the browser in demo mode on a separate preview build (port 3001, own
`NEXT_DIST_DIR`, deleted afterwards): every tab renders, logging and removing a change works, editing an alarm
works, and the phone layout (375 px) has no sideways scroll. **Not checked on live data:** the local Flowmerce
(ports 8787/3000) was not running at the time; the running app shows the page only after its frontend is rebuilt.

- **Added** menu entry "Conversion (CRO)" (`/cro`, after Shipping) with tabs Overview (KPI cards against the
  same-weekday baseline with "too early to compare", 14-day sales trend against the 14 days before, top
  recommendations, recent store changes), Conversion (daily conversion rate and sessions, funnel, day table),
  Cart & checkout (abandonment trends next to industry references, device and channel splits), Products (top /
  average / low), Sales (gross-to-total breakdown, 30-day order health), Recommendations, Alarms (switch all or
  one rule on/off, edit name / threshold / keyword, add a product alarm, alert history) and Change log (add, remove).
- **Added** one store at a time: the page follows the top bar's Ridhi / CPC, and shows its own Ridhi / CPC
  switch when the top bar says All (conversion rates of two stores are never added together). "Sync now" reads
  the store's latest orders.
- **Added** plain explanations instead of zeros: missing Shopify analytics access (`reports_access_missing`),
  CRO not set up, the `cro` schema not reachable, and "first order load still running".
- **Added** demo data for every `/api/cro/*` route (`src/demo/modules/cro.js`); demo snapshot version 2.

## 2026-11-19 (CRO: "sales declining" needs real volume)

Verified: 39 CRO tests pass (1 new, 1 updated); ruff and `mypy --strict` clean. Checked read-only on both stores'
live order copy. The running server picks the change up only after a restart.

- **Changed** a product is reported as declining only when it sold at least 5 units and $300 in the week before
  (`metrics.DECLINE_MIN_UNITS` / `DECLINE_MIN_REVENUE`, owner decision). On 19 Nov this cut Ridhi's 116 candidate
  drops to 14 and CPC's 80 to 13. The top three shown changed from quilts going from 2 sales to 0 to drops such as
  Oak Brown Quilt 9 -> 2 sold ($1,346 -> $248). The evidence line now shows units sold in both weeks.

## 2026-11-19 (CRO: safer order sync after the first live run)

Observed: Ridhi's first CRO order load stopped at 2,100 of its orders (placed 20 Sep - 6 Nov) and left its lock held,
with no error recorded; CPC never started. A thread dump (py-spy, installed in `.venv` only) of the running server
showed it had no CRO job at all (it started at 09:31 UTC, before CRO was mounted). The sync was run by another,
short-lived Flowmerce process that exited mid-load. Which process it was is not established. Meanwhile the
Recommendations page showed false "quilt orders stalled" and "sales declining" items from the partial data.

Verified: 38 CRO tests pass (6 new); full suite 658 passed, 1 failed (the existing
`test_unfinished_pages_are_not_mounted`); ruff and `mypy --strict` clean for `modules/cro`. Not re-run live.

- **Fixed** `SCHEDULER=false` (used by the smoke test and other short-lived runs) now also stops the CRO background
  job, so such runs never sync live data (`scheduler.enabled()`).
- **Fixed** the sync saves its progress (`cro.sync_state.cursor`, only moving forward) and refreshes its lock after
  every batch of 50 orders, so an interrupted load continues where it stopped instead of re-reading 60 days.
- **Fixed** a lock not refreshed for 10 minutes belongs to a process that died and is cleared (compare-and-set, so a
  live sync keeps its lock). Previously it blocked the store for 30 minutes.
- **Fixed** until a store's first order load has finished, every order-based response carries
  `order_data.first_load_complete = false` with a note, and Recommendations skips its order-based checks (listed in
  `skipped`). Alarms already waited for a finished sync.

## 2026-11-19 (CRO module, phase 2: backend, order copy, `/api/cro`)

Verified: 32 new tests in `tests/unit/cro/` pass; full suite 652 passed, 1 failed (the existing
`test_unfinished_pages_are_not_mounted`, about the `login` page folder); ruff and `mypy --strict` clean for
`modules/cro` (the 53 project-wide mypy findings are all in existing Shipping files). Read-only live checks:
112 is recorded as applied in Supabase; the `cro` schema is **not yet exposed** in the Data API (PGRST106);
Shopify order + line-item reads work on both stores; ShopifyQL is **refused** on both stores (no `read_reports` /
Level 2 customer data yet). Not verified: 113 has not been run; no sync, alarm or page tested against live data.

- **Added** `src/flowmerce/modules/cro/`, ported from the CRO prototype and rebuilt on Flowmerce's foundations:
  brand-aware (`ridhi`/`cpc`), Supabase through Shipping's REST client (schema `cro`), Shopify through each brand's
  existing app (one app per store for every module), `require_perm("view")` on every route and the audit log on
  every change. Routes under `/api/cro`: overview, sales-breakdown, sales-trend, order-health, products, conversion,
  funnel, segments, recommendations, benchmarks, alarms (list/create/update), alerts, settings, sync, status,
  change-log (list/add/delete).
- **Added** background job (`CRO_SYNC_MINUTES`, default 15): copies new Shopify orders into `cro.orders` /
  `cro.order_lines`, reloads the page snapshot, checks the alarms. Started next to Shipping's refresher in
  `seo/app.py`; a CRO failure never stops SEO or Shipping.
- **Added** `db/central/113_cro_orders.sql` (owner chose a CRO-owned order copy): `cro.orders`, `cro.order_lines`,
  `cro.sync_state`, functions `save_orders`, `begin_sync` / `end_sync` (per-store lock), `delete_change_log`; drops
  112's `cro.daily_sales` view, which the code does not use. Rollback 112 now also covers 113.
- **Added** dependency `tzdata` (seo extra, owner-approved): Windows has no timezone database, and CRO splits orders
  into the store's local days.
- **Changed** from the prototype: conversion rate is computed from Shopify's session counts (no 0.025-vs-2.5 guess);
  the "revenue pacing" recommendation compares today with the same weekday last week, not yesterday; the product
  alarm uses a keyword setting instead of the hard-coded "quilt", and waits while the order copy is stale; alarms
  are shown in the app only (no email); timezone comes from Shopify (fallback `ops.stores`, then UTC).
- **Removed** nothing from Flowmerce. Not ported from the prototype: its SQLAlchemy models and migrations, its own
  Shopify client and embedded-app login, the API-key and CORS setup, test endpoints, SMTP email, the Vite/TypeScript
  frontend.

## 2026-11-19 (CRO module, phase 1: the `cro` schema in Supabase)

Not verified: the SQL has not been run (no PostgreSQL on this computer); it was checked by reading only. No Python
or frontend code yet: the CRO pages and API come in later phases.

- **Added** `db/central/112_cro.sql` (and its copy `supabase/112_cro.sql`): schema `cro` with `store_settings`,
  `alarm_rules` (conversion-rate drop, no orders for a product keyword; thresholds editable), `alerts` (the database
  refuses a second open alert per rule and a second conversion-drop alert per day) and `change_log`, plus the view
  `cro.daily_sales` (orders and revenue per store per local day from `ops.orders`). Default rules: RBP conversion drop
  20% and no quilt orders for 12 hours; CPC conversion drop 20%. RLS on; only `service_role` / `flowmerce_app` get rights.
  Reads `ops.orders` / `ops.stores` only; never writes `ops`, `seo` or `public`.
- **Added** `db/central/rollback/112_rollback_cro.sql`: drops schema `cro` only; refuses while the team has recorded
  alerts, change-log entries, settings or added/edited rules, unless `flowmerce.allow_cro_rollback_with_data = 'yes'`.
- **Changed** `scripts/build_supabase_setup.py` includes 112, and the generated header says to expose `cro` as well
  as `ops`; `supabase_setup.sql` regenerated (112 appended, nothing else changed).
- **Known gap** `ops.orders` has no subtotal / discounts / shipping / tax / refunded amounts filled, and `ops.items` is
  never filled, so the sales breakdown, top products and the quilt alarm still need a data source (phase 2 decision).

## 2026-11-19 (Blog: Claude writes with each brand's own guides; content calendar; daily Claude limit)

Verified: 611 backend tests pass (new: 19 in `tests/unit/seo/test_blog_ai.py`; the 1 failure is the existing
`test_unfinished_pages_are_not_mounted`, about the `login` page folder), 54 frontend tests, Next.js build. Checked
in the browser on a copy of the data (calendar, planning). One real draft per brand was written on that copy.

- **Added** brand knowledge: CPC's and Ridhi's own guides (voice, claims, products, playbooks) in
  `modules/seo/knowledge/<brand>/`, sent as cached context with every Claude request for that brand.
- **Added** drafts fill every field the SEO check scores (the rules are in the prompt) and pick a featured image from
  the synced product photos. Claude's notes (claims to confirm, recommendations, admin checks, sources, next article,
  photo brief) are stored with the draft (`articles.ai_notes_json`) and shown beside it. An image that is not a
  product photo is removed; a link that is not a known page is listed for a person to check.
- **Added** "Claude instructions" in the article editor: standing instructions per brand (sent after the brand
  documents) and "Revise this draft" (AI job `content_revision`, saved as a new version through the normal save path).
- **Added** Ask Claude buttons for a new topic (ideas, keywords) and for an article's SEO fields. Nothing is saved
  until the person applies the suggestion.
- **Added** the daily Claude limit: monthly budget / days in the month, no carry-over. Every call is recorded with its
  token counts and estimated cost (`claude_usage`); a call that would pass today's limit is refused, and a queued job
  waits for the next day without using a retry. Budget $90 a month (about $3 a day), which is also the ceiling; admins can set it lower on the Content calendar page. A warning shows on every SEO & Blog page, in the limit meter and after Ask Claude once 80% of the day or the month is used.
- **Added** Content calendar (SEO & Blog): built-in events and seasons with publish-by dates, the team's own events,
  a schedule (research, draft, publish request) run by the scheduler within the daily limit, and "Plan upcoming
  events" (at most one Claude task per day). A scheduled publish only creates a publish request; a reviewer still
  authorizes it. Topic research is told about upcoming events.
- **Changed** drafts get the products whose names match the topic first (with their images), not the first 60.
- **Architecture** new tables `app_settings`, `claude_usage`, `calendar_events`, `content_schedule`, column `articles.ai_notes_json` (migration 5).

## 2026-11-19 (Shipping pages load faster: the built board is cached)

Verified: 103 shipping tests (new: one build serves repeated requests, a new snapshot / team mark / 5 minutes
rebuilds it, 6 parallel requests make one build), 592 backend tests pass (the 1 failure also fails on 7cd0758),
54 frontend tests, build, smoke test, no new mypy or ruff findings. Locally a repeated Shipping request went
from 128 ms to 6 ms; on the hosting's small CPU each request rebuilt the board in ~2 s.

- **Changed** every Shipping request used to rebuild the whole board from the cached snapshot (every parcel
  enriched, Amazon laid over it, the reship / delivered rules). The built board is now kept per brand and reused
  until the snapshot is reloaded, a team mark or outcome changes it, or 5 minutes pass; parallel requests for one
  brand wait for a single build. After each background reload (scheduler, MCF sheet sync, stale cache) the "all"
  board is built in the background so the next page does not wait.

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
