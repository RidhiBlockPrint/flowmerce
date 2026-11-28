# ADR 0012: Creative Strategist, what it monitors and uses (tags, products, rules, seasons)

- Status: accepted (owner approved the merge plan on 2026-11-28)
- Date: 2026-11-28

## Decision

Add to the existing Creative Strategist, for both stores (Ridhi and CPC):

1. **The ad's own copy is synced by the Ads module.** `ads/meta.py` also reads each ad's primary text, headline and destination link (`ad_copy`), and `ads/sync.py` saves them in three new `ads.ads` columns (`db/central/118_creative_tags.sql`). Until 118 is run, `ads/data.py: save_ads` saves the ads without the copy (Supabase answers PGRST204), so the Ads sync never fails because of Creative.
2. **Product context** in `creative.product`: each store's active Shopify products (read with SEO & Blog's Shopify connection), with print, color, category and season fit.
3. **Ad tags** in `creative.ad_tag`: hook type, hook line, visual style, print and color. Format comes from `ads.ads`; the product from the ad's `/products/<handle>` link.
4. **Claude suggests, a person corrects.** Tags come from a fixed vocabulary (`creative/taxonomy.py`), enforced by the JSON schema and checked again. A manual edit or a confirmation is never changed by Claude. Tagging uses the shared daily Claude limit (kind `creative_tagging`).
5. **Editable rules and seasons per store** in `creative.rule` and `creative.season`. Verdicts: not enough data, winner (ROAS at or above target), loser (below break-even), average.
6. **Frontend**: two new tabs on `/creative` (Ad tags, Product context) and a "Winners, losers and what they have in common" section on Insights.

## Rationale

The existing page could not compare hooks because the Ads sync did not store the ad's copy. Reading it once in the Ads sync keeps one Meta reader and one copy of the data (owner's choice over a second Creative-only reader). A fixed vocabulary keeps grouping meaningful; manual edits winning keeps the team in charge of the data behind every recommendation.

## Alternatives considered

- Creative reads the copy from Meta itself: no change to the Ads module, but two Meta readers and two copies of the ads.
- Free-text tags: flexible, but "floral", "Floral" and "flowers" would become three groups.
- Ridhi only: simpler to describe, but the module already serves both stores at no extra cost.

## Consequences and dependencies

- `118_creative_tags.sql` must be run by the owner in Supabase (needs 115 and 116). Before that: hooks stay empty, tag and product routes answer 503 with what to run.
- Small change in the Ads teammate's code (`meta.py`, `data.py`, `sync.py`); behaviour unchanged when 118 is not run.
- Demo mode: patterns, rules and seasons answer from the sample ads; every write answers 412 `pending_setup`.
- Rollback: `db/central/rollback/118_rollback_creative_tags.sql` (refuses while hand-set tags exist).
