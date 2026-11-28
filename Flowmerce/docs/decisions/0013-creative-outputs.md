# ADR 0013: Creative Strategist outputs read the tag patterns; variations of real ads; designer briefs

- Status: accepted (owner approved the Part 2 plan on 2026-11-28)
- Date: 2026-11-28

## Decision

1. **The AI pack reads the tag patterns** (`service.creative_patterns`: verdicts and results by hook type, visual style, format, print, color, category, season and product, plus the top winning and losing ads with their own copy), trimmed by `prompts.patterns_for_prompt` so the prompt stays small. When they cannot be read (118 not run, nothing tagged) the pack is written from the format and hook figures as before. `PACK_VERSION` 2.
2. **A Story per concept** in the pack: 3-4 full-screen 9:16 frames with on-screen words and at most one sticker.
3. **Variations of a real ad**: `POST /api/creative/ads/{ad_id}/variations` sends one of the store's own ads (copy, tags, figures) to Claude with the existing variations schema (one variable changes). Returned, not stored; each variation can be saved as a concept. The page offers it on winners.
4. **Designer briefs by Claude** for a saved concept: `POST /api/creative/concepts/{id}/designer-brief` writes objective, sizes (9:16 / 4:5 / 1:1 / 16:9), product, print and color, visual direction, a reference to what already wins, words on screen, must say, must not say and deliverables. The brief is turned into markdown by code and kept in the existing `creative.brief` table as a draft; `POST /api/creative/briefs/{id}/approve` records who approved it. No new SQL.
5. New Claude cost estimates in `seo/services/ai_budget.py`: `creative_ad_variations` $0.20, `creative_designer_brief` $0.25, and `creative_tagging` $0.03 (tagging fell back to the generic $0.15 estimate before).

## Rationale

The pack and variations should build on what the store's own ads show wins, not only on formats. A brief a designer can work from needs the product, its print and color and the sizes, which only the tag data has. Storing briefs in `creative.brief` uses the approval rule 116 already enforces (a brief cannot leave draft without an approver).

## Consequences

- A pack request reads more figures, so it costs a little more; variations and briefs run only when a person presses the button, within the daily Claude limit.
- Demo mode: briefs and variations of real ads are refused (412); the pack works as before.
- Not yet: the learnings loop (test results feeding the next round).
